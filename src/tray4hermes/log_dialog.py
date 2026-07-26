"""The log viewer window: editor, gutter, highlighting, toolbars, find bar.

A self-contained QPlainTextEdit + QSyntaxHighlighter implementation. No
third-party log-viewer library — Qt's own primitives cover every feature
we need: rolling buffer via setMaximumBlockCount, line numbers via a
custom QWidget in the viewport margin, syntax highlight via
QSyntaxHighlighter, search via QTextDocument.find().

Public surface:
    LogDialog      Modal viewer with two toolbars, find bar and statusbar
    LogTextEdit    The editor widget, gutter included
    LogHighlighter QSyntaxHighlighter for Python logging levels
"""

from __future__ import annotations

import os
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
from tray4hermes.log_parse import (
    LEVEL_ALIASES,
    LEVEL_PATTERN,
    is_traceback_line,
    line_level,
    line_timestamp,
)
from tray4hermes.log_settings import (
    LogSettingsDialog,
    load_log_settings,
    save_log_settings,
)
from tray4hermes.log_theme import (
    CRITICAL_BG,
    FILTERABLE_LEVELS,
    LEVEL_COLORS,
    LOG_FONT_FAMILY,
    TIME_WINDOW_KEYS,
    TIME_WINDOW_MINUTES,
    level_checkbox_style,
    time_window_index,
)

# After `i18n.install(...)` runs (in __main__), `tray4hermes.i18n._`
# is bound to the active translation. We use a *dynamic* lookup so
# that switching languages at runtime is picked up by modules that
# imported `_` at load time.
try:
    from tray4hermes import i18n as _i18n_mod

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        """Dynamic gettext wrapper — looks up i18n._ on every call."""
        return _i18n_mod._(s)  # type: ignore[attr-defined]
except ImportError:

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        return s


class LogHighlighter(QSyntaxHighlighter):
    """Highlights Python `logging` lines by severity.

    Recognised patterns (Python `logging.Formatter` default):
        2026-07-22 17:45:14,140 INFO gateway.run: ...message...
        2026-07-22T17:45:14 INFO hermes_plugins.discord...: ...
        INFO:root:message
        [2026-07-22 17:45:14] [INFO] gateway.run: message
    """

    # Compiled from the same pattern string the filters use, so the
    # highlighter can never colour a different set of lines than the
    # filter keeps. The two used to be hand-maintained copies, and the
    # Qt one had drifted — it listed one alternative twice.
    _LEVEL_RE = QRegularExpression(LEVEL_PATTERN)

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
        canonical = LEVEL_ALIASES.get(level, level)
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
        """Handle Ctrl+C / Ctrl+A for log ergonomics.

        Search keys (Ctrl+F, F3, Shift+F3) are deliberately *not* handled
        here — the search term lives in the parent dialog's find bar, so
        the dialog owns those shortcuts and they never reach us.
        """
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_C:
                self.copy()
                return
            if event.key() == Qt.Key_A:
                self.selectAll()
                return
        super().keyPressEvent(event)

    def find_text(self, text: str, backward: bool = False) -> bool:
        """Find `text` from the current cursor. Returns True if found."""
        flags = QTextDocument.FindFlags()
        if backward:
            flags |= QTextDocument.FindBackward
        cursor = self.textCursor()
        # Collapse the previous match before searching again. Left as-is,
        # a backward search would start at the *end* of the current
        # selection and match it a second time — F3, F3, Shift+F3 would
        # never leave the second hit.
        cursor.setPosition(cursor.selectionStart() if backward else cursor.selectionEnd())
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


