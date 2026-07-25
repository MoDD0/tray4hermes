"""Log-line parsing: levels, timestamps, traceback detection.

The level pattern is needed twice — once as a Python `re` for the
filters, once as a Qt `QRegularExpression` for the syntax highlighter.
They used to be two hand-maintained copies of the same regex, and the
copies had already drifted: the Qt one carried the same alternative
twice. These tests pin them to one shared source string.
"""

from __future__ import annotations

import pytest

_SAMPLES = [
    ("2026-07-22 17:45:14,140 INFO gateway.run: started", "INFO"),
    ("2026-07-22T17:45:14 WARNING hermes.discord: slow", "WARNING"),
    ("2026-07-22 17:45:14 ERROR boom", "ERROR"),
    ("[2026-07-22 17:45:14] [DEBUG] gateway: tick", "DEBUG"),
    ("[2026-07-22 17:45:14] CRITICAL down", "CRITICAL"),
    ("2026/07/22 17:45:14 TRACE noise", "TRACE"),
    ('  File "/usr/lib/x.py", line 3, in f', None),
    ("Traceback (most recent call last):", None),
    ("", None),
    ("no timestamp at all", None),
]


@pytest.mark.parametrize(("line", "expected"), _SAMPLES)
def test_line_level_reads_the_level_token(line: str, expected: str | None) -> None:
    from tray4hermes.log_parse import line_level

    assert line_level(line) == expected


@pytest.mark.parametrize(("line", "expected"), _SAMPLES)
def test_qt_and_python_engines_agree(line: str, expected: str | None) -> None:
    """The highlighter must colour exactly the lines the filter keeps.

    Both engines are built from `LEVEL_PATTERN`; if anyone forks that
    string again, this fails.
    """
    from PyQt5.QtCore import QRegularExpression

    from tray4hermes.log_parse import LEVEL_PATTERN, line_level

    qt_match = QRegularExpression(LEVEL_PATTERN).match(line)
    qt_level = qt_match.captured(1) if qt_match.hasMatch() else None

    assert qt_level == line_level(line) == expected


def test_the_highlighter_compiles_the_shared_pattern() -> None:
    """Without this, the test above only proves two regexes built from
    the same string behave alike — not that the highlighter is one of
    them. Someone could paste a private copy back into it and every
    other test here would stay green."""
    from tray4hermes.log_dialog import LogHighlighter
    from tray4hermes.log_parse import LEVEL_PATTERN

    assert LogHighlighter._LEVEL_RE.pattern() == LEVEL_PATTERN


def test_traceback_lines_are_recognised() -> None:
    from tray4hermes.log_parse import is_traceback_line

    assert is_traceback_line("Traceback (most recent call last):")
    assert is_traceback_line('  File "/usr/lib/x.py", line 3, in f')
    assert is_traceback_line("    ^^^^^")
    assert is_traceback_line("RuntimeError: boom")
    assert not is_traceback_line("2026-07-22 17:45:14 INFO fine")
    assert not is_traceback_line("")


def test_timestamps_parse_in_every_accepted_shape() -> None:
    from datetime import datetime

    from tray4hermes.log_parse import line_timestamp

    expected = datetime(2026, 7, 22, 17, 45, 14)
    assert line_timestamp("2026-07-22 17:45:14 INFO x") == expected
    assert line_timestamp("2026-07-22T17:45:14 INFO x") == expected
    assert line_timestamp("[2026-07-22 17:45:14] INFO x") == expected
    assert line_timestamp("2026-07-22 17:45:14,140 INFO x").microsecond == 140000
    assert line_timestamp("no timestamp") is None


def test_aliases_map_onto_canonical_levels() -> None:
    from tray4hermes.log_parse import LEVEL_ALIASES

    assert LEVEL_ALIASES["WARN"] == "WARNING"
    assert LEVEL_ALIASES["FATAL"] == "CRITICAL"
