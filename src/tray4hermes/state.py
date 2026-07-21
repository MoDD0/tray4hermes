"""State types and aggregation logic.

`aggregate_state()` is the single function that turns the messy real-world
inputs (gateway_state.json, systemd, filesystem races) into one of six
discrete UI states. Everything else in the app reads this — never the raw
inputs — so we test the contract here, not the chaos.

NOTE: All filesystem paths are constructed inside functions (not at
module level) so that ``HERMES_HOME`` env var changes are picked up at
runtime. This is what makes the test suite's per-test isolation work.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tray4hermes import paths as _paths
from tray4hermes.paths import (
    GATEWAY_STATE_MAX_AGE,
    SERVICE,
    TRAY_STATE_VERSION,
)

# ── State codes ─────────────────────────────────────────────────────────────
# All six are mutually exclusive. UI maps them 1:1 to icons + colors.

ACTIVE = "active"
WARMING = "warming"
ACTIVATING = "activating"
INACTIVE = "inactive"
FAILED = "failed"
UNKNOWN = "unknown"

ALL_STATES: tuple[str, ...] = (
    ACTIVE,
    WARMING,
    ACTIVATING,
    INACTIVE,
    FAILED,
    UNKNOWN,
)


@dataclass(frozen=True)
class GatewayState:
    """Immutable view of the gateway's runtime state."""

    code: str
    label: str

    def __post_init__(self) -> None:
        if self.code not in ALL_STATES:
            raise ValueError(f"unknown GatewayState code: {self.code!r}")


@dataclass(frozen=True)
class TrayState:
    """Persistent state owned by this app (mirrors TRAY_STATE_FILE on disk)."""

    selected_profile: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "version": TRAY_STATE_VERSION,
            "selected_profile": self.selected_profile,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> TrayState:
        return cls(selected_profile=str(data.get("selected_profile", "") or ""))

    @classmethod
    def default(cls) -> TrayState:
        return cls()


# ── I/O: tray state (atomic write, never raises into UI) ──────────────────
def load_tray_state() -> TrayState:
    """Read tray_state_file. Returns default on any error."""
    try:
        with open(_paths.tray_state_file()) as f:
            return TrayState.from_json(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return TrayState.default()


def save_tray_state(state: TrayState) -> None:
    """Atomic write (tmp + rename). Never raises — log + drop on error."""
    target_dir = _paths.tray_config_dir()
    target_file = _paths.tray_state_file()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp = target_file.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state.to_json(), f, indent=2)
        os.replace(tmp, target_file)
    except OSError as exc:
        print(f"[tray4hermes] save_tray_state failed: {exc}", file=__import__("sys").stderr)


# ── Hermes reads (best-effort, never raise into UI) ────────────────────────
def _hermes_home() -> Path:
    """Resolve HERMES_HOME at call time (not import time) so env overrides work."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _gateway_state_path() -> Path:
    return _hermes_home() / "gateway_state.json"


def read_gateway_state_file() -> dict[str, object] | None:
    """Parse gateway_state.json if it exists and is fresh (< GATEWAY_STATE_MAX_AGE)."""
    p = _gateway_state_path()
    try:
        if time.time() - p.stat().st_mtime > GATEWAY_STATE_MAX_AGE:
            return None
        with open(p) as f:
            result: dict[str, object] = json.load(f)
            return result
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return None


def list_profiles(profiles_dir: Path) -> list[str]:
    """List profile names. 'default' is always first, then the rest alphabetical."""
    profiles: list[str] = []
    if profiles_dir.is_dir():
        for entry in sorted(profiles_dir.iterdir()):
            if entry.is_dir() and entry.name != "default":
                profiles.append(entry.name)
    return ["default", *profiles]


def read_active_model(config_yaml: Path) -> str:
    """Best-effort read of model.default + provider without importing PyYAML."""
    try:
        text = config_yaml.read_text()
    except OSError:
        return "(config nečitelný)"

    model, provider = "", ""
    in_model = False
    for line in text.splitlines():
        if line.startswith("model:"):
            in_model = True
            continue
        if in_model and line and not line.startswith((" ", "\t")):
            in_model = False
        if in_model:
            stripped = line.strip()
            if stripped.startswith("default:"):
                model = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("provider:"):
                provider = stripped.split(":", 1)[1].strip()
    if not model:
        return "(model nenalezen)"
    return f"{model} ({provider})" if provider else model


# ── systemd wrapper (best-effort) ──────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Run subprocess. Never raises — returns (rc, output).

    All callers pass static lists (e.g. ["systemctl", "--user", "is-active", SERVICE]),
    so S603 (untrusted input) does not apply.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, f"(subprocess error: {exc})"


def systemd_is_active() -> str | None:
    """Return systemd state code or None if the call fails entirely."""
    code, out = _run(["systemctl", "--user", "is-active", SERVICE], timeout=15)
    out = out.strip()
    if code == 0 and "active" in out:
        return ACTIVE
    if "inactive" in out:
        return INACTIVE
    if "failed" in out:
        return FAILED
    if "activating" in out:
        return ACTIVATING
    return None


def aggregate_state() -> GatewayState:
    """Combine gateway_state.json (primary) + systemd (fallback) into one state."""
    gw = read_gateway_state_file()
    if gw is not None:
        if gw.get("running") is False:
            return GatewayState(INACTIVE, "Gateway hlásí stopped")
        if gw.get("discord") or gw.get("platforms"):
            return GatewayState(ACTIVE, "Gateway běží a je připojená")
        return GatewayState(WARMING, "Gateway běží, čeká na připojení")

    s = systemd_is_active()
    if s == ACTIVE:
        return GatewayState(WARMING, "Gateway běží (čekám na gateway_state.json)")
    if s == ACTIVATING:
        return GatewayState(ACTIVATING, "Gateway startuje…")
    if s == FAILED:
        return GatewayState(FAILED, "Gateway služba selhala")
    if s == INACTIVE:
        return GatewayState(INACTIVE, "Gateway je zastavená")
    return GatewayState(UNKNOWN, "Stav gateway je nečitelný")


# ── Profile switching (single high-level action used by the UI) ────────────
def switch_profile(name: str, *, hermes_bin: Path | None = None) -> tuple[bool, str]:
    """`hermes profile use <name>` + caller is expected to restart gateway.

    Returns (success, output). Does NOT restart gateway — the UI does that
    after user confirms the dialog, so we can keep this pure/testable.
    """
    bin_path = hermes_bin if hermes_bin is not None else _paths.hermes_bin()
    if not bin_path.exists():
        return False, f"hermes bin not found: {bin_path}"
    code, out = _run([str(bin_path), "profile", "use", name], timeout=15)
    return code == 0, out