class LogDialog(QDialog):
    """Hermes Gateway log viewer with toolbar, search, level filters, settings."""

    LOG_REFRESH_MS = 2000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            _("Hermes Gateway — logs (tray4hermes v{version})").format(version=__version__)
        )
        from tray4hermes.icons import brand_icon

        self.setWindowIcon(brand_icon())
        # Load settings first so we can restore the last-used geometry
        # before the default resize() triggers an unnecessary layout pass.
        self._settings = load_log_settings()
        self.resize(900, 500)
        # Restore the last-used window geometry, if any. ``restoreGeometry``
        # returns False on the first run or after a Qt version mismatch
        # — both are silent failures, the default size stays.
        if self._settings.window_geometry is not None:
            self.restoreGeometry(self._settings.window_geometry)

        # Layout: [toolbar] [filter toolbar] [editor + gutter] [find bar] [statusbar]
        self._build_editor()  # must be before _build_toolbar (which references self._editor)
        self._build_toolbar()
        self._build_find_bar()
        self._build_statusbar()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._toolbar)
        main_layout.addWidget(self._filter_toolbar)
        main_layout.addWidget(self._editor)
        main_layout.addWidget(self._find_bar)
        main_layout.addWidget(self._status)

        # Periodic refresh
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(self.LOG_REFRESH_MS)

        self._apply_settings()
        # No _update_status() here: `_refresh` already ends with one on the
        # happy path, and on a read error it puts the failure in the status
        # bar and returns. Calling it again overwrote that failure with a
        # cheerful "Visible: 0", so a viewer opened over an unreadable log
        # claimed the log was empty until the timer fired.
        self._refresh()

        # Re-apply level filter when toggles change
        for cb in self._level_checkboxes.values():
            cb.stateChanged.connect(self._on_level_toggle)
        self._tb_checkbox.stateChanged.connect(self._on_traceback_toggle)

        # Keyboard shortcuts. A QAction only reaches the shortcut map once
        # it belongs to a widget's action list — constructing it with
        # ``parent=self`` gives it an owner, not a key binding. Hence the
        # explicit ``addAction``.
        #
        # Esc is missing on purpose: as a shortcut it would shadow
        # QDialog's built-in reject and the viewer could no longer be
        # closed with it. It is handled in ``keyPressEvent`` instead.
        self._act_find = QAction(_("Find"), self, shortcut="Ctrl+F", triggered=self._focus_search)
        self._act_find_next = QAction(
            _("Find next"),
            self,
            shortcut="F3",
            triggered=lambda: self._find(backward=False),
        )
        self._act_find_prev = QAction(
            _("Find prev"),
            self,
            shortcut="Shift+F3",
            triggered=lambda: self._find(backward=True),
        )
        for action in (self._act_find, self._act_find_next, self._act_find_prev):
            self.addAction(action)

    # ── UI construction ───────────────────────────────────────────────────
    def _build_toolbar(self) -> None:
        tb = QToolBar("Log toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))

        # Buffer-size spinner — how many tail lines to keep. 0 = no limit.
        tb.addWidget(QLabel(_("Max lines: ")))
        self._max_lines_spin = QSpinBox()
        self._max_lines_spin.setRange(0, 100_000)
        self._max_lines_spin.setSingleStep(1)
        self._max_lines_spin.setAccelerated(True)
        self._max_lines_spin.setValue(self._settings.max_lines)
        self._max_lines_spin.setToolTip(
            _("0 = unlimited (all lines). At higher values, older lines are gradually removed.")
        )
        self._max_lines_spin.valueChanged.connect(self._on_max_lines_changed)
        tb.addWidget(self._max_lines_spin)

        # Time-range filter — only show lines newer than this many minutes.
        tb.addSeparator()
        tb.addWidget(QLabel(_("Time: ")))
        self._time_combo = QComboBox()
        # The combo shows translated labels but maps back to a stable
        # internal key. Without that indirection every translated string
        # would have to match an English dict key — fragile across
        # locales. Keys and minutes come from ``log_theme`` so this combo
        # and the settings dialog cannot drift apart.
        self._time_combo.addItems([_("All") if k == "all" else k for k in TIME_WINDOW_KEYS])
        self._time_combo.setCurrentIndex(time_window_index(self._settings.time_window_minutes))
        self._time_combo.setToolTip(_("Show only lines from the last X minutes (0 = all)."))
        self._time_combo.currentIndexChanged.connect(self._on_time_changed)
        tb.addWidget(self._time_combo)

        # Reverse order toggle — newest line at top (journalctl style)
        # vs default newest at bottom (tail -f style).
        self._btn_reverse = QAction(
            _("Reverse"), self, checkable=True, checked=self._settings.reverse_order
        )
        self._btn_reverse.setToolTip(
            _(
                "Journalctl style — newest lines at top, oldest at bottom. "
                "Default: newest at bottom (tail -f style)."
            )
        )
        self._btn_reverse.toggled.connect(self._on_reverse_toggle)
        tb.addAction(self._btn_reverse)

        tb.addSeparator()

        # Auto-scroll toggle
        self._btn_autoscroll = QAction(
            _("Auto-scroll"), self, checkable=True, checked=self._settings.auto_scroll
        )
        self._btn_autoscroll.toggled.connect(self._on_autoscroll_toggle)
        tb.addAction(self._btn_autoscroll)

        # Wrap toggle
        self._btn_wrap = QAction(_("Wrap"), self, checkable=True, checked=self._settings.word_wrap)
        self._btn_wrap.toggled.connect(self._on_wrap_toggle)
        tb.addAction(self._btn_wrap)

        # Search deliberately lives outside this toolbar — see
        # ``_build_find_bar``.
        tb.addSeparator()

        # Copy / Clear / Refresh / Settings
        tb.addAction(QAction(_("Copy"), self, triggered=self._editor.copy))
        clear = QAction(_("Clear"), self, triggered=self._editor.clear)
        tb.addAction(clear)
        tb.addAction(QAction(_("Refresh"), self, triggered=self._refresh))
        tb.addAction(QAction(_("Settings"), self, triggered=self._open_settings))

        self._toolbar = tb
        self._build_filter_toolbar()

    def _build_filter_toolbar(self) -> None:
        """Level filters on a row of their own.

        Together with the controls above they need well over 1900 px.
        Qt never shrinks a toolbar — it pushes the tail into an
        extension popup that starts closed, so on a single row
        everything from `INFO` rightwards was off screen at the default
        900 px, *Settings* included. Two rows cost ~30 px of log height
        and keep every control reachable.
        """
        tb = QToolBar("Log filter toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))

        tb.addWidget(QLabel(_("Filter: ")))
        self._level_checkboxes: dict[str, QCheckBox] = {}
        for level in FILTERABLE_LEVELS:
            cb = QCheckBox(level)
            cb.setChecked(level in self._settings.show_levels)
            cb.setStyleSheet(level_checkbox_style(level))
            tb.addWidget(cb)
            self._level_checkboxes[level] = cb

        tb.addSeparator()

        # Traceback toggle — separate category from log levels. Defaults to
        # ON because stack-trace continuations are usually what you want
        # to see alongside the triggering ERROR line.
        self._tb_checkbox = QCheckBox("TRACEBACK")
        self._tb_checkbox.setChecked(self._settings.show_tracebacks)
        self._tb_checkbox.setStyleSheet(level_checkbox_style("TRACEBACK"))
        tb.addWidget(self._tb_checkbox)

        self._filter_toolbar = tb

    def _build_find_bar(self) -> None:
        """A collapsible search row of its own, below the editor.

        Search used to be the tail end of the main toolbar. That toolbar
        asks for roughly 1975 px to lay out in full, so at the default
        900×500 everything past the level filters spilled into the
        toolbar's extension popup — and a widget parked in an unopened
        popup is not visible, which makes ``setFocus()`` a no-op. Ctrl+F
        did nothing at all until the window was dragged wide enough.

        A separate row cannot overflow: it holds four widgets and is
        hidden until asked for, so it costs no vertical space either.
        """
        self._find_bar = QWidget(self)
        row = QHBoxLayout(self._find_bar)
        row.setContentsMargins(4, 2, 4, 2)

        row.addWidget(QLabel(_("Search: ")))

        self._search = QLineEdit()
        self._search.setPlaceholderText(_("Ctrl+F"))
        self._search.returnPressed.connect(lambda: self._find())
        row.addWidget(self._search, stretch=1)

        btn_prev = QPushButton(_("Find prev"))
        btn_prev.clicked.connect(lambda: self._find(backward=True))
        row.addWidget(btn_prev)

        btn_next = QPushButton(_("Find next"))
        btn_next.clicked.connect(lambda: self._find(backward=False))
        row.addWidget(btn_next)

        btn_close = QPushButton("✕")
        btn_close.setToolTip(_("Close the find bar (Esc)"))
        btn_close.setFixedWidth(28)
        btn_close.clicked.connect(self._close_search)
        row.addWidget(btn_close)

        self._find_bar.setVisible(False)

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
        except OSError as exc:
            # Say so in the status bar. Returning silently left the
            # previous read's line/error counts on screen, which is
            # worse than an empty window: the viewer looked healthy
            # while showing stale numbers.
            self._status.setText(
                "  "
                + _("Cannot read {path}: {error}").format(
                    path=log, error=exc.strerror or type(exc).__name__
                )
            )
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
                ts = line_timestamp(line)
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
        active_canonical = {LEVEL_ALIASES.get(lvl, lvl) for lvl in active}
        known_canonical = {LEVEL_ALIASES.get(lvl, lvl) for lvl in known_levels}
        hidden = known_canonical - active_canonical
        show_tr = self._settings.show_tracebacks

        def _keep(line: str) -> bool:
            level = line_level(line)
            if level is not None:
                canonical = LEVEL_ALIASES.get(level, level)
                return canonical not in hidden
            if is_traceback_line(line):
                return show_tr
            return False

        # Always run the filter — even with default settings we want to
        # drop unparseable noise (curator dumps, RSS lines) that would
        # otherwise fill the buffer.
        lines = [line for line in lines if _keep(line)] if lines else lines

        # 3) Trim buffer in normal-order space before we optionally
        #    reverse. In default mode (newest at bottom), the trailing
        #    slice keeps the newest lines. In reverse mode (newest at
        #    top) the leading slice after reversal keeps the newest
        #    lines too. Either way, this bounds the buffer BEFORE the
        #    reversal so setMaximumBlockCount does not trim from the
        #    wrong end in reverse mode (where "top" is the live edge).
        if self._settings.max_lines > 0 and len(lines) > self._settings.max_lines:
            lines = lines[-self._settings.max_lines :]

        # 4) Reverse order — "newest at top" instead of the default
        #    "newest at bottom" (tail -f style).
        if self._settings.reverse_order:
            lines = list(reversed(lines))

        text = "\n".join(lines)

        scrollbar = self._editor.verticalScrollBar()
        old_scroll_value = scrollbar.value()
        old_scroll_maximum = scrollbar.maximum()
        # Replacing the document resets the cursor/scroll position. Only
        # follow the live-log edge when the user was already there; manual
        # investigation in the middle of the buffer must survive refreshes.
        at_live_edge = (
            old_scroll_value <= scrollbar.minimum() + 4
            if self._settings.reverse_order
            else old_scroll_value >= old_scroll_maximum - 4
        )
        self._editor.setPlainText(text)

        if self._settings.auto_scroll and at_live_edge:
            cursor = self._editor.textCursor()
            cursor.movePosition(
                QTextCursor.Start if self._settings.reverse_order else QTextCursor.End
            )
            self._editor.setTextCursor(cursor)
            self._editor.ensureCursorVisible()
            scrollbar.setValue(
                scrollbar.minimum() if self._settings.reverse_order else scrollbar.maximum()
            )
            if self._settings.reverse_order:
                scrollbar.setValue(scrollbar.minimum())
        elif not at_live_edge:
            scrollbar.setValue(old_scroll_value)

        self._update_status()

    def _update_status(self) -> None:
        # Compute quick stats from the visible text
        text = self._editor.toPlainText()
        total = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        errors = sum(1 for ln in text.splitlines() if line_level(ln) in ("ERROR", "CRITICAL"))
        warnings = sum(1 for ln in text.splitlines() if line_level(ln) == "WARNING")
        # Cursor line
        cur = self._editor.textCursor()
        line = cur.blockNumber() + 1
        col = cur.columnNumber() + 1
        self._status.setText(
            f"  {_('Line')} {line}  {_('Column')} {col}    "
            f"{_('Visible')}: {total}    {_('ERR')}: {errors}    {_('WARN')}: {warnings}    "
            f"{_('Auto-scroll')}: {_('ON') if self._settings.auto_scroll else _('OFF')}"
        )

    # ── Event handlers ────────────────────────────────────────────────────
    def _update_with(self, **kwargs) -> None:
        """Mutate settings, save, and re-render. Used by every toolbar toggle."""
        self._settings = dc_replace(self._settings, **kwargs)
        save_log_settings(self._settings)
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
        save_log_settings(self._settings)
        self._update_status()

    def _on_wrap_toggle(self, checked: bool) -> None:
        self._update_with(word_wrap=checked)

    def _on_level_toggle(self) -> None:
        levels = tuple(lvl for lvl, cb in self._level_checkboxes.items() if cb.isChecked())
        self._update_with(show_levels=levels)

    def _on_traceback_toggle(self, checked: bool) -> None:
        self._update_with(show_tracebacks=checked)

    def _on_time_changed(self, index: int) -> None:
        # ``index`` is the combo box position, which maps to a stable
        # internal key. We deliberately don't bind to the translated
        # label — that's user-visible text and shouldn't drive
        # persistence.
        if 0 <= index < len(TIME_WINDOW_KEYS):
            internal_key = TIME_WINDOW_KEYS[index]
        else:
            internal_key = "all"
        minutes = TIME_WINDOW_MINUTES.get(internal_key, 0)
        self._update_with(time_window_minutes=minutes)

    def _on_reverse_toggle(self, checked: bool) -> None:
        self._update_with(reverse_order=checked)

    def _find(self, backward: bool = False) -> bool:
        """Jump to the next (or previous) occurrence of the search term."""
        term = self._search.text()
        if not term:
            return False
        return self._editor.find_text(term, backward=backward)

    def _focus_search(self) -> None:
        """Reveal the find bar and put the caret in it.

        The reveal has to come first: focusing a widget that is still
        hidden does nothing at all.
        """
        self._find_bar.setVisible(True)
        self._search.setFocus()
        self._search.selectAll()

    def _close_search(self) -> None:
        """Leave the find bar: drop the term, hide it, focus the editor."""
        self._search.clear()
        self._find_bar.setVisible(False)
        self._editor.setFocus()

    def _open_settings(self) -> None:
        """Open the full settings dialog and apply all changes on OK.

        After the dialog closes with OK:
        - All settings (max_lines, font_size, time_window, reverse,
          tracebacks, levels, word_wrap, auto_scroll) are applied
          immediately to the running viewer.
        - The toolbar toggle buttons are re-synced to match the new
          state (so the UI doesn't lie about what's active).
        - Everything is saved to state.json via save_log_settings.
        """
        dlg = LogSettingsDialog(self._settings, self)
        if dlg.exec_() != QDialog.Accepted:
            return

        self._settings = dlg.result_settings()
        self._apply_settings()

        # Re-sync toolbar toggles so they reflect the new state.
        self._btn_autoscroll.setChecked(self._settings.auto_scroll)
        self._btn_wrap.setChecked(self._settings.word_wrap)
        self._btn_reverse.setChecked(self._settings.reverse_order)
        self._tb_checkbox.setChecked(self._settings.show_tracebacks)
        for lvl, cb in self._level_checkboxes.items():
            cb.setChecked(lvl in self._settings.show_levels)
        # Max-lines spinbox
        self._max_lines_spin.setValue(self._settings.max_lines)
        # Time-window combo
        self._time_combo.setCurrentIndex(time_window_index(self._settings.time_window_minutes))

        save_log_settings(self._settings)
        self._refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Persist the user's window size + position so the next open
        restores the same layout."""
        self._settings = dc_replace(self._settings, window_geometry=bytes(self.saveGeometry()))
        save_log_settings(self._settings)
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Esc leaves the find bar; anywhere else it closes the viewer.

        Kept as an event handler rather than a QAction shortcut — a
        shortcut would win over QDialog's built-in reject everywhere in
        the window, and Esc would stop closing the dialog at all.
        """
        if event.key() == Qt.Key_Escape and self._search.hasFocus():
            self._close_search()
            return
        super().keyPressEvent(event)
