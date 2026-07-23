"""Main tray class — builds the menu, owns the timers, reacts to clicks.

This module is the only place that imports PyQt5.QtWidgets at the top
level (other than logs_view.py), and it instantiates QApplication. Keep
all I/O and decision logic in state.py so this class is a thin glue layer
that can be smoke-tested in offscreen mode.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from tray4hermes import __version__
from tray4hermes import paths as _paths
from tray4hermes.icons import STATE_COLORS, STATE_TOOLTIPS, make_icon

# After `i18n.install(...)` runs (in __main__), `tray4hermes.i18n._`
# is bound to the active translation. We use a *dynamic* lookup so
# that switching languages at runtime (via switch_language) is
# picked up by modules that imported `_` at load time. The lambda
# reads ``i18n._`` on every call, not just once at import.
try:
    from tray4hermes import i18n as _i18n_mod

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        """Dynamic gettext wrapper — looks up i18n._ on every call."""
        return _i18n_mod._(s)  # type: ignore[attr-defined]
except ImportError:

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        return s


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

        self._status_action = QAction(_("Checking…"), menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        # ``Model: ?`` — shown in the status block before we've read
        # the config. ``?`` is intentional, not a translation slot.
        self._model_action = QAction(_("Model: ?"), menu)
        self._model_action.setEnabled(False)
        menu.addAction(self._model_action)

        menu.addSeparator()

        # Profile submenu — rebuilt every time we open the menu so the radio
        # state always reflects the persisted choice.
        self._profile_menu = menu.addMenu(_("Profile"))
        self._rebuild_profile_menu()

        menu.addSeparator()

        self._start_action = QAction(_("▶  Start"), menu)
        self._start_action.triggered.connect(lambda: self._systemctl("start"))
        menu.addAction(self._start_action)

        self._stop_action = QAction(_("⏹  Stop"), menu)
        self._stop_action.triggered.connect(lambda: self._systemctl("stop"))
        menu.addAction(self._stop_action)

        self._restart_action = QAction(_("🔄 Restart"), menu)
        self._restart_action.triggered.connect(lambda: self._systemctl("restart"))
        menu.addAction(self._restart_action)

        menu.addSeparator()

        self._logs_action = QAction(_("📋 Logs"), menu)
        self._logs_action.triggered.connect(self._show_logs)
        menu.addAction(self._logs_action)

        self._tray_settings_action = QAction(_("⚙  tray4hermes Settings"), menu)
        self._tray_settings_action.triggered.connect(self._open_tray_settings)
        menu.addAction(self._tray_settings_action)

        self._open_config_action = QAction(_("⚙  Hermes config"), menu)
        self._open_config_action.triggered.connect(self._open_config)
        menu.addAction(self._open_config_action)

        self._open_cli_action = QAction(_("💻  Hermes CLI"), menu)
        self._open_cli_action.triggered.connect(self._open_cli)
        menu.addAction(self._open_cli_action)

        menu.addSeparator()

        self._about_action = QAction(_("ℹ  About tray4hermes") + f" (v{__version__})", menu)
        self._about_action.triggered.connect(self._show_about)
        menu.addAction(self._about_action)

        self._quit_action = QAction(_("✖  Quit tray"), menu)
        self._quit_action.triggered.connect(self._quit)
        menu.addAction(self._quit_action)

        return menu

    def _retranslate_ui(self) -> None:
        """Rebuild the tray menu after changing the gettext language."""
        old_menu = self._menu
        self._profile_group = QActionGroup(self.app)
        self._profile_group.setExclusive(True)
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)
        old_menu.deleteLater()
        self._current_code = None
        self._refresh()

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
            _("Change profile?"),
            _(
                "Restart gateway with profile '{name}'?\n\n"
                "Current session in Discord/Hermes Desktop may briefly disconnect."
            ).format(name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        ok, out = switch_profile(name)
        if not ok:
            QMessageBox.warning(
                None,
                _("Error"),
                _(
                    "Cannot set profile '{name}':\n\n{out_msg}\n\n"
                    "Profile must exist in {profiles_dir}/."
                ).format(
                    name=name,
                    out_msg=out or _("(no output)"),
                    profiles_dir=str(_paths.profiles_dir()),
                ),
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

    def _open_tray_settings(self) -> None:
        """Open the global Tray4Hermes settings dialog.

        This is NOT the log viewer's settings (those live in
        LogSettingsDialog inside the log viewer). This is the
        tray-level control panel: language, default max lines,
        default levels, etc.
        """
        from tray4hermes.tray_settings import (
            TraySettingsDialog,
            load_tray_settings,
            save_tray_settings,
        )

        current = load_tray_settings()
        dlg = TraySettingsDialog(current)
        if dlg.exec_() == QDialog.Accepted:
            new_settings = dlg.result_settings()
            save_tray_settings(new_settings)
            # Apply the language immediately. ``None`` deliberately means
            # "follow the OS locale"; it must not be coerced to English.
            if new_settings.language != current.language:
                try:
                    from tray4hermes.i18n import switch_language

                    switch_language(new_settings.language)
                    self._retranslate_ui()
                except Exception as e:  # noqa: BLE001
                    import sys as _sys

                    print(f"[tray4hermes] language switch failed: {e}", file=_sys.stderr)

    def _open_config(self) -> None:
        config = _paths.config_yaml()
        if not config.exists():
            QMessageBox.warning(
                None, _("Error"), _("Config not found:\n{config}").format(config=config)
            )
            return

        # We never want to open a YAML config in a heavyweight office
        # suite just because that's what KDE happens to associate with
        # ``.yaml``. Resolve a smart editor in this order:
        #   1. ``$VISUAL`` (the user's preferred GUI editor)
        #   2. ``$EDITOR`` (the user's fallback non-GUI editor)
        #   3. A small whitelist of common text editors we know about
        #   4. ``xdg-open`` last-resort (LibreOffice is its default on
        #      Manjaro KDE, hence why we don't pick it eagerly)
        #
        # The launcher is fire-and-forget; we don't wait. Note we use
        # ``shlex.split`` rather than ``shell=True`` so the arguments
        # are tokenized safely (a hostile filename like
        # ``$VISUAL='evil-cmd; rm -rf /'`` would have been a real
        # shell-injection vector). S602/S607 ruff warnings are
        # suppressed because we control both the command surface
        # and the visible UI affordance (this dialog).
        import shlex as _shlex

        cmd_str = self._pick_editor_command(str(config))
        cmd_argv = _shlex.split(cmd_str) if cmd_str else ["xdg-open", str(config)]
        subprocess.Popen(cmd_argv)  # noqa: S603

    @staticmethod
    def _pick_editor_command(target: str) -> str:
        """Return a shell-runnable command that opens `target`.

        Centralised so it's easy to test (and so we don't sprinkle
        ``$VISUAL`` lookups through the code). The launcher is
        expected to be shell-quoted by ``subprocess.Popen(shell=True)``
        — we hand it a single string so the shell can resolve
        ``$VISUAL`` / ``$EDITOR`` at run-time, the same way a user
        would.
        """
        import os
        import shutil

        # 1 / 2 — honour user env vars. ``$VISUAL`` precedes ``$EDITOR``
        # by long-standing convention (visual = full-screen, editor =
        # fallback). Strip surrounding quotes if any.
        for var in ("VISUAL", "EDITOR"):
            val = os.environ.get(var, "").strip()
            if not val:
                continue
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            if val and shutil.which(val.split()[0]):
                # We always append the target path as a separate
                # token. The shell tokens it for us; the editor's
                # own argv parser picks the file up correctly. This
                # means a ``$VISUAL='code -w'`` setting still works
                # (``code -w /tmp/foo.yaml`` opens the file with
                # ``--wait``), and a plain ``$VISUAL='vim'`` setting
                # becomes ``vim /tmp/foo.yaml`` without surprises.
                return f"{val} {target}"

        # 3 — common GUI/text editors that ship with Manjaro KDE or
        # Kubuntu. Order matters: prefer graphical editors so the
        # user sees the file in their existing window stack.
        for editor in ("kate", "kwrite", "gedit", "xed", "micro", "nano", "vim", "vi"):
            path = shutil.which(editor)
            if path:
                return f"{path} {target}"

        # 4 — last resort. On Manjaro KDE this typically hands the
        # file to LibreOffice, which is not what we want for a
        # YAML config, but it's better than nothing.
        return f"xdg-open {target}"

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
            _(
                "<b>tray4hermes v{version}</b><br><br>"
                "Passive observer for Hermes Gateway.<br><br>"
                "<b>Reads:</b> ~/.hermes/{{gateway_state.json, profiles/, config.yaml, "
                "logs/gateway.log}}<br>"
                "<b>Writes:</b> ~/.config/tray4hermes/state.json<br>"
                "<b>Controls:</b> systemctl --user ({service})<br><br>"
                "Hermes Agent: github.com/NousResearch/hermes-agent"
            ).format(
                version=__version__,
                service=SERVICE,
            ),
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
