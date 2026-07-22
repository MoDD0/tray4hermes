"""i18n parity lint for tray4hermes README translations.

The hard problem of cross-language heading parity is intentionally
solved cheaply here: we just count headings (`## X`-on-its-own-line)
in each translation and warn when one is significantly shorter
than the canonical.

Rationale: a half-finished translation tends to lose whole sections,
which shows up as a heading count that is markedly lower than the
canonical. Cheap to detect, no false positives from paraphrasing.

If you ever need true section-by-section parity (e.g. for a
regulated translation workflow), extend `lint_one_headings()` to
match headings across languages using a curated translation
dictionary. We don't need that yet.

Run:
    python scripts/i18n_lint.py

Exit codes:
    0  All translations have parity with canonical (no errors)
    1  At least one parity error found
    2  Misconfiguration (missing canonical, etc.)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Headings: an H2 (`##`) is what defines a logical section in our
# README. We treat H1 and H3+ as out-of-scope for the parity check.
_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)


def heading_count(path: Path) -> int:
    """Return the number of H2 headings in the file at `path`."""
    return len(_HEADING_RE.findall(path.read_text(encoding="utf-8")))


def find_translations(repo_root: Path) -> list[Path]:
    """Return `docs/i18n/*.md` paths. The canonical translation
    (English, `en.md`) is always first; other translations follow
    in alphabetical order.

    Why we sort canonical first: callers assume `translations[0]`
    is canonical and that the rest are secondaries. Using
    alphabetically-sorted would put `cs.md` first (c < e), which
    makes the lint report wrong stats.
    """
    i18n_dir = repo_root / "docs" / "i18n"
    if not i18n_dir.is_dir():
        sys.stderr.write(f"error: {i18n_dir} not found\n")
        sys.exit(2)
    all_md = sorted(p for p in i18n_dir.iterdir() if p.suffix == ".md")
    canonical = next((p for p in all_md if p.stem == "en"), None)
    if canonical is None:
        sys.stderr.write(f"error: canonical English translation en.md not found in {i18n_dir}\n")
        sys.exit(2)
    others = [p for p in all_md if p != canonical]
    return [canonical, *others]  # canonical first, then alphabetical


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="i18n_lint.py",
        description="Check README translation parity (heading-count based).",
    )
    args = parser.parse_args(argv)
    del args

    repo_root = Path(__file__).resolve().parent.parent
    translations = find_translations(repo_root)
    if not translations:
        sys.stderr.write("error: no translations found in docs/i18n/\n")
        return 2

    canonical = translations[0]
    canonical_count = heading_count(canonical)
    sys.stderr.write(f"canonical ({canonical.name}): {canonical_count} ## sections\n")

    errs = 0
    for target in translations[1:]:
        count = heading_count(target)
        rel = repo_root
        rel_target = target.relative_to(rel)
        pct = (count / canonical_count * 100) if canonical_count else 100
        if count < canonical_count * 0.8:
            sys.stderr.write(
                f"error: {rel_target} has {count} ## sections "
                f"({pct:.0f}% of canonical). Half-finished translation?\n"
            )
            errs += 1
        elif count > canonical_count * 1.2:
            sys.stderr.write(
                f"error: {rel_target} has {count} ## sections "
                f"({pct:.0f}% of canonical — ahead of canonical?)\n"
            )
            errs += 1
        else:
            sys.stderr.write(
                f"ok: {rel_target} has {count} ## sections ({pct:.0f}% of canonical)\n"
            )

    if errs:
        sys.stderr.write(f"\n{errs} translation(s) out of parity.\n")
        return 1
    sys.stderr.write("\nall translations within parity tolerance.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
