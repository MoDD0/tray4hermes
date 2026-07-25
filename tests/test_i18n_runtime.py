"""Pytest coverage for runtime UI translation (gettext catalogue).

This complements ``tests/test_i18n_parity.py`` (which tests the
README i18n build/lint pipeline) by testing the in-app
behaviour:

1. ``install()`` succeeds both with and without a translation
   catalogue on disk.
2. ``available_languages()`` returns exactly the locales for
   which we shipped a compiled ``.mo`` file.
3. After ``install(language='cs')``, ``_(...)`` returns the
   Czech translation. After ``install(language='en')``, the
   same call returns the source string verbatim (English IS
   the source language for our package).
4. Unknown languages fall back to source strings, not crash.

Note on ``builtins._``: ``gettext.install()`` mutates the
``builtins`` module to bind ``_`` there. We access it via
``builtins.__dict__["_"]`` (look up by key) rather than
``builtins._`` (attribute lookup), because the latter can be
intercepted by name-shadowing in unrelated test modules.
"""

from __future__ import annotations

import ast
import builtins as _b
import gettext
from pathlib import Path

import pytest

from tray4hermes import i18n


@pytest.fixture(autouse=True)
def reset_gettext() -> None:
    """Restore gettext bindings to source strings after each test.

    ``gettext.install()`` mutates ``builtins._``; we want each
    test to start fresh, so after-yield we re-install the
    English source translation (which is a no-op round-trip —
    English strings resolve to themselves).

    Yields nothing — Pytest fixture marker is fine with
    ``autouse=True`` returning a no-op generator.
    """
    yield
    i18n.install(language="en")


def _gettext() -> object:
    """Return the installed gettext callable as stored on builtins."""
    return _b.__dict__.get("_", lambda s: s)


def _source_msgids() -> set[str]:
    """Every literal msgid the package passes to ``_()``.

    Implicit concatenation (``_("a" "b")``) is already a single
    Constant by the time we see the tree, so a msgid split across
    source lines is collected whole — exactly as xgettext sees it.
    Non-literal calls (``_(variable)``) are skipped: there is no
    msgid to look up statically.
    """
    src = Path(i18n.__file__).resolve().parent
    out: set[str] = set()
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "_":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.add(arg.value)
    return out


def test_install_with_cs_returns_czech_copy() -> None:
    """When ``install(language='cs')`` runs against our shipped
    ``cs.mo``, ``_(...)`` must return translated strings.

    Source code uses English msgIDs (e.g. ``_("Copy")``); the cs.po
    maps ``Copy → Kopírovat``. So after install('cs'), ``_("Copy")``
    must return the Czech translation.

    The second half checks the same claim for *every* msgid instead
    of three hand-picked ones. Spot checks cannot see a msgid the
    catalogue never got, and they cannot see one whose ``\\n`` was
    written ``\\\\n`` in the .po — gettext then keys the entry under a
    literal backslash-n that no source string will ever match, so the
    dialog silently stays English. Both had happened.
    """
    i18n.install(language="cs")
    _ = _gettext()
    assert _("Copy") == "Kopírovat"
    assert _("Settings") == "Nastavení"
    assert _("Find") == "Najít"

    # ``_catalog`` is the msgid → msgstr dict gettext builds from the
    # .mo. We read it directly rather than compare ``_(s) != s``:
    # a few msgids ("Auto-scroll") are legitimately identical in Czech,
    # and that comparison would flag them as missing.
    catalogue = gettext.translation(
        "tray4hermes",
        localedir=str(Path(i18n.__file__).resolve().parent / "_locales"),
        languages=["cs"],
    )._catalog  # type: ignore[attr-defined]
    missing = sorted(m for m in _source_msgids() if m not in catalogue)
    assert missing == [], f"msgids missing from cs.po ({len(missing)}): {missing}"


def test_install_with_en_returns_english_source() -> None:
    """English IS the source language; install(language='en')
    returns msgIDs verbatim (NullTranslations identity)."""
    i18n.install(language="en")
    _ = _gettext()
    assert _("Copy") == "Copy"
    assert _("Settings") == "Settings"
    assert _("Find") == "Find"
    assert (
        _("this string definitely does not exist in any translation")
        == "this string definitely does not exist in any translation"
    )


