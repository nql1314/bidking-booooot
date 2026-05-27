# -*- coding: utf-8 -*-
"""通用（非角色专用）画板快照定价策略。"""

from __future__ import annotations

from typing import Any, Dict

from .context import SnapshotPricingContext


def build_common_pricing_fields(ctx: SnapshotPricingContext) -> Dict[str, Any]:
    """组装与角色无关的 ``pricing`` 公共字段。"""
    return {
        "total": float(ctx.total_f),
        "vacant": int(ctx.vacant_num),
        "est_orange": int(round(ctx.est_orange)),
        "est_gold_red": int(round(ctx.est_gold_red)),
        "est_red": int(round(ctx.est_red)),
        "vacant_unit_all_orange": ctx.u_orange,
        "vacant_unit_gold_red": ctx.u_gr,
        "vacant_unit_all_red": ctx.u_red,
        "vacant_source": ctx.vacant_src,
        "early_vacant_unit_from_scan": int(ctx.u_early),
        "early_vacant_csv_group": str(ctx.qg_early or ""),
        "early_vacant_possible_qualities": sorted(int(x) for x in ctx.pq_early),
        "map_quality_avg_hit": bool(ctx.csv_cells_for_est),
        "map_quality_avg_csv": str(ctx.raw.get("map_quality_avg_csv") or "")
        if isinstance(ctx.raw, dict)
        else "",
        "known_contour_weighted_cells": int(ctx.kcw_geo),
        "known_contour_weighted_price": float(ctx.kcw_val),
        "tier_extra_value": float(ctx.tier_extra_val),
        "tier_extra_cells": int(ctx.tier_extra_cells),
        "vacant_pts_base": float(ctx.vacant_pts_base),
        "vacant_adj": int(ctx.vacant_adj),
        "unknown_contour_vacant_cell_excess_subtract": int(ctx.uc_vacant_subtract),
        "early_points_blended_with_random_avg": bool(ctx.early_pts_blended_with_random_avg),
        "self_uid_inference": dict(ctx.self_uid_infer_detail),
    }


def apply_generic_points(pricing: Dict[str, Any], ctx: SnapshotPricingContext) -> None:
    """写入通用主价 ``points*``（Ahmad 未激活时的默认输出）。"""
    generic_pts = int(round(ctx.pts))
    generic_floor = int(round(ctx.pts_floor))
    generic_ceil = int(round(ctx.pts_ceiling))
    pricing["points"] = generic_pts
    pricing["points_floor"] = generic_floor
    pricing["points_ceiling"] = generic_ceil


def finalize_pricing_dict(ctx: SnapshotPricingContext) -> Dict[str, Any]:
    """通用策略：直接输出通用主价。"""
    pricing = build_common_pricing_fields(ctx)
    apply_generic_points(pricing, ctx)
    if ctx.uc_excess_detail:
        pricing["unknown_contour_vacant_weighted_excess"] = dict(ctx.uc_excess_detail)
    return pricing
