"""i18n (gettext-based) for tray4hermes UI strings.

We use the standard library ``gettext`` module so we don't take
on a runtime dependency. Workflow:

1. Wrapped strings use ``_(...)`` (or ``gettext(...)`` if you
   need to defer resolution inside a callable).
2. Source-language catalogues are extracted with
   ``xgettext/pybabel`` (developer tool, not a runtime dep).
3. Compiled ``.mo`` files live under ``locales/<lang>/LC_MESSAGES/``
   next to the source tree. We bundle them as package data so
   ``pip install tray4hermes`` ships the right translations.

Why gettext and not a custom JSON loader:

- It's the Python ecosystem standard (Qt lupdate ships a
  gettext-compatible format; Sphinx/RST/pootle/weblate all
  consume ``.po`` directly).
- It is pluralisation-aware out of the box (we don't currently
  need plurals, but we'd hate to retrofit later).
- It is locale-aware: ``gettext.install(...)`` reads the
  user's ``LANG`` / ``LANGUAGE`` environment variables
  automatically and falls back to source strings if a
  translation is missing — zero ceremony in the call sites.

The module here is intentionally tiny. The interesting parts:

1. ``install(...)`` — call this exactly once, very early (in
   ``__main__`` before any UI is touched), so the rest of the
   code can use ``_(...)``.
2. ``switch_language(lang)`` — runtime language override for the
   settings dialog. Binds a new ``gettext`` translation on top
   of whatever was previously active.
3. ``available_languages`` — list of locales for which a
   compiled ``.mo`` file exists at startup. Drives the UI
   language picker dropdown.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

# Domain used in xgettext calls — keep in sync with the
# `msgid ""` field of every .po file we ship.
_DOMAIN = "tray4hermes"


# Where to look for compiled .mo files.
#
# Both during in-tree development (next to src/) and once the
# wheel is installed (Python locates these via ``__package__``
# using importlib.resources), this helper tries the obvious
# places in order.
def _candidate_dirs() -> Iterable[Path]:
    """Filesystem locations to look for locales/ in, in priority
    order.

    1. The source tree's ``locales/`` next to the project root.
       This is where contributors run the app from — convenient
       for live editing without re-installing.
    2. The installed location (under the ``tray4hermes`` package).
       When users ``pip install tray4hermes`` the ``.mo`` files
       ship inside the wheel.
    """
    cwd = Path.cwd()
    yield cwd / "locales"
    # Installed package locations
    try:
        from importlib.resources import files as _files

        pkg_root = _files("tray4hermes") / "_locales"
        if pkg_root.is_dir():
            yield Path(str(pkg_root))
    except (ImportError, ModuleNotFoundError):
        # importlib.resources raises ModuleNotFoundError if the
        # distribution isn't found; in older Pythons it raises
        # ImportError. Either way, we silently fall back to the
        # next candidate.
        pass
    # Fallback: walk up from this file's parent
    this = Path(__file__).resolve().parent
    for ancestor in this.parents:
        candidate = ancestor / "locales"
        if candidate.is_dir():
            yield candidate
            break
    yield cwd  # last-resort: per-project cwd


def _resolve_locales_dir() -> Path | None:
    """Return the first locales/ directory found, or None."""
    for d in _candidate_dirs():
        if d.is_dir():
            return d
    return None


def _candidate_locale_dirs(locales_root: Path) -> list[str]:
    """Walk locales/<lang>/ directories; return their `lang` names
    (ISO 639-1 short codes). We don't introspect `LC_MESSAGES/` —
    a locale is valid if its directory exists.
    """
    out: list[str] = []
    for child in sorted(locales_root.iterdir()):
        if not child.is_dir():
            continue
        # Skip meta-directories like __pycache__, .git, etc.
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        out.append(child.name)
    return out


def available_languages() -> list[str]:
    """Locale codes for which we can produce a gettext translation
    object — i.e. locales/<lang>/LC_MESSAGES/tray4hermes.mo exists.

    The languages are returned in the order they appear in the
    ``locales/`` tree so the UI's language picker is stable across
    runs (the underlying ``sorted()`` is in ``_candidate_locale_dirs``).
    """
    locales_root = _resolve_locales_dir()
    if locales_root is None:
        return []
    out: list[str] = []
    for lang in _candidate_locale_dirs(locales_root):
        mo = locales_root / lang / "LC_MESSAGES" / f"{_DOMAIN}.mo"
        if mo.is_file():
            out.append(lang)
    return out


def install(language: str | None = None) -> None:
    """Bind the appropriate gettext translation as ``builtins._``.

    Call this once at process startup, before any UI code path is
    loaded. Subsequent ``_(...)`` calls resolve against the bound
    translation.

    If a translation for ``language`` isn't available (e.g. user
    picks a locale we don't ship yet), falls back to the source
    strings — that's the documented gettext behaviour.

    If ``language`` is None, we honour the OS environment
    (``LANG``, ``LC_ALL``, ``LC_MESSAGES``) with a fallback chain
    of ``['en', 'cs']`` — English is the canonical reference, Czech
    is the maintainer's native tongue and the first translation
    we wrote.

    Implementation note: we shadow the module-level ``gettext``
    symbol with ``gettext.translation()`` for the explicit-import
    case (``from tray4hermes.i18n import gettext``). Be careful
    inside this function — anything called ``gettext`` after the
    shadowing is the *function*, not the stdlib module. We use a
    local alias ``_gettext`` (the stdlib module) so re-runs of
    install() still work.
    """
    import gettext as _stdlib_gettext

    locales_root = _resolve_locales_dir()
    if locales_root is None:
        # No translations available — fall back to source strings.
        _stdlib_gettext.install(_DOMAIN, localedir=None, names=["ngettext"])
        return

    candidates: list[str] = []
    if language:
        candidates.append(language)
    # Fallback chain: explicit ask → env vars → English (canonical
    # reference, fall-back to source) → Czech (first translation).
    candidates.extend(_resolve_from_env())
    candidates.extend(["en", "cs"])

    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    translation = _stdlib_gettext.translation(
        domain=_DOMAIN,
        localedir=str(locales_root),
        languages=ordered,
        fallback=True,
    )
    translation.install(names=["ngettext"])

    # Also expose `gettext` through our module so callers can do
    # ``from tray4hermes.i18n import gettext`` for explicit
    # ``gettext("string")`` calls (e.g. in lazy contexts where
    # ``_`` is shadowed). Mirrors the builtins._ bind.
    globals()["gettext"] = translation.gettext
    globals()["ngettext"] = translation.ngettext
    globals()["_"] = translation.gettext  # noqa: PLW0124 (re-bind for explicit imports)


def _resolve_from_env() -> list[str]:
    """Read the OS env vars (LANG, LC_ALL, LC_MESSAGES, LANGUAGE)
    and return a list of candidate locale codes in priority order.

    Does NOT include the source-language fallback chain — that's
    the caller's job (we add 'en', 'cs' in install()).
    """
    out: list[str] = []
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if not val:
            continue
        # LANG is "cs_CZ.UTF-8" or "cs" or "cs.UTF-8"; we want the
        # leading "cs" part, not the encoding.
        for piece in val.split(":"):
            code = piece.split(".")[0].split("_")[0]
            if code and code != "C" and code != "POSIX":
                out.append(code)
    return out


def switch_language(language: str) -> None:
    """Rebind ``builtins._`` to a different language at runtime.

    Used by the settings dialog when the user picks a new
    language from the dropdown. After this returns, every call to
    ``_(...)`` resolves against the new translation.

    Limitations / scope:

    - We don't translate UI strings that have already been
      constructed (window titles, button labels, etc.). Qt
      re-renders those strings only when a widget is rebuilt.
      If we wanted hot-swap, we'd cache the source strings
      and rebuild the affected widgets. For our use case
      (settings dialog → restart), this is fine.
    - We don't tear down the existing translation object — we
      just replace the bind in builtins. Translations are
      immutable per-request.
    """
    install(language=language)
