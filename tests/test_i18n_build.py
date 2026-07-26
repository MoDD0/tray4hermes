"""Tests for scripts/i18n_build.py helpers."""

from __future__ import annotations

import importlib.util
import re
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


# ── Version badge ───────────────────────────────────────────────────────────
# The badge is a markdown image link on a line of its own, matching the
# other shields.io badges under the H1. GitHub renders an inline
# `<img>` appended to the H1 as part of the heading, which is why the
# earlier inline form was dropped.

_PLACEHOLDER = "<!-- tray4hermes:version -->"


def test_rewrite_version_emits_markdown_badge_on_its_own_line(i18n_module) -> None:
    src = f"# tray4hermes\n\n{_PLACEHOLDER}\n[![License: MIT](x)](y)\nbody\n"
    out = i18n_module.rewrite_version_placeholder(src, "9.9.9")
    # The badge links to the repo, not to /releases: there is no release
    # and none is planned (the only tag is the pre-rewrite archive), so
    # a /releases target sends every reader to an empty page.
    assert (
        "[![version: 9.9.9](https://img.shields.io/badge/version-9.9.9-blue.svg)]"
        "(https://github.com/MoDD0/tray4hermes)" in out
    )
    assert "/releases" not in out, "the badge must not point at an empty releases page"
    assert "<img" not in out, "the badge must be markdown, not an inline HTML tag"


def test_rewrite_version_keeps_the_h1_intact(i18n_module) -> None:
    src = f"# tray4hermes\n\n{_PLACEHOLDER}\n"
    out = i18n_module.rewrite_version_placeholder(src, "9.9.9")
    assert out.splitlines()[0] == "# tray4hermes", (
        "the badge must not be welded onto the heading line"
    )


def test_rewrite_version_keeps_the_marker_as_a_do_not_edit_signal(i18n_module) -> None:
    """The marker survives into the compiled file.

    Not because the build reads it back — compiled READMEs are always
    regenerated from `docs/i18n/*.md` — but because someone opening
    `README.md` in the GitHub web editor should see that the line
    below is machine-written. That has already gone wrong once.
    """
    src = f"# tray4hermes\n\n{_PLACEHOLDER}\n"
    out = i18n_module.rewrite_version_placeholder(src, "9.9.9")
    assert _PLACEHOLDER in out


def test_rewrite_version_idempotent(i18n_module) -> None:
    src = f"# tray4hermes\n\n{_PLACEHOLDER}\nbody\n"
    once = i18n_module.rewrite_version_placeholder(src, "1.0.0")
    twice = i18n_module.rewrite_version_placeholder(once, "1.0.0")
    assert once == twice


def test_rewrite_version_refreshes_a_stale_badge(i18n_module) -> None:
    """Re-running with a new version replaces the old badge, not appends."""
    src = f"# tray4hermes\n\n{_PLACEHOLDER}\nbody\n"
    old = i18n_module.rewrite_version_placeholder(src, "1.0.0")
    new = i18n_module.rewrite_version_placeholder(old, "2.0.0")
    assert new.count("img.shields.io/badge/version-") == 1
    assert "1.0.0" not in new
    assert "2.0.0" in new


def test_rewrite_version_requires_the_placeholder(i18n_module) -> None:
    """A source that lost its marker is a misconfiguration, not a no-op.

    Silently emitting a README with no version badge is how the badge
    drifted away from `__version__` unnoticed before.
    """
    with pytest.raises(SystemExit) as excinfo:
        i18n_module.rewrite_version_placeholder("# tray4hermes\n\nbody\n", "1.0.0")
    assert excinfo.value.code == 2


# ── Language banner ─────────────────────────────────────────────────────────


@pytest.fixture()
def locales(i18n_module, tmp_path: Path):
    """Real Locale records, anchored at a throwaway repo root."""
    (tmp_path / "docs" / "i18n").mkdir(parents=True)
    for code in ("en", "cs"):
        (tmp_path / "docs" / "i18n" / f"{code}.md").write_text("x", encoding="utf-8")
    return i18n_module.load_locales(tmp_path)


_MARKER = "<!-- i18n:available-languages:END -->"


def test_banner_labels_are_english_in_the_english_readme(i18n_module, locales) -> None:
    out = i18n_module.rewrite_header_banner(f"{_MARKER}\n", locales, "en")
    assert "**Canonical:** English (this file)" in out
    assert "**Other languages:**" in out


