"""Colours and fonts shared by everything that renders a log line.

This module exists to break a dependency cycle. The colours used to
live in ``logs_view``, which ``tray_settings`` imported to paint its
level checkboxes — while ``logs_view`` imported ``tray_settings`` back
to seed its defaults. The cycle only held together because both
imports were made locally inside functions rather than at module
level. With the palette parked here, both modules depend on a leaf and
the local-import workaround is no longer needed.

It is a leaf on purpose: it imports nothing from the rest of the
package, so it cannot take part in a cycle no matter who imports it.
"""

from __future__ import annotations

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QLabel

# ── Colour scheme ───────────────────────────────────────────────────────────
# Dark theme inspired by the reference screenshot. A light theme would need
# separate colours; the gateway log is read against a dark IDE-style
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

# The six levels offered as filter checkboxes, in display order. Aliases
# (WARN, FATAL) and TRACEBACK are deliberately absent: aliases would be
# duplicate switches for the same thing, and TRACEBACK is its own
# category with its own toggle.
FILTERABLE_LEVELS: tuple[str, ...] = (
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
    "CRITICAL",
    "TRACE",
)

# Critical lines get a full-row red highlight (like the reference).
CRITICAL_BG = QColor("#7f1d1d")
CRITICAL_BG.setAlpha(180)

# Monospace font for log lines; tabular nums make line numbers align.
LOG_FONT_FAMILY = "Monospace"


# Time-window filter choices. Keys are internal and stable across
# translations; values are minutes, 0 meaning "no filter". Both the
# viewer's toolbar combo and the settings dialog read this one map —
# they used to carry a copy each.
TIME_WINDOW_KEYS: tuple[str, ...] = ("all", "5m", "15m", "1h", "6h", "24h")
TIME_WINDOW_MINUTES: dict[str, int] = {
    "all": 0,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "6h": 360,
    "24h": 1440,
}


def time_window_index(minutes: int) -> int:
    """Index of the combo entry matching `minutes`, or 0 ("all")."""
    for i, key in enumerate(TIME_WINDOW_KEYS):
        if TIME_WINDOW_MINUTES[key] == minutes:
            return i
    return 0


def level_checkbox_style(level: str) -> str:
    """Stylesheet for a level filter checkbox.

    Shared so the log viewer's filter row and the tray settings dialog
    cannot drift apart — they used to build this string separately.
    """
    colour = LEVEL_COLORS[level].name()
    weight = "; font-weight: bold" if level == "TRACEBACK" else ""
    return f"QCheckBox {{ color: {colour}{weight}; }}"


def section_label(text: str) -> QLabel:
    """A bold sub-header for grouping related controls.

    Used by both settings dialogs; it existed as a private static
    method on each of them.
    """
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold; font-size: 11pt; margin-top: 10px;")
    return label
