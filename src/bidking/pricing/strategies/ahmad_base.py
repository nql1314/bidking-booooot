from __future__ import annotations

from typing import Any


def compute_base_bid_points(
    pricing: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    board_snapshot: dict[str, Any] | None = None,
    round_no: int | None = None,
) -> tuple[int | None, dict[str, Any]]:
    """Ahmad：优先 ``pricing.ahmad_points``（event_stats 汇总），否则回落到 ``points``。"""
    if not isinstance(pricing, dict) or pricing.get("total") is None:
        return None, {"reason": "missing_or_invalid_pricing_total"}
    ap = pricing.get("ahmad_points")
    try:
        if ap is not None:
            v = int(round(float(ap)))
            if v > 0:
                return v, {
                    "points": v,
                    "bid_points_source": "snapshot_pricing.ahmad_points",
                    "points_floor": pricing.get("points_floor"),
                    "points_ceiling": pricing.get("points_ceiling"),
                }
    except (TypeError, ValueError):
        pass
    raw = pricing.get("points")
    if raw is None:
        return None, {"reason": "missing_pricing_points_fallback"}
    try:
        p = int(round(float(raw)))
    except (TypeError, ValueError):
        return None, {"reason": "invalid_pricing_points"}
    meta: dict[str, Any] = {
        "points": p,
        "bid_points_source": "snapshot_pricing.points_fallback",
        "points_floor": pricing.get("points_floor"),
        "points_ceiling": pricing.get("points_ceiling"),
    }
    if p <= 0:
        return None, meta
    return p, meta
