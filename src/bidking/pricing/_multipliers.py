from __future__ import annotations

from typing import Any, Mapping

from ..analysis.strategy.common import event_stat_grid_count_optional

BID_RATIO_BY_ROUND_MAX = 1.5
AISHA_Q5_KNOWN_BID_RATIO_MIN_ROUND = 5


def validate_bid_ratio_value(value: float, *, label: str | None = None) -> None:
    """``automation.bid_ratio_by_round`` 单回合系数须为正且不超过上限。"""
    who = label or "回合系数"
    try:
        r = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{who}: 无效数字") from exc
    if r <= 0:
        raise ValueError(f"{who}须为正数")
    if r > BID_RATIO_BY_ROUND_MAX:
        raise ValueError(f"{who}不能大于 {BID_RATIO_BY_ROUND_MAX:g}")


def validate_bid_ratio_by_round(raw: Any) -> None:
    """校验 ``bid_ratio_by_round`` 字典中各回合系数。"""
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ValueError("bid_ratio_by_round 须为对象")
    for key, val in raw.items():
        if val is None:
            continue
        if str(key).strip().lower() == "default":
            label = "默认回合系数"
        else:
            label = f"第{key}回合系数"
        validate_bid_ratio_value(val, label=label)


def validate_aisha_bid_ratio_when_q5_known(raw: Any) -> None:
    """校验 ``aisha_bid_ratio_by_round_when_q5_known``（第 5 回合及之后、已知金总格）。"""
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ValueError("aisha_bid_ratio_by_round_when_q5_known 须为对象")
    for key, val in raw.items():
        if val is None:
            continue
        if str(key).strip().lower() == "default":
            label = "艾莎已知金总格默认系数"
        else:
            label = f"艾莎已知金总格第{key}回合系数"
        validate_bid_ratio_value(val, label=label)


def board_snapshot_q5_grid_count_known(board_snapshot: dict[str, Any] | None) -> bool:
    """画板 ``raw_pricing.event_stats.q5_grid_count`` 已公开（金总格）。"""
    if not isinstance(board_snapshot, dict):
        return False
    raw = board_snapshot.get("raw_pricing")
    if not isinstance(raw, dict):
        return False
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return False
    return event_stat_grid_count_optional(st, "q5_grid_count") is not None


def _lookup_bid_ratio_from_map(raw: Mapping[str, Any], round_no: int) -> float | None:
    key = str(int(round_no))
    v = raw.get(key)
    if v is None:
        v = raw.get("default")
    if v is None:
        return None
    try:
        r = float(v)
    except (TypeError, ValueError):
        return None
    if r <= 0:
        return None
    return min(r, BID_RATIO_BY_ROUND_MAX)


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
    *,
    role: str | None = None,
    board_snapshot: dict[str, Any] | None = None,
) -> float:
    """``automation.bid_ratio_by_round``；艾莎第 5 回合起且已知金总格时用 ``aisha_bid_ratio_by_round_when_q5_known``。"""
    auto = config.get("automation") or {}
    rn = int(round_no)
    if (
        str(role or "").strip().lower() == "aisha"
        and rn >= AISHA_Q5_KNOWN_BID_RATIO_MIN_ROUND
        and board_snapshot_q5_grid_count_known(board_snapshot)
    ):
        aisha_raw = auto.get("aisha_bid_ratio_by_round_when_q5_known")
        if isinstance(aisha_raw, Mapping):
            r = _lookup_bid_ratio_from_map(aisha_raw, rn)
            if r is not None:
                return r
    raw = auto.get("bid_ratio_by_round")
    if raw is None:
        raw = config.get("bid_ratio_by_round")
    if not isinstance(raw, Mapping):
        return 1.0
    r = _lookup_bid_ratio_from_map(raw, rn)
    return 1.0 if r is None else r
