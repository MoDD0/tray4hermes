"""Tests for the single-instance lock (no Qt, no subprocess)."""

from __future__ import annotations

import os
from pathlib import Path

from tray4hermes.lock import acquire, release


class TestLock:
    def test_acquire_first_time_succeeds(self, tmp_path: Path) -> None:
        lock = tmp_path / "lock"
        assert acquire(lock) is True
        assert lock.exists()
        assert int(lock.read_text().strip()) == os.getpid()

    def test_acquire_twice_while_held_returns_false(self, tmp_path: Path) -> None:
        lock = tmp_path / "lock"
        assert acquire(lock) is True
        # Same process can't acquire twice — would re-enter _reclaim_stale_lock
        # and re-acquire because we own the PID. We assert idempotency only
        # for *different* processes, which we simulate by manually writing
        # another (live) PID.
        lock.write_text(str(os.getpid()))  # someone else "owns" it
        # Note: we can't truly simulate a second process without fork,
        # so we just assert the second acquire is safe (no exception).
        result = acquire(lock)
        # Since the PID is our own and alive, the lock should NOT be re-acquired
        # but the call should not raise either.
        assert result is False

    def test_release_removes_lock(self, tmp_path: Path) -> None:
        lock = tmp_path / "lock"
        acquire(lock)
        assert lock.exists()
        release(lock)
        assert not lock.exists()

    def test_release_nonexistent_is_safe(self, tmp_path: Path) -> None:
        # Must not raise
        release(tmp_path / "nope")

    def test_garbage_lockfile_is_overwritten(self, tmp_path: Path) -> None:
        # Existing lockfile with junk → reclaim succeeds
        lock = tmp_path / "lock"
        lock.write_text("not a pid\n")
        assert acquire(lock) is True
        assert int(lock.read_text().strip()) == os.getpid()

    def test_dead_pid_in_lockfile_is_reclaimed(self, tmp_path: Path) -> None:
        lock = tmp_path / "lock"
        # Pick a PID that almost certainly does not exist
        # (we use a high number; if it ever existed, that's astronomically unlikely)
        lock.write_text("999999\n")
        assert acquire(lock) is True
        assert int(lock.read_text().strip()) == os.getpid()
