"""Smoke tests for the full app in offscreen Qt mode.

These exercise the actual HermesTray class end-to-end: menu construction,
timer firing, profile menu rebuild. They do NOT block on user dialogs or
touch the real ~/.hermes/ (conftest.py isolates everything).

We monkey-patch ``aggregate_state`` so the tray never calls systemd during
tests — that would either hit the real gateway running on the dev
machine, or block waiting for a missing service.
"""

from __future__ import annotations

import json

import pytest

from tray4hermes.state import GatewayState

# pytest-qt provides the qtbot fixture and sets QT_QPA_PLATFORM=offscreen.
pytestmark = pytest.mark.usefixtures("qtbot")


# A stable fake state used across all tests
_FAKE_STATE = GatewayState(code="active", label="Test fake state")


@pytest.fixture(autouse=True)
def _stub_aggregate_state(monkeypatch):
    """Never call the real aggregate_state / systemd in tests."""
    monkeypatch.setattr(
        "tray4hermes.app.aggregate_state",
        lambda: _FAKE_STATE,
    )


class TestHermesTrayConstruction:
    def test_constructs_with_empty_hermes(self, hermes_home) -> None:
        from tray4hermes.app import HermesTray

        tray = HermesTray()
        try:
            # Menu must exist and contain the expected top-level items
            assert tray._menu is not None
            actions = [a.text() for a in tray._menu.actions() if a.text()]
            assert any("Profil" in t for t in actions), "missing profile submenu"
            assert any("Start" in t for t in actions)
            assert any("Logy" in t for t in actions)
        finally:
            tray._quit()

    def test_state_changes_reflect_in_tray(self, hermes_home, qtbot) -> None:
        from tray4hermes.app import HermesTray

        tray = HermesTray()
        try:
            # Initial state is whatever _stub_aggregate_state returns
            tray._refresh()
            qtbot.wait(50)
            assert tray._current_code == "active"
        finally:
            tray._quit()

    def test_profile_menu_includes_default(self, hermes_home, qtbot) -> None:
        from tray4hermes.app import HermesTray

        tray = HermesTray()
        try:
            profile_actions = [a.text() for a in tray._profile_menu.actions()]
            assert "default" in profile_actions
        finally:
            tray._quit()

    def test_persisted_profile_is_checked(self, hermes_home, xdg_config, qtbot) -> None:
        from tray4hermes import paths as _paths
        from tray4hermes.app import HermesTray

        _paths.tray_config_dir().mkdir(parents=True, exist_ok=True)
        _paths.tray_state_file().write_text(
            json.dumps({"version": 1, "selected_profile": "default"})
        )
        tray = HermesTray()
        try:
            default_action = next(a for a in tray._profile_menu.actions() if a.text() == "default")
            assert default_action.isChecked() is True
        finally:
            tray._quit()

    def test_profiles_from_disk_appear_in_menu(
        self,
        hermes_home,
        qtbot,
    ) -> None:
        # Create two extra profiles; the menu should reflect them
        (hermes_home / "profiles" / "alpha").mkdir()
        (hermes_home / "profiles" / "zeta").mkdir()
        from tray4hermes.app import HermesTray

        tray = HermesTray()
        try:
            profile_actions = [a.text() for a in tray._profile_menu.actions()]
            assert "default" in profile_actions
            assert "alpha" in profile_actions
            assert "zeta" in profile_actions
            # default must come first regardless of alphabet
            assert profile_actions[0] == "default"
        finally:
            tray._quit()


