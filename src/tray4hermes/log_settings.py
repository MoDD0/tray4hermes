"""Log-viewer preferences: the dataclass, its persistence, and its dialog.

Settings live in the same ``state.json`` as the rest of the tray state,
under a sibling ``log_settings`` key, so that changing "max log lines"
never rewrites the user's selected profile.
"""

from __future__ import annotations

import json
import os
import sys
from base64 import b64decode, b64encode
from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from tray4hermes.log_theme import (
    FILTERABLE_LEVELS,
    TIME_WINDOW_KEYS,
    TIME_WINDOW_MINUTES,
    level_checkbox_style,
    section_label,
    time_window_index,
)
from tray4hermes.paths import tray_state_file
from tray4hermes.tray_settings import load_tray_settings

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


def _as_int(value: object, default: int) -> int:
    """Coerce a value read from JSON to int, or fall back to `default`."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_geometry(value: object) -> bytes | None:
    """Decode a base64 geometry blob; anything unusable means "no geometry".

    ``binascii.Error`` is a ``ValueError`` subclass, which is why a
    corrupted blob used to look like a broken settings file.
    """
    if not isinstance(value, str):
        return None
    try:
        return b64decode(value, validate=True)
    except ValueError:
        return None


@dataclass(frozen=True)
class LogSettings:
    """Log-viewer-only preferences, kept apart from ``TrayState``."""

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

    # Encoded QDialog.saveGeometry() blob (base64). ``None`` = first open,
    # fall back to the dialog's default size.
    window_geometry: bytes | None = None

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
            # base64-encode so the JSON stays text-only and stays valid
            # even if the binary blob contains bytes outside 0x20..0x7e.
            "window_geometry": (
                b64encode(self.window_geometry).decode("ascii")
                if self.window_geometry is not None
                else None
            ),
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> LogSettings:
        """Rebuild from a state.json fragment. Never raises.

        Every field falls back to its own default independently. The
        earlier version wrapped the whole call in one try/except, so a
        single damaged value — a truncated geometry blob, a hand-edited
        ``"max_lines": {}`` — discarded the user's entire configuration.
        """
        defaults = cls()
        levels = data.get("show_levels")
        return cls(
            max_lines=_as_int(data.get("max_lines"), defaults.max_lines),
            auto_scroll=bool(data.get("auto_scroll", defaults.auto_scroll)),
            word_wrap=bool(data.get("word_wrap", defaults.word_wrap)),
            font_size=_as_int(data.get("font_size"), defaults.font_size),
            show_levels=tuple(str(x) for x in levels)
            if isinstance(levels, (list, tuple))
            else defaults.show_levels,
            show_tracebacks=bool(data.get("show_tracebacks", defaults.show_tracebacks)),
            time_window_minutes=_as_int(
                data.get("time_window_minutes"), defaults.time_window_minutes
            ),
            reverse_order=bool(data.get("reverse_order", defaults.reverse_order)),
            window_geometry=_as_geometry(data.get("window_geometry")),
        )

    @classmethod
    def default(cls) -> LogSettings:
        return cls()


def _seed_from_tray_defaults() -> LogSettings:
    """Viewer settings for a user who has never opened the viewer before.

    The starting point is the global tray configuration, so what the
    user picked in the Settings dialog is what they get on first open.
    """
    defaults = load_tray_settings()
    return LogSettings(
        max_lines=defaults.default_max_lines,
        auto_scroll=defaults.default_auto_scroll,
        word_wrap=defaults.default_word_wrap,
        show_levels=defaults.default_show_levels,
    )


def load_log_settings() -> LogSettings:
    """Read from tray4hermes state.json (under 'log_settings' key).

    Falls back to the tray defaults if missing or malformed. Never raises.
    """
    try:
        with open(tray_state_file()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        # OSError covers the missing file; ValueError covers unparseable
        # JSON. Field-level damage is handled inside `from_json`.
        data = {}

    raw_log_settings = data.get("log_settings") if isinstance(data, dict) else None
    if isinstance(raw_log_settings, dict):
        return LogSettings.from_json(raw_log_settings)
    return _seed_from_tray_defaults()


def save_log_settings(settings: LogSettings) -> None:
    """Persist into the same state.json under 'log_settings'. Never raises."""
    p = tray_state_file()
    try:
        # Ensure the parent config dir exists (first run after install
        # or under isolated test XDG_CONFIG_HOME).
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p) as f:
                data = json.load(f)
        except (FileNotFoundError, OSError, ValueError):
            data = {}
        data["log_settings"] = settings.to_json()
        # Reuse the TrayState save path: write the whole file atomically
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, p)
    except OSError as exc:
        print(f"[tray4hermes] save_log_settings failed: {exc}", file=sys.stderr)


class LogSettingsDialog(QDialog):
    """Modal dialog for editing all LogSettings.

    This is the 'one-stop settings' panel — every preference the log
    viewer supports is editable here, with sensible defaults shown
    as the initial state. The toolbar in LogDialog exposes quick-
    toggle shortcuts for the most-common controls, but this dialog
    is where the user lands when they click 'Settings' to see and
    change everything at once.
    """

    def __init__(self, current: LogSettings, parent=None) -> None:
        super().__init__(parent)
        # Kept so `result_settings()` can carry through the fields this
        # dialog has no widget for (see there).
        self._current = current
        self.setWindowTitle(_("Log viewer — settings"))
        # Brand icon so title bar / taskbar entry don't fall back to the
        # default Qt placeholder glyph when this dialog is opened outside
        # ``HermesTray`` (e.g. test harness, standalone CLI).
        from tray4hermes.icons import brand_icon

        self.setWindowIcon(brand_icon())
        self.resize(420, 560)
        layout = QVBoxLayout(self)

        # ── Buffer & display ───────────────────────────────────────────
        layout.addWidget(section_label(_("Display")))

        # max lines
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Maximum lines in buffer:")))
        self._max_lines = QSpinBox()
        self._max_lines.setRange(0, 100_000)
        self._max_lines.setSingleStep(1)
        self._max_lines.setAccelerated(True)
        self._max_lines.setValue(current.max_lines)
        self._max_lines.setToolTip(
            _("0 = unlimited (all lines). At higher values, older lines are gradually removed.")
        )
        row.addWidget(self._max_lines)
        layout.addLayout(row)

        # font size
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Font size:")))
        self._font_size = QSpinBox()
        self._font_size.setRange(6, 24)
        self._font_size.setValue(current.font_size)
        row.addWidget(self._font_size)
        layout.addLayout(row)

        # time window
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Time window:")))
        self._time_window = QComboBox()
        self._time_window.addItems([_("All") if k == "all" else k for k in TIME_WINDOW_KEYS])
        self._time_window.setCurrentIndex(time_window_index(current.time_window_minutes))
        row.addWidget(self._time_window)
        layout.addLayout(row)

        # ── Behaviour toggles ──────────────────────────────────────────
        layout.addWidget(section_label(_("Behavior")))

        self._auto_scroll = QCheckBox(_("Auto-scroll on new lines"))
        self._auto_scroll.setChecked(current.auto_scroll)
        self._auto_scroll.setToolTip(
            _(
                "When ON, the editor stays on the last line on refresh. "
                "When OFF, cursor position is preserved."
            )
        )
        layout.addWidget(self._auto_scroll)

        self._word_wrap = QCheckBox(_("Wrap long lines"))
        self._word_wrap.setChecked(current.word_wrap)
        layout.addWidget(self._word_wrap)

        self._reverse = QCheckBox(_("Reverse order (newest first)"))
        self._reverse.setChecked(current.reverse_order)
        self._reverse.setToolTip(
            _(
                "Journalctl style — newest lines at top, oldest at bottom. "
                "Default: newest at bottom (tail -f style)."
            )
        )
        layout.addWidget(self._reverse)

        self._show_tracebacks = QCheckBox(_("Show tracebacks (stack traces)"))
        self._show_tracebacks.setChecked(current.show_tracebacks)
        self._show_tracebacks.setToolTip(
            _(
                "Special category for stack trace lines. "
                "You can hide them and see only messages, or leave them visible."
            )
        )
        layout.addWidget(self._show_tracebacks)

        # ── Level filters ──────────────────────────────────────────────
        layout.addWidget(section_label(_("Level filtering")))
        layout.addWidget(QLabel(_("Visible levels:")))
        self._level_checks: dict[str, QCheckBox] = {}
        for level in FILTERABLE_LEVELS:
            cb = QCheckBox(level)
            cb.setChecked(level in current.show_levels)
            cb.setStyleSheet(level_checkbox_style(level))
            self._level_checks[level] = cb
            layout.addWidget(cb)

        # ── OK / Cancel ───────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_settings(self) -> LogSettings:
        """Build a fresh LogSettings from the dialog's current widget state.

        Fields without a widget here — currently ``window_geometry`` —
        are carried over from the settings we were opened with. Building
        them from widget state alone means confirming this dialog resets
        the viewer's window position on every visit.
        """
        levels = tuple(lvl for lvl, cb in self._level_checks.items() if cb.isChecked())
        tw_idx = self._time_window.currentIndex()
        tw_key = TIME_WINDOW_KEYS[tw_idx] if 0 <= tw_idx < len(TIME_WINDOW_KEYS) else "all"
        return LogSettings(
            max_lines=self._max_lines.value(),
            auto_scroll=self._auto_scroll.isChecked(),
            word_wrap=self._word_wrap.isChecked(),
            font_size=self._font_size.value(),
            show_levels=levels,
            show_tracebacks=self._show_tracebacks.isChecked(),
            time_window_minutes=TIME_WINDOW_MINUTES.get(tw_key, 0),
            reverse_order=self._reverse.isChecked(),
            window_geometry=self._current.window_geometry,
        )
