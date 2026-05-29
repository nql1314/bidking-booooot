"""Bot 总控定时启动时间计算。"""

from datetime import datetime

from bidking.ui._legacy_gui import (
    _format_countdown,
    _parse_clock_hour,
    _parse_clock_minute,
    _seconds_until_local_time,
)


def test_parse_clock_hour_minute_clamps() -> None:
    assert _parse_clock_hour("25") == 23
    assert _parse_clock_hour("-1") == 8
    assert _parse_clock_minute("99") == 59
    assert _parse_clock_minute("7") == 7


def test_seconds_until_local_time_same_day() -> None:
    now = datetime(2026, 5, 27, 10, 0, 30)
    assert _seconds_until_local_time(10, 30, now=now) == 29 * 60 + 30


def test_seconds_until_local_time_next_day() -> None:
    now = datetime(2026, 5, 27, 23, 59, 0)
    assert _seconds_until_local_time(8, 0, now=now) == 8 * 3600 + 60


def test_format_countdown() -> None:
    assert _format_countdown(90) == "1分30秒"
    assert _format_countdown(3661) == "1小时01分01秒"
