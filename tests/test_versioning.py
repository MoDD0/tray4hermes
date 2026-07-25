"""Tests for automatic Semantic Versioning helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def versioning_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "versioning.py"
    spec = importlib.util.spec_from_file_location("tray4hermes_versioning", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("fix: repair tray status", "patch"),
        ("perf(state): reduce polling overhead", "patch"),
        ("feat: add language picker", "minor"),
        ("feat!: replace state schema", "major"),
        ("refactor!: remove public API\n\nBREAKING CHANGE: old API removed", "major"),
        ("docs: update README", None),
        ("chore: format files", None),
    ],
)
def test_classify_bump(versioning_module, message: str, expected: str | None) -> None:
    assert versioning_module.classify_bump(message) == expected


@pytest.mark.parametrize(
    ("version", "level", "expected"),
    [
        ("2.0.0", "patch", "2.0.1"),
        ("2.0.1", "minor", "2.1.0"),
        ("2.1.7", "major", "3.0.0"),
        # Patch slot is unbounded: 2.0.99 + patch = 2.0.100, not 2.1.0.
        # Only `feat` and `feat!` move into the second/first slot.
        ("2.0.99", "patch", "2.0.100"),
        ("2.0.100", "patch", "2.0.101"),
        ("2.0.99", "minor", "2.1.0"),
        ("2.99.99", "minor", "2.100.0"),
        ("1.999.99", "major", "2.0.0"),
    ],
)
def test_bump_version(versioning_module, version: str, level: str, expected: str) -> None:
    assert versioning_module.bump_version(version, level) == expected


def test_rewrite_version_changes_only_version_assignment(versioning_module) -> None:
    source = '"""Package."""\n\n__version__ = "2.0.0"\n__all__ = ["__version__"]\n'
    updated = versioning_module.rewrite_version(source, "2.0.1")
    assert updated == source.replace('"2.0.0"', '"2.0.1"')


@pytest.mark.parametrize(
    ("base", "current", "message", "expected", "needs_write"),
    [
        ("2.0.0", "2.0.1", "fix: repair state", "2.0.1", False),
        ("2.0.1", "2.1.0", "feat: add widget", "2.1.0", False),
        ("2.1.0", "2.1.0", "docs: clarify install", "2.1.0", False),
    ],
)
def test_required_version_for_commit(
    versioning_module,
    base: str,
    current: str,
    message: str,
    expected: str,
    needs_write: bool,
) -> None:
    assert versioning_module.required_version_for_commit(base, current, message) == (
        expected,
        needs_write,
    )


def test_required_version_rejects_wrong_manual_bump(versioning_module) -> None:
    with pytest.raises(ValueError, match="expected 2.0.1"):
        versioning_module.required_version_for_commit("2.0.0", "2.1.0", "fix: repair state")


@pytest.fixture
def downgrade_gate(versioning_module, tmp_path: Path, monkeypatch):
    """Run `check_against` with a chosen version on the ref and in the tree."""
    version_file = tmp_path / "src" / "tray4hermes" / "__init__.py"
    version_file.parent.mkdir(parents=True)

    def run(*, on_ref: str | None, working: str) -> int:
        version_file.write_text(f'__version__ = "{working}"\n', encoding="utf-8")

        def fake_git(*args: str) -> str:
            if on_ref is None:
                raise RuntimeError("fatal: invalid object name 'origin/main'")
            return f'__version__ = "{on_ref}"\n'

        monkeypatch.setattr(versioning_module, "VERSION_FILE", version_file)
        monkeypatch.setattr(versioning_module, "_git", fake_git)
        return versioning_module.check_against("origin/main")

    return run


class TestDowngradeGate:
    """The gate that would have caught 2.0.11 → 2.0.6.

    Independent of the commit-message rules: whatever the bump policy
    says, the number must never move backwards.
    """

    @pytest.mark.parametrize(
        ("on_ref", "working"),
        [
            ("2.0.11", "2.0.12"),
            ("2.0.11", "2.1.0"),
            ("2.0.11", "3.0.0"),
            ("2.0.11", "2.0.11"),  # docs-only change, no bump
            ("2.0.99", "2.0.100"),  # unbounded patch slot, not a string compare
        ],
    )
    def test_forward_or_unchanged_passes(self, downgrade_gate, on_ref: str, working: str) -> None:
        assert downgrade_gate(on_ref=on_ref, working=working) == 0

    @pytest.mark.parametrize(
        ("on_ref", "working"),
        [
            ("2.0.11", "2.0.6"),  # the actual incident
            ("2.1.0", "2.0.12"),
            ("3.0.0", "2.9.9"),
            ("2.0.100", "2.0.99"),
        ],
    )
    def test_going_backwards_fails(self, downgrade_gate, capsys, on_ref: str, working: str) -> None:
        code = downgrade_gate(on_ref=on_ref, working=working)

        assert code == 1
        err = capsys.readouterr().err
        assert working in err and on_ref in err, f"the message must name both versions: {err!r}"

    def test_missing_ref_does_not_block(self, downgrade_gate, capsys) -> None:
        """Before the first push there is no `origin/main` to compare
        against. That is not a policy violation and must not fail CI."""
        assert downgrade_gate(on_ref=None, working="2.0.12") == 0
        assert capsys.readouterr().err, "skipping the check should still be visible"


@pytest.fixture
def commit_gate(versioning_module, tmp_path: Path, monkeypatch):
    """Run `prepare_commit` against a fake repo.

    Caller picks the version in HEAD, the version in the working tree,
    and the commit message; the fixture returns the hook's exit code.
    """
    version_file = tmp_path / "src" / "tray4hermes" / "__init__.py"
    version_file.parent.mkdir(parents=True)
    message_file = tmp_path / "COMMIT_EDITMSG"

    def run(*, committed: str, working: str, message: str, git_fails: bool = False) -> int:
        version_file.write_text(f'__version__ = "{working}"\n', encoding="utf-8")
        message_file.write_text(message, encoding="utf-8")

        def fake_git(*args: str) -> str:
            if git_fails:
                raise RuntimeError("fatal: not a git repository")
            if args[:2] == ("show", "HEAD:src/tray4hermes/__init__.py"):
                return f'__version__ = "{committed}"\n'
            raise AssertionError(f"unexpected git call: {args}")

        monkeypatch.setattr(versioning_module, "VERSION_FILE", version_file)
        monkeypatch.setattr(versioning_module, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(versioning_module, "_git", fake_git)
        return versioning_module.prepare_commit(message_file)

    return run


class TestCommitGate:
    """What the hook accepts and rejects.

    The previous single test asserted that `prepare_commit` had not
    written the version file and had not run `git add` — neither of
    which it can do; it only reads. Nothing covered the rejections,
    which are the entire point of the gate.
    """

    def test_correctly_pre_bumped_version_is_accepted(self, commit_gate) -> None:
        assert commit_gate(committed="2.0.0", working="2.0.1", message="fix: repair state\n") == 0

    def test_docs_commit_needs_no_bump(self, commit_gate) -> None:
        code = commit_gate(committed="2.0.1", working="2.0.1", message="docs: clarify install\n")

        assert code == 0

    def test_missing_bump_is_rejected(self, commit_gate, capsys) -> None:
        code = commit_gate(committed="2.0.0", working="2.0.0", message="fix: repair state\n")

        assert code == 1
        assert "expected 2.0.1" in capsys.readouterr().err

    def test_patch_bump_for_a_feature_is_rejected(self, commit_gate, capsys) -> None:
        code = commit_gate(committed="2.0.0", working="2.0.1", message="feat: add widget\n")

        assert code == 1
        assert "expected 2.1.0" in capsys.readouterr().err

    def test_bumping_a_docs_commit_is_rejected(self, commit_gate) -> None:
        """`docs:` must not move the version. 2.0.4 → 2.0.5 slipped
        through exactly this way while no gate was running."""
        assert commit_gate(committed="2.0.4", working="2.0.5", message="docs: update README\n") == 1

    def test_a_downgrade_is_rejected(self, commit_gate, capsys) -> None:
        """The incident this gate exists for: 2.0.11 → 2.0.6."""
        code = commit_gate(committed="2.0.11", working="2.0.6", message="fix: repair state\n")

        assert code == 1
        assert "expected 2.0.12" in capsys.readouterr().err

    def test_git_failure_is_reported_rather_than_raised(self, commit_gate, capsys) -> None:
        """A hook that raises leaves git printing a traceback at the
        user instead of a message."""
        code = commit_gate(
            committed="2.0.0", working="2.0.1", message="fix: repair state\n", git_fails=True
        )

        assert code == 1
        assert "versioning error" in capsys.readouterr().err
