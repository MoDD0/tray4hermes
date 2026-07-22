"""Tests for the global TraySettings + TraySettingsDialog.

Covers:
1. TraySettings round-trips through JSON (to_json/from_json).
2. Language None / "cs" / "" round-trips correctly.
3. load_tray_settings reads from state.json.
4. save_tray_settings writes into state.json under 'tray_settings'.
5. TraySettingsDialog exposes ALL fields (language, max_lines,
   auto_scroll, word_wrap, levels).
6. result_settings() preserves ALL fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from tray4hermes.tray_settings import (
    TraySettings,
    TraySettingsDialog,
    load_tray_settings,
    save_tray_settings,
)


def test_default_settings() -> None:
    s = TraySettings.default()
    assert s.language is None
    assert s.default_max_lines == 2000
    assert "ERROR" in s.default_show_levels
    assert s.default_auto_scroll is True
    assert s.default_word_wrap is False
    assert s.schema_version == 1


def test_json_round_trip() -> None:
    s = TraySettings(
        language="cs",
        default_max_lines=500,
        default_show_levels=("ERROR", "WARNING"),
        default_auto_scroll=False,
        default_word_wrap=True,
    )
    j = s.to_json()
    s2 = TraySettings.from_json(j)
    assert s2.language == "cs"
    assert s2.default_max_lines == 500
    assert s2.default_show_levels == ("ERROR", "WARNING")
    assert s2.default_auto_scroll is False
    assert s2.default_word_wrap is True


def test_language_none_round_trips() -> None:
    s = TraySettings(language=None)
    j = s.to_json()
    assert j["language"] is None
    s2 = TraySettings.from_json(j)
    assert s2.language is None


def test_language_empty_string_normalises_to_none() -> None:
    j: dict[str, object] = {"language": ""}
    s = TraySettings.from_json(j)
    assert s.language is None


def test_save_and_load_round_trip(hermes_home: Path) -> None:
    s = TraySettings(
        language="cs",
        default_max_lines=100,
        default_show_levels=("ERROR",),
        default_auto_scroll=False,
        default_word_wrap=True,
    )
    save_tray_settings(s)
    loaded = load_tray_settings()
    assert loaded.language == "cs"
    assert loaded.default_max_lines == 100
    assert loaded.default_show_levels == ("ERROR",)
    assert loaded.default_auto_scroll is False
    assert loaded.default_word_wrap is True


def test_save_writes_to_state_json(hermes_home: Path) -> None:
    """The tray_settings key must land in state.json."""
    from tray4hermes.paths import tray_state_file

    s = TraySettings(language="en", default_max_lines=42)
    save_tray_settings(s)
    p = tray_state_file()
    assert p.exists()
    data = json.loads(p.read_text())
    assert "tray_settings" in data
    assert data["tray_settings"]["language"] == "en"
    assert data["tray_settings"]["default_max_lines"] == 42


def test_load_returns_default_when_file_missing(hermes_home: Path) -> None:
    """If state.json doesn't exist, we get defaults."""
    s = load_tray_settings()
    assert s.language is None
    assert s.default_max_lines == 2000


def test_dialog_has_all_fields(hermes_home: Path, qtbot) -> None:
    s = TraySettings(
        language="cs",
        default_max_lines=500,
        default_show_levels=("ERROR", "WARNING"),
        default_auto_scroll=False,
        default_word_wrap=True,
    )
    dlg = TraySettingsDialog(s)
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Nastavení tray4hermes"
    assert dlg._max_lines.value() == 500
    assert dlg._auto_scroll.isChecked() is False
    assert dlg._word_wrap.isChecked() is True
    for level, cb in dlg._level_checks.items():
        expected = level in ("ERROR", "WARNING")
        assert cb.isChecked() == expected


def test_dialog_result_preserves_all_fields(hermes_home: Path, qtbot) -> None:
    s = TraySettings(
        language="cs",
        default_max_lines=300,
        default_show_levels=("INFO",),
        default_auto_scroll=True,
        default_word_wrap=False,
    )
    dlg = TraySettingsDialog(s)
    qtbot.addWidget(dlg)
    result = dlg.result_settings()
    assert result.language == "cs"
    assert result.default_max_lines == 300
    assert result.default_show_levels == ("INFO",)
    assert result.default_auto_scroll is True
    assert result.default_word_wrap is False


def test_dialog_language_system_default(hermes_home: Path, qtbot) -> None:
    s = TraySettings(language=None)
    dlg = TraySettingsDialog(s)
    qtbot.addWidget(dlg)
    assert dlg._language.currentIndex() == 0
    assert dlg._lang_keys[0] is None
