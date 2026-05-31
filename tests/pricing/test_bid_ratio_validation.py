# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest

from bidking.pricing._multipliers import (
    BID_RATIO_BY_ROUND_MAX,
    resolve_automation_bid_ratio,
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


def test_visual_schema_bid_ratio_fields_have_max() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "configs" / "visual_config_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    for rnd in range(1, 6):
        path = f"automation.bid_ratio_by_round.{rnd}"
        field = next(f for f in schema["fields"] if f.get("path") == path)
        assert field.get("max") == BID_RATIO_BY_ROUND_MAX
