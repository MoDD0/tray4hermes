"""Parity tests for the two-language README source.

These tests make sure ``docs/i18n/en.md`` and ``docs/i18n/cs.md`` stay in
sync: every image referenced in one must exist in the other and in the
repo. Drift between the two is the single most common cause of broken
GitHub READMEs, so we lock it down here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EN = REPO_ROOT / "docs" / "i18n" / "en.md"
CS = REPO_ROOT / "docs" / "i18n" / "cs.md"
IMAGES_DIR = REPO_ROOT / "docs" / "images"

# Image markdown syntax: ![alt](path). Absolute URLs and data URIs are
# ignored — only repo-relative paths are parity-checked.
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_IGNORED = ("http://", "https://", "data:", "/")


def _local_image_refs(md: Path) -> list[str]:
    text = md.read_text(encoding="utf-8")
    refs = []
    for match in _IMAGE_RE.finditer(text):
        ref = match.group(1).strip()
        if ref.startswith(_IGNORED):
            continue
        refs.append(ref)
    return refs


@pytest.fixture(scope="module")
def en_refs() -> list[str]:
    return _local_image_refs(EN)


@pytest.fixture(scope="module")
def cs_refs() -> list[str]:
    return _local_image_refs(CS)


def test_en_image_targets_exist(en_refs: list[str]) -> None:
    """Every image referenced in en.md must exist on disk."""
    for ref in en_refs:
        assert (REPO_ROOT / ref).is_file(), f"missing asset for en.md: {ref}"


def test_cs_image_targets_exist(cs_refs: list[str]) -> None:
    """Every image referenced in cs.md must exist on disk."""
    for ref in cs_refs:
        assert (REPO_ROOT / ref).is_file(), f"missing asset for cs.md: {ref}"


def test_en_and_cs_have_the_same_images(en_refs: list[str], cs_refs: list[str]) -> None:
    """Both README source files must reference the same set of images.

    Drift here is what caused the "CZ obrázek zmizel, v EN funguje"
    bug. The fix is to keep the source files in lock-step; the build
    script then copies that consistency to the compiled READMEs.
    """
    missing_in_cs = sorted(set(en_refs) - set(cs_refs))
    missing_in_en = sorted(set(cs_refs) - set(en_refs))
    assert missing_in_cs == [], f"images only in en.md: {missing_in_cs}"
    assert missing_in_en == [], f"images only in cs.md: {missing_in_en}"


@pytest.mark.parametrize(
    ("label", "path"),
    [
        ("kde_tray", "docs/images/kde_tray.png"),
        ("log_viewer", "docs/images/log_viewer.png"),
        ("preview", "docs/images/preview.png"),
        ("tray4hermes_logo", "docs/images/tray4hermes.png"),
    ],
)
def test_named_asset_present(label: str, path: str) -> None:
    """Image catalog: if a README references one of these, it must exist."""
    del label
    assert (REPO_ROOT / path).is_file(), f"missing asset: {path}"


def test_en_and_cs_have_the_same_h1(en_refs: list[str], cs_refs: list[str]) -> None:
    """Both files start with the same tray4hermes H1 line so the version
    badge lands in the same place. Drift here is mostly cosmetic, but
    an H1 mismatch usually means someone hand-edited one and forgot
    the other — better to surface that early.
    """
    en_h1 = EN.read_text(encoding="utf-8").splitlines()[:1]
    cs_h1 = CS.read_text(encoding="utf-8").splitlines()[:1]
    assert en_h1, "en.md is empty"
    assert cs_h1, "cs.md is empty"
    assert en_h1[0].startswith("# tray4hermes")
    assert cs_h1[0].startswith("# tray4hermes")


def test_i18n_image_paths_use_repo_root(en_refs: list[str], cs_refs: list[str]) -> None:
    """Source files live in ``docs/i18n/`` but image paths must be relative
    to the repo root (e.g. ``docs/images/X.png``) so the i18n build
    script can rewrite them per compiled README without losing
    resolution. A path like ``../images/X.png`` would point to a
    file outside the repo once rewritten.
    """
    for ref in en_refs + cs_refs:
        assert not ref.startswith("../"), f"image must be repo-relative: {ref}"
        assert not ref.startswith("./"), f"image must be repo-relative: {ref}"


def test_compiled_readme_uses_rewritten_image_paths() -> None:
    """The compiled READMEs must NOT use the canonical repo-relative
    paths from the source. ``i18n_build.py`` rewrites them per target;
    if the build script ever regresses, the CZ README would point at
    a path that doesn't exist in the docs/ tree.
    """
    for compiled in (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "README.cs.md"):
        text = compiled.read_text(encoding="utf-8")
        for match in _IMAGE_RE.finditer(text):
            ref = match.group(1).strip()
            if ref.startswith(_IGNORED):
                continue
            # ``docs/images/X.png`` only renders correctly from the
            # repo-root ``README.md``; from ``docs/README.cs.md`` the
            # same image has to be ``images/X.png``. Both forms are
            # acceptable, but the literal ``docs/images/X.png`` from
            # the source must not survive in the compiled docs/ output.
            if compiled.name == "README.cs.md":
                assert not ref.startswith("docs/"), (
                    f"unrewritten image path in docs/README.cs.md: {ref}"
                )
