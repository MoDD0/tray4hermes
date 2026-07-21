# tray4hermes

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Passive KDE/Plasma system-tray monitor and thin controller for
**Hermes Gateway** — the messaging bridge that ships with
[Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous
Research.

> **tray4hermes is read-only with respect to Hermes Agent.** It controls
> the gateway via `systemctl --user`, persists one small JSON file of its
> own, and reads everything else. It does not store tokens, does not
> configure providers, does not edit `~/.hermes/config.yaml`. All of
> that lives in Hermes Agent itself.

---

## Features

- 📊 **Live status icon** in the system tray (green/orange/blue/grey/red)
- ▶️ **Start / Stop / Restart** of `hermes-gateway.service`
- 🔄 **Profile switcher** submenu (driven by `~/.hermes/profiles/`)
- 📋 **Log viewer** with auto-refresh (tails `~/.hermes/logs/gateway.log`)
- ⚙️ **Open Hermes config** in your default editor
- 💻 **Launch Hermes CLI** in a new terminal

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
git clone https://forgejo.he1.co/HERMbuddy/tray4hermes.git
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