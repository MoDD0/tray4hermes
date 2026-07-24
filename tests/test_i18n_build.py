"""Tests for scripts/i18n_build.py helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def i18n_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "i18n_build.py"
    spec = importlib.util.spec_from_file_location("tray4hermes_i18n", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register the module in ``sys.modules`` before executing it. The
    # module uses ``@dataclass`` with PEP 563 string annotations
    # (``from __future__ import annotations``); Python's dataclass machinery
    # looks up the owning module by name to resolve those annotations,
    # and a freshly loaded module that's *not* in ``sys.modules`` would
    # make that lookup return ``None``.
    sys.modules["tray4hermes_i18n"] = module
    spec.loader.exec_module(module)
    return module


def test_rewrite_version_substitutes_placeholder(i18n_module) -> None:
    src = "# tray4hermes <!-- tray4hermes:version -->\nbody\n"
    out = i18n_module.rewrite_version_placeholder(src, "9.9.9")
    assert "9.9.9" in out
    assert "tray4hermes:version" not in out
    assert out.startswith("# tray4hermes")


def test_rewrite_version_with_suffix_in_h1(i18n_module) -> None:
    src = "# tray4hermes (česky) <!-- tray4hermes:version -->\nbody\n"
    out = i18n_module.rewrite_version_placeholder(src, "1.2.3")
    assert "1.2.3" in out
    assert "# tray4hermes (česky)" in out


def test_rewrite_version_idempotent(i18n_module) -> None:
    src = "# tray4hermes <!-- tray4hermes:version -->\nbody\n"
    once = i18n_module.rewrite_version_placeholder(src, "1.0.0")
    twice = i18n_module.rewrite_version_placeholder(once, "1.0.0")
    assert once == twice


def test_relative_image_paths_repo_root(i18n_module, tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "docs" / "images").mkdir(parents=True)
    (repo / "docs" / "i18n" / "en.md").parent.mkdir(parents=True)
    (repo / "docs" / "i18n" / "en.md").write_text(
        "![](docs/images/kde_tray.png)\n", encoding="utf-8"
    )
    # Simulate README.md at the repo root: from_dir is the repo root,
    # target is docs/images/kde_tray.png — the compiled README should
    # emit the literal repo-relative path.
    target_rel = Path("docs") / "images" / "kde_tray.png"
    from_dir = repo
    out = i18n_module._relative_inside_repo(from_dir, target_rel, repo)
    assert out == "docs/images/kde_tray.png"


def test_relative_image_paths_nested_readme(i18n_module, tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "docs" / "images").mkdir(parents=True)
    target_rel = Path("docs") / "images" / "kde_tray.png"
    # Compiled `docs/README.cs.md` lives in `docs/`, so `from_dir` is
    # `repo/docs`. The compiled README needs `images/kde_tray.png`.
    from_dir = repo / "docs"
    out = i18n_module._relative_inside_repo(from_dir, target_rel, repo)
    assert out == "images/kde_tray.png"


def test_verify_assets_fails_on_missing(i18n_module, tmp_path: Path) -> None:
    rc = i18n_module.verify_assets(tmp_path)
    assert rc == 1


def test_verify_assets_passes_when_present(i18n_module, tmp_path: Path) -> None:
    (tmp_path / "docs" / "images").mkdir(parents=True)
    for rel, _label in i18n_module._IMAGE_LOCATIONS:
        (tmp_path / rel).write_bytes(b"x")
    assert i18n_module.verify_assets(tmp_path) == 0
