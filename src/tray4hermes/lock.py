"""Single-instance lock via O_CREAT|O_EXCL + PID liveness probe.

Idempotent: a stale lock (PID dead) is reclaimed on the next call.
This is intentionally simple — no fcntl/flock, no unix socket. Just
PID file + signal 0 liveness check.
"""

from __future__ import annotations

import os
from pathlib import Path


def acquire(lock_file: Path) -> bool:
    """Try to acquire the lock. Returns True iff this is the only instance."""
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return _reclaim_stale_lock(lock_file)
    except OSError:
        return False


def _reclaim_stale_lock(lock_file: Path) -> bool:
    """Existing lockfile — check if its PID is alive; if not, remove and retry once."""
    try:
        with open(lock_file) as f:
            old_pid = int(f.read().strip())
        os.kill(old_pid, 0)  # signal 0 = existence check only
        return False  # PID is alive → another instance is running
    except (ValueError, ProcessLookupError, PermissionError):
        # ValueError → garbage in lockfile
        # ProcessLookupError → PID dead
        # PermissionError → process owned by another user (treat as live)
        pass

    try:
        lock_file.unlink()
    except OSError:
        return False
    return acquire(lock_file)


def release(lock_file: Path) -> None:
    """Best-effort lock removal. Never raises."""
    try:
        lock_file.unlink()
    except OSError:
        pass