def test_install_with_unknown_language_falls_back_to_source() -> None:
    """Calling install(language='xx') where 'xx' is not in our
    catalogue must fall back to source strings (English), not
    to Czech."""
    i18n.install(language="xx-this-does-not-exist")
    _ = _gettext()
    # Unknown language → gettext fallback chain → no match →
    # NullTranslations → returns msgID verbatim (English source).
    assert _("Copy") == "Copy"


def test_available_languages_includes_cs() -> None:
    """The shipped-translation surface should include at
    least 'cs'. (English is the source language, so it doesn't
    appear as a separate locale.)"""
    available = i18n.available_languages()
    assert "cs" in available, (
        f"expected 'cs' in available languages; got {available}. "
        f"Make sure locales/cs/LC_MESSAGES/tray4hermes.mo is "
        f"compiled and reachable from this test."
    )


def test_install_system_language_honours_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` means follow the OS locale, not force English."""
    monkeypatch.setenv("LC_ALL", "cs_CZ.UTF-8")
    i18n.install(language=None)
    assert i18n._("Settings") == "Nastavení"


def test_language_display_names_are_human_readable() -> None:
    assert i18n.language_display_name(None) == "System (follow locale)"
    assert i18n.language_display_name("en") == "English"
    assert i18n.language_display_name("cs") == "Čeština"


def test_gettext_source_strings_use_english_msgids() -> None:
    """English is canonical; Czech belongs only in the cs catalogue."""
    src = Path(__file__).resolve().parents[1] / "src" / "tray4hermes"
    offenders: list[str] = []
    for path in src.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "_":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if any(ch in arg.value for ch in "áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"):
                    offenders.append(f"{path.name}:{node.lineno}: {arg.value!r}")
    assert offenders == []


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of the Constant nodes that are module/class/function docstrings.

    Docstrings are developer prose, not UI. They may be written in any
    language without that being a translation bug.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add(id(first.value))
    return out


def _gettext_argument_nodes(tree: ast.AST) -> set[int]:
    """Ids of every node nested inside a ``_(...)`` call argument.

    Walks the whole argument subtree, not just a top-level Constant, so
    an implicitly concatenated msgid spanning several source lines is
    exempt as a whole.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "_":
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                out.add(id(sub))
    return out


def _language_endonym_nodes(tree: ast.AST) -> set[int]:
    """Ids of the string nodes in ``i18n._LANGUAGE_NAMES``.

    A language picker lists every language in its own language, so
    ``"cs": "Čeština"`` stays Czech in an English UI on purpose. The
    exemption is bound to that one assignment rather than to the word
    itself, so a stray "Čeština" anywhere else still fails.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or node.value is None:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_LANGUAGE_NAMES" for t in node.targets):
            continue
        for sub in ast.walk(node.value):
            out.add(id(sub))
    return out


def test_no_unwrapped_czech_strings_in_source() -> None:
    """Czech may only live in the catalogue, never in a source literal.

    The sibling test above inspects the *arguments of* ``_()``, so a
    Czech string that was never wrapped is invisible to it. That blind
    spot is how ``icons.STATE_TOOLTIPS`` and every ``GatewayState``
    label stayed hard-coded Czech through an entire i18n effort — the
    suite was green the whole time. This test walks every string
    literal in the package instead, skipping docstrings and anything
    already inside ``_()``.
    """
    src = Path(__file__).resolve().parents[1] / "src" / "tray4hermes"
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        exempt = (
            _docstring_nodes(tree) | _gettext_argument_nodes(tree) | _language_endonym_nodes(tree)
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in exempt:
                continue
            if any(ch in node.value for ch in "áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"):
                offenders.append(f"{path.name}:{node.lineno}: {node.value!r}")
    assert offenders == [], "Czech literals outside _(): " + " | ".join(offenders)


def test_no_translation_regression_against_growing_source() -> None:
    """If someone adds a new ``_('Foo')`` to a source file without
    updating the .pot, we still want the existing translations
    to keep working — they should just fall back to the source
    string for the new msgid.

    This test exercises that fallback path by calling _() with a
    string we know nothing about.
    """
    i18n.install(language="cs")
    _ = _gettext()
    sentinel = "this string was never in cs.po, ever"
    # Source fallback wins — `_()` returns the input unchanged
    # when no translation matches.
    assert _(sentinel) == sentinel
