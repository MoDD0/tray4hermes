#!/bin/bash
# Hermes Tray launcher s auto-restartem
# Exit 0 = úmyslné ukončení (Konec z menu) → nechat být
# Exit 2 = už běží (duplicita) → nechat být
# Jiný exit = crash → restartnout

cd "$(dirname "$(readlink -f "$0")")"

while true; do
    /usr/bin/python3 hermes_tray.py
    code=$?
    if [ $code -eq 0 ] || [ $code -eq 2 ]; then
        break
    fi
    # Crash — počkej 2s a restartuj
    sleep 2
done
