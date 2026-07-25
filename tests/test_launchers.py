"""Everything the tray spawns as an external process.

Two menu items shell out: "Hermes config" (opens config.yaml in an
editor) and "Hermes CLI" (opens a terminal). Both used to hand a
command straight to `subprocess.Popen` with no error handling, so a
missing binary raised inside a Qt slot — no dialog, no message, the
menu item simply did nothing. `_open_cli` additionally hardcoded
`konsole`, which is only present on KDE.

The editor resolver is tested through `_editor_argv`, which returns an
argv list. It used to return a single string that the caller re-split
with `shlex.split` — a round trip that tore a config path containing a
space into two arguments.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tray4hermes.app import HermesTray
from tray4hermes.state import GatewayState

pytestmark = pytest.mark.usefixtures("qtbot")


@pytest.fixture(autouse=True)
def _stub_aggregate_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never call the real aggregate_state / systemd in tests."""
    monkeypatch.setattr(
        "tray4hermes.app.aggregate_state",
        lambda: GatewayState(code="active", label="Test fake state"),
    )


@pytest.fixture
def clean_editor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no $VISUAL / $EDITOR leaks into a test from the host."""
    for var in ("VISUAL", "EDITOR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def tray(hermes_home):
    t = HermesTray()
    yield t
    t._quit()


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record every argv handed to Popen instead of running it."""
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, *a, **kw: calls.append(list(argv)))
    return calls


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Record QMessageBox.warning calls as (title, body)."""
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "tray4hermes.app.QMessageBox.warning",
        lambda parent, title, body, *a, **kw: shown.append((title, body)),
    )
    return shown


class TestEditorResolution:
    def test_visual_env_wins(self, monkeypatch, clean_editor_env) -> None:
        """$VISUAL beats $EDITOR and the built-in whitelist."""
        monkeypatch.setenv("VISUAL", "nano-fake-for-test")
        monkeypatch.setenv("EDITOR", "vim-fake-for-test")
        with patch.object(shutil, "which", side_effect=lambda cmd: f"/fake/{cmd}"):
            argv = HermesTray._editor_argv("/tmp/config.yaml")  # noqa: S108

        assert argv == ["nano-fake-for-test", "/tmp/config.yaml"]  # noqa: S108

    def test_editor_env_used_when_visual_unset(self, monkeypatch, clean_editor_env) -> None:
        monkeypatch.setenv("EDITOR", "vim-fake-for-test")
        with patch.object(shutil, "which", side_effect=lambda cmd: f"/fake/{cmd}"):
            argv = HermesTray._editor_argv("/tmp/config.yaml")  # noqa: S108

        assert argv == ["vim-fake-for-test", "/tmp/config.yaml"]  # noqa: S108

    def test_quotes_around_the_env_value_are_stripped(self, monkeypatch, clean_editor_env) -> None:
        """Some users write VISUAL='kate -w'; the quotes are shell
        syntax and must not reach the process."""
        monkeypatch.setenv("VISUAL", "'kate-fake-for-test -w'")
        monkeypatch.setattr(
            shutil, "which", lambda cmd: "/fake/kate" if cmd == "kate-fake-for-test" else None
        )

        argv = HermesTray._editor_argv("/tmp/foo.yaml")  # noqa: S108

        assert argv == ["kate-fake-for-test", "-w", "/tmp/foo.yaml"]  # noqa: S108

    def test_a_target_containing_a_space_stays_one_argument(
        self, monkeypatch, clean_editor_env
    ) -> None:
        """The resolver used to return a plain string that the caller
        re-tokenised, so `~/my configs/config.yaml` arrived at the
        editor as two nonexistent files."""
        monkeypatch.setenv("VISUAL", "kate-fake-for-test")
        monkeypatch.setattr(
            shutil, "which", lambda cmd: "/fake/kate" if cmd == "kate-fake-for-test" else None
        )

        argv = HermesTray._editor_argv("/home/u/my configs/config.yaml")

        assert argv == ["kate-fake-for-test", "/home/u/my configs/config.yaml"]

    def test_blank_env_value_is_treated_as_unset(self, monkeypatch, clean_editor_env) -> None:
        monkeypatch.setenv("VISUAL", "   ")
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/kate" if cmd == "kate" else None)

        argv = HermesTray._editor_argv("/tmp/foo.yaml")  # noqa: S108

        assert argv == ["/usr/bin/kate", "/tmp/foo.yaml"]  # noqa: S108

    def test_env_binary_that_does_not_exist_is_rejected(
        self, monkeypatch, clean_editor_env
    ) -> None:
        """A typo in $VISUAL must not become the launcher — otherwise
        every click on the menu item fails silently."""
        monkeypatch.setenv("VISUAL", "/definitely/not/here/typo")
        which_calls: list[str] = []

        def fake_which(cmd: str) -> None:
            which_calls.append(cmd)
            return None

        monkeypatch.setattr(shutil, "which", fake_which)
        argv = HermesTray._editor_argv("/tmp/foo.yaml")  # noqa: S108

        assert "/definitely/not/here/typo" in which_calls, "the env value was never validated"
        assert argv == ["xdg-open", "/tmp/foo.yaml"]  # noqa: S108

    def test_whitelisted_editor_is_used_before_xdg_open(
        self, monkeypatch, clean_editor_env
    ) -> None:
        """xdg-open hands a .yaml to whatever the desktop associates
        with it — LibreOffice on Manjaro KDE. Any real editor first."""
        monkeypatch.setattr(
            shutil, "which", lambda cmd: "/usr/bin/micro" if cmd == "micro" else None
        )

        argv = HermesTray._editor_argv("/tmp/foo.yaml")  # noqa: S108

        assert argv == ["/usr/bin/micro", "/tmp/foo.yaml"]  # noqa: S108

    def test_xdg_open_is_the_last_resort(self, monkeypatch, clean_editor_env) -> None:
        with patch.object(shutil, "which", return_value=None):
            argv = HermesTray._editor_argv("/tmp/foo.yaml")  # noqa: S108

        assert argv == ["xdg-open", "/tmp/foo.yaml"]  # noqa: S108


class TestOpenConfig:
    def test_missing_config_warns_and_launches_nothing(self, tray, spawned, warnings) -> None:
        tray._open_config()

        assert spawned == []
        assert warnings, "a missing config must be reported"

    def test_existing_config_is_handed_to_the_editor(
        self, tray, hermes_home, spawned, warnings, monkeypatch, clean_editor_env
    ) -> None:
        (hermes_home / "config.yaml").write_text("model: test\n")
        monkeypatch.setenv("VISUAL", "kate-fake-for-test")
        monkeypatch.setattr(
            shutil, "which", lambda cmd: "/fake/kate" if cmd == "kate-fake-for-test" else None
        )

        tray._open_config()

        assert warnings == []
        assert spawned == [["kate-fake-for-test", str(hermes_home / "config.yaml")]]

    def test_editor_that_cannot_be_started_warns_instead_of_raising(
        self, tray, hermes_home, warnings, monkeypatch
    ) -> None:
        """The failure mode this fixes: the exception escaped into the Qt
        event loop and the user saw nothing happen at all."""
        (hermes_home / "config.yaml").write_text("model: test\n")

        def boom(argv, *a, **kw):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(subprocess, "Popen", boom)

        tray._open_config()

        assert warnings, "a failed launch must be reported to the user"


class TestOpenCli:
    def test_terminal_is_resolved_from_path_not_hardcoded(
        self, tray, hermes_home, spawned, warnings, monkeypatch
    ) -> None:
        """`konsole` only exists on KDE. On a machine without it the
        old code raised FileNotFoundError inside the slot."""
        cli = hermes_home / "bin" / "hermes"
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.write_text("#!/bin/sh\n")
        monkeypatch.setattr("tray4hermes.paths.hermes_bin", lambda: cli)
        monkeypatch.setattr(
            shutil, "which", lambda cmd: "/usr/bin/xterm" if cmd == "xterm" else None
        )

        tray._open_cli()

        assert warnings == []
        assert spawned and spawned[0][0] == "/usr/bin/xterm"
        assert str(cli) in spawned[0]

    def test_no_terminal_available_warns(self, tray, spawned, warnings, monkeypatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda cmd: None)

        tray._open_cli()

        assert spawned == []
        assert warnings, "with no terminal emulator installed the user must be told"

    def test_terminal_that_cannot_be_started_warns_instead_of_raising(
        self, tray, warnings, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            shutil, "which", lambda cmd: "/usr/bin/xterm" if cmd == "xterm" else None
        )

        def boom(argv, *a, **kw):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(subprocess, "Popen", boom)

        tray._open_cli()

        assert warnings


def test_terminal_name_appears_only_in_the_whitelist() -> None:
    """Guard against the hardcoding creeping back in: the terminal
    table is the only place a terminal binary may be named."""
    app_src = (Path(__file__).resolve().parents[1] / "src" / "tray4hermes" / "app.py").read_text()

    assert app_src.count('"konsole"') == 1, '"konsole" must appear only in the terminal table'
