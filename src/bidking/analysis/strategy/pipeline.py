# -*- coding: utf-8 -*-
"""画板快照定价公共流水线。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ...logsys.perf_log import perf_log, perf_log_elapsed
from ...parsing import item_db
from .. import grid_overlay as _grid_overlay
from .. import unknown_value as _unknown_value
from . import common as _common
from .context import SnapshotPricingContext


def prepare_snapshot_pricing_context(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> SnapshotPricingContext:
    """初始化快照、``raw_pricing`` 与 CSV 格均价。"""
    from ...pricing._self_uid_inference import apply_self_uid_inference_to_board_snapshot

    t0_init = time.perf_counter()
    branch_bs = (
        board_snapshot_config
        if board_snapshot_config is not None
        else _common.local_board_snapshot_branch()
    )
    self_uid_infer_detail = apply_self_uid_inference_to_board_snapshot(
        board_snapshot,
        config_self_user_uid=str(branch_bs.get("self_user_uid") or "").strip(),
    )
    perf_log_elapsed("build_snapshot_pricing_dict: init", t0_init)

    game_state_json = board_snapshot.get("game_state") or {}
    skill_logs = list(board_snapshot.get("skill_logs") or [])
    map_id = int(board_snapshot.get("map_id") or (game_state_json.get("map_id") or 0))
    cr = board_snapshot.get("current_round")
    if cr is None:
        cr = game_state_json.get("current_round")
    current_round = int(cr or 1)
    raw = board_snapshot.get("raw_pricing")
    if not isinstance(raw, dict):
        from ..raw_pricing import build_raw_pricing_dict

        raw = build_raw_pricing_dict(
            map_id=int(map_id or 0),
            skill_logs=list(skill_logs or []),
            snapshot_path_hint=snapshot_path_hint,
        )

    snap_full = dict(board_snapshot)
    snap_full["game_state"] = game_state_json
    snap_full["skill_logs"] = skill_logs
    snap_full["map_id"] = map_id
    snap_full["current_round"] = current_round
    snap_full["raw_pricing"] = raw

    t0_csv = time.perf_counter()
    raw_csv_cells = raw.get("csv_quality_groups_avg_per_cell") if isinstance(raw, dict) else None
    raw_csv_items = raw.get("csv_quality_groups_avg_per_item") if isinstance(raw, dict) else None
    if isinstance(raw_csv_cells, dict):
        try:
            csv_cells_for_est = {str(k): float(v) for k, v in raw_csv_cells.items()}
        except (TypeError, ValueError):
            csv_cells_for_est = {}
    else:
        csv_cells_for_est = {}
    if csv_cells_for_est and int(map_id or 0) > 0:
        from ..map_quality_unit_config import apply_map_overrides_to_csv_quality_groups

        try:
            from ...config.runtime import load_runtime

            _cfg = load_runtime().raw
        except Exception:
            _cfg = None
        csv_cells_for_est, _item_adj, _ov_keys = apply_map_overrides_to_csv_quality_groups(
            csv_cells_for_est,
            raw_csv_items if isinstance(raw_csv_items, dict) else None,
            int(map_id),
            config=_cfg,
        )
        if _ov_keys and isinstance(raw, dict):
            raw = dict(raw)
            raw["csv_quality_groups_avg_per_cell"] = dict(csv_cells_for_est)
            if _item_adj:
                raw["csv_quality_groups_avg_per_item"] = dict(_item_adj)
            prev = raw.get("map_quality_unit_override_keys")
            merged_keys = list(prev) if isinstance(prev, list) else []
            for k in _ov_keys:
                if k not in merged_keys:
                    merged_keys.append(k)
            raw["map_quality_unit_override_keys"] = merged_keys
            snap_full["raw_pricing"] = raw
    perf_log_elapsed("build_snapshot_pricing_dict: csv_cells_parse", t0_csv)

    return SnapshotPricingContext(
        board_snapshot=board_snapshot,
        snap_full=snap_full,
        raw=raw,
        map_id=map_id,
        current_round=current_round,
        csv_cells_for_est=csv_cells_for_est,
        board_snapshot_config=board_snapshot_config,
        self_uid_infer_detail=dict(self_uid_infer_detail),
        st_ev=raw.get("event_stats") if isinstance(raw, dict) else None,
    )


def compute_base_metrics(ctx: SnapshotPricingContext) -> None:
    """物品总价、空置格、档位占位与有效空置调整。"""
    from .._board_pricing import compute_items_total

    t0_items = time.perf_counter()
    ctx.total_f = float(compute_items_total(ctx.snap_full))
    perf_log_elapsed("build_snapshot_pricing_dict: compute_items_total", t0_items)

    t0_vacant = time.perf_counter()
    vb = _grid_overlay.vacant_block_from_board_snapshot(ctx.snap_full)
    ctx.vacant_num = int(vb.get("geometric") or 0)
    ctx.vacant_src = str(vb.get("source") or "")
    perf_log_elapsed("build_snapshot_pricing_dict: vacant_block", t0_vacant)

    t0_units = time.perf_counter()
    ctx.u_orange = int(round(float(ctx.csv_cells_for_est.get("q5", 0.0))))
    ctx.u_gr = int(round(float(ctx.csv_cells_for_est.get("q5+q6", 0.0))))
    ctx.u_red = int(round(float(ctx.csv_cells_for_est.get("q6", 0.0))))
    u_early, qg_early, pq_early = _common.vacant_early_unit_excluding_q4_when_q4_total_known(
        board_snapshot=ctx.snap_full,
        csv_cells_for_est=ctx.csv_cells_for_est,
        event_stats=ctx.st_ev,
    )
    ctx.u_early = int(u_early)
    ctx.qg_early = str(qg_early or "")
    ctx.pq_early = set(int(x) for x in pq_early)
    perf_log_elapsed("build_snapshot_pricing_dict: unit_prices", t0_units)

    t0_tiers = time.perf_counter()
    ctx.cq4, ctx.cq5, ctx.cq6 = _common.confirmed_tier_footprint_q456(ctx.snap_full)
    phantom_cr, phantom_detail = _common.phantom_unknown_tier_credit_q456(ctx.snap_full)
    if phantom_detail:
        ctx.phantom_unknown_detail = phantom_detail
        ctx.cq5 += int(round(float(phantom_cr.get(5, 0.0) or 0.0)))
        ctx.cq6 += int(round(float(phantom_cr.get(6, 0.0) or 0.0)))

    t0_unknown = time.perf_counter()
    mid_n = item_db.normalize_map_id(ctx.map_id if ctx.map_id else None)
    _uc_excess_f, uc_excess_detail = _unknown_value.unknown_contour_vacant_weighted_excess(
        ctx.snap_full,
        ctx.csv_cells_for_est if ctx.csv_cells_for_est else None,
        {},
        mid_n,
    )
    perf_log_elapsed("build_snapshot_pricing_dict: unknown_contour", t0_unknown)
    uc_by_quality: Dict[int, float] = {}
    if isinstance(uc_excess_detail, dict):
        raw_bq = uc_excess_detail.get("excess_by_quality")
        if isinstance(raw_bq, dict):
            for k, v in raw_bq.items():
                try:
                    uc_by_quality[int(k)] = float(v)
                except (TypeError, ValueError):
                    continue
    ctx.uc_excess_detail = dict(uc_excess_detail) if uc_excess_detail else {}
    ctx.uc_vacant_subtract = 0

    ctx.tier_extra_val, ctx.tier_extra_cells = _common.tier_min_extra_value_and_cells(
        ctx.st_ev,
        confirmed_q4=ctx.cq4,
        confirmed_q5=ctx.cq5,
        confirmed_q6=ctx.cq6,
        csv_cells=ctx.csv_cells_for_est,
        unknown_contour_excess_by_quality=uc_by_quality,
    )
    perf_log_elapsed("build_snapshot_pricing_dict: tier_footprint", t0_tiers)

    ctx.vacant_adj = max(0, int(ctx.vacant_num) - int(ctx.tier_extra_cells))
    ctx.vacant_pts_base = float(ctx.total_f) + float(ctx.tier_extra_val)

    ctx.est_orange = ctx.vacant_pts_base + float(ctx.vacant_adj) * float(ctx.u_orange)
    ctx.est_gold_red = ctx.vacant_pts_base + float(ctx.vacant_adj) * float(ctx.u_gr)
    ctx.est_red = ctx.vacant_pts_base + float(ctx.vacant_adj) * float(ctx.u_red)


def compute_generic_points(ctx: SnapshotPricingContext) -> None:
    """通用空置主价 ``points`` / ``points_floor`` / ``points_ceiling``。"""
    t0_est = time.perf_counter()
    ctx.q14_grid_known = _common.event_stats_q14_grid_counts_all_known(ctx.raw)

    if not ctx.q14_grid_known:
        ctx.pts = ctx.vacant_pts_base + float(ctx.vacant_adj) * float(ctx.u_early)
        ctx.pts_floor = ctx.pts
        ctx.pts_ceiling = ctx.pts
        ctx.pts, ctx.pts_floor, ctx.pts_ceiling, ctx.early_pts_blended_with_random_avg = (
            _common.blend_points_with_random_avg_min_if_dominant(
                ctx.pts,
                ctx.pts_floor,
                ctx.pts_ceiling,
                ctx.st_ev,
                collapse_floor_ceiling=True,
            )
        )
    else:
        q5_gc = _common.event_stat_grid_count_optional(ctx.st_ev, "q5_grid_count")
        q6_gc = _common.event_stat_grid_count_optional(ctx.st_ev, "q6_grid_count")
        if q5_gc is not None and q6_gc is None:
            u_mid = float(ctx.u_red)
            u_lo = u_mid
            u_hi = u_mid
        elif q6_gc is not None and q5_gc is None:
            u_mid = float(ctx.u_orange)
            u_lo = u_mid
            u_hi = u_mid
        elif q6_gc is not None and q5_gc is not None:
            u_mid = float(ctx.u_red)
            u_lo = u_mid
            u_hi = u_mid
        else:
            u_mid = float(ctx.u_orange)
            u_lo = float(ctx.u_orange)
            from ...config.runtime import infer_big_gold_adjustment_enabled

            if infer_big_gold_adjustment_enabled():
                big_gold_cells, total_vacant = _common.detect_big_gold_regions(ctx.snap_full)
                u_early_adj = _common.adjust_u_early_for_big_gold(
                    float(ctx.u_early),
                    float(ctx.u_orange),
                    big_gold_cells,
                    total_vacant,
                )
                u_hi = u_early_adj
            else:
                u_hi = float(ctx.u_early)
        ctx.pts = ctx.vacant_pts_base + float(ctx.vacant_adj) * u_mid
        ctx.pts_floor = ctx.vacant_pts_base + float(ctx.vacant_adj) * u_lo
        ctx.pts_ceiling = ctx.vacant_pts_base + float(ctx.vacant_adj) * u_hi
        ctx.pts, ctx.pts_floor, ctx.pts_ceiling, ctx.early_pts_blended_with_random_avg = (
            _common.blend_points_with_random_avg_min_if_dominant(
                ctx.pts,
                ctx.pts_floor,
                ctx.pts_ceiling,
                ctx.st_ev,
                collapse_floor_ceiling=False,
            )
        )
    perf_log_elapsed("build_snapshot_pricing_dict: estimate_points", t0_est)


def build_pricing_context(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> SnapshotPricingContext:
    """完整公共流水线：上下文 → 基底指标 → 通用主价。"""
    ctx = prepare_snapshot_pricing_context(
        board_snapshot,
        snapshot_path_hint=snapshot_path_hint,
        board_snapshot_config=board_snapshot_config,
    )
    compute_base_metrics(ctx)
    compute_generic_points(ctx)
    return ctx
