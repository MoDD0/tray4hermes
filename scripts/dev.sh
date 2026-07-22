#!/usr/bin/env bash
# Dev helper — install editable + run tests in one go.
# Usage: ./scripts/dev.sh [pytest args...]
#
# Requires: uv (https://docs.astral.sh/uv/)

set -euo pipefail

cd "$(dirname "$0")/.."

# Install (idempotent) — uv skips already-installed packages
uv pip install --system -e ".[dev]"

# Rebuild translated READMEs from docs/i18n/*.md sources. This keeps
# README.md and docs/README.<lang>.md in sync with their i18n/ source
# files. The build is idempotent — re-runs are no-ops unless source
# changed. Cheap; safe to run before tests.
python scripts/i18n_build.py

# Parity check: every translation must have ~the same ## heading
# count as the canonical English file. Catches "I added a section
# to en.md but forgot to translate it".
python scripts/i18n_lint.py

# Run pytest with whatever args were passed (default: all tests, verbose)
exec pytest "${@:--v tests/}"