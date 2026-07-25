"""Shared pytest fixtures."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Qt must not need a display server. This has to happen at import time:
# conftest is loaded before any test module, and the value is read when
# the first QApplication is constructed. `setdefault` so a developer can
# still force `QT_QPA_PLATFORM=xcb` to watch a dialog on screen.
#
# It used to live in `pyproject.toml` as `env = [...]`, a key owned by
# `pytest-env` — a plugin this project does not install. The setting
# silently did nothing and pytest warned about it on every run.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolate_hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own fake ~/.hermes — no touching the real one."""
    fake_hermes = tmp_path / "hermes"
    fake_hermes.mkdir()
    (fake_hermes / "logs").mkdir()
    (fake_hermes / "profiles").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(fake_hermes))
    monkeypatch.setenv("TRAY4HERMES_HOME", str(fake_hermes))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("TRAY4HERMES_LOCK", str(tmp_path / "tray.lock"))


@pytest.fixture
def hermes_home() -> Path:
    """The (now isolated) ~/.hermes directory."""
    return Path(os.environ["TRAY4HERMES_HOME"])


@pytest.fixture
def xdg_config() -> Path:
    """The (now isolated) ~/.config directory."""
    return Path(os.environ["XDG_CONFIG_HOME"])


# ── Documentation build ──────────────────────────────────────────────────────
# `scripts/i18n_build.py` locates the repo relative to its own file and
# writes README.md / docs/README.cs.md there. Running it for real from a
# test therefore edits tracked files in the working tree — which is
# exactly what used to happen on every `pytest` run. Tests that need a
# writing build get a throwaway copy instead; tests that only need to
# *read* the build's verdict use `--check`, which never writes.

# Everything the doc build reads or writes. `src/tray4hermes/__init__.py`
# is here because the script reads `__version__` out of it for the badge.
_DOC_BUILD_TREE: tuple[str, ...] = (
    "scripts",
    "docs",
    "src/tray4hermes/__init__.py",
    "README.md",
)


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A disposable copy of the repo slice that the doc build touches."""
    dst_root = tmp_path / "repo"
    for rel in _DOC_BUILD_TREE:
        src = REPO_ROOT / rel
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    return dst_root


@pytest.fixture(scope="session")
def i18n_build() -> ModuleType:
    """`scripts/i18n_build.py` imported as a module.

    The scripts directory is not a package and is not on `sys.path`, so
    it is loaded by file location. The module is registered in
    `sys.modules` before execution because its `@dataclass` needs to
    resolve PEP 563 string annotations through its own module entry.
    """
    path = REPO_ROOT / "scripts" / "i18n_build.py"
    spec = importlib.util.spec_from_file_location("tray4hermes_i18n_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["tray4hermes_i18n_build"] = module
    spec.loader.exec_module(module)
    return module
