#!/usr/bin/env python3
"""Hermes Gateway Tray Monitor — pasivní observer pro KDE/Plasma.

Hermes Gateway je nativní součást Hermes Agenta (Nous Research).
Tato aplikace je tenký controller: sleduje stav brány, umožňuje
Start/Stop/Restart, přepnutí aktivního profilu a zobrazení logů.

Architektura: tray čte vše z ~/.hermes/, kam NEzapisuje. Jediný
soubor, kam tray zapisuje, je ~/.config/tray4hermes/state.json.

Viz __version__ dole.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QDialog,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSystemTrayIcon,
    QVBoxLayout,
)

__version__ = "2.0.0"

# ── Cesty k Hermes & tray state ────────────────────────────────────────────
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
GATEWAY_STATE = HERMES_HOME / "gateway_state.json"
GATEWAY_LOG = HERMES_HOME / "logs" / "gateway.log"
PROFILES_DIR = HERMES_HOME / "profiles"
CONFIG_YAML = HERMES_HOME / "config.yaml"
HERMES_BIN = HERMES_HOME / "hermes-agent" / "venv" / "bin" / "hermes"

TRAY_CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "tray4hermes"
TRAY_STATE_FILE = TRAY_CONFIG_DIR / "state.json"
LOCK_FILE = Path("/tmp/hermes-tray.lock")

SERVICE = "hermes-gateway.service"

# Jak starý smí být gateway_state.json, aby ho tray bral jako aktuální
GATEWAY_STATE_MAX_AGE = 30  # sekundy
LOG_TAIL_BYTES = 256 * 1024  # kolik posledních bytů logu čteme
REFRESH_INTERVAL_MS = 5000   # periodický refresh

TRAY_STATE_VERSION = 1


# ── Datové struktury ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GatewayState:
    """Reprezentuje aktuální stav gateway v UI."""
    code: str   # active | warming | inactive | failed | activating | unknown
    label: str  # lidsky čitelný popis


@dataclass(frozen=True)
class TrayState:
    """Stav který si tray drží mezi sezeními."""
    selected_profile: str

    def to_json(self) -> dict:
        return {
            "version": TRAY_STATE_VERSION,
            "selected_profile": self.selected_profile,
        }

    @classmethod
    def from_json(cls, data: dict) -> "TrayState":
        return cls(
            selected_profile=str(data.get("selected_profile", "") or ""),
        )

    @classmethod
    def default(cls) -> "TrayState":
        return cls(selected_profile="")


# ── Util ───────────────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Spustí příkaz a vrátí (exit, output). Nikdy nevyhodí výjimku."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, f"(subprocess error: {exc})"


# ── Tray state (čte + píše JEN svůj vlastní soubor) ────────────────────────
def load_tray_state() -> TrayState:
    """Načte tray state z disku, nebo vrátí default. Nikdy nevyhodí výjimku."""
    try:
        with open(TRAY_STATE_FILE) as f:
            return TrayState.from_json(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return TrayState.default()


def save_tray_state(state: TrayState) -> None:
    """Atomický zápis (tmp + rename). Nikdy nevyhodí výjimku."""
    try:
        TRAY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = TRAY_STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state.to_json(), f, indent=2)
        os.replace(tmp, TRAY_STATE_FILE)
    except OSError as exc:
        # Tray state je best-effort. Log, ale neblokuj UI.
        print(f"[tray4hermes] save_tray_state failed: {exc}", file=sys.stderr)


# ── Čtení z Hermes (read-only) ─────────────────────────────────────────────
def read_gateway_state() -> Optional[dict]:
    """Vrátí gateway_state.json pokud existuje a je mladší než GATEWAY_STATE_MAX_AGE."""
    try:
        if time.time() - GATEWAY_STATE.stat().st_mtime > GATEWAY_STATE_MAX_AGE:
            return None
        with open(GATEWAY_STATE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return None


def list_profiles() -> list[str]:
    """Vrátí profily z ~/.hermes/profiles/. 'default' vždy první."""
    profiles: list[str] = []
    if PROFILES_DIR.is_dir():
        for entry in sorted(PROFILES_DIR.iterdir()):
            if entry.is_dir():
                profiles.append(entry.name)
    return ["default", *profiles] if "default" not in profiles else profiles


def read_active_model() -> str:
    """Nejlepší pokus o přečtení `model.default` + `provider` z config.yaml bez PyYAML."""
    try:
        with open(CONFIG_YAML) as f:
            text = f.read()
    except OSError:
        return "(nelze číst config)"

    model, provider = "", ""
    in_model = False
    for line in text.splitlines():
        if line.startswith("model:"):
            in_model = True
            continue
        # Opustíme `model:` blok při novém top-level klíči
        if in_model and line and not line.startswith((" ", "\t")):
            in_model = False
        if in_model:
            stripped = line.strip()
            if stripped.startswith("default:"):
                model = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("provider:"):
                provider = stripped.split(":", 1)[1].strip()
    return f"{model} ({provider})" if model else "(model nenalezen)"


# ── Systemd wrapper ────────────────────────────────────────────────────────
def _systemctl(action: str) -> tuple[int, str]:
    return _run(["systemctl", "--user", action, SERVICE], timeout=15)


def systemd_is_active() -> Optional[str]:
    """Vrátí 'active' | 'inactive' | 'failed' | 'activating' | None (při chybě)."""
    code, out = _systemctl("is-active")
    out = out.strip()
    if code == 0 and "active" in out:
        return "active"
    if "inactive" in out:
        return "inactive"
    if "failed" in out:
        return "failed"
    if "activating" in out:
        return "activating"
    return None


def aggregate_state() -> GatewayState:
    """Kombinuje gateway_state.json (primár) + systemd (fallback) do jednoho stavu."""
    gw = read_gateway_state()
    if gw is not None:
        # gateway_state.json je autoritativní — píše ho samotný gateway.
        # `running=false` znamená že gateway ví, že neběží (planned shutdown).
        if gw.get("running") is False:
            return GatewayState("inactive", "Gateway hlásí stopped")
        # Discord připojen? Pak je to plně aktivní.
        if gw.get("discord") or gw.get("platforms"):
            return GatewayState("active", "Gateway běží a je připojená")
        # Proces běží, ale platforma se ještě nepřipojila = warming.
        return GatewayState("warming", "Gateway běží, čeká na připojení")

    # Fallback: systemd
    s = systemd_is_active()
    if s == "active":
        return GatewayState("warming", "Gateway běží (čekám na gateway_state.json)")
    if s == "activating":
        return GatewayState("activating", "Gateway startuje…")
    if s == "failed":
        return GatewayState("failed", "Gateway služba selhala")
    if s == "inactive":
        return GatewayState("inactive", "Gateway je zastavená")
    return GatewayState("unknown", "Stav gateway je nečitelný")


# ── Single-instance lock ───────────────────────────────────────────────────
def acquire_lock() -> bool:
    """Získá PID-based lock. Vrátí True, pokud jsme jediná instance."""
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Existující lock — ověř, jestli jeho PID žije
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # signal 0 = jen test existence
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            # PID nežije / nevalidní — smaž a zkus znovu
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass
            return acquire_lock()
    except OSError:
        return False


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


# ── Ikony (generované až po QApplication) ──────────────────────────────────
def make_icon(color: str, size: int = 64) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, size - 8, size - 8)
    p.setPen(QColor("white"))
    font = p.font()
    font.setPixelSize(int(size * 0.55))
    font.setBold(True)
    p.setFont(font)
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "H")
    p.end()
    return QIcon(px)


# Barvy + tooltipy pro jednotlivé stavy
STATE_COLORS = {
    "active":     "#4caf50",  # zelená
    "warming":    "#ff9800",  # oranžová
    "activating": "#2196f3",  # modrá
    "inactive":   "#9e9e9e",  # šedá
    "failed":     "#f44336",  # červená
    "unknown":    "#9e9e9e",  # šedá
}

STATE_TOOLTIPS = {
    "active":     "Hermes Gateway — běží a připojená",
    "warming":    "Hermes Gateway — běží, čeká na připojení",
    "activating": "Hermes Gateway — startuje…",
    "inactive":   "Hermes Gateway — zastavena",
    "failed":     "Hermes Gateway — selhala!",
    "unknown":    "Hermes Gateway — neznámý stav",
}


# ── Log viewer ──────────────────────────────────────────────────────────────
class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Hermes Gateway — logy (tray4hermes v{__version__})")
        self.resize(700, 400)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        font = self._text.font()
        font.setFamily("monospace")
        self._text.setFont(font)

        layout = QVBoxLayout(self)
        layout.addWidget(self._text)

        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _refresh(self):
        try:
            with open(GATEWAY_LOG, "rb") as f:
                f.seek(-LOG_TAIL_BYTES, os.SEEK_END)
                data = f.read()
            text = data.decode("utf-8", errors="replace")
            self._text.setPlainText(text)
            # scroll na konec
            bar = self._text.verticalScrollBar()
            bar.setValue(bar.maximum())
        except OSError:
            # log smazán / nepřístupný — tiše, další tick to zkusí znovu
            pass


# ── Hlavní tray ─────────────────────────────────────────────────────────────
class HermesTray:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self._tray_state = load_tray_state()
        self._icons = {
            code: make_icon(color)
            for code, color in STATE_COLORS.items()
        }
        self._current_state: Optional[str] = None

        self._tray = QSystemTrayIcon()
        self._tray.activated.connect(self._on_tray_activated)

        self._menu = self._build_menu()

        self._tray.setContextMenu(self._menu)

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(REFRESH_INTERVAL_MS)

        self._refresh()
        self._tray.show()

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        # Stav (read-only)
        self._status_action = QAction("Kontroluji…", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        self._model_action = QAction("Model: ?", menu)
        self._model_action.setEnabled(False)
        menu.addAction(self._model_action)

        menu.addSeparator()

        # Profily
        self._profile_menu = menu.addMenu("Profil")
        self._profile_group = QActionGroup(menu)
        self._profile_group.setExclusive(True)
        self._rebuild_profile_menu()

        menu.addSeparator()

        # Akce
        self._start_action = QAction("▶  Start", menu)
        self._start_action.triggered.connect(lambda: self._systemd("start"))
        menu.addAction(self._start_action)

        self._stop_action = QAction("⏹  Stop", menu)
        self._stop_action.triggered.connect(lambda: self._systemd("stop"))
        menu.addAction(self._stop_action)

        self._restart_action = QAction("🔄 Restart", menu)
        self._restart_action.triggered.connect(lambda: self._systemd("restart"))
        menu.addAction(self._restart_action)

        menu.addSeparator()

        self._logs_action = QAction("📋 Logy", menu)
        self._logs_action.triggered.connect(self._show_logs)
        menu.addAction(self._logs_action)

        self._open_config_action = QAction("⚙  Hermes config", menu)
        self._open_config_action.triggered.connect(self._open_config)
        menu.addAction(self._open_config_action)

        self._open_cli_action = QAction("💻  Hermes CLI", menu)
        self._open_cli_action.triggered.connect(self._open_cli)
        menu.addAction(self._open_cli_action)

        menu.addSeparator()

        self._about_action = QAction(f"ℹ  O tray4hermes (v{__version__})", menu)
        self._about_action.triggered.connect(self._show_about)
        menu.addAction(self._about_action)

        self._quit_action = QAction("✖  Ukončit tray", menu)
        self._quit_action.triggered.connect(self._quit)
        menu.addAction(self._quit_action)

        return menu

    def _rebuild_profile_menu(self):
        self._profile_menu.clear()
        profiles = list_profiles()
        selected = self._tray_state.selected_profile or "default"
        for name in profiles:
            act = QAction(name, self._profile_menu, checkable=True)
            act.setChecked(name == selected)
            act.triggered.connect(lambda checked, n=name: self._select_profile(n))
            self._profile_group.addAction(act)
            self._profile_menu.addAction(act)

    def _select_profile(self, name: str):
        """Zapíše vybraný profil + restartuje gateway přes `hermes profile use`."""
        self._tray_state = TrayState(selected_profile=name)
        save_tray_state(self._tray_state)

        reply = QMessageBox.question(
            None,
            "Změnit profil?",
            f"Restartovat gateway s profilem '{name}'?\n\n"
            f"Aktuální session v Discordu/Hermes Desktopu se může krátce odpojit.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        if HERMES_BIN.exists():
            code, out = _run([str(HERMES_BIN), "profile", "use", name])
            if code != 0:
                QMessageBox.warning(
                    None, "Chyba",
                    f"Nelze nastavit profil '{name}':\n\n{out or '(bez výstupu)'}\n\n"
                    f"Profil musí existovat v {PROFILES_DIR}/.",
                )
                return

        _systemctl("restart")
        QTimer.singleShot(2000, self._refresh)

    def _refresh(self):
        state = aggregate_state()
        if state.code != self._current_state:
            self._current_state = state.code
            self._tray.setIcon(self._icons.get(state.code, self._icons["unknown"]))
            self._tray.setToolTip(STATE_TOOLTIPS.get(state.code, state.label))
            self._status_action.setText(state.label)

        self._model_action.setText(f"Model: {read_active_model()}")

        is_running = state.code in ("active", "warming", "activating")
        self._start_action.setEnabled(not is_running)
        self._stop_action.setEnabled(is_running)
        self._restart_action.setEnabled(True)

    def _systemd(self, action: str):
        _systemctl(action)
        QTimer.singleShot(2000, self._refresh)

    def _show_logs(self):
        LogDialog().exec_()

    def _open_config(self):
        if CONFIG_YAML.exists():
            subprocess.Popen(["xdg-open", str(CONFIG_YAML)])
        else:
            QMessageBox.warning(None, "Chyba", f"Config nenalezen:\n{CONFIG_YAML}")

    def _open_cli(self):
        cmd = [str(HERMES_BIN)] if HERMES_BIN.exists() else ["bash", "-c", "hermes; exec bash"]
        subprocess.Popen(["konsole", "-e", *cmd])

    def _show_about(self):
        QMessageBox.information(
            None,
            f"tray4hermes v{__version__}",
            f"<b>tray4hermes v{__version__}</b><br><br>"
            f"Pasivní observer pro Hermes Gateway.<br><br>"
            f"<b>Čte:</b> ~/.hermes/gateway_state.json, profiles/, config.yaml, logs/gateway.log<br>"
            f"<b>Píše:</b> {TRAY_STATE_FILE}<br>"
            f"<b>Ovládá:</b> systemctl --user ({SERVICE})<br><br>"
            f"Hermes Agent: github.com/NousResearch/hermes-agent",
        )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_logs()

    def _quit(self):
        release_lock()
        self.app.quit()
        # Zabij i watchdog (run.sh smyčku)
        try:
            os.kill(os.getppid(), signal.SIGTERM)
        except ProcessLookupError:
            pass

    def run(self) -> int:
        rc = self.app.exec_()
        release_lock()
        return rc or 0


# ── Entry point ─────────────────────────────────────────────────────────────
def main() -> int:
    if not acquire_lock():
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(
            None, "Hermes Tray",
            "tray4hermes už běží.\nNajdeš ho v systémové liště.",
        )
        return 2

    try:
        return HermesTray().run()
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())