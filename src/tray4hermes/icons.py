"""Icon factory and state → color/tooltip mapping.

Icons are drawn programmatically — no PNG assets to ship. The QPainter
API requires QApplication to exist before QPixmap is created; this module
only exposes the maker function so callers must instantiate QApplication
first (see app.py).
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap

# ── State → (color, tooltip) ───────────────────────────────────────────────
STATE_COLORS: dict[str, str] = {
    "active": "#4caf50",  # zelená
    "warming": "#ff9800",  # oranžová
    "activating": "#2196f3",  # modrá
    "inactive": "#9e9e9e",  # šedá
    "failed": "#f44336",  # červená
    "unknown": "#9e9e9e",  # šedá
}

STATE_TOOLTIPS: dict[str, str] = {
    "active": "Hermes Gateway — běží a připojená",
    "warming": "Hermes Gateway — běží, čeká na připojení",
    "activating": "Hermes Gateway — startuje…",
    "inactive": "Hermes Gateway — zastavena",
    "failed": "Hermes Gateway — selhala!",
    "unknown": "Hermes Gateway — neznámý stav",
}


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
