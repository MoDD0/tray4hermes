# tray4hermes

Systémová lišta (KDE/Plasma tray) pro **Hermes Gateway** – nativní
součást [Hermes Agent](https://hermes-agent.nousresearch.com/) od Nous
Research.

Tray je **pasivní observer a tenký controller** – nesahá na žádný
soubor v `~/.hermes/`. Čte stav, logy a profily; ovládá jen
`systemctl --user`; jediné místo, kam zapisuje, je
`~/.config/tray4hermes/state.json`.

## Co umí

- Zobrazuje stav `hermes-gateway.service` v systémové liště (ikona podle stavu)
- Start / Stop / Restart brány
- Přepnutí aktivního profilu z menu (přes `hermes profile use`)
- Log viewer s auto-refresh (tail `~/.hermes/logs/gateway.log`)
- Otevření `~/.hermes/config.yaml` v externím editoru
- Otevření Hermes CLI v novém terminálu

## Architektura

```
┌──────────────────────────────────────────────────────┐
│  Hermes Agent (~/dev/hermes-agent/, Nous Research)   │
│  • hermes-gateway.service  (systemd --user)          │
│  • Hermes Desktop          (Electron consumer)       │
│  • CLI / TUI                                          │
└──────────────────────┬───────────────────────────────┘
                       │ sdílí
                       ▼
              ~/.hermes/    ←  jediný zdroj pravdy
              ├── config.yaml
              ├── auth.json
              ├── gateway_state.json
              ├── logs/gateway.log
              └── profiles/<name>/
                       ▲
                       │ čte (read-only)
┌──────────────────────┴───────────────────────────────┐
│  tray4hermes  (~/dev/tray4hermes/)                   │
│  • systray ikona  • Start/Stop/Restart               │
│  • profily  • log viewer                             │
└──────────────────────────────────────────────────────┘
```

## Požadavky

- Linux s KDE/Plasma (testováno na Manjaro)
- Python 3.11+
- PyQt5 (`pip install --user PyQt5`)
- Běžící `hermes-gateway.service` pod `systemd --user`
- `loginctl enable-linger $USER` (autostart po odhlášení)

## Instalace

```bash
git clone <url> ~/dev/tray4hermes
cd ~/dev/tray4hermes
pip install --user PyQt5

# Autostart po startu KDE
cp hermes-tray.desktop ~/.config/autostart/

# Spustit ručně (s watchdogem)
./run.sh
```

## Stavová logika

Tray kombinuje dva zdroje stavu:

| Zdroj | Co říká |
|-------|---------|
| `~/.hermes/gateway_state.json` (primární) | Autoritativní – píše ho samotný gateway. Pokud je starší než 30 s, ignorujeme. |
| `systemctl --user is-active hermes-gateway.service` (fallback) | Když `gateway_state.json` chybí nebo je zastaralý. |

Výsledné stavy:

| Kód | Ikona | Význam |
|-----|-------|--------|
| `active` | 🟢 zelená | Gateway běží a je připojená k platformám |
| `warming` | 🟠 oranžová | Gateway běží, ale ještě nepřipojena (typicky OAuth credential warm-up) |
| `activating` | 🔵 modrá | systemd startuje službu |
| `inactive` | ⚫ šedá | Gateway zastavena |
| `failed` | 🔴 červená | systemd služba selhala |
| `unknown` | ⚫ šedá | Nelze přečíst stav |

## Přepnutí profilu

Tray menu → `Profil` → vyber profil. Akce provede:

1. Zapíše `selected_profile` do `~/.config/tray4hermes/state.json`
2. Potvrdí s tebou dialogem
3. Spustí `hermes profile use <name>` (built-in agent příkaz)
4. Restartuje `hermes-gateway.service`

Aktuální Discord session se může krátce odpojit (WebSocket reconnect).

## Konfigurace tray

`~/.config/tray4hermes/state.json` (vytvoří se automaticky):

```json
{
  "version": 1,
  "selected_profile": ""
}
```

`selected_profile` se **použije při Start/Restart z tray**. Když je
prázdné, tray startuje s `hermes profile use default`.

## Verze

Viz `__version__` v `hermes_tray.py`. Zobrazuje se v menu „O tray4hermes".