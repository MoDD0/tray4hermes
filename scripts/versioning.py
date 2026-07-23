#!/usr/bin/env python3
"""Small dependency-free Semantic Versioning helper for tray4hermes."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "src" / "tray4hermes" / "__init__.py"
_VERSION_RE = re.compile(r'^__version__[ \t]*=[ \t]*"(\d+)\.(\d+)\.(\d+)"[ \t]*$', re.MULTILINE)
_COMMIT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]+\))?(?P<breaking>!)?:\s+.+")


def classify_bump(message: str) -> str | None:
    """Map a Conventional Commit message to a SemVer bump level."""
    first_line = message.splitlines()[0] if message else ""
    match = _COMMIT_RE.match(first_line)
    if "BREAKING CHANGE:" in message or (match and match.group("breaking")):
        return "major"
    if not match:
        return None
    commit_type = match.group("type")
    if commit_type == "feat":
        return "minor"
    if commit_type in {"fix", "perf"}:
        return "patch"
    return None


def bump_version(version: str, level: str) -> str:
    """Increment a strict X.Y.Z version."""
    try:
        major, minor, patch = (int(part) for part in version.split("."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid SemVer version: {version!r}") from exc
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"invalid bump level: {level!r}")


def current_version(source: str) -> str:
    match = _VERSION_RE.search(source)
    if not match:
        raise ValueError("__version__ assignment not found")
    return ".".join(match.groups())


def rewrite_version(source: str, version: str) -> str:
    """Replace exactly one package version assignment."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"invalid SemVer version: {version!r}")
    updated, count = _VERSION_RE.subn(f'__version__ = "{version}"', source)
    if count != 1:
        raise ValueError(f"expected one __version__ assignment, found {count}")
    return updated


def required_version_for_commit(base_version: str, current: str, message: str) -> tuple[str, bool]:
    """Return the required version and whether the working tree must be changed."""
    level = classify_bump(message)
    expected = bump_version(base_version, level) if level else base_version
    if current == expected:
        return expected, False
    raise ValueError(
        f"version {current} does not match commit policy; expected {expected} "
        f"from base {base_version}"
    )


def _git(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def prepare_commit(message_file: Path) -> int:
    """Commit hook: infer the bump from the message and enforce/apply it."""
    message = message_file.read_text(encoding="utf-8")
    try:
        base_source = _git("show", "HEAD:src/tray4hermes/__init__.py")
        base = current_version(base_source)
        source = VERSION_FILE.read_text(encoding="utf-8")
        current = current_version(source)
        expected, needs_write = required_version_for_commit(base, current, message)
        if needs_write:
            raise ValueError("automatic version write unexpectedly required")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"versioning error: {exc}", file=sys.stderr)
        return 1
    return 0


def bump_file(level: str, *, path: Path = VERSION_FILE) -> tuple[str, str]:
    source = path.read_text(encoding="utf-8")
    old = current_version(source)
    new = bump_version(old, level)
    path.write_text(rewrite_version(source, new), encoding="utf-8")
    return old, new


def main() -> int:
    parser = argparse.ArgumentParser(description="Bump tray4hermes Semantic Version")
    parser.add_argument("level", choices=("patch", "minor", "major"), nargs="?")
    parser.add_argument("--prepare-commit-msg", type=Path, metavar="FILE")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.prepare_commit_msg:
        return prepare_commit(args.prepare_commit_msg)
    if args.level is None:
        parser.error("a bump level is required unless --prepare-commit-msg is used")

    source = VERSION_FILE.read_text(encoding="utf-8")
    old = current_version(source)
    new = bump_version(old, args.level)
    if not args.dry_run:
        VERSION_FILE.write_text(rewrite_version(source, new), encoding="utf-8")
    print(f"{old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
