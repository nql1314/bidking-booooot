from __future__ import annotations

from typing import Any

from ..vacant_red import apply_vacant_red_floor_ceiling_pick


def compute_base_bid_points(
    pricing: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    board_snapshot: dict[str, Any] | None = None,
    round_no: int | None = None,
) -> tuple[int | None, dict[str, Any]]:
    """艾莎：主锚价为 ``pricing.points``，再在 ``points_floor`` / ``points_ceiling`` 间做空置红择优。"""
    if not isinstance(pricing, dict) or pricing.get("total") is None:
        return None, {"reason": "missing_or_invalid_pricing_total"}
    raw = pricing.get("points")
    if raw is None:
        return None, {"reason": "missing_pricing_points"}
    try:
        p = int(round(float(raw)))
    except (TypeError, ValueError):
        return None, {"reason": "invalid_pricing_points"}
    meta: dict[str, Any] = {
        "points": p,
        "points_floor": pricing.get("points_floor"),
        "points_ceiling": pricing.get("points_ceiling"),
        "bid_points_source": "snapshot_pricing.points",
        "pricing": {k: pricing.get(k) for k in ("total", "vacant", "early_vacant_unit_from_scan")},
    }
    if p <= 0:
        return None, meta

    if config is None or board_snapshot is None or round_no is None:
        return p, meta

    anchor, vac_pick = apply_vacant_red_floor_ceiling_pick(
        config, board_snapshot, pricing, int(round_no), int(p)
    )
    meta_out = dict(meta)
    meta_out["pricing_reason"] = f"{meta_out.get('bid_points_source', '')}: base={p}"
    if vac_pick.get("applied"):
        meta_out["vacant_red_floor_ceiling_pick"] = vac_pick
        meta_out["pricing_reason"] = (
            f"{meta_out['pricing_reason']}; vacant_red_pick->{anchor}"
        ).strip("; ")
    return int(anchor), meta_out
