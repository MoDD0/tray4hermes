"""Icon factory and state → color/tooltip mapping.

Icons are drawn programmatically — no PNG assets to ship. The QPainter
API requires QApplication to exist before QPixmap is created; this module
only exposes the maker function so callers must instantiate QApplication
first (see app.py).
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap

# Dynamic gettext lookup — see the same wrapper in app.py for why it
# reads ``i18n._`` on every call instead of binding it at import time.
try:
    from tray4hermes import i18n as _i18n_mod

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        """Dynamic gettext wrapper — looks up i18n._ on every call."""
        return _i18n_mod._(s)  # type: ignore[attr-defined]
except ImportError:

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        return s


# ── State → color ──────────────────────────────────────────────────────────
STATE_COLORS: dict[str, str] = {
    "active": "#4caf50",  # green
    "warming": "#ff9800",  # orange
    "activating": "#2196f3",  # blue
    "inactive": "#9e9e9e",  # grey
    "failed": "#f44336",  # red
    "unknown": "#9e9e9e",  # grey
}


def state_tooltip(code: str) -> str:
    """Translated tray tooltip for a state code.

    A function, not a module-level dict: the dict literal would be
    evaluated at import time, which is *before* ``i18n.install()``
    runs, so every tooltip would freeze in the startup language and
    ignore a later ``switch_language()``. Building it per call costs
    nothing — the tray only asks when the state actually changes.
    """
    tooltips = {
        "active": _("Hermes Gateway — running and connected"),
        "warming": _("Hermes Gateway — running, waiting for connection"),
        "activating": _("Hermes Gateway — starting…"),
        "inactive": _("Hermes Gateway — stopped"),
        "failed": _("Hermes Gateway — failed!"),
        "unknown": _("Hermes Gateway — unknown state"),
    }
    return tooltips.get(code, tooltips["unknown"])


def make_icon(color: str, size: int = 64) -> QIcon:
    """Generate a colored circle with a white 'H' glyph. Qt only."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(4, 4, size - 8, size - 8)
        p.setPen(QColor("white"))
        font = p.font()
        font.setPixelSize(int(size * 0.55))
        font.setBold(True)
        p.setFont(font)
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "H")
    finally:
        p.end()
    return QIcon(px)


# Cached brand icon (green H-circle). Created lazily once QApplication
# exists; safe to call from dialog constructors pre-QApplication too —
# the cache is empty and the fallback is just a transparent QIcon.
_brand_icon: QIcon | None = None


def brand_icon() -> QIcon:
    """The tray4hermes brand icon: green circle with a white H.

    Used as the window icon for every dialog (Log, About, Settings) so
    you don't get the default Qt placeholder glyph in the title bar.
    """
    global _brand_icon
    if _brand_icon is None:
        # The "active" color is the brand green. Qt caches the icon
        # itself on QApplication, so creating it once is enough.
        _brand_icon = make_icon(STATE_COLORS["active"], size=64)
    return _brand_icon
