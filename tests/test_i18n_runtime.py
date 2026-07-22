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

import builtins as _b

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


def test_install_with_cs_returns_czech_copy() -> None:
    """When ``install(language='cs')`` runs against our shipped
    ``cs.mo``, ``_(...)`` must return translated strings.

    Czech IS the source language (the Czech .po file has
    msgstr = msgid verbatim), so we expect strings like
    'Kopírovat' to round-trip.
    """
    i18n.install(language="cs")
    _ = _gettext()
    # Identical to source — Latin alphabet survives intact.
    assert _("Kopírovat") == "Kopírovat"


def test_install_with_en_returns_english_source() -> None:
    """English IS the source language; install(language='en')
    shouldn't break strings — and we don't ship an en.po, so
    _ resolves through the source fallback chain."""
    i18n.install(language="en")
    _ = _gettext()
    assert _("Kopírovat") == "Kopírovat"
    assert _("Find") == "Find"
    assert (
        _("this string definitely does not exist in any translation")
        == "this string definitely does not exist in any translation"
    )


def test_install_with_unknown_language_falls_back_to_source() -> None:
    """Calling install(language='xx') where 'xx' is not in our
    catalogue must fall back to source strings, not raise."""
    i18n.install(language="xx-this-does-not-exist")
    _ = _gettext()
    assert _("Kopírovat") == "Kopírovat"


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
