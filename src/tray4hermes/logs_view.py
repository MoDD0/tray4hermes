"""Log viewer with level-based syntax highlighting, filters, search, and settings.

A self-contained QPlainTextEdit + QSyntaxHighlighter implementation. No
third-party log-viewer library — Qt's own primitives cover every feature
we need: rolling buffer via setMaximumBlockCount, line numbers via a
custom QWidget in the viewport margin, syntax highlight via
QSyntaxHighlighter, search via QTextDocument.find().

Public surface:
    LogDialog      Modal viewer with toolbar + statusbar
    LogHighlighter QSyntaxHighlighter for Python logging levels
    LogSettings    Persisted user preferences (max lines, wrap, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta

from PyQt5.QtCore import QRect, QRegularExpression, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from tray4hermes import __version__
from tray4hermes import paths as _paths

# A separate dataclass for log-viewer-only settings. Kept separate from
# TrayState so changing "max log lines" doesn't touch the user's
# selected_profile persistence.


@dataclass(frozen=True)
class LogSettings:
    max_lines: int = 2000
    auto_scroll: bool = True
    word_wrap: bool = False
    font_size: int = 9
    show_levels: tuple[str, ...] = (
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
        "TRACE",
    )
    show_tracebacks: bool = True
    time_window_minutes: int = 0  # 0 = show everything
    reverse_order: bool = False  # False = newest at bottom (tail -f style)

    def to_json(self) -> dict[str, object]:
        return {
            "max_lines": self.max_lines,
            "auto_scroll": self.auto_scroll,
            "word_wrap": self.word_wrap,
            "font_size": self.font_size,
            "show_levels": list(self.show_levels),
            "show_tracebacks": self.show_tracebacks,
            "time_window_minutes": self.time_window_minutes,
            "reverse_order": self.reverse_order,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> LogSettings:
        levels = data.get("show_levels", ("ERROR", "WARNING", "INFO", "DEBUG", "TRACE"))
        return cls(
            max_lines=int(data.get("max_lines", 2000)),
            auto_scroll=bool(data.get("auto_scroll", True)),
            word_wrap=bool(data.get("word_wrap", False)),
            font_size=int(data.get("font_size", 9)),
            show_levels=tuple(str(x) for x in levels)
            if isinstance(levels, (list, tuple))
            else cls.show_levels,
            show_tracebacks=bool(data.get("show_tracebacks", True)),
            time_window_minutes=int(data.get("time_window_minutes", 0)),
            reverse_order=bool(data.get("reverse_order", False)),
        )

    @classmethod
    def default(cls) -> LogSettings:
        return cls()


def _load_log_settings() -> LogSettings:
    """Read from tray4hermes state.json (under 'log_settings' key).

    Falls back to default() if missing or malformed. Never raises.
    """
    # TrayState is a frozen dataclass; we add log settings to its JSON
    # shape but keep the dataclass clean by reading from a sibling key
    # in the same file.
    from tray4hermes.paths import tray_state_file

    try:
        import json as _json

        with open(tray_state_file()) as f:
            data = _json.load(f)
        return LogSettings.from_json(data.get("log_settings", {}))
    except (FileNotFoundError, OSError, ValueError):
        return LogSettings.default()


def _save_log_settings(settings: LogSettings) -> None:
    """Persist into the same state.json under 'log_settings'. Never raises."""
    import json as _json

    from tray4hermes.paths import tray_state_file

    p = tray_state_file()
    try:
        # Ensure the parent config dir exists (first run after install
        # or under isolated test XDG_CONFIG_HOME).
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p) as f:
                data = _json.load(f)
        except (FileNotFoundError, OSError, ValueError):
            data = {}
        data["log_settings"] = settings.to_json()
        # Reuse the TrayState save path: write the whole file atomically
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w") as f:
            _json.dump(data, f, indent=2)
        os.replace(tmp, p)
    except OSError as exc:
        print(f"[tray4hermes] save_log_settings failed: {exc}", file=__import__("sys").stderr)


# ── Color scheme ────────────────────────────────────────────────────────────
# Dark theme inspired by the reference screenshot. Light theme would need
# separate colors; the gateway log is read against a dark IDE-style
# background and we match that aesthetic.

LEVEL_COLORS: dict[str, QColor] = {
    "DEBUG": QColor("#6b7280"),  # gray
    "INFO": QColor("#e5e7eb"),  # near-white
    "WARNING": QColor("#facc15"),  # amber
    "WARN": QColor("#facc15"),  # alias for WARNING (loguru, some 3rd-party libs)
    "ERROR": QColor("#fca5a5"),  # light red
    "CRITICAL": QColor("#dc2626"),  # strong red
    "FATAL": QColor("#dc2626"),  # alias for CRITICAL
    "TRACE": QColor("#4b5563"),  # darker gray
    "TRACEBACK": QColor("#fb923c"),  # warm orange — distinct from WARNING
}

# Aliases so a user with WARN / FATAL in their logs gets the same
# color treatment as WARNING / CRITICAL.
_LEVEL_ALIASES: dict[str, str] = {
    "WARN": "WARNING",
    "FATAL": "CRITICAL",
}

# A line is considered a "traceback context" (continuation of a stack trace)
# if it matches any of these patterns. They cover the common Python
# `logging` output for unhandled exceptions:
#
#   Traceback (most recent call last):
#     File "/usr/lib/...", line 123, in func_name        ← 2 spaces
#       x = foo()                                        ← 4 spaces
#           ^                                            ← 4 spaces + ^
#   RuntimeError: boom
#   During handling of the above exception, another exception occurred:
_TRACEBACK_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Traceback \(most recent call last\):"),
    # Exception line at the bottom of a traceback (flush-left, e.g.
    # "RuntimeError: boom", "ValueError: nope", "ZeroDivisionError")
    re.compile(
        r"^[A-Za-z][A-Za-z0-9_]*(?:Error|Exception|Warning|Interrupt|Exit|StopIteration|KeyboardInterrupt)"
    ),
    # Exception line indented (e.g. "  RuntimeError: boom")
    re.compile(
        r"^[ ]{2,}[A-Za-z]+(?:Error|Exception|Warning|Interrupt|Exit|StopIteration|KeyboardInterrupt)"  # noqa: E501 (regex)
    ),
    # File "x", line N — 2-space indent (Python stdlib format)
    re.compile(r'^[ ]{2,}File ".*", line \d+'),
    # pointer line under the failing line (col-aligned)
    re.compile(r"^[ ]{4,}\^"),
    re.compile(r"^During handling of the above exception,"),
    # "The above exception was the direct cause of the following exception:"
    re.compile(r"^The above exception was the direct cause"),
)

# Critical lines get a full-row red highlight (like the reference).
CRITICAL_BG = QColor("#7f1d1d")
CRITICAL_BG.setAlpha(180)

# Monospace font for log lines; tabular nums make line numbers align.
LOG_FONT_FAMILY = "Monospace"


# ── Syntax highlighter ──────────────────────────────────────────────────────
class LogHighlighter(QSyntaxHighlighter):
    """Highlights Python `logging` lines by severity.

    Recognised patterns (Python `logging.Formatter` default):
        2026-07-22 17:45:14,140 INFO gateway.run: ...message...
        2026-07-22T17:45:14 INFO hermes_plugins.discord...: ...
        INFO:root:message
        [2026-07-22 17:45:14] [INFO] gateway.run: message
    """

    # Match the level token after the timestamp. We use a non-capturing
    # group for the prefix so highlightRange fires on the whole line.
    _LEVEL_RE = QRegularExpression(
        r"^(?:\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\s+"
        r"|\[\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\]\s*\[?"
        r"|\[\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\]\s*\[?"
        r")([A-Z]+)(?:\]|:)?\s"
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._critical_format = QTextCharFormat()
        self._critical_format.setBackground(CRITICAL_BG)
        font = QFont()
        font.setBold(True)
        self._critical_format.setFont(font)
        self._critical_format.setForeground(QColor("#ffffff"))

    def highlightBlock(self, text: str) -> None:
        match = self._LEVEL_RE.match(text)
        if not match:
            return
        level = match.captured(1)
        # Normalize aliases (WARN → WARNING, FATAL → CRITICAL) so a
        # line uses the same color regardless of the formatter.
        canonical = _LEVEL_ALIASES.get(level, level)
        color = LEVEL_COLORS.get(canonical) or LEVEL_COLORS.get(level)
        if color is None:
            return

        # Color the level token
        level_start = match.capturedStart(1)
        level_length = match.capturedLength(1)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        if level in ("ERROR", "CRITICAL"):
            fmt.setFontWeight(QFont.Bold)
        self.setFormat(level_start, level_length, fmt)

        # Color the timestamp + logger name + rest of line subtly for
        # readability. We don't change the timestamp color — keep it as
        # default so lines stay scannable.
        if level == "CRITICAL":
            # Full row highlight for critical lines (like the screenshot)
            self.setFormat(0, len(text), self._critical_format)

        # Soft-tint the message after the level so the level pops.
        # (Subtle — we don't want to drown the level color.)
        rest_color = QColor(color)
        rest_color.setAlpha(220)
        rest_fmt = QTextCharFormat()
        rest_fmt.setForeground(rest_color)
        self.setFormat(level_start + level_length, len(text) - level_start - level_length, rest_fmt)


# ── Line-number gutter ──────────────────────────────────────────────────────
class LineNumberArea(QWidget):
    """A small gutter on the left of the QPlainTextEdit showing line numbers."""

    def __init__(self, editor: LogTextEdit) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # noqa: N802
        self._editor.paint_line_numbers(event)


class LogTextEdit(QPlainTextEdit):
    """QPlainTextEdit subclass that owns its line-number gutter."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gutter = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._on_update_request)
        self._update_gutter_width()
        self.setUndoRedoEnabled(False)  # read-only; saves memory
        self.setLineWrapMode(QPlainTextEdit.NoWrap)  # default; user can toggle

    def line_number_area_width(self) -> int:
        """Pixel width to reserve for the line-number gutter."""
        digits = len(str(max(1, self.blockCount())))
        fm = QFontMetrics(self.font())
        return 8 + fm.horizontalAdvance("9") * digits + 8

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        bg = self.palette().base().color()
        painter.fillRect(event.rect(), bg)

        # Only paint numbers for visible blocks
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        fm = QFontMetrics(self.font())
        color = self.palette().placeholderText().color()
        painter.setPen(color)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - 4,
                    fm.height(),
                    Qt.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Handle Ctrl+C / Ctrl+A / Ctrl+F / F3 / Shift+F3 for log ergonomics."""
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_C:
                self.copy()
                return
            if event.key() == Qt.Key_A:
                self.selectAll()
                return
            if event.key() == Qt.Key_F:
                # Find handled by parent dialog; ignore here.
                return
        if event.key() == Qt.Key_F3:
            self._find_next(backward=bool(event.modifiers() & Qt.ShiftModifier))
            return
        super().keyPressEvent(event)

    def find_text(self, text: str, backward: bool = False) -> bool:
        """Find `text` from the current cursor. Returns True if found."""
        flags = QTextDocument.FindFlags()
        if backward:
            flags |= QTextDocument.FindBackward
        cursor = self.textCursor()
        found = self.document().find(text, cursor, flags)
        if not found.isNull():
            self.setTextCursor(found)
            return True
        # Wrap to start
        cursor.movePosition(QTextCursor.Start if not backward else QTextCursor.End)
        found = self.document().find(text, cursor, flags)
        if not found.isNull():
            self.setTextCursor(found)
            return True
        return False


# ── Settings dialog ────────────────────────────────────────────────────────
class LogSettingsDialog(QDialog):
    """Modal dialog for editing LogSettings."""

    def __init__(self, current: LogSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log viewer — nastavení")
        layout = QVBoxLayout(self)

        # max lines
        row = QHBoxLayout()
        row.addWidget(QLabel("Maximální počet řádků v bufferu:"))
        self._max_lines = QSpinBox()
        self._max_lines.setRange(100, 100_000)
        self._max_lines.setSingleStep(500)
        self._max_lines.setValue(current.max_lines)
        row.addWidget(self._max_lines)
        layout.addLayout(row)

        # font size
        row = QHBoxLayout()
        row.addWidget(QLabel("Velikost písma:"))
        self._font_size = QSpinBox()
        self._font_size.setRange(6, 24)
        self._font_size.setValue(current.font_size)
        row.addWidget(self._font_size)
        layout.addLayout(row)

        # auto_scroll
        self._auto_scroll = QCheckBox("Auto-scroll na nové řádky")
        self._auto_scroll.setChecked(current.auto_scroll)
        layout.addWidget(self._auto_scroll)

        # word wrap
        self._word_wrap = QCheckBox("Zalamovat dlouhé řádky")
        self._word_wrap.setChecked(current.word_wrap)
        layout.addWidget(self._word_wrap)

        # show levels
        layout.addWidget(QLabel("Zobrazované úrovně:"))
        self._level_checks: dict[str, QCheckBox] = {}
        for level in ("ERROR", "WARNING", "INFO", "DEBUG", "TRACE"):
            cb = QCheckBox(level)
            cb.setChecked(level in current.show_levels)
            self._level_checks[level] = cb
            layout.addWidget(cb)

        # OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_settings(self) -> LogSettings:
        levels = tuple(lvl for lvl, cb in self._level_checks.items() if cb.isChecked())
        return LogSettings(
            max_lines=self._max_lines.value(),
            auto_scroll=self._auto_scroll.isChecked(),
            word_wrap=self._word_wrap.isChecked(),
            font_size=self._font_size.value(),
            show_levels=levels,
        )


# ── Main viewer dialog ─────────────────────────────────────────────────────
class LogDialog(QDialog):
    """Hermes Gateway log viewer with toolbar, search, level filters, settings."""

    LOG_REFRESH_MS = 2000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Hermes Gateway — logy (tray4hermes v{__version__})")
        self.resize(900, 500)

        self._settings = _load_log_settings()

        # Layout: [toolbar] [editor + gutter] [statusbar]
        self._build_editor()  # must be before _build_toolbar (which references self._editor)
        self._build_toolbar()
        self._build_statusbar()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._toolbar)
        main_layout.addWidget(self._editor)
        main_layout.addWidget(self._status)

        # Periodic refresh
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(self.LOG_REFRESH_MS)

        self._apply_settings()
        self._refresh()
        self._update_status()

        # Re-apply level filter when toggles change
        for cb in self._level_checkboxes.values():
            cb.stateChanged.connect(self._on_level_toggle)
        self._tb_checkbox.stateChanged.connect(self._on_traceback_toggle)

        # Keyboard shortcuts
        QAction("Find", self, shortcut="Ctrl+F", triggered=self._focus_search)
        QAction(
            "Find next",
            self,
            shortcut="F3",
            triggered=lambda: self._editor.find_text(self._search.text()),
        )
        QAction(
            "Find prev",
            self,
            shortcut="Shift+F3",
            triggered=lambda: self._editor.find_text(self._search.text(), backward=True),
        )
        QAction("Escape", self, shortcut="Esc", triggered=self._close_search)

    # ── UI construction ───────────────────────────────────────────────────
    def _build_toolbar(self) -> None:
        tb = QToolBar("Log toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))

        # Buffer-size spinner — how many tail lines to keep. 0 = no limit.
        tb.addWidget(QLabel("Max řádků: "))
        self._max_lines_spin = QSpinBox()
        self._max_lines_spin.setRange(0, 100_000)
        self._max_lines_spin.setSingleStep(500)
        self._max_lines_spin.setValue(self._settings.max_lines)
        self._max_lines_spin.setToolTip(
            "Maximální počet řádků v bufferu (0 = bez limitu).\n"
            "Starší řádky jsou průběžně odstraňovány."
        )
        self._max_lines_spin.valueChanged.connect(self._on_max_lines_changed)
        tb.addWidget(self._max_lines_spin)

        # Time-range filter — only show lines newer than this many minutes.
        tb.addSeparator()
        tb.addWidget(QLabel("Čas: "))
        self._time_combo = QComboBox()
        self._time_combo.addItems(["Vše", "5m", "15m", "1h", "6h", "24h"])
        # Map label → minutes; 0 means "no time filter"
        self._time_choices = {"Vše": 0, "5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}
        # Pre-select based on settings
        current_label = "Vše"
        for label, mins in self._time_choices.items():
            if mins == self._settings.time_window_minutes:
                current_label = label
                break
        self._time_combo.setCurrentText(current_label)
        self._time_combo.setToolTip("Zobrazit pouze řádky z posledních X minut (0 = vše).")
        self._time_combo.currentTextChanged.connect(self._on_time_changed)
        tb.addWidget(self._time_combo)

        # Reverse order toggle — newest line at top (journalctl style)
        # vs default newest at bottom (tail -f style).
        self._btn_reverse = QAction(
            "Obrátit", self, checkable=True, checked=self._settings.reverse_order
        )
        self._btn_reverse.setToolTip(
            "Při zapnutí: nejnovější řádky nahoře (journalctl styl).\n"
            "Při vypnutí: nejnovější dole (tail -f styl)."
        )
        self._btn_reverse.toggled.connect(self._on_reverse_toggle)
        tb.addAction(self._btn_reverse)

        tb.addSeparator()

        # Auto-scroll toggle
        self._btn_autoscroll = QAction(
            "Auto-scroll", self, checkable=True, checked=self._settings.auto_scroll
        )
        self._btn_autoscroll.toggled.connect(self._on_autoscroll_toggle)
        tb.addAction(self._btn_autoscroll)

        # Wrap toggle
        self._btn_wrap = QAction(
            "Zalamovat", self, checkable=True, checked=self._settings.word_wrap
        )
        self._btn_wrap.toggled.connect(self._on_wrap_toggle)
        tb.addAction(self._btn_wrap)

        tb.addSeparator()

        # Level filters
        tb.addWidget(QLabel("Filtr: "))
        self._level_checkboxes: dict[str, QCheckBox] = {}
        for level in ("ERROR", "WARNING", "INFO", "DEBUG", "TRACE"):
            cb = QCheckBox(level)
            cb.setChecked(level in self._settings.show_levels)
            cb.setStyleSheet(f"QCheckBox {{ color: {LEVEL_COLORS[level].name()}; }}")
            tb.addWidget(cb)
            self._level_checkboxes[level] = cb

        # Traceback toggle — separate category from log levels. Defaults to
        # ON because stack-trace continuations are usually what you want
        # to see alongside the triggering ERROR line.
        self._tb_checkbox = QCheckBox("TRACEBACK")
        self._tb_checkbox.setChecked(self._settings.show_tracebacks)
        self._tb_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {LEVEL_COLORS['TRACEBACK'].name()}; font-weight: bold; }}"
        )
        tb.addWidget(self._tb_checkbox)

        tb.addSeparator()

        # Search
        tb.addWidget(QLabel("Hledat: "))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Ctrl+F")
        self._search.setMaximumWidth(220)
        self._search.returnPressed.connect(lambda: self._editor.find_text(self._search.text()))
        tb.addWidget(self._search)

        btn_next = QPushButton("Najít")
        btn_next.clicked.connect(lambda: self._editor.find_text(self._search.text()))
        tb.addWidget(btn_next)

        tb.addSeparator()

        # Copy / Clear / Refresh / Settings
        tb.addAction(QAction("Kopírovat", self, triggered=self._editor.copy))
        clear = QAction("Vyčistit", self, triggered=self._editor.clear)
        tb.addAction(clear)
        tb.addAction(QAction("Obnovit", self, triggered=self._refresh))
        tb.addAction(QAction("Nastavení", self, triggered=self._open_settings))

        self._toolbar = tb

    def _build_editor(self) -> None:
        self._editor = LogTextEdit(self)
        self._editor.setReadOnly(True)
        font = QFont(LOG_FONT_FAMILY, self._settings.font_size)
        font.setStyleHint(QFont.Monospace)
        self._editor.setFont(font)
        self._highlighter = LogHighlighter(self)
        self._highlighter.setDocument(self._editor.document())

    def _build_statusbar(self) -> None:
        self._status = QLabel()

    def _apply_settings(self) -> None:
        # Buffer limit (rolling window)
        self._editor.setMaximumBlockCount(self._settings.max_lines)
        # Wrap mode — use QPlainTextEdit's own enum (not QTextEdit's) because
        # the integer values differ between the two classes.
        wrap = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if self._settings.word_wrap
            else QPlainTextEdit.NoWrap
        )
        self._editor.setLineWrapMode(wrap)
        # Font
        font = self._editor.font()
        font.setPointSize(self._settings.font_size)
        self._editor.setFont(font)

    # ── Refresh ────────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        log = _paths.gateway_log()
        try:
            with open(log, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                # Read more than the block limit so the highlighter has
                # headroom; we let setMaximumBlockCount trim from the top.
                want = max(self._settings.max_lines * 200, 256 * 1024)
                f.seek(-min(want, size), os.SEEK_END)
                data = f.read()
        except OSError:
            return

        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()

        # ── Filter pipeline ───────────────────────────────────────────────
        # 1) Time-window filter — drop lines older than (now - window).
        #    Lines without a parseable timestamp pass through (they're
        #    traceback continuations or noise; the next stage deals with them).
        time_window_minutes = self._settings.time_window_minutes
        if time_window_minutes > 0:
            cutoff = datetime.now() - timedelta(minutes=time_window_minutes)
            kept: list[str] = []
            last_seen_ts: datetime | None = None
            for line in lines:
                ts = _line_timestamp(line)
                if ts is not None:
                    last_seen_ts = ts
                # Apply cutoff only to lines WITH a timestamp (so
                # traceback continuations next to a fresh ERROR line
                # stay visible). Without a timestamp, follow the
                # nearest neighbor's decision.
                if last_seen_ts is not None and last_seen_ts < cutoff:
                    continue
                kept.append(line)
            lines = kept

        # 2) Level + traceback filter.
        #    Every line is classified as either a known level
        #    (DEBUG/INFO/WARNING/ERROR/CRITICAL/TRACE) or as "traceback
        #    context" (stack-trace continuation). The user toggles which
        #    of these categories are visible. Unparseable lines (truly
        #    neither) are dropped — that prevents the curator-snapshot
        #    dumps from leaking through when filtered.
        known_levels = set(LEVEL_COLORS.keys()) - {"TRACEBACK"}
        active = set(self._settings.show_levels)
        active_canonical = {_LEVEL_ALIASES.get(lvl, lvl) for lvl in active}
        known_canonical = {_LEVEL_ALIASES.get(lvl, lvl) for lvl in known_levels}
        hidden = known_canonical - active_canonical
        show_tr = self._settings.show_tracebacks

        def _keep(line: str) -> bool:
            level = _line_level(line)
            if level is not None:
                canonical = _LEVEL_ALIASES.get(level, level)
                return canonical not in hidden
            if _is_traceback_line(line):
                return show_tr
            return False

        # Always run the filter — even with default settings we want to
        # drop unparseable noise (curator dumps, RSS lines) that would
        # otherwise fill the buffer.
        lines = [line for line in lines if _keep(line)] if lines else lines

        # 3) Reverse order — "newest at top" instead of the default
        #    "newest at bottom" (tail -f style).
        if self._settings.reverse_order:
            lines = list(reversed(lines))

        text = "\n".join(lines)

        scrollbar = self._editor.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        # Hooks reserved for future per-line append optimization (would let us
        # avoid resetting the cursor). Kept as no-ops to make the intent
        # explicit and silence the unused-var lint.
        _was_modified = False  # noqa: F841
        _cursor_pos = 0  # noqa: F841

        self._editor.setPlainText(text)

        if self._settings.auto_scroll and at_bottom:
            scrollbar.setValue(scrollbar.maximum())

        self._update_status()

    def _update_status(self) -> None:
        # Compute quick stats from the visible text
        text = self._editor.toPlainText()
        total = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        errors = sum(1 for ln in text.splitlines() if _line_level(ln) in ("ERROR", "CRITICAL"))
        warnings = sum(1 for ln in text.splitlines() if _line_level(ln) == "WARNING")
        # Cursor line
        cur = self._editor.textCursor()
        line = cur.blockNumber() + 1
        col = cur.columnNumber() + 1
        self._status.setText(
            f"  Řádek {line}  Sloupec {col}    "
            f"Viditelných: {total}    ERR: {errors}    WARN: {warnings}    "
            f"Auto-scroll: {'ZAP' if self._settings.auto_scroll else 'VYP'}"
        )

    # ── Event handlers ────────────────────────────────────────────────────
    def _update_with(self, **kwargs) -> None:
        """Mutate settings, save, and re-render. Used by every toolbar toggle."""
        self._settings = dc_replace(self._settings, **kwargs)
        _save_log_settings(self._settings)
        self._apply_settings()
        self._refresh()
        self._update_status()

    def _on_max_lines_changed(self, value: int) -> None:
        # 0 means "no limit" — setMaximumBlockCount(0) is documented as
        # "remove the limit", so that's Qt-native and we just propagate.
        self._update_with(max_lines=value)

    def _on_autoscroll_toggle(self, checked: bool) -> None:
        # autoscroll doesn't need re-render — but we still want the
        # status bar updated so the user sees the new state.
        self._settings = dc_replace(self._settings, auto_scroll=checked)
        _save_log_settings(self._settings)
        self._update_status()

    def _on_wrap_toggle(self, checked: bool) -> None:
        self._update_with(word_wrap=checked)

    def _on_level_toggle(self) -> None:
        levels = tuple(lvl for lvl, cb in self._level_checkboxes.items() if cb.isChecked())
        self._update_with(show_levels=levels)

    def _on_traceback_toggle(self, checked: bool) -> None:
        self._update_with(show_tracebacks=checked)

    def _on_time_changed(self, label: str) -> None:
        minutes = self._time_choices.get(label, 0)
        self._update_with(time_window_minutes=minutes)

    def _on_reverse_toggle(self, checked: bool) -> None:
        self._update_with(reverse_order=checked)

    def _focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    def _close_search(self) -> None:
        self._search.clear()

    def _open_settings(self) -> None:
        dlg = LogSettingsDialog(self._settings, self)
        if dlg.exec_() == QDialog.Accepted:
            self._settings = dlg.result_settings()
            self._apply_settings()
            # Update toolbar toggles to match
            self._btn_autoscroll.setChecked(self._settings.auto_scroll)
            self._btn_wrap.setChecked(self._settings.word_wrap)
            for lvl, cb in self._level_checkboxes.items():
                cb.setChecked(lvl in self._settings.show_levels)
            _save_log_settings(self._settings)
            self._refresh()

    # Esc closes dialog (override default reject)
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self._search.hasFocus():
            self._search.clearFocus()
            self._editor.setFocus()
            return
        super().keyPressEvent(event)


# ── Helpers ────────────────────────────────────────────────────────────────
_LEVEL_RE = re.compile(
    r"^(?:\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\s+"
    r"|\[\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\]\s*\[?"
    r")([A-Z]+)(?:\]|:)?\s"
)

# Captures the leading timestamp (and nothing else) so callers can
# re-format / time-filter without re-running regex.
_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})(?:[T ](?P<time>\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?))?"
    r"|^\[(?P<date2>\d{4}[-/]\d{2}[-/]\d{2})(?:[T ](?P<time2>\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?))?\]"
)


def _line_level(line: str) -> str | None:
    """Return the log level of a line, or None if it doesn't match."""
    m = _LEVEL_RE.match(line)
    return m.group(1) if m else None


def _line_timestamp(line: str) -> datetime | None:
    """Extract a datetime from the leading timestamp on a log line.

    Returns None when the line has no parseable timestamp (e.g. a
    traceback continuation). The time-based filter uses this to
    decide whether a line is inside the configured window.
    """
    m = _TIMESTAMP_RE.match(line)
    if not m:
        return None
    date = m.group("date") or m.group("date2")
    time = (m.group("time") or m.group("time2") or "00:00:00").replace(",", ".")
    try:
        return datetime.fromisoformat(f"{date}T{time}")
    except ValueError:
        return None


def _is_traceback_line(line: str) -> bool:
    """True if `line` looks like a Python stack-trace continuation.

    Used by the level filter to give stack-trace lines their own toggle
    (TRACEBACK) so the user can show only the message (no traceback),
    only the traceback (no surrounding log noise), or everything.
    """
    if not line:
        return False
    return any(p.match(line) for p in _TRACEBACK_LINE_PATTERNS)


# Late import to keep `os` in one place at the bottom of the file.
import os  # noqa: E402
