"""Keyboard shortcuts of the log viewer.

Every test here drives the *real* key path: the dialog is shown and
activated, then `QTest.keyClick` delivers the key the same way the
window system would. That matters — the bug these tests were written
against was four `QAction` objects that were constructed but never
handed to `addAction()`, so their `shortcut=` never reached the
shortcut map. Asserting "the callback works when called directly"
would have passed the whole time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5 import sip
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

pytestmark = pytest.mark.usefixtures("qtbot")

_LOG = (
    "2026-07-22 10:00:00 INFO needle one\n"
    "2026-07-22 10:00:01 INFO haystack\n"
    "2026-07-22 10:00:02 INFO needle two\n"
)


def _cursor_line(dlg) -> str:
    """Text of the block the editor cursor currently sits on."""
    return dlg._editor.textCursor().block().text()


@pytest.fixture
def dialog(hermes_home: Path, qtbot):
    """A shown, activated LogDialog with three lines of log content."""
    log = hermes_home / "logs" / "gateway.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(_LOG)

    from tray4hermes.logs_view import LogDialog

    dlg = LogDialog()
    # Wide enough that the whole toolbar fits. At the default 900×500 the
    # find bar overflows into the toolbar's extension popup, where it is
    # not visible — and `setFocus()` on a hidden widget does nothing.
    dlg.resize(1800, 600)
    dlg.show()
    qtbot.waitExposed(dlg)
    # Shortcuts with the default WindowShortcut context are only
    # delivered to the *active* window.
    QApplication.setActiveWindow(dlg)
    dlg._editor.setFocus()
    yield dlg
    # Destroy the window for real — `qtbot.addWidget` only closes it, and
    # a merely-hidden LogDialog keeps its F3 / Shift+F3 bindings in the
    # shortcut map. Qt then sees an ambiguous overload and the *next*
    # dialog's shortcuts silently stop firing. Hence no addWidget here.
    dlg.close()
    sip.delete(dlg)
    QApplication.processEvents()


class TestEditorKeyHandling:
    def test_f3_in_editor_does_not_raise(self, hermes_home, qtbot) -> None:
        """A bare LogTextEdit used to call `self._find_next(...)`, which
        does not exist anywhere in the package — every F3 with focus in
        the editor raised AttributeError."""
        from tray4hermes.logs_view import LogTextEdit

        editor = LogTextEdit()
        qtbot.addWidget(editor)
        editor.setPlainText("needle\n")

        QTest.keyClick(editor, Qt.Key_F3)
        QTest.keyClick(editor, Qt.Key_F3, Qt.ShiftModifier)


class TestDialogShortcuts:
    @pytest.mark.parametrize("sequence", ["Ctrl+F", "F3", "Shift+F3"])
    def test_shortcut_is_registered_on_the_dialog(self, dialog, sequence) -> None:
        """`QAction(parent=dlg, shortcut=...)` alone is not enough: until
        the action is passed to `dlg.addAction()` it never appears in
        `dlg.actions()` and never receives a key event."""
        registered = [a.shortcut() for a in dialog.actions()]
        assert QKeySequence(sequence) in registered, (
            f"{sequence} is not registered on the dialog; registered: "
            f"{[s.toString() for s in registered]}"
        )

    def test_ctrl_f_moves_focus_to_the_search_box(self, dialog) -> None:
        assert not dialog._search.hasFocus()

        QTest.keyClick(dialog._editor, Qt.Key_F, Qt.ControlModifier)

        assert dialog._search.hasFocus(), "Ctrl+F did not focus the search box"

    def test_f3_walks_forward_through_matches(self, dialog) -> None:
        dialog._search.setText("needle")

        QTest.keyClick(dialog._editor, Qt.Key_F3)
        assert "needle one" in _cursor_line(dialog)

        QTest.keyClick(dialog._editor, Qt.Key_F3)
        assert "needle two" in _cursor_line(dialog)

    def test_shift_f3_walks_backward_through_matches(self, dialog) -> None:
        dialog._search.setText("needle")
        # Walk forward to the second match first, so backward has
        # somewhere to go.
        QTest.keyClick(dialog._editor, Qt.Key_F3)
        QTest.keyClick(dialog._editor, Qt.Key_F3)
        assert "needle two" in _cursor_line(dialog)

        QTest.keyClick(dialog._editor, Qt.Key_F3, Qt.ShiftModifier)

        assert "needle one" in _cursor_line(dialog)

    def test_f3_selects_the_match(self, dialog) -> None:
        dialog._search.setText("haystack")

        QTest.keyClick(dialog._editor, Qt.Key_F3)

        assert dialog._editor.textCursor().selectedText() == "haystack"


class TestEscape:
    def test_escape_clears_the_search_and_returns_focus_to_the_editor(self, dialog) -> None:
        dialog._search.setText("needle")
        dialog._search.setFocus()

        QTest.keyClick(dialog._search, Qt.Key_Escape)

        assert dialog._search.text() == "", "Escape left the search term behind"
        assert dialog._editor.hasFocus(), "Escape did not hand focus back to the editor"

    def test_escape_outside_the_search_box_closes_the_dialog(self, dialog) -> None:
        """Esc must keep its standard QDialog meaning when the user is
        not in the find bar — registering it as an application shortcut
        would have taken that away."""
        dialog._editor.setFocus()

        QTest.keyClick(dialog._editor, Qt.Key_Escape)

        assert not dialog.isVisible(), "Escape in the editor should close the viewer"
