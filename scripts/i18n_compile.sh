#!/usr/bin/env bash
# Compile gettext .po → .mo files for tray4hermes UI translations.
# Idempotent — re-running produces byte-identical .mo when sources
# haven't changed.
#
# Why a wrapper rather than ``find + msgfmt``:
# - We pin the exact command so CI logs are predictable.
# - We support `set -euo pipefail` and fail loudly on a partial
#   compile (which is the worst case: an old .mo lingers for an
#   unbuilt locale).
#
# Use this from `dev.sh`, `i18n_build.py`, and CI; not from runtime.

set -euo pipefail

cd "$(dirname "$0")/.."

# We store .po files next to the package as package data (under
# src/tray4hermes/_locales/), so they ship inside the installed
# wheel. The companion .po sources that translators edit live
# under ``locales/`` at the repo root for ergonomic editing.
# Compile both layouts.
shopt -s nullglob
errors=0

# 1. Package-data translations (ship in the wheel).
for po_file in src/tray4hermes/_locales/*/LC_MESSAGES/*.po; do
    mo_file="${po_file%.po}.mo"
    locale="$(basename "$(dirname "$(dirname "$po_file")")")"
    printf 'compile (package): %-30s -> %s\n' "$locale" "$mo_file"
    msgfmt -o "$mo_file" "$po_file" || errors=$((errors + 1))
done

# 2. Repo-root translations (translator working copies; also
# useful for in-tree runs of the dev script).
if [[ -d locales ]]; then
    for po_file in locales/*/LC_MESSAGES/*.po; do
        mo_file="${po_file%.po}.mo"
        locale="$(basename "$(dirname "$(dirname "$po_file")")")"
        printf 'compile (work copy): %-30s -> %s\n' "$locale" "$mo_file"
        msgfmt -o "$mo_file" "$po_file" || errors=$((errors + 1))
    done
fi
shopt -u nullglob

if (( errors > 0 )); then
    echo
    echo "error: $errors compile failure(s)"
    exit 1
fi
echo
echo "compiled .mo files (run tests/CI for full coverage)"
