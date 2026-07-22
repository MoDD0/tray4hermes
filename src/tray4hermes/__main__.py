"""`python -m tray4hermes` entry point.

Supports `--help` and `--version` flags without spinning up a
QApplication. All other paths acquire the single-instance lock and
run the tray.
"""

from __future__ import annotations

import argparse
import sys

from tray4hermes import __version__
from tray4hermes import paths as _paths


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Keep argparse deliberately small — flags are documented in README."""
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
    return parser.parse_args(argv)


def main() -> int:
    """Acquire single-instance lock, run the tray, release on exit."""
    args = _parse_args(sys.argv[1:])
    del args  # placeholder for future flags; nothing to act on today

    from tray4hermes.lock import acquire, release

    if not acquire(_paths.lock_file()):
        # Another tray is already running — pop a dialog so the user knows.
        from PyQt5.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(
            None,
            "Hermes Tray",
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
