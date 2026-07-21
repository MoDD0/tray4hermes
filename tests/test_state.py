"""Tests for state types and the I/O layer (no Qt, no subprocess)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from tray4hermes.state import (
    ACTIVE,
    FAILED,
    INACTIVE,
    UNKNOWN,
    WARMING,
    TrayState,
    aggregate_state,
    list_profiles,
    load_tray_state,
    read_active_model,
    read_gateway_state_file,
    save_tray_state,
)


# ── Dataclass invariants ────────────────────────────────────────────────────
class TestGatewayState:
    def test_construction_with_unknown_code_rejected(self) -> None:
        from tray4hermes.state import GatewayState

        with pytest.raises(ValueError, match="unknown GatewayState code"):
            GatewayState(code="made-up", label="x")

    @pytest.mark.parametrize(
        "code",
        ["active", "warming", "activating", "inactive", "failed", "unknown"],
    )
    def test_all_six_codes_accepted(self, code: str) -> None:
        from tray4hermes.state import GatewayState

        s = GatewayState(code=code, label="x")
        assert s.code == code

    def test_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        from tray4hermes.state import GatewayState

        s = GatewayState(code=ACTIVE, label="x")
        with pytest.raises(FrozenInstanceError):
            s.code = FAILED  # type: ignore[misc]


class TestTrayState:
    def test_default(self) -> None:
        assert TrayState.default() == TrayState()

    def test_to_json_shape(self) -> None:
        d = TrayState(selected_profile="default").to_json()
        assert d == {"version": 1, "selected_profile": "default"}

    def test_from_json_with_missing_keys(self) -> None:
        s = TrayState.from_json({})
        assert s.selected_profile == ""

    def test_from_json_with_garbage_type(self) -> None:
        # None or int should coerce to "" (defensive)
        assert TrayState.from_json({"selected_profile": None}).selected_profile == ""
        assert TrayState.from_json({"selected_profile": 42}).selected_profile == "42"


# ── I/O: tray state ────────────────────────────────────────────────────────
class TestTrayStateIO:
    def test_load_returns_default_when_file_missing(self, xdg_config: Path) -> None:
        s = load_tray_state()
        assert s == TrayState.default()

    def test_save_then_load_roundtrip(self, xdg_config: Path) -> None:
        save_tray_state(TrayState(selected_profile="hermes-minimax-subs"))
        loaded = load_tray_state()
        assert loaded.selected_profile == "hermes-minimax-subs"

    def test_save_creates_directory(self, tmp_path: Path, monkeypatch) -> None:
        nested = tmp_path / "deeply" / "nested" / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(nested))
        save_tray_state(TrayState(selected_profile="x"))
        assert (nested / "tray4hermes" / "state.json").exists()

    def test_save_is_atomic(self, xdg_config: Path) -> None:
        # After save, no leftover .tmp file should remain
        save_tray_state(TrayState(selected_profile="x"))
        from tray4hermes.paths import tray_state_file

        tmp = tray_state_file().with_suffix(".tmp")
        assert not tmp.exists()


# ── Hermes readers ─────────────────────────────────────────────────────────
class TestGatewayStateFile:
    def test_missing_returns_none(self, hermes_home: Path) -> None:
        assert read_gateway_state_file() is None

    def test_stale_file_returns_none(self, hermes_home: Path) -> None:
        import time

        f = hermes_home / "gateway_state.json"
        f.write_text(json.dumps({"running": True, "discord": True}))
        # Backdate by 60s — well past the 30s freshness window
        old = time.time() - 60
        import os as _os

        _os.utime(f, (old, old))
        assert read_gateway_state_file() is None

    def test_fresh_file_returns_dict(self, hermes_home: Path) -> None:
        (hermes_home / "gateway_state.json").write_text(
            json.dumps({"running": True, "discord": True})
        )
        d = read_gateway_state_file()
        assert d is not None
        assert d["discord"] is True

    def test_garbage_json_returns_none(self, hermes_home: Path) -> None:
        (hermes_home / "gateway_state.json").write_text("not json at all")
        assert read_gateway_state_file() is None


class TestListProfiles:
    def test_empty_profiles_dir_returns_default_only(self, hermes_home: Path) -> None:
        assert list_profiles(hermes_home / "profiles") == ["default"]

    def test_alphabetic_order(self, hermes_home: Path) -> None:
        for name in ["zeta", "alpha", "mu"]:
            (hermes_home / "profiles" / name).mkdir()
        result = list_profiles(hermes_home / "profiles")
        assert result == ["default", "alpha", "mu", "zeta"]

    def test_default_present_not_duplicated(self, hermes_home: Path) -> None:
        (hermes_home / "profiles" / "default").mkdir()
        (hermes_home / "profiles" / "alpha").mkdir()
        result = list_profiles(hermes_home / "profiles")
        assert result.count("default") == 1
        assert result == ["default", "alpha"]


class TestReadActiveModel:
    def test_missing_file_returns_placeholder(self, hermes_home: Path) -> None:
        assert read_active_model(hermes_home / "config.yaml") == "(config nečitelný)"

    def test_extracts_default_and_provider(self, hermes_home: Path) -> None:
        (hermes_home / "config.yaml").write_text(
            textwrap.dedent("""\
                model:
                  default: MiniMax-M3
                  provider: minimax-oauth
                other_key: ignored
            """)
        )
        assert read_active_model(hermes_home / "config.yaml") == "MiniMax-M3 (minimax-oauth)"

    def test_model_block_terminates_on_top_level_key(self, hermes_home: Path) -> None:
        # The `fallback_providers:` key is at top level — must NOT bleed into model
        (hermes_home / "config.yaml").write_text(
            textwrap.dedent("""\
                model:
                  default: MiniMax-M3
                  provider: minimax-oauth
                fallback_providers: '[{"provider":"openrouter"}]'
            """)
        )
        assert read_active_model(hermes_home / "config.yaml") == "MiniMax-M3 (minimax-oauth)"

    def test_only_default_no_provider(self, hermes_home: Path) -> None:
        (hermes_home / "config.yaml").write_text(
            textwrap.dedent("""\
            model:
              default: some-model
        """)
        )
        assert read_active_model(hermes_home / "config.yaml") == "some-model"

    def test_no_model_block(self, hermes_home: Path) -> None:
        (hermes_home / "config.yaml").write_text("other_key: value\n")
        assert read_active_model(hermes_home / "config.yaml") == "(model nenalezen)"


# ── Aggregation: the one function that matters ─────────────────────────────
class TestAggregateState:
    def test_no_inputs_returns_unknown(self, hermes_home: Path, monkeypatch) -> None:
        # No gateway_state.json, and pretend systemd is unreachable
        from tray4hermes import state as state_mod

        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: None)
        s = aggregate_state()
        assert s.code == UNKNOWN

    def test_gateway_state_active(self, hermes_home: Path, monkeypatch) -> None:
        from tray4hermes import state as state_mod

        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: None)
        (hermes_home / "gateway_state.json").write_text(
            json.dumps({"running": True, "discord": True})
        )
        s = aggregate_state()
        assert s.code == ACTIVE

    def test_gateway_state_warming_when_running_but_no_platforms(
        self,
        hermes_home: Path,
        monkeypatch,
    ) -> None:
        from tray4hermes import state as state_mod

        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: None)
        (hermes_home / "gateway_state.json").write_text(
            json.dumps({"running": True, "discord": None, "platforms": None})
        )
        s = aggregate_state()
        assert s.code == WARMING

    def test_gateway_state_running_false_is_inactive(
        self,
        hermes_home: Path,
        monkeypatch,
    ) -> None:
        from tray4hermes import state as state_mod

        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: None)
        (hermes_home / "gateway_state.json").write_text(
            json.dumps({"running": False, "discord": True})  # discord ignored
        )
        s = aggregate_state()
        assert s.code == INACTIVE

    def test_fresh_state_takes_precedence_over_stale_systemd(
        self,
        hermes_home: Path,
        monkeypatch,
    ) -> None:
        from tray4hermes import state as state_mod

        # systemd would say FAILED — but fresh state file wins
        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: FAILED)
        (hermes_home / "gateway_state.json").write_text(
            json.dumps({"running": True, "discord": True})
        )
        s = aggregate_state()
        assert s.code == ACTIVE
        assert s.label != ""

    def test_fallback_to_systemd_when_state_file_missing(
        self,
        hermes_home: Path,
        monkeypatch,
    ) -> None:
        from tray4hermes import state as state_mod

        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: FAILED)
        s = aggregate_state()
        assert s.code == FAILED

    def test_fallback_active_is_treated_as_warming(
        self,
        hermes_home: Path,
        monkeypatch,
    ) -> None:
        # systemd says active but no state file → we don't trust it fully,
        # show warming until gateway_state.json appears
        from tray4hermes import state as state_mod

        monkeypatch.setattr(state_mod, "systemd_is_active", lambda: ACTIVE)
        s = aggregate_state()
        assert s.code == WARMING
