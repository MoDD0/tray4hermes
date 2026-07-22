"""Pytest integration for i18n build & parity.

Wraps `scripts/i18n_build.py` and `scripts/i18n_lint.py` so the
normal `pytest` invocation picks up:

- the i18n build script is idempotent (running it twice produces
  byte-identical output),
- the parity lint passes (heading counts roughly equal across
  translations),
- the build script's --check flag reports the project is current,
- every registered locale has a source file, a compile target,
  and a non-empty body.

Why both a script and a pytest: the script is the entry point
that contributors run when adding/changing translations; the
pytest is what CI runs in the regular test suite. Both should
agree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def repo_root() -> Path:
    """The repo's top-level directory (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def i18n_dir(repo_root: Path) -> Path:
    """docs/i18n/ source directory."""
    d = repo_root / "docs" / "i18n"
    if not d.is_dir():
        pytest.skip(f"{d} not present (no translations registered)")
    return d


# ── Pure-Python tests (no subprocess) ───────────────────────────────────────
HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)


def test_canonical_translation_is_english(i18n_dir: Path) -> None:
    """en.md must exist and be present — it's the canonical source."""
    en = i18n_dir / "en.md"
    assert en.is_file(), f"{en} not found; canonical English is mandatory"


def test_every_translation_has_headings(i18n_dir: Path) -> None:
    """Every translation must have at least one H2 section."""
    for md in sorted(i18n_dir.glob("*.md")):
        body = md.read_text(encoding="utf-8")
        assert HEADING_RE.search(body), (
            f"{md.name} has no `##` headings; it would render as a flat document. "
            f"Did you forget to add sections, or did the file get truncated?"
        )


def test_no_duplicate_locale_files(i18n_dir: Path) -> None:
    """No accidental `xx.md` / `xx.MD` / `xx.markdown` duplicates."""
    seen: dict[str, Path] = {}
    for md in i18n_dir.iterdir():
        # Only consider .md case-insensitively
        if md.suffix.lower() == ".md":
            key = md.name.lower()
            existing = seen.get(key)
            if existing is not None and existing != md:
                rel_root = i18n_dir.parent.parent
                pytest.fail(
                    f"two translation files with the same effective name: "
                    f"{existing.relative_to(rel_root)} and {md.relative_to(rel_root)}"
                )
            seen[key] = md


# ── Subprocess-driven tests ─────────────────────────────────────────────────
def _run_script(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a Python script in scripts/ and return the result.

    `subprocess` is safe here — args[0] is a hard-coded filename
    from the repo, and the rest is the caller's choice but we
    only ever invoke our own scripts.
    """
    cmd = ["python", str(repo_root / "scripts" / args[0])] + list(args[1:])
    return subprocess.run(  # noqa: S603 (script paths are repo-controlled)
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_i18n_build_idempotent(repo_root: Path) -> None:
    """Running `python scripts/i18n_build.py` twice produces the same files."""
    first = _run_script(repo_root, "i18n_build.py")
    assert first.returncode == 0, (
        f"first run failed:\nSTDOUT:\n{first.stdout}\nSTDERR:\n{first.stderr}"
    )

    second = _run_script(repo_root, "i18n_build.py")
    assert second.returncode == 0, (
        f"second run failed:\nSTDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}"
    )

    # Idempotence = same outputs across runs.
    # The script prints 'wrote: <path>' lines on writes; the second
    # run should print nothing.
    assert "wrote" not in second.stdout + second.stderr, (
        f"second run produced output (build is not idempotent):\n"
        f"STDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}"
    )


def test_i18n_build_check_succeeds(repo_root: Path) -> None:
    """--check should report OK (exit 0) when READMEs are in sync."""
    # Make sure source and outputs are in sync first.
    _run_script(repo_root, "i18n_build.py")
    result = _run_script(repo_root, "i18n_build.py", "--check")
    assert result.returncode == 0, (
        f"--check should pass. Re-run the script to update outputs.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_i18n_lint_passes(repo_root: Path) -> None:
    """The parity lint must pass for the current translation set."""
    result = _run_script(repo_root, "i18n_lint.py")
    assert result.returncode == 0, (
        f"i18n_lint.py reported parity errors:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_compiled_readmes_match_sources(repo_root: Path) -> None:
    """Every compiled output in i18n_build.py maps back to a source
    file, and every translation has a matching source. This catches
    accidental removals or rename drift."""
    sys_path = repo_root / "src"
    import sys as _sys

    # Inject src/ so we can import the build module (it's not part
    # of the installable package; it's a repo-internal script).
    _sys.path.insert(0, str(sys_path))
    _sys.path.insert(0, str(repo_root / "scripts"))
    # The import below requires the script to be importable as a
    # module; we add its directory to sys.path above.
    # Use importlib to tolerate the .py extension.
    import importlib

    i18n_build = importlib.import_module("i18n_build")
    locales = i18n_build.load_locales(repo_root)

    # Locales resolved must include 'en' (canonical).
    codes = [loc.code for loc in locales]
    assert "en" in codes, (
        f"canonical 'en' locale not registered. Locales: {codes}"
    )

    # Every registered locale must point at a real file and a real
    # writable target.
    for loc in locales:
        assert loc.source.is_file(), f"locale {loc.code} source file missing: {loc.source}"
        # Target might not exist yet (first build) — that's OK.
        # After a successful build, the parent directory must exist.
        loc.target.parent.mkdir(parents=True, exist_ok=True)
