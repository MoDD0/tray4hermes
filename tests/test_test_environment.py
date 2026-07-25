"""Guards on the test environment itself.

`pyproject.toml` carried `env = ["QT_QPA_PLATFORM = offscreen"]` with a
comment claiming pytest-qt reads it. It does not — that key belongs to
`pytest-env`, which is not installed, so the setting never applied and
pytest reported `Unknown config option: env` on every run. Locally the
tests passed anyway because a real X display was there to catch them.
On a headless runner they would not have.
"""

from __future__ import annotations

import os

from PyQt5.QtWidgets import QApplication


def test_qt_runs_headless(qapp: QApplication) -> None:
    """No display server may be required to run the suite."""
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    assert qapp.platformName() == "offscreen", (
        f"Qt is talking to a real display ({qapp.platformName()}); "
        "the suite would fail on a headless runner"
    )
