"""The compiled READMEs must already be current in the working tree.

`scripts/i18n_build.py --check` is the gate: exit 0 means every compiled
README matches what its source under `docs/i18n/` would produce right
now. That verdict only means something if nothing regenerates the files
first — a test that builds and *then* checks passes even when the
committed README is stale, which is precisely the failure the check
exists to catch. So nothing here runs a writing build against the real
repo.

The last test perturbs a throwaway copy to prove the gate can actually
fail; without it the other three would still pass if `--check` were
hard-wired to return 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPILED = ("README.md", "docs/README.cs.md")


def _check(repo_root: Path) -> subprocess.CompletedProcess:
    """Run `i18n_build.py --check` inside `repo_root`. Never writes."""
    return subprocess.run(  # noqa: S603 (script path is repo-controlled)
        [sys.executable, str(repo_root / "scripts" / "i18n_build.py"), "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _fingerprints(repo_root: Path) -> dict[str, tuple[str, int]]:
    out = {}
    for rel in COMPILED:
        path = repo_root / rel
        out[rel] = (path.read_text(encoding="utf-8"), path.stat().st_mtime_ns)
    return out


def test_check_passes_without_a_prior_build() -> None:
    """The committed READMEs are already what the sources compile to."""
    result = _check(REPO_ROOT)
    assert result.returncode == 0, (
        "compiled READMEs are stale — a source in docs/i18n/ changed "
        "without re-running the build. Fix with:\n"
        "    python scripts/i18n_build.py\n"
        "and commit the regenerated files alongside the source.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_check_leaves_the_working_tree_untouched() -> None:
    """`--check` reports; it must not repair. A checking run that quietly
    rewrote the files would make the gate unfalsifiable and would dirty
    the working tree on every `pytest`.
    """
    before = _fingerprints(REPO_ROOT)
    _check(REPO_ROOT)
    assert _fingerprints(REPO_ROOT) == before, (
        "`--check` modified a compiled README; it is supposed to be read-only"
    )


def test_no_locale_is_stale(i18n_build: ModuleType) -> None:
    """Same verdict as the CLI, but in-process so the failure names the
    locale instead of only handing back an exit code.
    """
    locales = i18n_build.load_locales(REPO_ROOT)
    version = i18n_build._current_version()
    stale = [
        loc.code
        for loc in locales
        if not i18n_build.build_one(loc, locales, True, REPO_ROOT, version)
    ]
    assert stale == [], f"stale compiled README(s) for locale(s): {stale}"


@pytest.mark.parametrize("source", ["docs/i18n/en.md", "docs/i18n/cs.md"])
def test_check_reports_stale_when_a_source_changes(repo_copy: Path, source: str) -> None:
    """Editing a source without rebuilding must fail the check — for every
    locale, not just the canonical one.
    """
    edited = repo_copy / source
    edited.write_text(
        edited.read_text(encoding="utf-8") + "\n## Section added without a rebuild\n",
        encoding="utf-8",
    )

    result = _check(repo_copy)
    assert result.returncode == 1, (
        f"--check accepted a {source} edit that was never compiled.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "stale" in result.stderr, (
        f"--check failed without naming the stale file:\nSTDERR:\n{result.stderr}"
    )
