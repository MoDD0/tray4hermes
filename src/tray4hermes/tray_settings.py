"""Global Tray4Hermes settings dialog and persistence.

This is the 'control panel' for Tray4Hermes itself — separate from
the log viewer's own settings (which live in ``LogSettings`` /
``LogSettingsDialog`` in ``logs_view.py``).

The user opens it from the tray menu: **Nastavení tray4hermes**.
It shows a Qt form with:

- **Jazyk** (Language): System / English / Čeština / …
  — populated from ``i18n.available_languages()`` + the canonical
  English source. Stored as ``language`` in the JSON state file.
  Takes effect on restart (the dialog tells the user).

- **Výchozí počet řádků** (Default max lines): the ``max_lines``
  the log viewer starts with on first open. Stored as
  ``default_max_lines``.

- **Výchozí úrovně** (Default visible levels): which log levels
  are checked by default when the log viewer opens. Stored as
  ``default_show_levels``.

- **Auto-scroll od startu** (Auto-scroll from start): whether
  auto-scroll is ON when the log viewer opens. Stored as
  ``default_auto_scroll``.

- **Zalamovat od startu** (Word wrap from start): whether word-wrap
  is ON when the log viewer opens. Stored as ``default_word_wrap``.

All five are persisted into the same ``~/.config/tray4hermes/
state.json`` under a ``tray_settings`` key, alongside the existing
``log_settings`` key (which stores the log viewer's *last-used*
state, not the defaults).
"""

from __future__ import annotations

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

from tray4hermes.logs_view import LEVEL_COLORS
from tray4hermes.paths import tray_state_file

# Re-export the gettext stub so this module doesn't need the
# try/except dance. If i18n.install() hasn't been called yet,
# `_` falls back to identity (returns source strings verbatim).
try:
    from tray4hermes.i18n import _ as _  # noqa: PLC0415
except ImportError:

    def _(s: str) -> str:  # type: ignore[no-redef]  # noqa: ANN001
        return s


# ── Data model ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraySettings:
    """Global, persistent preferences for Tray4Hermes itself.

    These are the *defaults* that the log viewer and the tray read
    when they start up. The log viewer's *last-used* state is stored
    separately in ``LogSettings`` (which has its own persistence
    under the ``log_settings`` key in the same JSON file).
    """

    # UI language. ``None`` = follow OS locale.
    language: str | None = None

    # Default max_lines for the log viewer on first open.
    # 0 = unlimited.
    default_max_lines: int = 2000

    # Default visible log levels on first open.
    default_show_levels: tuple[str, ...] = (
        "ERROR",
        "WARNING",
        "INFO",
        "DEBUG",
        "CRITICAL",
        "TRACE",
    )

    # Default auto_scroll on first open.
    default_auto_scroll: bool = True

    # Default word_wrap on first open.
    default_word_wrap: bool = False

    # Schema version for forward-compat migrations.
    schema_version: int = 1

    def to_json(self) -> dict[str, object]:
        return {
            "language": self.language,
            "default_max_lines": self.default_max_lines,
            "default_show_levels": list(self.default_show_levels),
            "default_auto_scroll": self.default_auto_scroll,
            "default_word_wrap": self.default_word_wrap,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> TraySettings:
        levels = data.get("default_show_levels")
        raw_lang = data.get("language", None)
        language = str(raw_lang) if raw_lang else None
        return cls(
            language=language,
            default_max_lines=int(data.get("default_max_lines", 2000)),
            default_show_levels=tuple(str(x) for x in levels)
            if isinstance(levels, (list, tuple))
            else cls().default_show_levels,
            default_auto_scroll=bool(data.get("default_auto_scroll", True)),
            default_word_wrap=bool(data.get("default_word_wrap", False)),
            schema_version=int(data.get("schema_version", 1)),
        )

    @classmethod
    def default(cls) -> TraySettings:
        return cls()


# ── Persistence (same state.json, different key) ──────────────────────────


def load_tray_settings() -> TraySettings:
    """Read tray_settings from state.json. Returns default on error."""
    import json as _json

    p = tray_state_file()
    try:
        with open(p) as f:
            data = _json.load(f)
        raw = data.get("tray_settings", {})
        if not isinstance(raw, dict):
            return TraySettings.default()
        return TraySettings.from_json(raw)
    except (FileNotFoundError, OSError, ValueError, KeyError):
        return TraySettings.default()


def save_tray_settings(settings: TraySettings) -> None:
    """Persist tray_settings into state.json. Never raises."""
    import json as _json
    import os
    import sys

    p = tray_state_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p) as f:
                data = _json.load(f)
        except (FileNotFoundError, OSError, ValueError):
            data = {}
        data["tray_settings"] = settings.to_json()
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w") as f:
            _json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError as exc:
        print(f"[tray4hermes] save_tray_settings failed: {exc}", file=sys.stderr)


