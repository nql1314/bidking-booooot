from __future__ import annotations

from typing import Any

from ._numeric import parse_int_config


def _thousands_digit_tail_pattern(high: int) -> int:
    """千分位数字重复 3 次，如千位为 3 → 333，为 9 → 999。"""
    return (high % 10) * 111


def apply_human_like_price_tail(fin: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """千分位尾数：按千分位数字重复该数字 3 次（如 13321→13333，299333→299999）。"""
    fin = int(fin)
    before = fin
    if fin < 1000:
        payload["human_price_tail"] = {
            "before": before,
            "after": fin,
            "pattern": "skip_lt_1000",
        }
        return fin, payload

    high, _low = divmod(fin, 1000)
    pattern = _thousands_digit_tail_pattern(high)
    cand = high * 1000 + pattern
    if cand >= fin:
        fin = cand
        tag = str(pattern)
    else:
        high += 1
        pattern = _thousands_digit_tail_pattern(high)
        fin = high * 1000 + pattern
        tag = f"{pattern}_carry"
    payload["human_price_tail"] = {"before": before, "after": fin, "pattern": tag}
    return fin, payload


def apply_ceiling_points(
    fin: int,
    fin_before_opp: int,
    ceiling_pts: int | None,
    payload: dict[str, Any],
    round_no: int,
    *,
    bid_ratio: float = 1.0,
) -> tuple[int, dict[str, Any]]:
    if ceiling_pts is None:
        return int(fin), payload
    if int(round_no) <= 3:
        return int(fin), payload
    ceil_cap = int(ceiling_pts)
    if float(bid_ratio) > 1.0:
        ceil_cap = int(round(ceiling_pts * float(bid_ratio)))
    if int(fin) <= int(ceil_cap * 1.15):
        ce: dict[str, Any] = {
            "applied": True,
            "q5_q6_ceiling": int(ceil_cap),
            "before": int(fin_before_opp),
            "after": int(fin),
        }
        if ceil_cap != int(ceiling_pts):
            ce["points_ceiling_config"] = int(ceiling_pts)
            ce["bid_ratio_scale"] = float(bid_ratio)
        payload["ceiling_points"] = ce
        return int(fin), payload
    capped = min(int(ceil_cap), int(fin_before_opp))
    ce2: dict[str, Any] = {
        "applied": True,
        "q5_q6_ceiling": int(ceil_cap),
        "before": int(fin_before_opp),
        "after": capped,
        "clamped": True,
    }
    if ceil_cap != int(ceiling_pts):
        ce2["points_ceiling_config"] = int(ceiling_pts)
        ce2["bid_ratio_scale"] = float(bid_ratio)
    payload["ceiling_points"] = ce2
    return capped, payload


def apply_early_round_fallback_floor(
    fin: int,
    round_no: int,
    fallback_floor: int,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    fin = int(fin)
    fb_floor = int(fallback_floor)
    r = int(round_no)
    if r not in (1, 2):
        payload["early_round_fallback_floor"] = {
            "applied": False,
            "reason": "not_round_1_or_2",
        }
        return fin, payload
    if fin >= fb_floor:
        payload["early_round_fallback_floor"] = {
            "applied": False,
            "reason": "already_ge_fallback",
            "fallback": fb_floor,
            "round": r,
        }
        return fin, payload
    before = fin
    fin = fb_floor
    payload["early_round_fallback_floor"] = {
        "applied": True,
        "fallback": fb_floor,
        "before": before,
        "after": fin,
        "round": r,
    }
    return fin, payload


def apply_late_round_low_bid_surrender(
    config: dict[str, Any],
    fin: int,
    round_no: int,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """
    超过 ``late_round_low_bid_surrender_after_round`` 且出价低于
    ``late_round_low_bid_surrender_below`` 时，强制改为放弃价（默认 886）。

    由 ``pricing.enable_late_round_low_bid_surrender`` 总开关控制。
    """
    fin = int(fin)
    pricing_cfg = config.get("pricing") or {}
    key = "late_round_low_bid_surrender"
    enabled = bool(pricing_cfg.get("enable_late_round_low_bid_surrender", False))
    after_round = max(0, parse_int_config(pricing_cfg.get("late_round_low_bid_surrender_after_round"), 4))
    below_bid = max(0, parse_int_config(pricing_cfg.get("late_round_low_bid_surrender_below"), 5000))
    surrender_bid = max(0, parse_int_config(pricing_cfg.get("late_round_low_bid_surrender_bid"), 886))
    r = int(round_no)
    meta: dict[str, Any] = {
        "enabled": enabled,
        "after_round": after_round,
        "below": below_bid,
        "surrender_bid": surrender_bid,
        "round": r,
    }
    if not enabled:
        meta["applied"] = False
        meta["reason"] = "disabled"
        payload[key] = meta
        return fin, payload
    if r < after_round:
        meta["applied"] = False
        meta["reason"] = "round_not_past_threshold"
        payload[key] = meta
        return fin, payload
    if fin >= below_bid:
        meta["applied"] = False
        meta["reason"] = "bid_not_below_threshold"
        meta["before"] = fin
        payload[key] = meta
        return fin, payload
    before = fin
    fin = int(surrender_bid)
    meta["applied"] = True
    meta["before"] = before
    meta["after"] = fin
    payload[key] = meta
    # 界面出放弃价，但 self_bid 缓存仍记截断前的策略出价
    payload["self_bid_cache_amount"] = before
    return fin, payload


def known_items_total_from_pricing(pricing: Any) -> float | None:
    """从 ``pricing`` 取已知物品总价；缺字段时返回 ``None``（由调用方决定是否回算）。"""
    if not isinstance(pricing, dict):
        return None
    raw = pricing.get("known_items_total")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def apply_bid_cap(
    config: dict[str, Any],
    final_price: int,
    payload: dict[str, Any],
    *,
    known_items_total: float | int | None = None,
    pricing_total: float | int | None = None,
) -> tuple[int, dict[str, Any]]:
    """封顶出价；``bid_cap_skip_when_total_above`` 与 **已知物品总价**（不含 ``phantom_vac_*`` 自动填充）比较。"""
    automation = config.get("automation") or {}
    bid_cap = max(0, parse_int_config(automation.get("bid_cap_price"), 0))
    if bid_cap <= 0:
        payload["bid_cap"] = {"enabled": False, "cap_price": 0, "applied": False}
        return int(final_price), payload

    skip_threshold = max(
        0, parse_int_config(automation.get("bid_cap_skip_when_total_above"), 0)
    )
    if skip_threshold <= 0:
        skip_threshold = bid_cap

    compare_total: float | None = None
    if known_items_total is not None:
        try:
            compare_total = float(known_items_total)
        except (TypeError, ValueError):
            compare_total = None
    if compare_total is None and pricing_total is not None:
        try:
            compare_total = float(pricing_total)
        except (TypeError, ValueError):
            compare_total = None

    if compare_total is not None and compare_total > float(skip_threshold):
        payload["bid_cap"] = {
            "enabled": True,
            "cap_price": bid_cap,
            "applied": False,
            "skipped": True,
            "reason": "known_items_total_above_skip_threshold",
            "known_items_total": compare_total,
            "skip_threshold": skip_threshold,
            "original_price": int(final_price),
        }
        return int(final_price), payload

    capped = min(int(final_price), bid_cap)
    payload["bid_cap"] = {
        "enabled": True,
        "cap_price": bid_cap,
        "applied": capped != int(final_price),
        "original_price": int(final_price),
    }
    return int(capped), payload
