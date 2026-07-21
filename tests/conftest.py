"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own fake ~/.hermes — no touching the real one."""
    fake_hermes = tmp_path / "hermes"
    fake_hermes.mkdir()
    (fake_hermes / "logs").mkdir()
    (fake_hermes / "profiles").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(fake_hermes))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("TRAY4HERMES_LOCK", str(tmp_path / "tray.lock"))


@pytest.fixture
def hermes_home() -> Path:
    """The (now isolated) ~/.hermes directory."""
    return Path(os.environ["HERMES_HOME"])


@pytest.fixture
def xdg_config() -> Path:
    """The (now isolated) ~/.config directory."""
    return Path(os.environ["XDG_CONFIG_HOME"])
