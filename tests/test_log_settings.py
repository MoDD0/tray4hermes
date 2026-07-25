"""Persistence of LogSettings — serialization and the settings dialog.

Two regressions live here:

* the settings dialog rebuilt LogSettings from widget state only, so
  confirming it wiped the stored window geometry;
* one unreadable field in state.json threw away *every* other stored
  preference, because the whole `from_json` call was wrapped in a
  single fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5.QtWidgets import QDialog

pytestmark = pytest.mark.usefixtures("qtbot")

_GEOMETRY = b"\x01\xd9\xd0\xcb\x00\x03\x00\x00fake-qt-geometry-blob"


def _write_state(xdg_config: Path, log_settings: dict) -> None:
    import json

    from tray4hermes.paths import tray_state_file

    path = tray_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "log_settings": log_settings}))


class TestGeometryRoundTrip:
    def test_to_json_from_json_preserves_geometry(self) -> None:
        from tray4hermes.log_settings import LogSettings

        original = LogSettings(window_geometry=_GEOMETRY)

        restored = LogSettings.from_json(original.to_json())

        assert restored.window_geometry == _GEOMETRY

    def test_settings_dialog_result_keeps_geometry(self, qtbot) -> None:
        """The dialog has no geometry widget, so it has to carry the
        incoming value through untouched."""
        from tray4hermes.log_settings import LogSettings, LogSettingsDialog

        dlg = LogSettingsDialog(LogSettings(window_geometry=_GEOMETRY))
        qtbot.addWidget(dlg)

        assert dlg.result_settings().window_geometry == _GEOMETRY

    def test_settings_dialog_result_still_reflects_edited_widgets(self, qtbot) -> None:
        """Carrying geometry through must not turn the dialog into a
        pass-through — the edited fields still have to win."""
        from tray4hermes.log_settings import LogSettings, LogSettingsDialog

        dlg = LogSettingsDialog(LogSettings(max_lines=2000, font_size=9))
        qtbot.addWidget(dlg)
        dlg._max_lines.setValue(4321)
        dlg._font_size.setValue(14)

        result = dlg.result_settings()

        assert result.max_lines == 4321
        assert result.font_size == 14

    def test_confirming_settings_does_not_wipe_stored_geometry(
        self, hermes_home, xdg_config, qtbot, monkeypatch
    ) -> None:
        """`_open_settings` saves whatever `result_settings()` returns.
        With geometry dropped there, one trip through the settings
        dialog erased the window position from state.json — and a crash
        before the next clean close lost it for good."""
        from tray4hermes.log_dialog import LogDialog
        from tray4hermes.log_settings import LogSettings, load_log_settings

        _write_state(xdg_config, LogSettings(window_geometry=_GEOMETRY).to_json())
        monkeypatch.setattr(
            "tray4hermes.log_dialog.LogSettingsDialog.exec_",
            lambda self: QDialog.Accepted,
        )
        dlg = LogDialog()
        qtbot.addWidget(dlg)
        assert dlg._settings.window_geometry == _GEOMETRY, "precondition: geometry was loaded"

        dlg._open_settings()

        assert load_log_settings().window_geometry == _GEOMETRY


class TestMalformedState:
    def test_corrupt_geometry_only_drops_the_geometry(self) -> None:
        """`binascii.Error` subclasses `ValueError`, so a damaged base64
        blob used to be caught by the catch-all fallback and take every
        other preference down with it."""
        from tray4hermes.log_settings import LogSettings

        stored = LogSettings(
            max_lines=777,
            font_size=17,
            reverse_order=True,
            show_tracebacks=False,
            time_window_minutes=60,
        ).to_json()
        stored["window_geometry"] = "not!!!base64"

        restored = LogSettings.from_json(stored)

        assert restored.window_geometry is None
        assert restored.max_lines == 777
        assert restored.font_size == 17
        assert restored.reverse_order is True
        assert restored.show_tracebacks is False
        assert restored.time_window_minutes == 60

    @pytest.mark.parametrize(
        "broken",
        [
            {"max_lines": {}},
            {"max_lines": "many"},
            {"font_size": []},
            {"time_window_minutes": None},
            {"show_levels": 5},
        ],
        ids=["dict-max-lines", "text-max-lines", "list-font-size", "null-window", "int-levels"],
    )
    def test_unreadable_field_falls_back_to_the_default_for_that_field(self, broken: dict) -> None:
        """`from_json` promises it never raises. `int({})` raises
        TypeError, which the old fallback did not catch."""
        from tray4hermes.log_settings import LogSettings

        stored = LogSettings(max_lines=777, font_size=17).to_json()
        stored.update(broken)
        defaults = LogSettings()

        restored = LogSettings.from_json(stored)

        for field, bad_value in broken.items():
            assert getattr(restored, field) == getattr(defaults, field), (
                f"{field}={bad_value!r} should fall back to the default"
            )
        # Fields around the damaged one are untouched.
        untouched = {"max_lines": 777, "font_size": 17}
        for field, value in untouched.items():
            if field not in broken:
                assert getattr(restored, field) == value

    def test_load_log_settings_never_raises_on_a_broken_file(self, hermes_home, xdg_config) -> None:
        from tray4hermes.log_settings import load_log_settings

        _write_state(xdg_config, {"max_lines": {}, "auto_scroll": "yes"})

        assert load_log_settings().max_lines == 2000
