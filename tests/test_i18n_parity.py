"""Pytest integration for i18n build & parity.

Wraps `scripts/i18n_build.py` and `scripts/i18n_lint.py` so the
normal `pytest` invocation picks up:

- the i18n build script is idempotent (running it twice produces
  byte-identical output),
- the parity lint passes (heading counts roughly equal across
  translations),
- every registered locale has a source file, a compile target,
  and a non-empty body.

Why both a script and a pytest: the script is the entry point
that contributors run when adding/changing translations; the
pytest is what CI runs in the regular test suite. Both should
agree.

Whether the *committed* READMEs are current is a separate question,
and it lives in ``test_readme_freshness.py`` — it has to be asked
before anything here runs a build. Builds in this file therefore
happen in a throwaway copy of the repo (the ``repo_copy`` fixture),
never in the working tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

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
    only ever invoke our own scripts. `sys.executable` keeps the
    run inside the same interpreter pytest is using rather than
    whatever `python` happens to be first on PATH.
    """
    cmd = [sys.executable, str(repo_root / "scripts" / args[0])] + list(args[1:])
    return subprocess.run(  # noqa: S603 (script paths are repo-controlled)
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_i18n_build_idempotent(repo_copy: Path, i18n_build: ModuleType) -> None:
    """Running `python scripts/i18n_build.py` twice produces the same files.

    Runs in a copy: this is the one test here that legitimately needs a
    *writing* build, and the working tree is not the place for it.

    Idempotence is asserted on the file contents, not on the absence of
    a "wrote:" line in stderr — a build that rewrote a file with the
    same bytes would be quiet in the log and still idempotent, while one
    that silently changed a byte without logging would slip past a
    log-only check.
    """
    targets = [repo_copy / rel for rel in i18n_build._README_TARGETS.values()]

    first = _run_script(repo_copy, "i18n_build.py")
    assert first.returncode == 0, (
        f"first run failed:\nSTDOUT:\n{first.stdout}\nSTDERR:\n{first.stderr}"
    )
    after_first = {t.name: t.read_text(encoding="utf-8") for t in targets}

    second = _run_script(repo_copy, "i18n_build.py")
    assert second.returncode == 0, (
        f"second run failed:\nSTDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}"
    )
    after_second = {t.name: t.read_text(encoding="utf-8") for t in targets}

    changed = sorted(name for name in after_first if after_first[name] != after_second[name])
    assert changed == [], f"build is not idempotent; rebuilt output differs for: {changed}"

    # A settled build also has nothing left to write, so the second run
    # should stay silent. Weaker than the content check above, but it is
    # what `--check` keys off, so a regression here matters too.
    assert "wrote" not in second.stdout + second.stderr, (
        f"second run rewrote a file it did not need to:\n"
        f"STDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}"
    )


def test_i18n_lint_passes(repo_root: Path) -> None:
    """The parity lint must pass for the current translation set."""
    result = _run_script(repo_root, "i18n_lint.py")
    assert result.returncode == 0, (
        f"i18n_lint.py reported parity errors:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_compiled_readmes_match_sources(repo_root: Path, i18n_build: ModuleType) -> None:
    """Every compiled output in i18n_build.py maps back to a source
    file, and every translation has a matching source. This catches
    accidental removals or rename drift."""
    locales = i18n_build.load_locales(repo_root)

    # Locales resolved must include 'en' (canonical).
    codes = [loc.code for loc in locales]
    assert "en" in codes, f"canonical 'en' locale not registered. Locales: {codes}"

    for loc in locales:
        assert loc.source.is_file(), f"locale {loc.code} source file missing: {loc.source}"
        # The target itself is generated, so it may legitimately be
        # absent before the first build — but the directory it lands in
        # has to be part of the repo already. Creating it here instead
        # of asserting would hide a typo in _README_TARGETS behind a
        # stray directory in the working tree.
        assert loc.target.parent.is_dir(), (
            f"locale {loc.code} targets {loc.target}, whose directory does not exist"
        )
        assert loc.source.read_text(encoding="utf-8").strip(), (
            f"locale {loc.code} source {loc.source.name} is empty"
        )
