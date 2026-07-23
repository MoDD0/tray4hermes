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


def test_prepare_commit_accepts_pre_bumped_version(
    versioning_module, tmp_path: Path, monkeypatch
) -> None:
    version_file = tmp_path / "src" / "tray4hermes" / "__init__.py"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('__version__ = "2.0.1"\n', encoding="utf-8")
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text("fix: repair state\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("show", "HEAD:src/tray4hermes/__init__.py"):
            return '__version__ = "2.0.0"\n'
        return ""

    monkeypatch.setattr(versioning_module, "VERSION_FILE", version_file)
    monkeypatch.setattr(versioning_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(versioning_module, "_git", fake_git)
    assert versioning_module.prepare_commit(message_file) == 0
    assert version_file.read_text(encoding="utf-8") == '__version__ = "2.0.1"\n'
    assert not any(call[0] == "add" for call in calls)
