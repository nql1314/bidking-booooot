# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest

from bidking.pricing._multipliers import (
    BID_RATIO_BY_ROUND_MAX,
    board_snapshot_q5_grid_count_known,
    resolve_automation_bid_ratio,
    validate_aisha_bid_ratio_when_q5_known,
    validate_bid_ratio_by_round,
    validate_bid_ratio_value,
)


def test_validate_bid_ratio_rejects_above_max() -> None:
    with pytest.raises(ValueError, match="不能大于"):
        validate_bid_ratio_value(1.51, label="第3回合系数")


def test_validate_bid_ratio_by_round_dict() -> None:
    validate_bid_ratio_by_round({"1": 1.0, "5": 1.5})
    with pytest.raises(ValueError, match="第2回合系数"):
        validate_bid_ratio_by_round({"2": 2.0})


def test_resolve_automation_bid_ratio_caps_at_max() -> None:
    cfg = {"automation": {"bid_ratio_by_round": {"3": 2.0}}}
    assert resolve_automation_bid_ratio(cfg, 3) == BID_RATIO_BY_ROUND_MAX


def test_aisha_q5_known_uses_dedicated_ratio_from_round5() -> None:
    cfg = {
        "automation": {
            "bid_ratio_by_round": {"5": 0.9},
            "aisha_bid_ratio_by_round_when_q5_known": {"5": 1.05, "default": 1.1},
        }
    }
    snap = {"raw_pricing": {"event_stats": {"q5_grid_count": 40}}}
    assert (
        resolve_automation_bid_ratio(cfg, 5, role="aisha", board_snapshot=snap)
        == 1.05
    )
    assert (
        resolve_automation_bid_ratio(cfg, 6, role="aisha", board_snapshot=snap)
        == 1.1
    )


def test_aisha_q5_unknown_falls_back_to_bid_ratio_by_round() -> None:
    cfg = {
        "automation": {
            "bid_ratio_by_round": {"5": 0.88},
            "aisha_bid_ratio_by_round_when_q5_known": {"5": 1.0},
        }
    }
    snap = {"raw_pricing": {"event_stats": {}}}
    assert resolve_automation_bid_ratio(cfg, 5, role="aisha", board_snapshot=snap) == 0.88


def test_aisha_q5_known_ignored_before_round5() -> None:
    cfg = {
        "automation": {
            "bid_ratio_by_round": {"4": 0.75},
            "aisha_bid_ratio_by_round_when_q5_known": {"4": 1.2},
        }
    }
    snap = {"raw_pricing": {"event_stats": {"q5_grid_count": 10}}}
    assert resolve_automation_bid_ratio(cfg, 4, role="aisha", board_snapshot=snap) == 0.75


def test_board_snapshot_q5_grid_count_known() -> None:
    assert board_snapshot_q5_grid_count_known(
        {"raw_pricing": {"event_stats": {"q5_grid_count": 0}}}
    )
    assert not board_snapshot_q5_grid_count_known(
        {"raw_pricing": {"event_stats": {"q5_grid_avg": 3.0}}}
    )


def test_validate_aisha_bid_ratio_when_q5_known() -> None:
    validate_aisha_bid_ratio_when_q5_known({"5": 1.0, "default": 1.2})
    with pytest.raises(ValueError, match="艾莎已知金总格"):
        validate_aisha_bid_ratio_when_q5_known({"5": 2.0})


def test_visual_schema_bid_ratio_fields_have_max() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "configs" / "visual_config_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    for rnd in range(1, 6):
        path = f"automation.bid_ratio_by_round.{rnd}"
        field = next(f for f in schema["fields"] if f.get("path") == path)
        assert field.get("max") == BID_RATIO_BY_ROUND_MAX
