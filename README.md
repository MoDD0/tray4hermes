# tray4hermes

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**A passivní KDE/Plasma system-tray monitor pro Hermes Gateway** — messaging
bridge from [Hermes Agent](https://github.com/NousResearch/hermes-agent)
by Nous Research.

> tray4hermes is **read-only with respect to Hermes Agent**. Controls the
> gateway via `systemctl --user`, persists one small JSON file of its
> own, reads everything else. Does not store tokens, does not configure
> providers, does not edit `~/.hermes/config.yaml`. All of that lives
> in Hermes Agent itself.

---

## Proč to vzniklo (a proč bys to mohl chtít taky)

Hermes Agent je šikovný kus softwaru, ale jeho `hermes-gateway` běží
jako **`systemd --user` service** — což znamená, že se ti defaultně
spustí při loginu a zůstane běžet na pozadí, i když ho zrovna nepotřebuješ.
Trochu jako Slack, Discord, nebo Telegram na Windows — ty běží taky
furt, ale mají **iconku v systray**, aby ses mohl rozhodnout, jestli
je chceš mít aktivní, nebo je na chvíli umrtvit.

Hermes tohle (zatím) nemá. Přišlo mi to škoda, a tak vznikl
**tray4hermes** — malý Python tray, který:

- **ukazuje stav gateway** přímo v KDE liště (zelená/oranžová/červená),
- **umožňuje Start / Stop / Restart** bez nutnosti otevírat terminál,
- **přepíná profily** (`default`, `work`, `off`…) z menu,
- **zobrazuje logy** v docela vyladěném vieweru (barevné levely,
  filtry, hledání, traceback-aware, time-window),
- a hlavně — **nesnaží se být chytřejší než samotný Hermes**. Jen
  pozoruje, občas klikne, a mluví přes standardní `systemctl`.

Pokud ti tedy vyhovuje filozofie "Hermes běží jen když chci, a já vidím
co se děje" — tohle je pro tebe.

> ⚠️ **Disclaimer:** tray4hermes is a *passive convenience addon*, not an
> official Hermes Agent component. Hermes Agent can run perfectly well
> without it. Use it if you like it; ignore it if you don't.

---

## Features

- 📊 **Live status icon** v system trayi (🟢 active, 🟠 warming,
   🔵 activating, ⚫ inactive, 🔴 failed, ⚪ unknown)
- ▶️ **Start / Stop / Restart** of `hermes-gateway.service` z jednoho kliku
- 🔄 **Profile switcher** submenu, driven by `~/.hermes/profiles/`
- 📋 **Log viewer** — *see below*, je to docela vyladěné
- ⚙️ **Open Hermes config** v default editoru
- 💻 **Launch Hermes CLI** v novém terminálu

### Log viewer

`~/.hermes/logs/gateway.log` je často obrovský soubor plný tracebacků,
který je potřeba *rychle* projít, ne číst od shora dolů. Proto viewer
nabízí:

- **Barevné log levely**: `DEBUG` šedá, `INFO` bílá, `WARNING` žlutá,
  `ERROR` červená, `CRITICAL` červená + celořádkový highlight
- **Line number gutter** jako Qt Creator/VS Code
- **Filtry per level** (toggle na toolbaru) — vidíš jen to, co chceš
- **TRACEBACK toggle** — zvláštní kategorie pro stack trace; můžeš je
  vypnout a vidět jen zprávy, nebo naopak
- **Time-window filter** (Vše / 5m / 15m / 1h / 6h / 24h) — vidíš
  jen logy z poslední hodiny apod.
- **Reverse order** (Obrátit) — přepne na `journalctl` styl
  (nejnovější nahoře)
- **Max řádků** spinbox — rolling buffer (0 = unlimited)
- **Search** (`Ctrl+F` → `F3` next, `Shift+F3` prev, `Esc` close)
- **Auto-scroll toggle** (default ON; OFF = zachová pozici při refresh)
- **Word-wrap toggle**
- **Copy / Clear / Refresh** akce
- **Settings dialog** (font size, max lines, per-level visibility, …)
- **Persisted** — všechna nastavení se ukládají do
  `~/.config/tray4hermes/state.json`

![Log viewer demo](docs/images/log_viewer.png)

Screenshot výše ukazuje DEBUG řádek šedě a WARNING řádek žlutě (s
`WARNING` tokenem zvýrazněným), s line numbers vlevo a status barem
dole. Stejný dialog na tvém systému bude mít tvoje reálná log data
– tento screenshot je ze sandboxového testu, kde se do fake
gateway.log nasypaly dva ilustrační řádky.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Hermes Agent (Nous Research)                         │
│  • hermes-gateway.service   (systemd --user)         │
│  • Hermes Desktop           (Electron consumer)      │
│  • CLI / TUI / MCP / Plugins                          │
└──────────────────────┬───────────────────────────────┘
                       │ shares
                       ▼
              ~/.hermes/    ←  single source of truth
              ├── config.yaml
              ├── auth.json
              ├── gateway_state.json
              ├── logs/gateway.log
              └── profiles/<name>/
                       ▲
                       │ reads (read-only)
┌──────────────────────┴───────────────────────────────┐
│  tray4hermes  (this package)                          │
│  • systray icon  • Start/Stop/Restart                │
│  • profile switcher  • log viewer                    │
│  • writes only: ~/.config/tray4hermes/state.json     │
└──────────────────────────────────────────────────────┘
```

The package has zero coupling to the Hermes Agent source code. It only
knows about files in `~/.hermes/`, the systemd unit name, and the path
to the `hermes` CLI. The tray can be uninstalled at any time without
affecting the gateway.

## State machine

The tray combines two sources of truth into six discrete states:

| Code | Icon | Meaning |
|------|------|---------|
| `active` | 🟢 | Gateway running, at least one platform connected |
| `warming` | 🟠 | Gateway running, credentials/platforms still initialising |
| `activating` | 🔵 | systemd is starting the service |
| `inactive` | ⚫ | Gateway stopped |
| `failed` | 🔴 | systemd unit failed |
| `unknown` | ⚫ | Cannot determine state (both sources unavailable) |

`gateway_state.json` is the primary source when fresh (< 30 s old);
`systemctl is-active` is the fallback. The two-source design avoids
the OAuth warm-up race where the systemd unit shows `active` for a few
seconds before the first model call actually succeeds.

## Requirements

- Linux with KDE Plasma 5 (Plasma 6 uses Qt6; tray4hermes is Qt5)
- Python ≥ 3.11
- Running `hermes-gateway.service` under `systemd --user`
- `loginctl enable-linger $USER` for autostart after logout

## Installation

### End-user (system-wide)

```bash
uv pip install --system tray4hermes
# or with pipx:
pipx install tray4hermes
```

Then enable autostart:

```bash
cp hermes-tray.desktop ~/.config/autostart/
```

### Development (editable)

```bash
git clone https://github.com/HERMbuddy/tray4hermes.git
cd tray4hermes
uv pip install --system -e ".[dev]"
./scripts/dev.sh   # installs deps + runs tests
```

Launch the tray:

```bash
# Either via the installed console script:
tray4hermes

# Or via the watchdog wrapper (auto-restart on crash):
./run.sh

# Or as a module:
python -m tray4hermes
```

## Security

This package **does not handle any credentials, tokens, or secrets**.
The only file it writes is `~/.config/tray4hermes/state.json`, which
contains the currently-selected profile name and a schema version:

```json
{
  "version": 1,
  "selected_profile": "default"
}
```

If you find a security issue, please open a private issue on the
Forgejo instance (preferred) or contact the maintainer directly. Do
**not** disclose vulnerabilities in public issues or commits.

### Threat model

| Vector | Mitigation |
|--------|------------|
| RCE via malicious `gateway_state.json` | Loaded as JSON only; no `eval`/`exec`/shell. Strict shape. |
| Log injection | Log viewer is read-only; uses `QPlainTextEdit` (escapes HTML). |
| Profile path injection | Profile name validated by Hermes Agent itself (`hermes profile use` returns non-zero on missing). |
| Lock file race | `O_CREAT\|O_EXCL` + PID liveness probe + recursive single retry. |
| Filesystem exhaustion on `state.json` write | Atomic `tmp` + `os.replace`; directory created with `parents=True`. |

The tray is sandboxed against the rest of Hermes Agent: even a
zero-day in tray4hermes cannot read `auth.json`, the `.env` file, or
trigger a model call. The worst it can do is crash and be restarted
by the watchdog — at which point it just reads the (still intact)
state and re-renders the tray icon.

## Development

### Run tests

```bash
./scripts/dev.sh                          # install + pytest
./scripts/dev.sh tests/test_state.py -v   # specific file
```

Tests use `QT_QPA_PLATFORM=offscreen` so they run in CI / headless
environments without a display server.

### Lint & format

```bash
uv run ruff check src tests
uv run ruff format src tests
```

### Security scan

```bash
uv run bandit -c pyproject.toml -r src
```

### Pre-commit hooks (optional but recommended)

```bash
uv pip install --system pre-commit
pre-commit install
pre-commit run --all-files
```

## Project layout

```
tray4hermes/
├── pyproject.toml            # PEP 621, uv-friendly, exact-pinned deps
├── LICENSE                   # MIT
├── README.md
├── .gitignore                # incl. secret patterns
├── .pre-commit-config.yaml
├── run.sh                    # watchdog wrapper
├── hermes-tray.desktop       # KDE autostart
├── scripts/
│   └── dev.sh                # install + test convenience
├── src/
│   └── tray4hermes/
│       ├── __init__.py       # __version__
│       ├── __main__.py       # python -m tray4hermes
│       ├── app.py            # HermesTray QObject glue
│       ├── state.py          # @dataclass + aggregation logic
│       ├── paths.py          # all filesystem constants
│       ├── icons.py          # QPainter icon factory
│       ├── lock.py           # single-instance lock
│       ├── logs_view.py      # LogDialog
│       └── py.typed          # PEP 561 marker
└── tests/
    ├── conftest.py
    ├── test_state.py         # pure-Python, ~30 tests
    ├── test_lock.py          # pure-Python, ~5 tests
    └── test_app.py           # Qt offscreen, ~4 tests
```

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

Issues, comments, návrhy — všechno vítáno. Ať už je to:

- 🐛 **Bug report** — ideálně s výstupem z `~/.hermes/logs/gateway.log`
  a `tray4hermes --debug` logu
- 💡 **Feature request** — krátký popis, k čemu by to bylo. Nevadí mi
  "wild" nápady (jiný backend, Wayland support, custom ikony…),
  posoudíme
- 🎨 **UI tweak** — barvy, layout, fonty, tooltips. Tohle je doména,
  kde se nejvíc projeví vkus contributorů
- 📖 **Documentation** — chybí tady mockupy screenshot log vieweru,
  klidně přidejte
- 🌍 **Localization** — momentálně UI je v češtině. Pokud by se to
  hodilo v jiných jazycích, brzo dodám `_()` wrappers

### Jak poslat PR / patch

```bash
git clone https://github.com/HERMbuddy/tray4hermes.git
cd tray4hermes
./scripts/dev.sh            # nainstaluje deps, spustí testy
# proveďte změnu
./scripts/dev.sh -v         # re-run testy s verbose
uv run ruff check src tests
uv run ruff format src tests
git commit -m "popis"
git push
```

Pravidla (pružná):

1. **Nerozbij testy.** 56 testů musí zůstat zelených.
2. **Nepřidávej nové runtime závislosti** bez diskuze — balíček má
   jedinou závislost (`PyQt5`), a chceme to tak udržet.
3. **Bez tajných dat** v diffu (`grep -rE "sk-[a-z0-9]{16,}|api_key.*[a-z0-9]{20,}"`).
4. **Žádné úpravy `~/.hermes/*`** zevnitř tray — to je owned Hermes Agent.
5. **MIT-compatible contributions.** Pokud přidáváš kód, drž se MIT.

Pokud se ti líbí tenhle projekt a přemýšlíš o něčem, **klidně se ozvi**
v issues — diskutujeme a najdeme společné řešení. I drobnost jako
"tohle slovo se mi nelíbí v překladu" je vítaná.

---

## Roadmap (next-up ideas)

Něco, co se mi honí hlavou, ale ještě není hotovo. Pokud tě něco z toho
zajímá víc než zbytek, dej vědět:

- **Wayland support** — momentálně jsem `xcb` (X11) jen kvůli
  KDE Plasma tray API; Plasma 6 + Qt6 by otevřelo Wayland. PR vítán.
- **Custom ikony per status** — SVG ikony místo `QPainter` raster
- **Log search across sessions** (FTS5 přes sessions DB)
- **Notifications on ERROR** — toast přes `D-Bus` když gateway
  napíše traceback (líbí se mi to, ale je to otázka vkusu)
- **Settings export/import** — sdílení presetů log vieweru mezi
  profily

---

## Credits & thanks

**Vyvinuto s využitím MiniMax M3** (`MiniMax-M3` přes `MiniMax OAuth`),
jak hlavní model pro kód, tak pro revize. Většina kódu v této verzi
vznikla v rámci testování AI-asistovaného vývoje — od diagnózy bugů
přes refaktoring až po celý přepis `logs_view.py` z 59 řádků na 800+.
Pokud M3 (nebo jeho budoucí iterace) udělá chybu v něčem co tady mám,
je to moje chyba — finální review a commity jsou moje.

Díky [@NousResearch](https://github.com/NousResearch) za Hermes Agent
a obecně za celý ekosystém open-source AI agentů.

A díky kterémukoli contributorovi, který se tu objeví — ať už s PR,
nebo jenom s issue. Tohle je malý projekt, ale malé projekty mají
tendenci žít déle než velké. 😉