class TestLogDialog:
    def test_dialog_construction_with_missing_log(self, hermes_home, qtbot) -> None:
        # No log file → dialog must still construct and not crash
        from tray4hermes.logs_view import LogDialog

        dlg = LogDialog()
        # Manually invoke the first refresh — it should swallow the OSError
        dlg._refresh()
        assert dlg._editor.toPlainText() == ""

    def test_dialog_reads_existing_log(self, hermes_home, qtbot) -> None:
        # Write some lines that include a level, plus a traceback
        # continuation, so they survive the default filter
        # (show_tracebacks=True).
        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "2026-07-22 10:00:00 INFO line 1\n"
            "2026-07-22 10:00:01 INFO line 2\n"
            "2026-07-22 10:00:02 INFO line 3\n"
        )
        from tray4hermes.logs_view import LogDialog

        dlg = LogDialog()
        dlg._refresh()
        text = dlg._editor.toPlainText()
        assert "line 1" in text
        assert "line 3" in text

    def test_reverse_order_toggle(self, hermes_home, qtbot) -> None:
        # Default order: newest at bottom (tail -f). Reversed: newest at top.
        from tray4hermes.logs_view import LogDialog, LogSettings

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "2026-07-22 10:00:00 INFO first\n"
            "2026-07-22 10:00:01 INFO second\n"
            "2026-07-22 10:00:02 INFO third\n"
        )
        dlg = LogDialog()
        dlg._refresh()
        original = dlg._editor.toPlainText().splitlines()
        assert original[0].endswith("first")
        assert original[-1].endswith("third")

        # Toggle reverse
        object.__setattr__(dlg, "_settings", LogSettings(reverse_order=True))
        dlg._refresh()
        reversed_lines = dlg._editor.toPlainText().splitlines()
        assert reversed_lines[0].endswith("third")
        assert reversed_lines[-1].endswith("first")

    def test_time_filter_disabled_keeps_all(self, hermes_home, qtbot) -> None:
        # With time_window_minutes=0 the filter is disabled; everything
        # in the file passes through.
        from datetime import datetime, timedelta

        from tray4hermes.logs_view import LogDialog

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        old_dt = datetime.now() - timedelta(days=365)  # a year ago
        log.write_text(
            f"{old_dt.strftime('%Y-%m-%d %H:%M:%S')} INFO very_old_line\n"
            f"{old_dt.strftime('%Y-%m-%d %H:%M:%S')} ERROR very_old_error\n"
        )
        dlg = LogDialog()
        # Default (time_window_minutes=0) → no time filter
        dlg._refresh()
        text = dlg._editor.toPlainText()
        assert "very_old_line" in text
        assert "very_old_error" in text

    def test_max_lines_spinbox_zero_means_unlimited(self, hermes_home, qtbot) -> None:
        # Setting max_lines=0 removes the rolling-window cap.
        from tray4hermes.logs_view import LogDialog, LogSettings

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(f"2026-07-22 10:00:{i:02d} INFO line {i}" for i in range(50)))
        dlg = LogDialog()
        object.__setattr__(dlg, "_settings", LogSettings(max_lines=0))
        dlg._apply_settings()
        dlg._refresh()
        # No rolling cap → all 50 lines pass through
        assert "line 0" in dlg._editor.toPlainText()
        assert "line 49" in dlg._editor.toPlainText()
        # "## Human Summary" / "rss=218MB" / "archived 31 skill(s):" are
        # neither level-tagged nor traceback continuations. They should
        # be dropped when the filter is active (i.e. always with the
        # current default).
        from tray4hermes.logs_view import LogDialog

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "## Human Summary\n"
            "rss=218MB threads=7\n"
            "archived 31 skill(s):\n"
            "  • foo → bar\n"
            "2026-07-22 10:00:00 INFO  real line\n"
        )
        dlg = LogDialog()
        dlg._refresh()
        text = dlg._editor.toPlainText()
        assert "real line" in text
        assert "Human Summary" not in text
        assert "rss=218MB" not in text
        assert "archived" not in text

    def test_traceback_lines_dropped_when_toggle_off(self, hermes_home, qtbot) -> None:
        # A real Python traceback, with TRACEBACK toggle off, should be
        # hidden — even though the triggering ERROR line stays visible.
        from tray4hermes.logs_view import LogDialog, LogSettings

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "2026-07-22 10:00:00 ERROR something failed\n"
            "Traceback (most recent call last):\n"
            '  File "x.py", line 1, in <module>\n'
            "    raise RuntimeError('boom')\n"
            "RuntimeError: boom\n"
        )
        dlg = LogDialog()
        object.__setattr__(
            dlg,
            "_settings",
            LogSettings(
                show_levels=("ERROR", "WARNING", "INFO", "DEBUG", "TRACE"),
                show_tracebacks=False,
            ),
        )
        dlg._refresh()
        text = dlg._editor.toPlainText()
        assert "ERROR something failed" in text
        assert "Traceback" not in text
        assert 'File "x.py"' not in text
        assert "RuntimeError: boom" not in text

    def test_level_filter_hides_other_levels(self, hermes_home, qtbot) -> None:
        # If only ERROR is enabled, WARN/INFO lines should be hidden after refresh
        from tray4hermes.logs_view import LogDialog

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "2026-07-22 10:00:00 INFO  this is info\n"
            "2026-07-22 10:00:01 WARN  this is warn\n"
            "2026-07-22 10:00:02 ERROR this is error\n"
        )
        dlg = LogDialog()
        from tray4hermes.logs_view import LogSettings

        # LogSettings is a frozen dataclass — bypass the frozen check to
        # swap in a settings object with a different level filter.
        object.__setattr__(dlg, "_settings", LogSettings(show_levels=("ERROR",)))
        dlg._refresh()
        text = dlg._editor.toPlainText()
        assert "this is error" in text
        assert "this is info" not in text
        assert "this is warn" not in text

    def test_max_lines_buffer_limit(self, hermes_home, qtbot) -> None:
        # setMaximumBlockCount trims old lines from the top
        from tray4hermes.logs_view import LogDialog, LogSettings

        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(f"2026-07-22 10:00:{i:02d} INFO line {i}" for i in range(50)))
        dlg = LogDialog()
        dlg._settings = LogSettings(max_lines=10)
        dlg._apply_settings()
        dlg._refresh()
        block_count = dlg._editor.blockCount()
        # 10 visible lines + maybe a trailing empty block
        assert block_count <= 11
        # Newest content is preserved
        assert "line 49" in dlg._editor.toPlainText()
        # Oldest content is dropped
        assert "line 0" not in dlg._editor.toPlainText()
