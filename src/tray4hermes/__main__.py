"""`python -m tray4hermes` entry point.

Supports `--help`, `--version`, and `--language` flags. The
language flag accepts an ISO 639-1 code (e.g. ``cs``, ``en``,
``de``); when set, the runtime UI strings are translated into
that language if a translation exists. When omitted, the
selection follows the OS environment (``LC_ALL`` / ``LC_MESSAGES``
/ ``LANG``) with ``en`` (canonical) and ``cs`` (the first
translation we shipped) as the fallback chain.

Other paths acquire the single-instance lock and run the tray.
"""

from __future__ import annotations

import argparse
import sys

from tray4hermes import __version__
from tray4hermes import paths as _paths

# ``install`` is the runtime binding step for gettext; importing
# the symbol at module-load ensures we fail loudly if i18n
# machinery is missing, rather than later at the first ``_()``
# call. ``available_languages`` lets ``--language`` (with no
# argument) report what's shipped.
from tray4hermes.i18n import available_languages
from tray4hermes.i18n import install as _i18n_install


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Keep argparse deliberately small — flags are documented in README.

    Recognised flags:

    - ``--version``: print version and exit.
    - ``--help``:    print usage and exit.
    - ``--language`` / ``-L``: ISO 639-1 short code. ``--language cs``
      forces Czech. ``--language none`` (or ``--language`` with no
      value) reads from the OS environment.
    """
    parser = argparse.ArgumentParser(
        prog="tray4hermes",
        description=(
            "Passive KDE/Plasma tray monitor for Hermes Gateway. "
            "Controls the gateway via systemctl --user; otherwise read-only."
        ),
        epilog=(
            "See https://github.com/MoDD0/tray4hermes for full documentation, "
            "installation instructions, and contributing guidelines."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-L",
        "--language",
        default=None,
        metavar="CODE",
        help=(
            "Force a UI language (ISO 639-1 code, e.g. 'cs', 'en'). "
            "Default is to honour the OS locale (LANG / LC_ALL / LC_MESSAGES) "
            "with English / Czech as fallback. Pass --language without an "
            "argument to query which languages have been built into the wheel."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    """Acquire single-instance lock, run the tray, release on exit.

    Step 1: parse argv BEFORE binding gettext, so argparse's
    --help / --version text can still be read in source lang.

    Step 2: bind the UI translation. We do this only after we
    know which language to install (CLI flag or env), so Qt
    widgets constructed later pick up the right strings.
    """
    args = _parse_args(sys.argv[1:])
    language_arg: str | None = args.language

    # The ``--language`` flag with no argument is a short-circuit
    # to list available languages and exit; convenient for the
    # README snippet "what languages does this build support?"
    if "--language" in sys.argv[1:] and (
        "--language" == sys.argv[-1] or sys.argv[-2:] == ["--language", ""]
    ):
        print(
            "Available languages:",
            ", ".join(available_languages()) or "(none — no compiled .mo files found)",
        )
        return 0

    # Bind gettext with the requested language.
    #
    # Priority:
    #   1. --language CLI flag (highest)
    #   2. Saved TraySettings.language (from state.json)
    #   3. OS env (LANG/LC_ALL/LC_MESSAGES)
    #   4. English source (fallback)
    saved_lang = None
    try:
        from tray4hermes.tray_settings import load_tray_settings

        saved_lang = load_tray_settings().language
    except Exception as e:  # noqa: BLE001
        # Non-fatal — fall through to env/CLI
        import sys as _sys

        print(f"[tray4hermes] could not load saved language: {e}", file=_sys.stderr)
    effective_lang = language_arg or saved_lang
    _i18n_install(language=effective_lang)

    from tray4hermes.lock import acquire, release

    if not acquire(_paths.lock_file()):
        # Another tray is already running — pop a dialog so the user knows.
        from PyQt5.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(
            None,
            "Hermes Tray",
            # TRANSLATORS: body of a dialog shown when another instance
            # of the tray is already running (we hold a single-instance
            # lock and refuse to start a second).
            "tray4hermes is already running.\nFind it in the system tray.",
        )
        return 2

    try:
        from tray4hermes.app import HermesTray

        return HermesTray().run()
    finally:
        release(_paths.lock_file())


if __name__ == "__main__":
    sys.exit(main())
