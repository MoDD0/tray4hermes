"""Tests for the expanded LogSettings + LogSettingsDialog.

Verifies that the dialog exposes and preserves every log-viewer-specific
setting. The global UI language intentionally lives only in TraySettingsDialog.
"""

from __future__ import annotations

from pathlib import Path

from tray4hermes.logs_view import LogSettings, LogSettingsDialog


def test_settings_dialog_has_all_fields(hermes_home: Path, qtbot) -> None:
    s = LogSettings(
        max_lines=1000,
        auto_scroll=False,
        word_wrap=True,
        font_size=12,
        show_levels=("ERROR", "WARNING"),
        show_tracebacks=False,
        time_window_minutes=60,
        reverse_order=True,
    )
    dlg = LogSettingsDialog(s)
    qtbot.addWidget(dlg)

    assert dlg._max_lines.value() == 1000
    assert dlg._font_size.value() == 12
    assert dlg._auto_scroll.isChecked() is False
    assert dlg._word_wrap.isChecked() is True
    assert dlg._reverse.isChecked() is True
    assert dlg._show_tracebacks.isChecked() is False

    tw_idx = dlg._time_window.currentIndex()
    tw_key = dlg._tw_keys[tw_idx]
    assert dlg._tw_map[tw_key] == 60

    for level, cb in dlg._level_checks.items():
        expected = level in ("ERROR", "WARNING")
        assert cb.isChecked() == expected

    assert not hasattr(dlg, "_language")


def test_settings_dialog_result_preserves_all_fields(hermes_home: Path, qtbot) -> None:
    s = LogSettings(
        max_lines=42,
        auto_scroll=True,
        word_wrap=False,
        font_size=14,
        show_levels=("INFO",),
        show_tracebacks=False,
        time_window_minutes=15,
        reverse_order=True,
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


def test_settings_dialog_has_reverse_order_toggle(hermes_home: Path, qtbot) -> None:
    dlg = LogSettingsDialog(LogSettings(reverse_order=True))
    qtbot.addWidget(dlg)
    assert dlg._reverse.isChecked() is True
