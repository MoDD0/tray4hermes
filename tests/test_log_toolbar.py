"""Toolbar layout of the log viewer at realistic window sizes.

Everything in the viewer's toolbar used to sit on a single row that
needs far more width than the dialog's default 900 px. Qt does not
shrink a toolbar — it moves the tail end into an extension popup that
is closed by default, so those controls simply are not on screen.
That silently swallowed *Settings*, the only way into the full
configuration dialog.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5 import sip
from PyQt5.QtWidgets import QApplication

pytestmark = pytest.mark.usefixtures("qtbot")


def _hidden_items(dlg) -> list[str]:
    """Labels of toolbar entries that are not on screen right now."""
    hidden: list[str] = []
    for toolbar in dlg.findChildren(type(dlg._toolbar)):
        for action in toolbar.actions():
            widget = toolbar.widgetForAction(action)
            if widget is None or action.isSeparator():
                continue
            if not widget.isVisible():
                label = action.text() or getattr(widget, "text", lambda: "")()
                hidden.append(label or type(widget).__name__)
    return hidden


@pytest.fixture
def dialog(hermes_home: Path, qtbot):
    log = hermes_home / "logs" / "gateway.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-07-27 09:00:00 INFO up\n")

    from tray4hermes.logs_view import LogDialog

    dlg = LogDialog()
    dlg.show()
    qtbot.waitExposed(dlg)
    yield dlg
    dlg.close()
    sip.delete(dlg)
    QApplication.processEvents()


@pytest.mark.parametrize("width", [1100, 1400, 1800])
def test_no_toolbar_control_is_pushed_off_screen(dialog, width: int) -> None:
    """1100 px rather than the dialog's own 900 on purpose.

    Widths here are a compromise, not a target. On a real X11 desktop
    both rows fit into 900 px with 164–239 px to spare (checked in
    English and Czech). The offscreen platform used by the test suite
    has no fontconfig, so it falls back to a font roughly 40 % wider
    and reports 901–1010 px for the first row — a number no user ever
    sees. 1100 px clears that inflated measurement while still failing
    loudly on the bug this guards: back on a single row the toolbar
    wanted 1975 px, so everything past the filters would still be in
    the overflow popup here.
    """
    dialog.resize(width, 500)
    QApplication.processEvents()

    assert _hidden_items(dialog) == [], (
        f"at {width} px these controls fell into the toolbar overflow popup"
    )


def test_level_filters_do_not_share_a_row_with_the_controls(dialog) -> None:
    """The structural half of the guard, and the font-independent one.

    Whatever the metrics, the filters must live on a toolbar of their
    own — that is what stops the row from growing past any sane window
    width and swallowing *Settings*.
    """
    assert dialog._filter_toolbar is not dialog._toolbar

    main_row = {a.text() for a in dialog._toolbar.actions()}
    assert "Settings" in main_row
    for level in ("ERROR", "INFO", "DEBUG"):
        assert level not in main_row, f"{level} is back on the main toolbar row"


def test_neither_row_carries_the_bulk_of_the_toolbar(dialog) -> None:
    """A split that leaves 90 % of the width on one row is not a split.

    Expressed as a ratio so it holds under any font.
    """
    row1 = dialog._toolbar.sizeHint().width()
    row2 = dialog._filter_toolbar.sizeHint().width()

    assert max(row1, row2) / (row1 + row2) < 0.65, (
        f"toolbar rows are lopsided: {row1} px vs {row2} px"
    )
