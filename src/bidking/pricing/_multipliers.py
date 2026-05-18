from __future__ import annotations

from typing import Any

ROUND_RULES = {
    1: {"multiplier": 2.0, "pace": 0.42, "label": "两倍出价第二直接获得"},
    2: {"multiplier": 1.6, "pace": 0.56, "label": "1.6 倍出价第二直接获得"},
    3: {"multiplier": 1.3, "pace": 0.77, "label": "1.3 倍出价第二直接获得"},
    4: {"multiplier": 1.1, "pace": 0.91, "label": "1.1 倍出价第二直接获得"},
    5: {"multiplier": 1.0, "pace": 1.00, "label": "价高者得"},
}


def resolve_round_multiplier(round_no: int, price_config: dict[str, Any]) -> float:
    r = max(1, min(5, int(round_no)))
    rr = price_config.get("round_rules") or {}
    item = rr.get(str(r))
    if isinstance(item, dict) and item.get("multiplier") is not None:
        return float(item["multiplier"])
    return float(ROUND_RULES.get(r, ROUND_RULES[5])["multiplier"])


def resolve_automation_bid_ratio(
    config: dict[str, Any],
    round_no: int,
) -> float:
    """automation.bid_ratio_by_round。"""
    auto = config.get("automation") or {}
    raw = auto.get("bid_ratio_by_round")
    if raw is None:
        raw = config.get("bid_ratio_by_round")
    if not isinstance(raw, dict):
        return 1.0
    key = str(int(round_no))
    v = raw.get(key)
    if v is None:
        v = raw.get("default")
    if v is None:
        return 1.0
    try:
        r = float(v)
    except (TypeError, ValueError):
        return 1.0
    return r if r > 0 else 1.0
