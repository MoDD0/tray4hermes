"""Parsing of individual log lines: level, timestamp, traceback shape.

Pure text handling, no Qt widgets — the level pattern is exported as a
plain string so the syntax highlighter can compile it as a
``QRegularExpression`` while the filters use Python's ``re``. Those two
used to be separately maintained copies of the same expression, and had
already drifted (the Qt copy listed one alternative twice).
"""

from __future__ import annotations

import re
from datetime import datetime

# Matches the level token that follows a leading timestamp. The prefix is
# a non-capturing group, so group(1) is the bare level.
#
# Recognised shapes (Python `logging.Formatter` defaults and friends):
#     2026-07-22 17:45:14,140 INFO gateway.run: ...message...
#     2026-07-22T17:45:14 INFO hermes_plugins.discord...: ...
#     [2026-07-22 17:45:14] [INFO] gateway.run: message
LEVEL_PATTERN = (
    r"^(?:\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\s+"
    r"|\[\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\]\s*\[?"
    r")([A-Z]+)(?:\]|:)?\s"
)

LEVEL_RE = re.compile(LEVEL_PATTERN)

# Captures the leading timestamp (and nothing else) so callers can
# re-format / time-filter without re-running regex.
TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})(?:[T ](?P<time>\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?))?"
    r"|^\[(?P<date2>\d{4}[-/]\d{2}[-/]\d{2})(?:[T ](?P<time2>\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?))?\]"
)

# Aliases so a user with WARN / FATAL in their logs gets the same
# treatment as WARNING / CRITICAL.
LEVEL_ALIASES: dict[str, str] = {
    "WARN": "WARNING",
    "FATAL": "CRITICAL",
}

# A line is considered a "traceback context" (continuation of a stack trace)
# if it matches any of these patterns. They cover the common Python
# `logging` output for unhandled exceptions:
#
#   Traceback (most recent call last):
#     File "/usr/lib/...", line 123, in func_name        ← 2 spaces
#       x = foo()                                        ← 4 spaces
#           ^                                            ← 4 spaces + ^
#   RuntimeError: boom
#   During handling of the above exception, another exception occurred:
_EXCEPTION_SUFFIXES = r"(?:Error|Exception|Warning|Interrupt|Exit|StopIteration|KeyboardInterrupt)"

TRACEBACK_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Traceback \(most recent call last\):"),
    # Exception line at the bottom of a traceback (flush-left, e.g.
    # "RuntimeError: boom", "ValueError: nope", "ZeroDivisionError")
    re.compile(r"^[A-Za-z][A-Za-z0-9_]*" + _EXCEPTION_SUFFIXES),
    # Exception line indented (e.g. "  RuntimeError: boom")
    re.compile(r"^[ ]{2,}[A-Za-z]+" + _EXCEPTION_SUFFIXES),
    # File "x", line N — 2-space indent (Python stdlib format)
    re.compile(r'^[ ]{2,}File ".*", line \d+'),
    # pointer line under the failing line (col-aligned)
    re.compile(r"^[ ]{4,}\^"),
    re.compile(r"^During handling of the above exception,"),
    # "The above exception was the direct cause of the following exception:"
    re.compile(r"^The above exception was the direct cause"),
)


def line_level(line: str) -> str | None:
    """Return the log level of a line, or None if it doesn't match."""
    match = LEVEL_RE.match(line)
    return match.group(1) if match else None


def line_timestamp(line: str) -> datetime | None:
    """Extract a datetime from the leading timestamp on a log line.

    Returns None when the line has no parseable timestamp (e.g. a
    traceback continuation). The time-based filter uses this to
    decide whether a line is inside the configured window.
    """
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None
    date = match.group("date") or match.group("date2")
    time = (match.group("time") or match.group("time2") or "00:00:00").replace(",", ".")
    try:
        return datetime.fromisoformat(f"{date}T{time}")
    except ValueError:
        return None


def is_traceback_line(line: str) -> bool:
    """True if `line` looks like a Python stack-trace continuation.

    Used by the level filter to give stack-trace lines their own toggle
    (TRACEBACK) so the user can show only the message (no traceback),
    only the traceback (no surrounding log noise), or everything.
    """
    if not line:
        return False
    return any(pattern.match(line) for pattern in TRACEBACK_LINE_PATTERNS)