def test_banner_labels_are_czech_in_the_czech_readme(i18n_module, locales) -> None:
    """The CZ banner used to read `**Hlavní jazyk:** Čeština (this file)`
    with `**Other languages:**` underneath — half translated."""
    out = i18n_module.rewrite_header_banner(f"{_MARKER}\n", locales, "cs")
    assert "**Hlavní jazyk:** Čeština (tento soubor)" in out
    assert "**Ostatní jazyky:**" in out
    assert "this file" not in out
    assert "Other languages" not in out


def test_banner_links_to_the_other_locale(i18n_module, locales) -> None:
    en = i18n_module.rewrite_header_banner(f"{_MARKER}\n", locales, "en")
    cs = i18n_module.rewrite_header_banner(f"{_MARKER}\n", locales, "cs")
    assert "[Čeština](docs/README.cs.md)" in en
    assert "[English](../README.md)" in cs


def test_banner_does_not_link_a_readme_to_itself(i18n_module, locales) -> None:
    out = i18n_module.rewrite_header_banner(f"{_MARKER}\n", locales, "en")
    assert "README.md)" not in out.split("**Other languages:**")[1].replace(
        "docs/README.cs.md)", ""
    )


def test_relative_image_paths_repo_root(i18n_module, tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "docs" / "images").mkdir(parents=True)
    (repo / "docs" / "i18n" / "en.md").parent.mkdir(parents=True)
    (repo / "docs" / "i18n" / "en.md").write_text(
        "![](docs/images/preview.png)\n", encoding="utf-8"
    )
    # Simulate README.md at the repo root: from_dir is the repo root,
    # target is docs/images/preview.png — the compiled README should
    # emit the literal repo-relative path.
    target_rel = Path("docs") / "images" / "preview.png"
    from_dir = repo
    out = i18n_module._relative_inside_repo(from_dir, target_rel, repo)
    assert out == "docs/images/preview.png"


def test_relative_image_paths_nested_readme(i18n_module, tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "docs" / "images").mkdir(parents=True)
    target_rel = Path("docs") / "images" / "preview.png"
    # Compiled `docs/README.cs.md` lives in `docs/`, so `from_dir` is
    # `repo/docs`. The compiled README needs `images/preview.png`.
    from_dir = repo / "docs"
    out = i18n_module._relative_inside_repo(from_dir, target_rel, repo)
    assert out == "images/preview.png"


def test_relative_image_paths_climb_out_of_the_target_dir(i18n_module, tmp_path: Path) -> None:
    """An asset above the compiled file's directory needs `..` segments.

    `docs/README.cs.md` referencing a repo-root asset is the case that
    reaches this path. The old fallback claimed to handle it but just
    re-raised, so the build crashed instead of emitting `../logo.png`.
    """
    repo = tmp_path
    out = i18n_module._relative_inside_repo(
        from_dir=repo / "docs", to_file=Path("logo.png"), repo_root=repo
    )
    assert out == "../logo.png"


def test_verify_assets_fails_on_missing(i18n_module, tmp_path: Path) -> None:
    rc = i18n_module.verify_assets(tmp_path)
    assert rc == 1


def test_verify_assets_passes_when_present(i18n_module, tmp_path: Path) -> None:
    (tmp_path / "docs" / "images").mkdir(parents=True)
    for rel, _label in i18n_module._IMAGE_LOCATIONS:
        (tmp_path / rel).write_bytes(b"x")
    assert i18n_module.verify_assets(tmp_path) == 0


def test_compiled_readmes_use_absolute_image_urls() -> None:
    """PyPI renders the README with no access to the repository.

    A relative path like `docs/images/preview.png` resolves against
    pypi.org there and shows as a broken image — which is exactly what
    happened to 2.0.17. GitHub renders absolute raw URLs just as happily
    as relative ones, so absolute is the form that works in both places.
    """
    repo_root = Path(__file__).resolve().parent.parent
    for name in ("README.md", "docs/README.cs.md"):
        text = (repo_root / name).read_text(encoding="utf-8")
        refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
        relative = [r for r in refs if not r.startswith(("http://", "https://", "data:"))]
        assert relative == [], f"{name} has image paths PyPI cannot resolve: {relative}"
