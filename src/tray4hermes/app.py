"""Main tray class — builds the menu, owns the timers, reacts to clicks.

This module is the only place that imports PyQt5.QtWidgets at the top
level (other than logs_view.py), and it instantiates QApplication. Keep
all I/O and decision logic in state.py so this class is a thin glue layer
that can be smoke-tested in offscreen mode.
"""

from __future__ import annotations

import signal
import subprocess
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from tray4hermes import __version__
from tray4hermes import paths as _paths
from tray4hermes.icons import STATE_COLORS, STATE_TOOLTIPS, make_icon
from tray4hermes.logs_view import LogDialog
from tray4hermes.paths import REFRESH_INTERVAL_MS, SERVICE
from tray4hermes.state import (
    ACTIVATING,
    ACTIVE,
    WARMING,
    GatewayState,
    TrayState,
    aggregate_state,
    list_profiles,
    load_tray_state,
    read_active_model,
    save_tray_state,
    switch_profile,
)


class HermesTray:
    """Builds and runs the tray. Single public method: run()."""

    def __init__(self) -> None:
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self._tray_state: TrayState = load_tray_state()
        self._icons = {code: make_icon(color) for code, color in STATE_COLORS.items()}
        self._current_code: str | None = None

        # Parent the tray to the QApplication so it survives any parent
        # destruction (the test case showed that without a parent, an
        # immediate show() + DBus register works; inside HermesTray we
        # wanted to be defensive but a parent doesn't hurt).
        self._tray = QSystemTrayIcon(self.app)
        # Set icon and tooltip BEFORE show() so the very first paint
        # already has a glyph. Without this, the tray may register
        # empty and be ignored by KDE's StatusNotifierWatcher.
        self._tray.setIcon(self._icons["unknown"])
        self._tray.setToolTip(STATE_TOOLTIPS["unknown"])
        # Tooltip with menu must also exist for some shells
        self._tray.activated.connect(self._on_activated)

        # Build menu actions (rebuilt on profile change to keep radio group in sync)
        self._profile_group = QActionGroup(self.app)
        self._profile_group.setExclusive(True)
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)

        # Periodic state poll
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(REFRESH_INTERVAL_MS)

        # Run an immediate refresh so the icon is correct on first paint
        # (not the unknown placeholder) — and so the very first
        # StatusNotifierItem registration carries the right glyph.
        self._refresh()

        self._tray.show()
        # Process pending events so the StatusNotifierItem registers on
        # the session bus BEFORE the event loop starts. Without this,
        # some KDE 6 shells see an empty/uninitialized tray and drop
        # the registration.
        self.app.processEvents()
        # DEBUG: confirm registration — removed once the icon is reliable
        if "TRAY4HERMES_DEBUG" in os.environ:
            print(
                f"[tray4hermes] shown={self._tray.isVisible()} "
                f"geometry={self._tray.geometry()} "
                f"iconNull={self._tray.icon().isNull()}",
                file=sys.stderr,
            )

    # ── Menu construction ───────────────────────────────────────────────────
    def _build_menu(self) -> QMenu:
        menu = QMenu()

        self._status_action = QAction("Kontroluji…", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        self._model_action = QAction("Model: ?", menu)
        self._model_action.setEnabled(False)
        menu.addAction(self._model_action)

        menu.addSeparator()

        # Profile submenu — rebuilt every time we open the menu so the radio
        # state always reflects the persisted choice.
        self._profile_menu = menu.addMenu("Profil")
        self._rebuild_profile_menu()

        menu.addSeparator()

        self._start_action = QAction("▶  Start", menu)
        self._start_action.triggered.connect(lambda: self._systemctl("start"))
        menu.addAction(self._start_action)

        self._stop_action = QAction("⏹  Stop", menu)
        self._stop_action.triggered.connect(lambda: self._systemctl("stop"))
        menu.addAction(self._stop_action)

        self._restart_action = QAction("🔄 Restart", menu)
        self._restart_action.triggered.connect(lambda: self._systemctl("restart"))
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

    def _rebuild_profile_menu(self) -> None:
        """(Re)populate the profile submenu with a checked radio for the saved choice."""
        self._profile_menu.clear()
        profiles = list_profiles(_paths.profiles_dir())
        selected = self._tray_state.selected_profile or "default"
        for name in profiles:
            act = QAction(name, self._profile_menu, checkable=True)
            act.setChecked(name == selected)
            act.triggered.connect(lambda _checked, n=name: self._select_profile(n))
            self._profile_group.addAction(act)
            self._profile_menu.addAction(act)

    # ── Actions ──────────────────────────────────────────────────────────────
    def _select_profile(self, name: str) -> None:
        """Persist choice, ask user to confirm, switch + restart gateway."""
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

        ok, out = switch_profile(name)
        if not ok:
            QMessageBox.warning(
                None,
                "Chyba",
                f"Nelze nastavit profil '{name}':\n\n{out or '(bez výstupu)'}\n\n"
                f"Profil musí existovat v {_paths.profiles_dir()}/.",
            )
            return

        self._systemctl("restart")
        QTimer.singleShot(2000, self._refresh)

    def _systemctl(self, action: str) -> None:
        """Fire-and-forget systemd action; refresh after a short delay."""
        # `action` comes from a QAction click (one of {"start","stop","restart"}),
        # not user-provided free text, so S603/S607 (untrusted input) are N/A.
        subprocess.run(  # noqa: S603
            ["systemctl", "--user", action, SERVICE],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        QTimer.singleShot(2000, self._refresh)

    def _show_logs(self) -> None:
        LogDialog().exec_()

    def _open_config(self) -> None:
        config = _paths.config_yaml()
        if config.exists():
            # `xdg-open` is the only thing being launched; it ignores the
            # path's host application and just opens the file. Safe.
            subprocess.Popen(["xdg-open", str(config)])  # noqa: S603,S607
        else:
            QMessageBox.warning(None, "Chyba", f"Config nenalezen:\n{config}")

    def _open_cli(self) -> None:
        cli = _paths.hermes_bin()
        if cli.exists():
            # `konsole` is the user's terminal, the bin path is read-only
            # and the user explicitly chose this action. Safe.
            subprocess.Popen(["konsole", "-e", str(cli)])  # noqa: S603,S607
        else:
            subprocess.Popen(["konsole", "-e", "bash", "-c", "hermes; exec bash"])  # noqa: S603,S607

    def _show_about(self) -> None:
        QMessageBox.information(
            None,
            f"tray4hermes v{__version__}",
            f"<b>tray4hermes v{__version__}</b><br><br>"
            f"Pasivní observer pro Hermes Gateway.<br><br>"
            f"<b>Čte:</b> ~/.hermes/{{gateway_state.json, profiles/, config.yaml, "
            f"logs/gateway.log}}<br>"
            f"<b>Píše:</b> ~/.config/tray4hermes/state.json<br>"
            f"<b>Ovládá:</b> systemctl --user ({SERVICE})<br><br>"
            f"Hermes Agent: github.com/NousResearch/hermes-agent",
        )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_logs()

    def _refresh(self) -> None:
        """Periodic poll — update icon/tooltip/status line + button enablement."""
        state: GatewayState = aggregate_state()
        if state.code != self._current_code:
            self._current_code = state.code
            self._tray.setIcon(self._icons.get(state.code, self._icons["unknown"]))
            self._tray.setToolTip(STATE_TOOLTIPS.get(state.code, state.label))
            self._status_action.setText(state.label)

        self._model_action.setText(f"Model: {read_active_model(_paths.config_yaml())}")

        is_running = state.code in (ACTIVE, WARMING, ACTIVATING)
        self._start_action.setEnabled(not is_running)
        self._stop_action.setEnabled(is_running)
        self._restart_action.setEnabled(True)

    def _quit(self) -> None:
        self.app.quit()
        # Kill the watchdog wrapper (run.sh) so the whole tree exits.
        # Skip when running under pytest — the parent process is pytest itself,
        # and SIGTERM there would just kill the test runner.
        if "PYTEST_CURRENT_TEST" not in os.environ:
            try:
                os.kill(os.getppid(), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        self._cleanup()

    def _cleanup(self) -> None:
        """Best-effort cleanup — never raises."""
        from tray4hermes.lock import release
        from tray4hermes.paths import lock_file

        release(lock_file())

    def run(self) -> int:
        rc = self.app.exec_()
        self._cleanup()
        return rc or 0


# Late import to keep all `os` references in one place; also helps tests.
import os  # noqa: E402
