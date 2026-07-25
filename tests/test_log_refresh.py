"""What the viewer does when the log file cannot be read.

`_refresh` runs from a 2-second timer. Its OSError branch used to be a
bare `return`: no editor content, no status update, nothing on stderr —
thirty times a minute. The status bar kept the numbers from the last
successful read, so it did not merely stay silent, it stated something
untrue.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("qtbot")


@pytest.fixture
def dialog(hermes_home, qtbot):
    from tray4hermes.logs_view import LogDialog

    dlg = LogDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_missing_log_is_reported_in_the_status_bar(dialog, hermes_home) -> None:
    log = hermes_home / "logs" / "gateway.log"
    assert not log.exists(), "precondition: the gateway has never written a log"

    dialog._refresh()

    assert str(log) in dialog._status.text(), (
        f"the status bar should name the unreadable file; got: {dialog._status.text()!r}"
    )


def test_unreadable_log_is_reported_in_the_status_bar(dialog, hermes_home, monkeypatch) -> None:
    """Not just "missing" — any OSError (permissions, mid-rotation,
    I/O error) has to surface."""
    directory = hermes_home / "logs"
    monkeypatch.setattr("tray4hermes.paths.gateway_log", lambda: directory)

    dialog._refresh()

    assert str(directory) in dialog._status.text()


def test_the_editor_is_left_empty_rather_than_filled_with_the_error(dialog) -> None:
    """The error belongs in the status bar. Writing it into the buffer
    would put a fake line into a log viewer."""
    dialog._refresh()

    assert dialog._editor.toPlainText() == ""


def test_status_recovers_once_the_log_shows_up(dialog, hermes_home) -> None:
    log = hermes_home / "logs" / "gateway.log"
    dialog._refresh()
    assert str(log) in dialog._status.text(), "precondition: error is shown"

    log.write_text("2026-07-22 10:00:00 INFO gateway started\n")
    dialog._refresh()

    assert str(log) not in dialog._status.text(), "the error outlived the condition"
    assert "gateway started" in dialog._editor.toPlainText()