# ── Dialog ────────────────────────────────────────────────────────────────


class TraySettingsDialog(QDialog):
    """Global Tray4Hermes settings — Qt form, not a text editor.

    This is what opens when the user clicks 'Nastavení tray4hermes'
    in the tray menu. It is NOT the log viewer's settings dialog
    (that's ``LogSettingsDialog`` in ``logs_view.py``).
    """

    def __init__(self, current: TraySettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Nastavení tray4hermes"))
        self.resize(400, 450)
        layout = QVBoxLayout(self)

        # ── Language ──────────────────────────────────────────────
        layout.addWidget(self._section_label(_("Jazyk")))

        row = QHBoxLayout()
        row.addWidget(QLabel(_("Jazyk rozhraní:")))
        self._language = QComboBox()
        # The first entry is always "System (follow locale)"; then
        # English (canonical source); then every compiled .mo.
        self._lang_keys: list[str | None] = [None]
        self._language.addItem(_("Systémový (dle locale)"))
        # English is always available (it's the source language).
        self._lang_keys.append("en")
        self._language.addItem("English")
        try:
            from tray4hermes.i18n import available_languages

            for lang_code in available_languages():
                if lang_code == "en":
                    continue
                self._lang_keys.append(lang_code)
                self._language.addItem(lang_code)
        except Exception as e:  # noqa: BLE001
            import sys as _sys

            print(f"[tray4hermes] language list unavailable: {e}", file=_sys.stderr)

        # Select current
        if current.language is None:
            self._language.setCurrentIndex(0)
        else:
            for i, k in enumerate(self._lang_keys):
                if k == current.language:
                    self._language.setCurrentIndex(i)
                    break
        row.addWidget(self._language)
        layout.addLayout(row)

        hint = QLabel(_("ℹ Změna jazyka se projeví po restartu tray4hermes."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(hint)

        # ── Log viewer defaults ───────────────────────────────────
        layout.addWidget(self._section_label(_("Výchozí nastavení logů")))

        # Default max lines
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Výchozí počet řádků:")))
        self._max_lines = QSpinBox()
        self._max_lines.setRange(0, 100_000)
        self._max_lines.setSingleStep(500)
        self._max_lines.setValue(current.default_max_lines)
        self._max_lines.setToolTip(_("0 = bez limitu"))
        row.addWidget(self._max_lines)
        layout.addLayout(row)

        # Default auto-scroll
        self._auto_scroll = QCheckBox(_("Auto-scroll od startu"))
        self._auto_scroll.setChecked(current.default_auto_scroll)
        layout.addWidget(self._auto_scroll)

        # Default word wrap
        self._word_wrap = QCheckBox(_("Zalamovat od startu"))
        self._word_wrap.setChecked(current.default_word_wrap)
        layout.addWidget(self._word_wrap)

        # Default levels
        layout.addWidget(QLabel(_("Výchozí viditelné úrovně:")))
        self._level_checks: dict[str, QCheckBox] = {}
        for level in ("ERROR", "WARNING", "INFO", "DEBUG", "TRACE"):
            cb = QCheckBox(level)
            cb.setChecked(level in current.default_show_levels)
            cb.setStyleSheet(f"QCheckBox {{ color: {LEVEL_COLORS[level].name()}; }}")
            self._level_checks[level] = cb
            layout.addWidget(cb)

        # ── OK / Cancel ───────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; font-size: 11pt; margin-top: 10px;")
        return lbl

    def result_settings(self) -> TraySettings:
        """Build a fresh TraySettings from the dialog's widget state."""
        levels = tuple(lvl for lvl, cb in self._level_checks.items() if cb.isChecked())
        lang_idx = self._language.currentIndex()
        language = self._lang_keys[lang_idx] if 0 <= lang_idx < len(self._lang_keys) else None
        return TraySettings(
            language=language,
            default_max_lines=self._max_lines.value(),
            default_show_levels=levels,
            default_auto_scroll=self._auto_scroll.isChecked(),
            default_word_wrap=self._word_wrap.isChecked(),
        )
