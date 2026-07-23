"""Path constants — single source of truth for every filesystem location.

IMPORTANT: Path objects are wrapped in helper functions, not built at
import time. This lets tests override ``TRAY4HERMES_HOME`` / ``XDG_CONFIG_HOME``
via ``monkeypatch.setenv`` and have the changes take effect. If you
add a new path, wrap it in a function the same way — do not bind a
``Path(...)`` at module level that reads an env var.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Tunables (pure values, safe at module level) ────────────────────────────
SERVICE: str = "hermes-gateway.service"
# gateway_state.json is rewritten only on state transitions (connect, disconnect,
# platform errors), not on every API call. 30s is too short — a stable connected
# gateway would always show as "warming" because the file is hours old. 1 hour
# is enough to catch real outages while still detecting stale data.
GATEWAY_STATE_MAX_AGE: int = 3600  # seconds
LOG_TAIL_BYTES: int = 256 * 1024  # how much of gateway.log the dialog reads
REFRESH_INTERVAL_MS: int = 5000  # period between state polls
LOG_REFRESH_INTERVAL_MS: int = 2000  # period between log-tail reads
TRAY_STATE_VERSION: int = 1


# ── Path resolvers (call these, don't import the Path directly) ─────────────
def hermes_home() -> Path:
    """Canonical Hermes home monitored by this desktop utility.

    Deliberately ignore generic ``HERMES_HOME``: a tray launched from a
    profile-scoped Hermes terminal inherits that profile path even though the
    systemd gateway still writes runtime state to ``~/.hermes``. Use the
    tray-specific override for tests or non-standard deployments.
    """
    return Path(os.environ.get("TRAY4HERMES_HOME", Path.home() / ".hermes"))


def gateway_state() -> Path:
    return hermes_home() / "gateway_state.json"


def gateway_log() -> Path:
    return hermes_home() / "logs" / "gateway.log"


def profiles_dir() -> Path:
    return hermes_home() / "profiles"


def config_yaml() -> Path:
    return hermes_home() / "config.yaml"


def hermes_bin() -> Path:
    return hermes_home() / "hermes-agent" / "venv" / "bin" / "hermes"


def tray_config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tray4hermes"


def tray_state_file() -> Path:
    return tray_config_dir() / "state.json"


def lock_file() -> Path:
    # /tmp is fine here: the file holds only this process's PID; ownership
    # is the process UID; and TRAY4HERMES_LOCK env var lets tests and
    # paranoid users override the path.
    return Path(
        os.environ.get("TRAY4HERMES_LOCK", "/tmp/hermes-tray.lock")  # noqa: S108
    )
