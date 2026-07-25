#!/usr/bin/env python3
"""i18n build script for tray4hermes README.

This script does several things:

1. **Generates the canonical English `README.md`** from
   `docs/i18n/en.md`, expanding the
   `<!-- i18n:available-languages:START --> … END -->` region
   with a list of currently available translations.
2. **Emits the Czech `docs/README.cs.md`** so people who land
   on the GitHub root or browse `docs/` see a direct link to the
   Czech translation.
3. **Rewrites image references** so each compiled README points at
   the shared `docs/images/` directory using a path relative to the
   compiled file's location.
4. **Verifies that every image the source READMEs reference is
   present on disk** — exit non-zero if any are missing, so a
   missing PNG is caught by `pytest` rather than by a confused
   GitHub reader.
5. **Substitutes the live package version** as a shields.io badge on
   the line below the `<!-- tray4hermes:version -->` marker, next to
   the hand-written License / Python / ruff badges. The version comes
   from `src/tray4hermes/__init__.py::__version__`, so the README
   always shows the version it was built from.
6. **Renders the visible language banner** under the auto-managed
   comment block, with every label in the target locale's own
   language.

Run from the repo root:
    python scripts/i18n_build.py

Verify only (no writes), to use in CI / pre-commit:
    python scripts/i18n_build.py --check

Exit codes:
    0  README(s) up-to-date (or written successfully)
    1  Stale (used by `--check`) — running the script would change a file
    2  Misconfiguration — unknown language metadata, missing files, etc.
    3  Missing image asset (caught before any writes)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Locales we ship today ──────────────────────────────────────────────────
# Order matters: the canonical (reference) language goes first so the EN
# README is the default in the GitHub picker.
_LOCALES: list[tuple[str, str, str]] = [
    # (locale_code, native_name, github_label)
    # The first entry is the canonical language — its source file is
    # `docs/i18n/en.md` and its compiled output is the root README.md.
    ("en", "English", "English"),
    ("cs", "Čeština", "Čeština"),
]

# Aliases — keep one source path per locale even if `en.md` is the
# "English" GitHub tab.
_LOCALE_FILES: dict[str, str] = {
    "en": "docs/i18n/en.md",
    "cs": "docs/i18n/cs.md",
}

# README paths emitted from each source file.
_README_TARGETS: dict[str, str] = {
    "en": "README.md",
    "cs": "docs/README.cs.md",
}

# Asset catalog: every image the README references. The first member is the
# repo-relative path; the second is a human label used in error messages.
# Adding a new image means dropping it in `docs/images/` and adding a
# tuple here — the i18n lint then fails if anyone deletes the file by
# accident.
_IMAGE_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("docs/images/preview.png", "KDE Plasma tray screenshot"),
    ("docs/images/tray4hermes.png", "package logo"),
)


@dataclass(frozen=True)
class Locale:
    code: str
    name: str
    github_label: str
    source: Path
    target: Path


def _link_from_to(from_locale: Locale, target: Locale) -> str:
    """Compute the relative repo-rooted link that goes from
    `from_locale`'s compiled file to `target`'s compiled file.
    Returns the bare path with no leading `./` or `/`.
    """
    repo_root = Path(__file__).resolve().parent.parent
    # Build relative-to-repo paths manually — `.resolve()` on a
    # non-existent target file may pick up cwd rather than repo_root,
    # which makes `.relative_to(repo_root)` blow up. Going through
    # strings is the simplest way around it.
    src_str = str(from_locale.target).removeprefix(str(repo_root) + "/")
    tgt_str = str(target.target).removeprefix(str(repo_root) + "/")
    src_dir = Path(src_str).parent
    tgt_dir = Path(tgt_str).parent
    src_parts = src_dir.parts
    tgt_parts = tgt_dir.parts
    common = 0
    while (
        common < len(src_parts)
        and common < len(tgt_parts)
        and src_parts[common] == tgt_parts[common]
    ):
        common += 1
    ups = [".." for _ in src_parts[common:]]
    downs = list(tgt_parts[common:])
    rel = ups + downs + [Path(tgt_str).name]
    return "/".join(rel).lstrip("/")


def load_locales(repo_root: Path) -> list[Locale]:
    """Resolve Locale records; bail (exit 2) if a source file is missing."""
    locales = []
    for code, name, label in _LOCALES:
        src_rel = _LOCALE_FILES.get(code)
        if src_rel is None:
            die(f"missing source-file mapping for locale '{code}'", code=2)
        src = (repo_root / src_rel).resolve()
        if not src.is_file():
            die(f"source file not found: {src}", code=2)
        tgt_rel = _README_TARGETS.get(code)
        if tgt_rel is None:
            die(f"missing target-file mapping for locale '{code}'", code=2)
        # Targets may not exist yet (we're generating them on first
        # run). Don't `.resolve()` — instead keep them as a PosixPath
        # anchored at repo_root so the relative-from-repo computation
        # stays consistent regardless of cwd.
        tgt = repo_root / tgt_rel
        locales.append(
            Locale(
                code=code,
                name=name,
                github_label=label,
                source=src,
                target=tgt,
            )
        )
    return locales


_LANGS_RE = re.compile(
    r"<!-- i18n:available-languages:START -->.*?<!-- i18n:available-languages:END -->",
    re.DOTALL,
)


def render_languages_banner(locales: list[Locale]) -> str:
    """Render the auto-managed language banner block.

    Layout goal: a single paragraph that lists the languages with
    links to each compiled README, so a reader can jump to their
    native-language documentation in one click.
    """
    parts = [
        "<!-- i18n:available-languages:START -->",
        "<!-- DO NOT EDIT — auto-generated by scripts/i18n_build.py from the files in docs/i18n/. -->",  # noqa: E501
        f"<!-- Available languages: {', '.join(f'{loc.code} → {loc.name}' for loc in locales)} -->",
        "<!-- i18n:available-languages:END -->",
    ]
    return "\n".join(parts)


def expand_languages(md: str, locales: list[Locale]) -> str:
    """Replace the auto-managed comment block with a real banner.

    The block is identified by `<!-- i18n:available-languages:START -->`.
    Falls back to a warning marker if the comment markers are missing —
    that means the author copied an out-of-date README and forgot to
    re-run the build script.
    """
    if not _LANGS_RE.search(md):
        die(
            "i18n marker not found in source. Add the comment block:\n"
            "  <!-- i18n:available-languages:START -->\n"
            "  <!-- DO NOT EDIT — auto-generated by scripts/i18n_build.py ... -->\n"
            "  <!-- i18n:available-languages:END -->",
            code=2,
        )
    return _LANGS_RE.sub(render_languages_banner(locales), md)


# Visible language banner, rendered under the auto-managed comment
# block. Every label is per-locale: a Czech README with an English
# "Other languages:" heading reads as a bug, because it is one.
#
# Adding a locale means adding a row here. A missing row is a hard
# error — falling back to English would ship the very mixed-language
# banner this table exists to prevent.
_BANNER_LABELS: dict[str, tuple[str, str, str]] = {
    # locale: (canonical label, other-languages label, self marker)
    "en": ("Canonical:", "Other languages:", "(this file)"),
    "cs": ("Hlavní jazyk:", "Ostatní jazyky:", "(tento soubor)"),
}

_BANNER_ANCHOR = "<!-- i18n:available-languages:END -->"


def rewrite_header_banner(md: str, locales: list[Locale], current_code: str) -> str:
    """Insert the visible language banner under the i18n comment block.

    The comment block is invisible on GitHub; this paragraph is what a
    reader actually sees and clicks. It names the language of the file
    they're on and links to every other translation — never to itself.
    """
    labels = _BANNER_LABELS.get(current_code)
    if labels is None:
        die(
            f"no banner labels for locale '{current_code}'. "
            f"Add a row to _BANNER_LABELS in {Path(__file__).name}.",
            code=2,
        )
    canonical_label, others_label, self_marker = labels

    current = next(loc for loc in locales if loc.code == current_code)
    others = [loc for loc in locales if loc.code != current_code]
    other_links = " · ".join(
        f"[{loc.github_label}]({_link_from_to(current, loc)})" for loc in others
    )

    banner = (
        f"> **{canonical_label}** {current.github_label} {self_marker}\n"
        f">\n"
        f"> **{others_label}** {other_links}"
    )

    if _BANNER_ANCHOR not in md:
        die(
            f"i18n marker not found — cannot place the language banner. "
            f"Expected a line containing: {_BANNER_ANCHOR}",
            code=2,
        )
    return md.replace(_BANNER_ANCHOR, _BANNER_ANCHOR + "\n\n" + banner, 1)


# Image-rewrite machinery. We want every compiled README to point at
# the shared `docs/images/` directory using a path relative to the
# compiled file's location. Authors write `![alt](images/X.png)` in
# `docs/i18n/en.md`; the EN README at the repo root should resolve to
# `docs/images/X.png`, the CS README at `docs/README.cs.md` should
# resolve to `images/X.png`.
_IMAGE_REF_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")


def _rewrite_image_paths(md: str, target: Path, source: Path, repo_root: Path) -> str:
    """Rewrite `![](X)` references so the compiled file finds the asset.

    Authors write paths relative to the **repo root** inside
    `docs/i18n/*.md` (e.g. `docs/images/kde_tray.png`). We resolve them
    against the repo root, then compute the relative path from the
    target file's location. Absolute URLs and data URIs pass through.
    """
    target_dir = target.parent

    def _rewrite(match: re.Match[str]) -> str:
        prefix, ref, suffix = match.group(1), match.group(2), match.group(3)
        if ref.startswith(("http://", "https://", "data:", "/")):
            return match.group(0)
        if not ref:
            return match.group(0)
        candidate = (repo_root / ref).resolve()
        try:
            rel_to_repo = candidate.relative_to(repo_root)
        except ValueError:
            return match.group(0)
        rel_to_target = _relative_inside_repo(
            from_dir=target_dir, to_file=rel_to_repo, repo_root=repo_root
        )
        return f"{prefix}{rel_to_target}{suffix}"

    return _IMAGE_REF_RE.sub(_rewrite, md)


def _relative_inside_repo(from_dir: Path, to_file: Path, repo_root: Path) -> str:
    """Compute a posix-style path from `from_dir` to `to_file`, both inside
    the repo. `to_file` must be repo-relative (no leading slash).

    `from_dir` is the directory containing the compiled file (e.g. ``/``
    for the root ``README.md`` or ``docs/`` for ``docs/README.cs.md``).
    `to_file` is the absolute path of the asset within the repo.
    The result is the path the compiled file should use, expressed as
    a posix string.
    """
    target_abs = repo_root / to_file
    try:
        return Path(target_abs).relative_to(from_dir).as_posix()
    except ValueError:
        # Asset sits above `from_dir` (e.g. a repo-root logo referenced
        # from `docs/README.cs.md`). `relative_to` can't express that;
        # `os.path.relpath` climbs out with `..` segments.
        return Path(os.path.relpath(target_abs, from_dir)).as_posix()


_VERSION_RE = re.compile(r"^__version__\s*=\s*\"(\d+\.\d+\.\d+)\"\s*$", re.MULTILINE)


def _current_version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "src" / "tray4hermes" / "__init__.py"
    source = version_file.read_text(encoding="utf-8")
    match = _VERSION_RE.search(source)
    if not match:
        die(
            f"could not find __version__ assignment in {version_file}",
            code=2,
        )
    return match.group(1)


# Version badge. The source marks the spot with a standalone
# `<!-- tray4hermes:version -->` line; the compiled file keeps that
# marker and puts a shields.io badge underneath, styled like the
# hand-written License / Python / ruff badges next to it.
#
# The marker survives into the output as a DO-NOT-EDIT signal, the same
# way the languages block does. Nothing in the build reads it back —
# compiled READMEs are always regenerated from `docs/i18n/*.md`, never
# from themselves. Matching an already-present badge line is what makes
# the substitution safe to apply to its own output.
_VERSION_PLACEHOLDER = "<!-- tray4hermes:version -->"
_VERSION_BLOCK_RE = re.compile(
    r"^<!--\s*tray4hermes:version[^<>]*?-->[ \t]*\n"
    r"(?:\[!\[version:[^\n]*\n)?",
    re.MULTILINE,
)
# The badge links back to the repository. It used to point at
# ``/releases``, which is an empty page — no release has ever been
# cut and none is planned; the only tag is the pre-rewrite archive.
_BADGE_URL = "https://github.com/MoDD0/tray4hermes"


def rewrite_version_placeholder(md: str, version: str) -> str:
    """Substitute the live package version into the README.

    Emits a markdown badge on a line of its own. An inline `<img>`
    appended to the H1 — the shape this used to have — is swallowed by
    GitHub's heading renderer and comes out misformatted, so the badge
    has to be a sibling of the other badges, not part of the title.
    """
    if not _VERSION_BLOCK_RE.search(md):
        die(
            f"version marker not found in source. Add a line containing:\n  {_VERSION_PLACEHOLDER}",
            code=2,
        )
    badge = (
        f"[![version: {version}]"
        f"(https://img.shields.io/badge/version-{version}-blue.svg)]"
        f"({_BADGE_URL})"
    )
    return _VERSION_BLOCK_RE.sub(f"{_VERSION_PLACEHOLDER}\n{badge}\n", md, count=1)


def verify_assets(repo_root: Path) -> int:
    """Fail if any image the README references is missing on disk."""
    missing = [(rel, label) for rel, label in _IMAGE_LOCATIONS if not (repo_root / rel).is_file()]
    for rel, label in missing:
        sys.stderr.write(f"missing README asset: {rel} ({label})\n")
    return 1 if missing else 0


def build_one(
    loc: Locale, locales: list[Locale], check_only: bool, repo_root: Path, version: str
) -> bool:
    """Compile one locale's source into its target README. Returns False if
    `--check` is in effect and the file would change.
    """
    src = loc.source.read_text(encoding="utf-8")
    src = expand_languages(src, locales)
    src = rewrite_header_banner(src, locales, loc.code)
    src = rewrite_version_placeholder(src, version)
    src = _rewrite_image_paths(src, loc.target, loc.source, repo_root)
    target = loc.target

    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if src == current:
        return True

    if check_only:
        sys.stderr.write(f"stale: {target.relative_to(repo_root)}\n")
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(src, encoding="utf-8")
    sys.stderr.write(f"wrote: {target.relative_to(repo_root)}\n")
    return True


def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="i18n_build.py",
        description=(
            "Compile docs/i18n/*.md into the canonical README.md (and the locale-specific ones)."
        ),  # noqa: E501
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write files; exit 1 if anything would change.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    locales = load_locales(repo_root)
    rc = verify_assets(repo_root)
    if rc:
        return rc
    version = _current_version()
    sys.stderr.write(f"tray4hermes version: {version}\n")

    ok = True
    for loc in locales:
        ok = build_one(loc, locales, args.check, repo_root, version) and ok
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
