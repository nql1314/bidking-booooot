from __future__ import annotations

import math
import random
from typing import Any

from ._numeric import parse_float_config, parse_int_config


def apply_human_like_price_tail(fin: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """千分位尾数：333 / 666 / 888；抽到「000」模式则千位进一。"""
    fin = int(fin)
    before = fin
    high, _low = divmod(fin, 1000)
    pattern = random.choice((333, 666, 888, None))
    if pattern is None:
        fin = (high + 1) * 1000
        tag = "000_carry"
    else:
        cand = high * 1000 + pattern
        fin = cand if cand >= fin else (high + 1) * 1000 + pattern
        tag = str(pattern)
    payload["human_price_tail"] = {"before": before, "after": fin, "pattern": tag}
    return fin, payload


def apply_ceiling_points(
    fin: int,
    fin_before_opp: int,
    ceiling_pts: int | None,
    payload: dict[str, Any],
    round_no: int,
) -> tuple[int, dict[str, Any]]:
    if ceiling_pts is None:
        return int(fin), payload
    if int(round_no) <= 3:
        return int(fin), payload
    if int(fin) <= int(ceiling_pts):
        payload["ceiling_points"] = {
            "applied": True,
            "q5_q6_ceiling": int(ceiling_pts),
            "before": int(fin_before_opp),
            "after": int(fin),
        }
        return int(fin), payload
    capped = min(int(ceiling_pts), int(fin_before_opp))
    payload["ceiling_points"] = {
        "applied": True,
        "q5_q6_ceiling": int(ceiling_pts),
        "before": int(fin_before_opp),
        "after": capped,
        "clamped": True,
    }
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


def apply_bid_cap(config: dict[str, Any], final_price: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    automation = config.get("automation") or {}
    bid_cap = max(0, parse_int_config(automation.get("bid_cap_price"), 0))
    if bid_cap <= 0:
        payload["bid_cap"] = {"enabled": False, "cap_price": 0, "applied": False}
        return int(final_price), payload
    capped = min(int(final_price), bid_cap)
    payload["bid_cap"] = {
        "enabled": True,
        "cap_price": bid_cap,
        "applied": capped != int(final_price),
        "original_price": int(final_price),
    }
    return int(capped), payload


def apply_safe_guard(config: dict[str, Any], final_price: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    automation = config.get("automation") or {}
    safe_enabled = bool(automation.get("safe_guard_enabled", False))
    safe_limit = max(0.0, parse_float_config(automation.get("safe_guard_max_increase_ratio"), 0.0))
    previous_price = config.get("pricing", {}).get("last_submitted_price")
    if not safe_enabled:
        payload["safe_guard"] = {"enabled": False, "triggered": False}
        return int(final_price), payload
    try:
        previous = int(previous_price) if previous_price not in (None, "") else None
    except Exception:
        previous = None
    if previous is None or previous <= 0:
        payload["safe_guard"] = {"enabled": True, "triggered": False, "previous_price": previous}
        return int(final_price), payload
    limit_price = int(math.floor(previous * (1.0 + safe_limit)))
    triggered = final_price > limit_price
    payload["safe_guard"] = {
        "enabled": True,
        "triggered": triggered,
        "previous_price": previous,
        "limit_price": limit_price,
        "safe_limit_ratio": safe_limit,
    }
    if triggered:
        payload["skip_submit"] = True
        payload["reason"] = (
            f"safe_guard blocked: {final_price} > {limit_price} "
            f"(previous={previous}, ratio={safe_limit:.4f})"
        )
        return int(final_price), payload
    return int(final_price), payload
