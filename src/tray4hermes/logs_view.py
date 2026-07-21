"""Modal log viewer — tails the last N bytes of gateway.log with auto-refresh.

Separate QDialog so the tray menu stays responsive while the user reads logs.
"""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout

from tray4hermes import __version__
from tray4hermes import paths as _paths
from tray4hermes.paths import LOG_REFRESH_INTERVAL_MS, LOG_TAIL_BYTES


class LogDialog(QDialog):
    """Read-only log viewer with 2s auto-refresh."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Hermes Gateway — logy (tray4hermes v{__version__})")
        self.resize(700, 400)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        font = QFont("monospace")
        self._text.setFont(font)

        layout = QVBoxLayout(self)
        layout.addWidget(self._text)

        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(LOG_REFRESH_INTERVAL_MS)

    def _refresh(self) -> None:
        log = _paths.gateway_log()
        try:
            with open(log, "rb") as f:
                # seek-from-end with a negative offset is only valid when
                # the file is at least LOG_TAIL_BYTES long. For shorter
                # files (fresh gateway, post-rotation), fall back to 0.
                size = f.seek(0, os.SEEK_END)
                f.seek(-min(LOG_TAIL_BYTES, size), os.SEEK_END)
                data = f.read()
        except OSError:
            return  # log missing/unreadable; next tick will retry

        text = data.decode("utf-8", errors="replace")
        self._text.setPlainText(text)
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())


# Imported here (not at top) so tests can import without pulling os into
# their namespace globally. Standard late-binding trick.
import os  # noqa: E402
