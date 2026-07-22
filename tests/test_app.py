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
        # Write some lines to a log file in the standard location
        log = hermes_home / "logs" / "gateway.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("line 1\nline 2\nline 3\n")
        from tray4hermes.logs_view import LogDialog

        dlg = LogDialog()
        dlg._refresh()
        text = dlg._editor.toPlainText()
        assert "line 1" in text
        assert "line 3" in text

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
