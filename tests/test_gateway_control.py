"""The two menu paths that actually change the gateway's state.

Neither `_systemctl` nor `_select_profile` had any coverage — the only
parts of the tray that run `systemctl --user` and swap the active
profile. The tests drive the real QAction objects rather than calling
the methods directly, so a menu item wired to the wrong lambda fails
here instead of on the user's desktop.
"""

from __future__ import annotations

import subprocess

import pytest
from PyQt5.QtWidgets import QMessageBox

from tray4hermes.paths import SERVICE
from tray4hermes.state import GatewayState

pytestmark = pytest.mark.usefixtures("qtbot")


@pytest.fixture(autouse=True)
def _stub_aggregate_state(monkeypatch):
    monkeypatch.setattr(
        "tray4hermes.app.aggregate_state",
        lambda: GatewayState(code="active", label="Test fake state"),
    )


@pytest.fixture(autouse=True)
def _no_deferred_refresh(monkeypatch):
    """`QTimer.singleShot(2000, self._refresh)` would fire into a
    half-torn-down tray after the test ends."""
    monkeypatch.setattr("tray4hermes.app.QTimer.singleShot", lambda ms, fn: None)


@pytest.fixture
def systemctl(monkeypatch) -> list[tuple[list[str], dict]]:
    """Record `subprocess.run` calls instead of talking to systemd."""
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


@pytest.fixture
def tray(hermes_home):
    from tray4hermes.app import HermesTray

    t = HermesTray()
    yield t
    t._quit()


class TestSystemctlActions:
    @pytest.mark.parametrize(
        ("attribute", "action"),
        [
            ("_start_action", "start"),
            ("_stop_action", "stop"),
            ("_restart_action", "restart"),
        ],
    )
    def test_menu_item_runs_the_matching_user_unit_action(
        self, tray, systemctl, attribute: str, action: str
    ) -> None:
        menu_action = getattr(tray, attribute)
        # Enablement follows the polled state (Start is greyed out while
        # the gateway runs); this test is about the wiring, not that.
        menu_action.setEnabled(True)

        menu_action.trigger()

        assert [argv for argv, _kw in systemctl] == [["systemctl", "--user", action, SERVICE]]

    def test_the_call_is_bounded_by_a_timeout(self, tray, systemctl) -> None:
        """systemd can block. Without a timeout the tray would freeze
        with no way out — it has no other thread."""
        tray._systemctl("restart")

        _argv, kwargs = systemctl[0]
        assert kwargs.get("timeout"), "systemctl must not be able to hang the tray forever"
        assert kwargs.get("check") is False, "a failed unit action must not raise inside the slot"


class TestSelectProfile:
    def test_declining_the_confirmation_touches_no_unit(
        self, tray, hermes_home, systemctl, monkeypatch
    ) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.No)
        switched: list[str] = []
        monkeypatch.setattr("tray4hermes.app.switch_profile", lambda name: switched.append(name))

        tray._select_profile("alpha")

        assert systemctl == []
        assert switched == [], "declining must not swap the profile either"

    def test_declining_still_remembers_the_picked_profile(
        self, tray, hermes_home, systemctl, monkeypatch
    ) -> None:
        """The radio button the user clicked stays clicked; only the
        restart is skipped."""
        from tray4hermes.state import load_tray_state

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.No)

        tray._select_profile("alpha")

        assert load_tray_state().selected_profile == "alpha"

    def test_confirming_switches_the_profile_and_restarts(
        self, tray, hermes_home, systemctl, monkeypatch
    ) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Yes)
        switched: list[str] = []

        def fake_switch(name: str) -> tuple[bool, str]:
            switched.append(name)
            return True, ""

        monkeypatch.setattr("tray4hermes.app.switch_profile", fake_switch)

        tray._select_profile("alpha")

        assert switched == ["alpha"]
        assert [argv for argv, _kw in systemctl] == [["systemctl", "--user", "restart", SERVICE]], (
            "the gateway has to be restarted for the new profile to take effect"
        )

    def test_a_failed_switch_warns_and_leaves_the_gateway_running(
        self, tray, hermes_home, systemctl, monkeypatch
    ) -> None:
        """A profile directory that does not exist must not lead to a
        restart into a broken configuration."""
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Yes)
        monkeypatch.setattr(
            "tray4hermes.app.switch_profile", lambda name: (False, "no such profile")
        )
        shown: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda parent, title, body, *a, **kw: shown.append(body)
        )

        tray._select_profile("ghost")

        assert systemctl == [], "a failed switch must not restart the gateway"
        assert shown, "a failed switch must be reported"
        assert "ghost" in shown[0]
