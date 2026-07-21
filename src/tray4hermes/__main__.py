"""`python -m tray4hermes` entry point."""

from __future__ import annotations

import sys

from tray4hermes import paths as _paths
from tray4hermes.lock import acquire, release


def main() -> int:
    """Acquire single-instance lock, run the tray, release on exit."""
    if not acquire(_paths.lock_file()):
        # Another tray is already running — pop a dialog so the user knows.
        from PyQt5.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(
            None,
            "Hermes Tray",
            "tray4hermes už běží.\nNajdeš ho v systémové liště.",
        )
        return 2

    try:
        from tray4hermes.app import HermesTray

        return HermesTray().run()
    finally:
        release(_paths.lock_file())


if __name__ == "__main__":
    sys.exit(main())
