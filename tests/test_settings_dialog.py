"""Tests for the expanded LogSettings + LogSettingsDialog.

Verifies:
1. ``language`` field round-trips through to_json/from_json.
2. ``None`` (default) means "follow OS locale" and persists as null.
3. A specific language code ("cs") persists and is read back.
4. Empty string in JSON normalises to None (backwards-compat).
5. ``LogSettingsDialog`` exposes ALL settings fields (not just
   the old max_lines/font/auto_scroll/word_wrap/levels subset).
"""

from __future__ import annotations

import json
from pathlib import Path

from tray4hermes.logs_view import LogSettings, LogSettingsDialog


def test_language_defaults_to_none() -> None:
    """Default LogSettings.language is None = 'follow OS locale'."""
    s = LogSettings.default()
    assert s.language is None


def test_language_round_trip_cs() -> None:
    """A specific language code survives to_json → from_json."""
    s = LogSettings(language="cs")
    j = s.to_json()
    assert j["language"] == "cs"
    s2 = LogSettings.from_json(j)
    assert s2.language == "cs"


def test_language_none_round_trip() -> None:
    """None (follow OS locale) round-trips as JSON null."""
    s = LogSettings(language=None)
    j = s.to_json()
    assert j["language"] is None
    s2 = LogSettings.from_json(j)
    assert s2.language is None


def test_language_empty_string_normalises_to_none() -> None:
    """An empty string in JSON (from old state files or user edits)
    should be treated as None, not ''."""
    j = {"language": ""}
    s = LogSettings.from_json(j)
    assert s.language is None


def test_language_persists_in_state_json(hermes_home: Path, qtbot) -> None:
    """When we save settings with a language, it lands in state.json."""
    from tray4hermes.logs_view import _save_log_settings

    s = LogSettings(language="cs", max_lines=500)
    _save_log_settings(s)

    state_file = hermes_home.parent / "xdg" / "tray4hermes" / "state.json"
    # The state file is under XDG_CONFIG_HOME which the conftest
    # sets to a tmp_path sibling of hermes_home.
    # Find it via the paths module instead.
    from tray4hermes.paths import tray_state_file

    state_file = tray_state_file()
    assert state_file.exists(), f"state.json not written to {state_file}"
    data = json.loads(state_file.read_text())
    assert data["log_settings"]["language"] == "cs"


def test_settings_dialog_has_all_fields(hermes_home: Path, qtbot) -> None:
    """LogSettingsDialog must expose every LogSettings field.

    This is the regression test for the bug where the dialog only
    had max_lines/font_size/auto_scroll/word_wrap/show_levels but
    was missing time_window, reverse_order, show_tracebacks, and
    language.
    """
    s = LogSettings(
        max_lines=1000,
        auto_scroll=False,
        word_wrap=True,
        font_size=12,
        show_levels=("ERROR", "WARNING"),
        show_tracebacks=False,
        time_window_minutes=60,
        reverse_order=True,
        language="cs",
    )
    dlg = LogSettingsDialog(s)
    qtbot.addWidget(dlg)

    # ── Verify every field is represented in the dialog ────────────
    assert dlg._max_lines.value() == 1000
    assert dlg._font_size.value() == 12
    assert dlg._auto_scroll.isChecked() is False
    assert dlg._word_wrap.isChecked() is True
    assert dlg._reverse.isChecked() is True
    assert dlg._show_tracebacks.isChecked() is False

    # Time window combo
    tw_idx = dlg._time_window.currentIndex()
    tw_key = dlg._tw_keys[tw_idx]
    assert dlg._tw_map[tw_key] == 60  # 1h = 60 minutes

    # Level checkboxes
    for level, cb in dlg._level_checks.items():
        expected = level in ("ERROR", "WARNING")
        assert cb.isChecked() == expected, (
            f"level {level}: expected {expected}, got {cb.isChecked()}"
        )

    # Language combo
    lang_idx = dlg._language.currentIndex()
    lang_val = dlg._lang_keys[lang_idx]
    assert lang_val == "cs"


def test_settings_dialog_result_preserves_all_fields(hermes_home: Path, qtbot) -> None:
    """result_settings() must return a LogSettings with every
    field populated from the dialog widgets — not just the old
    subset."""
    s = LogSettings(
        max_lines=42,
        auto_scroll=True,
        word_wrap=False,
        font_size=14,
        show_levels=("INFO",),
        show_tracebacks=False,
        time_window_minutes=15,
        reverse_order=True,
        language="en",
    )
    dlg = LogSettingsDialog(s)
    qtbot.addWidget(dlg)

    result = dlg.result_settings()
    assert result.max_lines == 42
    assert result.auto_scroll is True
    assert result.word_wrap is False
    assert result.font_size == 14
    assert result.show_levels == ("INFO",)
    assert result.show_tracebacks is False
    assert result.time_window_minutes == 15
    assert result.reverse_order is True
    assert result.language == "en"


def test_settings_dialog_language_system_default(hermes_home: Path, qtbot) -> None:
    """When language is None, the combo shows 'System' (index 0)."""
    s = LogSettings(language=None)
    dlg = LogSettingsDialog(s)
    qtbot.addWidget(dlg)
    assert dlg._language.currentIndex() == 0
    assert dlg._lang_keys[0] is None
