"""`python -m tray4hermes` argument handling.

The README documents `tray4hermes --language` as the way to list the
languages built into the wheel. It never worked: `--language` was
declared without `nargs`, so argparse rejected the missing value and
exited 2 long before the block that would have printed the list. That
block sat in `main()` and was unreachable.
"""

from __future__ import annotations

import sys

import pytest

from tray4hermes.__main__ import LIST_LANGUAGES, _parse_args, _resolve_language, main


class TestLanguageArgument:
    @pytest.mark.parametrize("flag", ["--language", "-L"])
    def test_flag_without_a_value_asks_for_the_language_list(self, flag: str) -> None:
        """Both spellings — the short form was never covered."""
        assert _parse_args([flag]).language == LIST_LANGUAGES

    def test_flag_with_a_value_keeps_the_value(self) -> None:
        assert _parse_args(["--language", "cs"]).language == "cs"

    def test_flag_absent_means_no_preference(self) -> None:
        assert _parse_args([]).language is None

    def test_listing_languages_prints_them_and_exits_zero(
        self, monkeypatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from tray4hermes.i18n import available_languages

        monkeypatch.setattr(sys, "argv", ["tray4hermes", "--language"])

        assert main() == 0

        out = capsys.readouterr().out
        for code in available_languages():
            assert code in out, f"{code} is shipped but missing from the listing"

    def test_listing_languages_does_not_start_the_tray(self, monkeypatch) -> None:
        """The short-circuit has to return before the single-instance
        lock is taken — otherwise querying the build steals the lock
        from a running tray."""
        monkeypatch.setattr(sys, "argv", ["tray4hermes", "--language"])
        monkeypatch.setattr(
            "tray4hermes.lock.acquire",
            lambda *a, **kw: pytest.fail("the lock must not be touched"),
        )

        assert main() == 0


class TestLanguageResolution:
    """Priority: explicit CLI flag → saved TraySettings → OS environment."""

    def test_cli_flag_wins_over_the_saved_language(self) -> None:
        assert _resolve_language("en", saved="cs") == "en"

    def test_saved_language_is_used_when_the_flag_is_absent(self) -> None:
        assert _resolve_language(None, saved="cs") == "cs"

    def test_nothing_saved_and_no_flag_follows_the_os_environment(self) -> None:
        assert _resolve_language(None, saved=None) is None

    @pytest.mark.parametrize("value", ["none", "None", "NONE", "", "  "])
    def test_explicit_none_overrides_the_saved_language(self, value: str) -> None:
        """`--language none` is documented as "read from the OS
        environment". It has to beat the saved setting, otherwise it is
        indistinguishable from passing nothing at all."""
        assert _resolve_language(value, saved="cs") is None
