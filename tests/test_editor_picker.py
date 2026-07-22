"""Tests for the smart editor selector in app.HermesTray._pick_editor_command.

Goal: prove that opening the Hermes config from the tray menu
actually picks a sensible editor and doesn't fall through to
`xdg-open` (which on Manjaro KDE hands the file to LibreOffice,
which mangles a YAML config into a wall of plain text).

We test the *resolver* directly via the static method so we don't
need a full HermesTray instance — just the env and the PATH.
"""

from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from tray4hermes.app import HermesTray


@pytest.fixture
def clean_visual_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no $VISUAL / $EDITOR leaks into a test from the host."""
    for var in ("VISUAL", "EDITOR"):
        monkeypatch.delenv(var, raising=False)


def test_resolve_editor_prefers_env_visual_when_set(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """When $VISUAL is set and points to a real binary, that's
    what wins (over any later rule)."""
    # We can't rely on a real binary on the test system (different
    # CI environment), so we shim shutil.which to lie and pretend
    # the editor exists. The point of this test is the priority
    # order, not the binary's actual presence.
    fake_editor = "/usr/bin/nano-fake-for-test"
    monkeypatch.setenv("VISUAL", fake_editor)
    with patch.object(
        shutil, "which", side_effect=lambda cmd: f"/fake/{cmd}" if cmd == fake_editor else None
    ):
        out = HermesTray._pick_editor_command("/tmp/config.yaml")  # noqa: S108 (test fixture string literal)
    assert out == f"{fake_editor} /tmp/config.yaml"


def test_resolve_editor_uses_editor_when_visual_unset(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """$EDITOR is honoured after $VISUAL."""
    fake_editor = "/usr/bin/vim-fake-for-test"
    monkeypatch.setenv("EDITOR", fake_editor)
    with patch.object(
        shutil, "which", side_effect=lambda cmd: f"/fake/{cmd}" if cmd == fake_editor else None
    ):
        out = HermesTray._pick_editor_command("/tmp/config.yaml")  # noqa: S108 (test fixture string literal)
    assert out == f"{fake_editor} /tmp/config.yaml"


def test_resolve_editor_strips_quotes_in_env(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """Some users set $VISUAL='kate -w'; the surrounding quotes
    should not leak through to the launched command."""
    monkeypatch.setenv("VISUAL", "'kate-fake-for-test -w'")
    # The resolver extracts ``val.split()[0]`` (the binary name)
    # before calling shutil.which. Mock that name resolution
    # explicitly so we don't depend on the test environment.
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/fake/kate-fake-for-test" if cmd == "kate-fake-for-test" else None,
    )
    out = HermesTray._pick_editor_command("/tmp/foo")  # noqa: S108 (test fixture string literal)
    assert out == "kate-fake-for-test -w /tmp/foo"


def test_resolve_editor_falls_through_to_known_editor(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """No env, no $PATH editors? We don't fake an empty PATH —
    if a real common editor is installed (kate, gedit, micro...)
    the test environment often has at least one of them, and
    that's exactly the path the code should take."""
    out = HermesTray._pick_editor_command("/tmp/foo.yaml")  # noqa: S108 (test fixture string literal)
    # We expect a known editor (something from the whitelist),
    # never a LibreOffice-style binary path.
    assert "xdg-open" not in out, (
        f"xdg-open should only be the final fallback when no editor is available; got: {out!r}"
    )
    assert out.endswith("/tmp/foo.yaml"), f"the target file must always be appended; got: {out!r}"  # noqa: S108 (test fixture string literal)


def test_resolve_editor_uses_xdg_open_only_if_no_editor_available(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """Path isolation: pretend PATH contains no real editors so we
    fall through to xdg-open. We don't actually want xdg-open to
    run on a real file (it could open LibreOffice and lock the
    test machine); the unit test just exercises the resolver."""
    with patch.object(shutil, "which", return_value=None):
        # Make sure env vars are clean so they're not picked up
        for var in ("VISUAL", "EDITOR"):
            monkeypatch.delenv(var, raising=False)
        out = HermesTray._pick_editor_command("/tmp/foo.yaml")  # noqa: S108 (test fixture string literal)
    assert out.startswith("xdg-open "), (
        f"with no editor available the resolver must fall back to xdg-open; got: {out!r}"
    )


def test_resolve_editor_skips_unset_env_var(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """$VISUAL set to empty/whitespace should be treated as unset."""
    monkeypatch.setenv("VISUAL", "   ")
    # Provide a fake editor via PATH so the resolver picks it.
    monkeypatch.setenv("PATH", "/usr/local/bin")
    # We don't actually want to launch, so we mock shutil.which.
    with patch.object(
        shutil, "which", side_effect=lambda cmd: f"/usr/bin/{cmd}" if cmd == "kate" else None
    ):
        out = HermesTray._pick_editor_command("/tmp/foo.yaml")  # noqa: S108 (test fixture string literal)
    assert "kate" in out
    assert "VISUAL" not in out


def test_resolve_editor_handles_command_with_spaces(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """If $VISUAL='kate -w' we don't double-append the path."""
    fake = "kate-fake-for-test -w"
    monkeypatch.setenv("VISUAL", fake)
    # The resolver passes ``val.split()[0]`` (the binary) to shutil.which.
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/fake/kate-fake-for-test" if cmd == "kate-fake-for-test" else None,
    )
    out = HermesTray._pick_editor_command("/tmp/foo.yaml")  # noqa: S108 (test fixture string literal)
    # The whitespace in the string is the signal that we already
    # have an argument list — never append.
    assert out == f"{fake} /tmp/foo.yaml", (
        f"$VISUAL containing a space should be passed through as-is; got: {out!r}"
    )


def test_which_helper_used_for_env_var_validation(
    monkeypatch: pytest.MonkeyPatch, clean_visual_editor
) -> None:
    """$VISUAL='not-a-real-binary' should NOT be trusted. We use
    shutil.which to validate the binary exists. This is the
    safety net: a user typo or stripped $PATH shouldn't throw
    us into an editor-error loop on every click."""
    monkeypatch.setenv("VISUAL", "/definitely/not/here/typo")
    with patch.object(shutil, "which", return_value=None):
        out = HermesTray._pick_editor_command("/tmp/foo.yaml")  # noqa: S108 (test fixture string literal)
    # We should NOT have used the typo value as a launcher.
    assert "typo" not in out
