#!/usr/bin/env bash
# Dev helper — install editable + run tests in one go.
# Usage: ./scripts/dev.sh [pytest args...]
#
# Requires: uv (https://docs.astral.sh/uv/)

set -euo pipefail

cd "$(dirname "$0")/.."

# Install (idempotent) — uv skips already-installed packages
uv pip install --system -e ".[dev]"

# Run pytest with whatever args were passed (default: all tests, verbose)
exec pytest "${@:--v tests/}"