from __future__ import annotations

from bidking.interaction._legacy_bot import (
    parse_round_number,
    resolve_loop_round_no,
)


def test_parse_round_number_accepts_round_six() -> None:
    assert parse_round_number("当前第6轮") == 6
    assert parse_round_number("第 六 回合") == 6
    assert parse_round_number("第VI轮") == 6


def test_resolve_loop_round_no_uses_snapshot_when_ocr_lags() -> None:
    snap = {"current_round": 6}
    assert resolve_loop_round_no(5, snap) == 6
    assert resolve_loop_round_no(None, snap) == 6


def test_resolve_loop_round_no_ocr_only() -> None:
    assert resolve_loop_round_no(6, None) == 6
