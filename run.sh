#!/bin/bash
# tray4hermes launcher with auto-restart on crash.
#
# Exit codes:
#   0 = intentional quit (tray menu "Ukončit") → wrapper exits cleanly
#   2 = already running (single-instance lock) → wrapper exits cleanly
#   anything else = crash → wrapper sleeps 2s and respawns
#
# Uses the installed `tray4hermes` console script. If you haven't
# installed the package yet, see README "Development install" section.

set -u

while true; do
    if command -v tray4hermes >/dev/null 2>&1; then
        tray4hermes
    else
        # Fallback: run as module (works after `uv pip install -e .`)
        python3 -m tray4hermes
    fi
    code=$?
    if [ "$code" -eq 0 ] || [ "$code" -eq 2 ]; then
        exit "$code"
    fi
    sleep 2
done