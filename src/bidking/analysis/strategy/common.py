# -*- coding: utf-8 -*-
"""画板快照定价流水线公共辅助（非角色专用）。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .. import grid_overlay as _grid_overlay
from .. import scan_inference as _scan_inference
from .. import unknown_value as _unknown_value
from ..grid_overlay_item_merge import apply_manual_confirm_projection
from ..phantom_pricing_ui_sync import PHANTOM_Q_INFER, phantom_quality_pref_explicit_quality
from .._shape_wh import shape_wh_from_snapshot
from ...logsys.perf_log import perf_log_elapsed
from ...parsing import item_db
from ...parsing.item_db import CsvItem, candidate_probabilities, filter_csv_candidates_for_query

_RANDOM_AVG_MIN_DOMINANCE_RATIO = 0.5

# 大金区域定义：(宽, 高) 或 (高, 宽) 都匹配
_BIG_GOLD_SHAPES = frozenset([
    (3, 4), (4, 3),
    (4, 4),
    (3, 5), (5, 3),
    (5, 2), (2, 5),
])


def parse_random_avg_price_min(event_stats: Any) -> Optional[int]:
    if not isinstance(event_stats, dict):
        return None
    rv = event_stats.get("random_avg_price_min")
    if rv is None:
        return None
    try:
        v = int(rv)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def blend_points_with_random_avg_min_if_dominant(
    pts: float,
    pts_floor: float,
    pts_ceiling: float,
    event_stats: Any,
    *,
    collapse_floor_ceiling: bool,
) -> tuple[float, float, float, bool]:
    rnd_min = parse_random_avg_price_min(event_stats)
    if rnd_min is None or pts <= 0:
        return pts, pts_floor, pts_ceiling, False
    if float(rnd_min) <= _RANDOM_AVG_MIN_DOMINANCE_RATIO * float(pts):
        return pts, pts_floor, pts_ceiling, False
    blended_mid = float(rnd_min) + float(pts) / 3.0
    if collapse_floor_ceiling:
        return blended_mid, blended_mid, blended_mid, True
    return (
        blended_mid,
        float(rnd_min) + float(pts_floor) / 3.0,
        float(rnd_min) + float(pts_ceiling) / 3.0,
        True,
    )


def event_stat_grid_min_optional(st: Any, key: str) -> Optional[int]:
    if not isinstance(st, dict):
        return None
    v = st.get(key)
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def event_stat_grid_count_optional(st: Any, key: str) -> Optional[int]:
    if not isinstance(st, dict):
        return None
    v = st.get(key)
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def event_stat_q4_grid_count_optional(st: Any) -> Optional[int]:
    return event_stat_grid_count_optional(st, "q4_grid_count")


def vacant_early_unit_excluding_q4_when_q4_total_known(
    *,
    board_snapshot: Dict[str, Any],
    csv_cells_for_est: Dict[str, float],
    event_stats: Any,
) -> Tuple[int, str, frozenset[int]]:
    t0 = time.perf_counter()
    u0, qg0, pq0 = _scan_inference.vacant_early_unit_from_exclusions(
        board_snapshot=board_snapshot,
        csv_cells_raw=csv_cells_for_est if csv_cells_for_est else None,
        pricing={},
    )
    if event_stat_q4_grid_count_optional(event_stats) is not None:
        if 4 not in pq0:
            return u0, qg0, pq0
        pq_ex = frozenset(q for q in pq0 if int(q) != 4)
        qg = _scan_inference.csv_quality_group_from_possible_set(pq_ex)
        if qg is None or not csv_cells_for_est or qg not in csv_cells_for_est:
            perf_log_elapsed("_vacant_early_unit_excluding_q4 (fallback)", t0)
            return u0, qg0, pq0
        u = int(round(float(csv_cells_for_est[qg])))
        perf_log_elapsed("_vacant_early_unit_excluding_q4 (adjusted)", t0)
        return u, str(qg), pq_ex
    return u0, qg0, pq0


def _parse_shape_int(shape: Any) -> Optional[int]:
    if shape is None:
        return None
    if isinstance(shape, int):
        return shape
    try:
        return int(shape)
    except (TypeError, ValueError):
        s = str(shape)
        if len(s) == 2 and s.isdigit():
            return int(s)
        return None


def _geo_footprint_cells_from_shape_field(shape_val: Any) -> Optional[float]:
    sh = _parse_shape_int(shape_val)
    if sh is None:
        return None
    w, h = shape_wh_from_snapshot(sh)
    return float(max(1, w * h))


_PHANTOM_TIER_CANDIDATE_QUALITIES = frozenset({5, 6})
_PHANTOM_TIER_DEFAULT_ITEM_PROB_THRESHOLD = 0.6
_PHANTOM_TIER_DEFAULT_QUALITY_PROB_THRESHOLD = 0.6
_PHANTOM_TIER_DEFAULT_POST_GOLD_Q5_THRESHOLD = 0.7
_PHANTOM_TIER_DEFAULT_POST_GOLD_Q6_THRESHOLD = 0.7


def resolve_phantom_unknown_tier_config(
    *,
    pricing_dict: Optional[Dict[str, Any]] = None,
    snapshot_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """解析 ``pricing.phantom_unknown_tier`` / ``raw_pricing.phantom_unknown_tier`` 阈值。"""
    cfg: Dict[str, float] = {
        "item_prob_threshold": _PHANTOM_TIER_DEFAULT_ITEM_PROB_THRESHOLD,
        "quality_prob_threshold": _PHANTOM_TIER_DEFAULT_QUALITY_PROB_THRESHOLD,
        "post_gold_quality_threshold_q5": _PHANTOM_TIER_DEFAULT_POST_GOLD_Q5_THRESHOLD,
        "post_gold_quality_threshold_q6": _PHANTOM_TIER_DEFAULT_POST_GOLD_Q6_THRESHOLD,
    }

    def _merge(src: Any) -> None:
        if not isinstance(src, dict):
            return
        legacy_raw = src.get("post_gold_quality_threshold")
        if legacy_raw is not None:
            try:
                legacy_f = float(legacy_raw)
            except (TypeError, ValueError):
                legacy_f = None
            if legacy_f is not None and 0.0 < legacy_f <= 1.0:
                cfg["post_gold_quality_threshold_q5"] = legacy_f
                cfg["post_gold_quality_threshold_q6"] = legacy_f
        for key in (
            "item_prob_threshold",
            "quality_prob_threshold",
            "post_gold_quality_threshold_q5",
            "post_gold_quality_threshold_q6",
        ):
            if src.get(key) is None:
                continue
            try:
                v = float(src.get(key))
            except (TypeError, ValueError):
                continue
            if 0.0 < v <= 1.0:
                cfg[key] = v

    if isinstance(pricing_dict, dict):
        tier_cfg = pricing_dict.get("phantom_unknown_tier")
        if isinstance(tier_cfg, dict):
            _merge(tier_cfg)
    if isinstance(snapshot_override, dict):
        _merge(snapshot_override)
    return cfg


def _int_set_from_field(raw: Any) -> Set[int]:
    out: Set[int] = set()
    if not isinstance(raw, (list, tuple, set)):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _phantom_tier_alloc_config(board_snapshot: Dict[str, Any]) -> Dict[str, float]:
    raw = board_snapshot.get("raw_pricing")
    if isinstance(raw, dict):
        tier_raw = raw.get("phantom_unknown_tier")
        if isinstance(tier_raw, dict):
            return resolve_phantom_unknown_tier_config(snapshot_override=tier_raw)
    pricing_dict: Optional[Dict[str, Any]] = None
    try:
        from ...config.runtime import load_runtime

        pricing_raw = load_runtime().raw.get("pricing")
        if isinstance(pricing_raw, dict):
            pricing_dict = pricing_raw
    except Exception:
        pass
    return resolve_phantom_unknown_tier_config(pricing_dict=pricing_dict)


def _phantom_tier_remaining_cells(
    grid_min: Optional[int],
    grid_count: Optional[int],
    confirmed: int,
) -> Optional[float]:
    """``grid_min`` 与 ``grid_count`` 中更紧的「剩余可占格」；皆无则 ``None``。"""
    caps: List[float] = []
    if grid_min is not None:
        caps.append(float(max(0, int(grid_min) - int(confirmed))))
    if grid_count is not None:
        caps.append(float(max(0, int(grid_count) - int(confirmed))))
    if not caps:
        return None
    return float(min(caps))


def _phantom_gr_remaining_budget(
    event_stats: Any,
    *,
    confirmed_q5: int,
    confirmed_q6: int,
) -> Tuple[float, float]:
    """金/红剩余可分摊格数（``grid_min`` 与 ``grid_count`` 取更紧者）。

    ``rem6`` 供 tier_min 等参考；幽灵占位 cap 见 ``_phantom_effective_q5_budget``。
    """
    m5 = event_stat_grid_min_optional(event_stats, "q5_grid_min")
    m6 = event_stat_grid_min_optional(event_stats, "q6_grid_min")
    g5 = event_stat_grid_count_optional(event_stats, "q5_grid_count")
    g6 = event_stat_grid_count_optional(event_stats, "q6_grid_count")
    r5 = _phantom_tier_remaining_cells(m5, g5, confirmed_q5)
    r6 = _phantom_tier_remaining_cells(m6, g6, confirmed_q6)
    if r5 is None and r6 is None:
        return float("inf"), float("inf")
    return float(r5 or 0.0), float(r6 or 0.0)


def _phantom_effective_q5_budget(
    event_stats: Any,
    *,
    confirmed_q5: int,
) -> Tuple[float, bool]:
    """返回 ``(rem5, q5_grid_count_known)``。

    无 ``q5_grid_count`` 且无 ``q5_grid_min`` 时视为 ``q5_grid_min=0``。
    """
    g5 = event_stat_grid_count_optional(event_stats, "q5_grid_count")
    m5 = event_stat_grid_min_optional(event_stats, "q5_grid_min")
    if g5 is None and m5 is None:
        m5 = 0
    r5 = _phantom_tier_remaining_cells(m5, g5, confirmed_q5)
    rem5 = float("inf") if r5 is None else float(r5)
    return rem5, g5 is not None


def _excluded_qualities_set_from_row(row: Dict[str, Any]) -> Set[int]:
    ex: Set[int] = set()
    raw = row.get("excluded_qualities")
    if not isinstance(raw, (list, tuple, set)):
        return ex
    for x in raw:
        try:
            ex.add(int(x))
        except (TypeError, ValueError):
            continue
    return ex


def _map_id_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    gs = board_snapshot.get("game_state")
    mid = None
    if isinstance(gs, dict):
        mid = gs.get("map_id")
    if mid is None:
        mid = board_snapshot.get("map_id")
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


def _phantom_uids_from_snapshot(board_snapshot: Dict[str, Any]) -> Set[str]:
    overlay = board_snapshot.get("grid_overlay")
    if not isinstance(overlay, dict):
        return set()
    ph = overlay.get("phantom_items")
    if not isinstance(ph, dict):
        return set()
    return {str(k) for k in ph}


def _phantom_quality_user_locked_uids(board_snapshot: Dict[str, Any]) -> Set[str]:
    overlay = board_snapshot.get("grid_overlay")
    if not isinstance(overlay, dict):
        return set()
    raw = overlay.get("phantom_quality_user_locked")
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(u) for u in raw}


def _phantom_row_alloc_synced(
    board_snapshot: Dict[str, Any],
    uid_s: str,
    ph_row: Dict[str, Any],
    explicit_pref: Optional[int],
) -> bool:
    """分摊写回后 ``phantom_items.quality`` 与 ``phantom_quality_pref`` 一致，且用户未手改锁定。"""
    if uid_s in _phantom_quality_user_locked_uids(board_snapshot):
        return False
    row_q_raw = ph_row.get("quality")
    if row_q_raw is None or explicit_pref is None:
        return False
    try:
        return int(row_q_raw) == int(explicit_pref)
    except (TypeError, ValueError):
        return False


def _phantom_row_manually_confirmed(
    board_snapshot: Dict[str, Any],
    uid: str,
    it: Dict[str, Any],
) -> bool:
    """手动画板已确认品质或物品：不参与自动分摊。"""
    uid_s = str(uid)
    if uid_s in _phantom_quality_user_locked_uids(board_snapshot):
        return True

    overlay = board_snapshot.get("grid_overlay")
    if not isinstance(overlay, dict):
        overlay = {}
    ph = overlay.get("phantom_items")
    ph_row: Dict[str, Any] = {}
    if isinstance(ph, dict) and isinstance(ph.get(uid_s), dict):
        ph_row = ph[uid_s]

    pref = overlay.get("phantom_quality_pref")
    pval: Any = None
    if isinstance(pref, dict):
        pval = pref.get(uid_s)
        if pval is None:
            pval = pref.get(uid)
    explicit_pref = phantom_quality_pref_explicit_quality(pval)

    if _phantom_row_alloc_synced(board_snapshot, uid_s, ph_row, explicit_pref):
        return False

    mc = it.get("manual_confirm_item_id")
    if mc is not None:
        try:
            if int(mc) > 0:
                return True
        except (TypeError, ValueError):
            pass
    mc_ph = ph_row.get("manual_confirm_item_id")
    if mc_ph is not None:
        try:
            if int(mc_ph) > 0:
                return True
        except (TypeError, ValueError):
            pass

    if isinstance(pval, str) and pval.strip() == PHANTOM_Q_INFER:
        return False

    if explicit_pref is not None:
        return True

    q_raw = it.get("quality")
    if q_raw is not None:
        try:
            if 1 <= int(q_raw) <= 6:
                return True
        except (TypeError, ValueError):
            pass

    cid = it.get("item_cid")
    if cid is not None and it.get("price") is not None:
        return True

    q_ph = ph_row.get("quality")
    if q_ph is not None:
        try:
            if 1 <= int(q_ph) <= 6:
                return True
        except (TypeError, ValueError):
            pass

    return False


def _phantom_row_csv_candidates(
    it: Dict[str, Any],
    *,
    csv_index: Dict[int, CsvItem],
    csv_items: List[CsvItem],
    map_category_weights: Optional[Dict[int, float]],
    map_id_normalized: Optional[int],
    c_gr: Set[int],
) -> Tuple[List[CsvItem], Dict[int, float]]:
    sh = _parse_shape_int(it.get("shape"))
    cats = _int_set_from_field(it.get("categories"))
    cats_any = _int_set_from_field(it.get("categories_any"))
    excl_q = _excluded_qualities_set_from_row(it)
    excl_c = _int_set_from_field(it.get("excluded_categories"))
    cid_raw = it.get("item_cid")
    try:
        item_cid_i = int(cid_raw) if cid_raw is not None else None
    except (TypeError, ValueError):
        item_cid_i = None

    loose = filter_csv_candidates_for_query(
        sh,
        None,
        cats,
        item_cid_i,
        csv_index,
        csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
        categories_any=cats_any if cats_any else None,
    )
    cands = [c for c in loose if c.quality in c_gr]
    if not cands:
        return [], {}
    probs = candidate_probabilities(cands, map_category_weights, map_id_normalized)
    return cands, probs


def _phantom_gold_budget_full(rem5: float) -> bool:
    """金格预算已用尽（``rem5`` 为有限值且 ≤0）。"""
    return rem5 != float("inf") and rem5 <= 1e-9


def _renormalized_probs(cands: List[CsvItem], probs: Dict[int, float]) -> Dict[int, float]:
    total = sum(float(probs.get(c.item_id, 0.0)) for c in cands)
    if total <= 0.0:
        eq = 1.0 / float(len(cands))
        return {c.item_id: eq for c in cands}
    return {c.item_id: float(probs.get(c.item_id, 0.0)) / total for c in cands}


def _phantom_resolution_row_patch(
    a5: float,
    a6: float,
    cells: float,
    *,
    resolved_item_id: Optional[int],
    red_only_budget: bool = False,
) -> Tuple[Dict[str, Any], bool]:
    """
    由分摊结果生成写回幽灵行的字段。

    返回 ``(patch, needs_phantom_tier_credit)``；已锁定物品或整格单品质时不再走 tier 幽灵分摊。
    """
    if resolved_item_id is not None:
        return {"manual_confirm_item_id": int(resolved_item_id)}, False
    fp = float(cells)
    if fp <= 1e-9:
        return {}, False
    if red_only_budget:
        return {"quality": 6}, False
    if a5 > 1e-9 and a6 > 1e-9:
        if abs(a5 + a6 - fp) > 1e-6:
            pass
        return (
            {
                "phantom_tier_credit_by_quality": {
                    "5": round(a5, 6),
                    "6": round(a6, 6),
                }
            },
            True,
        )
    if a5 > 1e-9 and a6 <= 1e-9:
        return {"quality": 5}, False
    if a6 > 1e-9 and a5 <= 1e-9:
        return {"quality": 6}, False
    return {}, False


def _sync_phantom_alloc_to_board_snapshot(
    board_snapshot: Dict[str, Any],
    uid: str,
    patch: Dict[str, Any],
) -> None:
    """将分摊结果写入 ``phantom_items``、``phantom_quality_pref`` 与缓存 ``merged_items_dict``。"""
    if not patch:
        return
    overlay = board_snapshot.get("grid_overlay")
    if not isinstance(overlay, dict):
        return
    uid_s = str(uid)
    ph = overlay.get("phantom_items")
    if isinstance(ph, dict) and isinstance(ph.get(uid_s), dict):
        row = dict(ph[uid_s])
        row.update(patch)
        if patch.get("quality") is not None or patch.get("manual_confirm_item_id") is not None:
            row.pop("phantom_tier_credit_by_quality", None)
        ph[uid_s] = row
    merged = overlay.get("merged_items_dict")
    if isinstance(merged, dict) and isinstance(merged.get(uid_s), dict):
        merged[uid_s].update(patch)
    q_raw = patch.get("quality")
    if q_raw is not None:
        try:
            q_i = int(q_raw)
        except (TypeError, ValueError):
            q_i = None
        if q_i is not None and 1 <= q_i <= 6:
            pref = overlay.get("phantom_quality_pref")
            if not isinstance(pref, dict):
                pref = {}
                overlay["phantom_quality_pref"] = pref
            pref[uid_s] = q_i


def _phantom_row_quality_probs(
    cands: List[CsvItem],
    probs: Dict[int, float],
) -> Tuple[float, float]:
    if not cands:
        return 0.0, 0.0
    norm = _renormalized_probs(cands, probs)
    p5 = sum(norm[c.item_id] for c in cands if int(c.quality) == 5)
    p6 = sum(norm[c.item_id] for c in cands if int(c.quality) == 6)
    return float(p5), float(p6)


def _phantom_try_confirm_item_by_prob(
    cands: List[CsvItem],
    probs: Dict[int, float],
    item_thr: float,
) -> Optional[int]:
    """候选物品归一化权重最高且 > ``item_thr`` 时返回 ``item_id``。"""
    if not cands:
        return None
    best: Optional[CsvItem] = None
    best_p = 0.0
    for c in cands:
        p = float(probs.get(c.item_id, 0.0))
        if p > best_p:
            best_p = p
            best = c
    if best is not None and best_p > item_thr:
        return int(best.item_id)
    return None


def _phantom_record_remaining_cells(rec: Dict[str, Any]) -> float:
    fp = float(rec["fp"])
    a5 = float(rec.get("a5") or 0.0)
    a6 = float(rec.get("a6") or 0.0)
    return max(0.0, fp - a5 - a6)


def _phantom_record_append_step(
    rec: Dict[str, Any],
    rnd: Any,
    q: Optional[int],
    amount: float,
    *,
    reason: str,
    **extra: Any,
) -> None:
    step: Dict[str, Any] = {
        "round": rnd,
        "cells": round(float(amount), 6),
        "reason": reason,
    }
    if q is not None:
        step["quality"] = int(q)
    step.update(extra)
    rec.setdefault("steps", []).append(step)


def _phantom_find_exact_gold_subset(
    candidates: List[Dict[str, Any]],
    target: float,
) -> List[Dict[str, Any]]:
    """回退搜索 footprint 之和正好等于 ``target`` 的候选子集。

    ``candidates`` 须已按金权重从高到低排序；首个合法解即返回（高权重优先）。
    """
    target_i = int(round(float(target)))
    if target_i <= 0 or not candidates:
        return []

    sizes: List[Tuple[int, Dict[str, Any]]] = []
    for rec in candidates:
        sz = int(round(float(rec["fp"])))
        if sz > 0:
            sizes.append((sz, rec))

    chosen: List[Dict[str, Any]] = []
    found = False

    def _dfs(idx: int, remaining: int, cur: List[Dict[str, Any]]) -> None:
        nonlocal found
        if found:
            return
        if remaining == 0:
            chosen.extend(cur)
            found = True
            return
        if remaining < 0 or idx >= len(sizes):
            return
        sz, rec = sizes[idx]
        if sz <= remaining:
            _dfs(idx + 1, remaining - sz, cur + [rec])
            if found:
                return
        _dfs(idx + 1, remaining, cur)

    _dfs(0, target_i, [])
    return chosen


def _phantom_record_assign_gold(
    rec: Dict[str, Any],
    amount: float,
    rnd: int,
    reason: str,
    rem5_ref: List[float],
) -> float:
    rem5 = float(rem5_ref[0])
    if amount <= 1e-9 or rem5 <= 1e-9:
        return 0.0
    a = min(float(amount), rem5)
    if a <= 1e-9:
        return 0.0
    rec["a5"] = float(rec.get("a5") or 0.0) + a
    rem5_ref[0] = rem5 - a
    _phantom_record_append_step(rec, rnd, 5, a, reason=reason)
    return a


def _phantom_resolve_post_gold(
    records: List[Dict[str, Any]],
    *,
    q5_count_known: bool,
    post_gold_thr_q5: float,
    post_gold_thr_q6: float,
    item_thr: float,
) -> None:
    """金格预算用尽后，解析尚未分配的幽灵 footprint。"""
    for rec in records:
        remaining = _phantom_record_remaining_cells(rec)
        if remaining <= 1e-9:
            continue
        cands = rec.get("cands") or []
        probs = rec.get("probs") or {}
        c_gr = rec["c_gr"]
        a5 = float(rec.get("a5") or 0.0)
        a6 = float(rec.get("a6") or 0.0)
        p5 = float(rec.get("p5") or 0.0)
        p6 = float(rec.get("p6") or 0.0)

        confirmed = _phantom_try_confirm_item_by_prob(cands, probs, item_thr)
        if confirmed is not None:
            rec["resolved_item_id"] = confirmed
            _phantom_record_append_step(
                rec,
                "post",
                None,
                remaining,
                reason="item_prob_confirm",
                item_id=int(confirmed),
            )
            continue

        if q5_count_known:
            if 6 in c_gr:
                rec["a6"] = a6 + remaining
                _phantom_record_append_step(
                    rec,
                    "post",
                    6,
                    remaining,
                    reason="count_known_red",
                )
            continue

        if 5 in c_gr and p5 > post_gold_thr_q5:
            rec["a5"] = a5 + remaining
            _phantom_record_append_step(
                rec,
                "post",
                5,
                remaining,
                reason="quality_prob_gold",
            )
        elif 6 in c_gr and p6 > post_gold_thr_q6:
            rec["a6"] = a6 + remaining
            _phantom_record_append_step(
                rec,
                "post",
                6,
                remaining,
                reason="quality_prob_red",
            )
        elif 5 in c_gr and 6 in c_gr:
            half = remaining / 2.0
            rec["a5"] = a5 + half
            rec["a6"] = a6 + (remaining - half)
            _phantom_record_append_step(
                rec,
                "post",
                None,
                remaining,
                reason="q56_candidate_split",
            )
        elif 5 in c_gr:
            rec["a5"] = a5 + remaining
            _phantom_record_append_step(
                rec,
                "post",
                5,
                remaining,
                reason="single_quality_gold",
            )
        elif 6 in c_gr:
            rec["a6"] = a6 + remaining
            _phantom_record_append_step(
                rec,
                "post",
                6,
                remaining,
                reason="single_quality_red",
            )


def _phantom_global_gold_allocate(
    records: List[Dict[str, Any]],
    *,
    board_snapshot: Dict[str, Any],
    rem5: float,
    q5_count_known: bool,
    post_gold_thr_q5: float,
    post_gold_thr_q6: float,
    item_thr: float,
) -> Tuple[float, List[Dict[str, Any]]]:
    """
    艾莎第四回合幽灵全局分摊：

    1. 按金权重从高到低，用回退算法选取 footprint 之和正好等于 ``rem5`` 的矩形；
    2. 仍有金预算时从几何 ``vacant`` 扣减；
    3. 金满后按 ``q5_grid_count`` / ``q5_grid_min`` 规则解析余格。
    """
    global_steps: List[Dict[str, Any]] = []
    if not records:
        return rem5, global_steps

    rem5_ref = [float(rem5)]

    def _eligible_for_gold() -> List[Dict[str, Any]]:
        out = [
            rec
            for rec in records
            if 5 in rec["c_gr"] and _phantom_record_remaining_cells(rec) > 1e-9
        ]
        out.sort(
            key=lambda rec: (
                -float(rec.get("p5") or 0.0),
                float(rec["fp"]),
                str(rec["uid"]),
            )
        )
        return out

    # ── 第一轮：按金权重回退精确匹配剩余金格 ──
    gold_pool = _eligible_for_gold()
    if gold_pool and rem5_ref[0] > 1e-9:
        if rem5_ref[0] == float("inf"):
            for rec in gold_pool:
                _phantom_record_assign_gold(
                    rec,
                    _phantom_record_remaining_cells(rec),
                    1,
                    "quality_prob_gold",
                    rem5_ref,
                )
        else:
            for rec in _phantom_find_exact_gold_subset(gold_pool, rem5_ref[0]):
                _phantom_record_assign_gold(
                    rec,
                    _phantom_record_remaining_cells(rec),
                    1,
                    "quality_prob_gold",
                    rem5_ref,
                )

    # ── 第二轮：空格吸收金预算 ──
    if rem5_ref[0] > 1e-9:
        vb = _grid_overlay.vacant_block_from_board_snapshot(board_snapshot)
        vacant = int(vb.get("geometric") or 0)
        if vacant > 0:
            deduct = min(float(vacant), rem5_ref[0])
            rem5_ref[0] -= deduct
            global_steps.append(
                {
                    "round": 2,
                    "quality": 5,
                    "cells": round(deduct, 6),
                    "reason": "vacant_absorb",
                }
            )

    _phantom_resolve_post_gold(
        records,
        q5_count_known=q5_count_known,
        post_gold_thr_q5=post_gold_thr_q5,
        post_gold_thr_q6=post_gold_thr_q6,
        item_thr=item_thr,
    )
    return rem5_ref[0], global_steps


def phantom_unknown_tier_credit_q456(
    board_snapshot: Dict[str, Any],
    *,
    event_stats: Any = None,
    confirmed_q5: int = 0,
    confirmed_q6: int = 0,
) -> Tuple[Dict[int, float], Dict[str, Any]]:
    """
    品质未知幽灵（``quality is None``）在 ``C_gr={5,6}\\excluded`` 上全局分摊占位，
    同步写回 ``grid_overlay`` 幽灵行（品质 / 手动确认物品 / 分拆 tier 字段）。

    艾莎第四回合金格优先：按金权重回退精确匹配 → 空格吸收；
    金满后若已知 ``q5_grid_count`` 则余格记红，否则按阈值定档或保留 Q5/Q6 候选分拆。
    手动画板已确认品质或物品的幽灵格不参与分摊。

    返回 ``({5: cells, 6: cells}, detail)``；detail 写入 ``pricing.phantom_unknown_quality``。
    """
    t0 = time.perf_counter()
    phantom_uids = _phantom_uids_from_snapshot(board_snapshot)
    if not phantom_uids:
        return {5: 0.0, 6: 0.0}, {}

    alloc_cfg = _phantom_tier_alloc_config(board_snapshot)
    item_thr = float(alloc_cfg["item_prob_threshold"])
    qual_thr = float(alloc_cfg["quality_prob_threshold"])
    post_gold_thr_q5 = float(alloc_cfg["post_gold_quality_threshold_q5"])
    post_gold_thr_q6 = float(alloc_cfg["post_gold_quality_threshold_q6"])
    rem5_init, q5_count_known = _phantom_effective_q5_budget(
        event_stats,
        confirmed_q5=int(confirmed_q5),
    )
    _, rem6_ref = _phantom_gr_remaining_budget(
        event_stats,
        confirmed_q5=int(confirmed_q5),
        confirmed_q6=int(confirmed_q6),
    )

    csv_index, csv_items = _unknown_value._load_item_prices_db()
    map_id_n = item_db.normalize_map_id(_map_id_from_board_snapshot(board_snapshot))
    map_weights = item_db.map_category_ratios(map_id_n) or {}

    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    credit_all: Dict[int, float] = {5: 0.0, 6: 0.0}
    credit_for_tier_min: Dict[int, float] = {5: 0.0, 6: 0.0}
    per_item: List[Dict[str, Any]] = []
    pending_records: List[Dict[str, Any]] = []

    for uid, it in items.items():
        if uid not in phantom_uids or not isinstance(it, dict):
            continue
        if _phantom_row_manually_confirmed(board_snapshot, str(uid), it):
            continue
        bid_raw = it.get("box_id")
        if bid_raw is None:
            continue
        try:
            int(bid_raw)
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed"):
            continue
        fp = _geo_footprint_cells_from_shape_field(it.get("shape"))
        if fp is None:
            continue
        c_gr = _PHANTOM_TIER_CANDIDATE_QUALITIES - _excluded_qualities_set_from_row(it)
        if not c_gr:
            continue
        cands, probs = _phantom_row_csv_candidates(
            it,
            csv_index=csv_index,
            csv_items=csv_items,
            map_category_weights=map_weights if map_weights else None,
            map_id_normalized=map_id_n,
            c_gr=c_gr,
        )
        p5, p6 = _phantom_row_quality_probs(cands, probs) if cands else (0.0, 0.0)
        pending_records.append(
            {
                "uid": str(uid),
                "it": it,
                "fp": float(fp),
                "c_gr": c_gr,
                "cands": cands,
                "probs": probs,
                "p5": p5,
                "p6": p6,
                "a5": 0.0,
                "a6": 0.0,
                "steps": [],
                "resolved_item_id": None,
            }
        )

    pending_records.sort(key=lambda rec: (-float(rec["fp"]), str(rec["uid"])))

    rem5, global_steps = _phantom_global_gold_allocate(
        pending_records,
        board_snapshot=board_snapshot,
        rem5=rem5_init,
        q5_count_known=q5_count_known,
        post_gold_thr_q5=post_gold_thr_q5,
        post_gold_thr_q6=post_gold_thr_q6,
        item_thr=item_thr,
    )

    for rec in pending_records:
        uid = str(rec["uid"])
        it = rec["it"]
        fp = float(rec["fp"])
        c_gr = rec["c_gr"]
        a5 = float(rec.get("a5") or 0.0)
        a6 = float(rec.get("a6") or 0.0)
        steps = list(rec.get("steps") or [])
        resolved_item_id = rec.get("resolved_item_id")
        red_only = (
            _phantom_gold_budget_full(rem5_init)
            and 6 in c_gr
            and resolved_item_id is None
            and a5 <= 1e-9
            and a6 > 1e-9
        )
        patch, needs_tier_credit = _phantom_resolution_row_patch(
            a5,
            a6,
            fp,
            resolved_item_id=resolved_item_id,
            red_only_budget=red_only,
        )
        _sync_phantom_alloc_to_board_snapshot(board_snapshot, uid, patch)
        it.update(patch)

        credit_all[5] += a5
        credit_all[6] += a6
        if needs_tier_credit:
            credit_for_tier_min[5] += a5
            credit_for_tier_min[6] += a6
        row_detail: Optional[Dict[str, Any]] = None
        if len(per_item) < 48:
            tier_by_q: Dict[str, float] = {}
            if a5 > 1e-9:
                tier_by_q["5"] = round(a5, 6)
            if a6 > 1e-9:
                tier_by_q["6"] = round(a6, 6)
            row_detail = {
                "uid": uid,
                "shape": it.get("shape"),
                "cells": int(round(fp)),
                "candidate_qualities": sorted(int(q) for q in c_gr),
                "tier_credit_by_quality": tier_by_q,
                "allocation_steps": steps,
                "row_patch": dict(patch),
                "needs_phantom_tier_credit": bool(needs_tier_credit),
            }
            if resolved_item_id is not None:
                row_detail["resolved_item_id"] = int(resolved_item_id)
            if patch.get("quality") is not None:
                row_detail["resolved_quality"] = int(patch["quality"])
            per_item.append(row_detail)

    merged_after = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    apply_manual_confirm_projection(merged_after, csv_index)
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict):
        ph = overlay.get("phantom_items")
        if isinstance(ph, dict):
            for uid_s in phantom_uids:
                src = merged_after.get(uid_s)
                dst = ph.get(uid_s)
                if not isinstance(src, dict) or not isinstance(dst, dict):
                    continue
                for key in (
                    "item_cid",
                    "quality",
                    "shape",
                    "price",
                    "manual_confirm_item_id",
                ):
                    if key in src:
                        dst[key] = src[key]
        merged_cache = overlay.get("merged_items_dict")
        if isinstance(merged_cache, dict):
            for uid_s, row in merged_after.items():
                if uid_s in phantom_uids and isinstance(row, dict):
                    merged_cache[uid_s] = dict(row)

    if not per_item and credit_all[5] == 0.0 and credit_all[6] == 0.0:
        perf_log_elapsed("phantom_unknown_tier_credit_q456 (empty)", t0)
        return {5: 0.0, 6: 0.0}, {}

    detail: Dict[str, Any] = {
        "items": per_item,
        "tier_credit_q5": round(credit_all[5], 6),
        "tier_credit_q6": round(credit_all[6], 6),
        "tier_credit_for_min_q5": round(credit_for_tier_min[5], 6),
        "tier_credit_for_min_q6": round(credit_for_tier_min[6], 6),
        "alloc_config": {
            "item_prob_threshold": item_thr,
            "quality_prob_threshold": qual_thr,
            "post_gold_quality_threshold_q5": post_gold_thr_q5,
            "post_gold_quality_threshold_q6": post_gold_thr_q6,
        },
        "q5_grid_count_known": q5_count_known,
        "gr_remaining_budget_initial": {
            "q5": round(rem5_init, 6),
            "q6_reference_only": (
                None if rem6_ref == float("inf") else round(rem6_ref, 6)
            ),
        },
        "gr_remaining_budget_final_q5": round(rem5, 6),
    }
    if global_steps:
        detail["gold_allocation_steps"] = global_steps
    perf_log_elapsed(
        f"phantom_unknown_tier_credit_q456 (items={len(per_item)})", t0
    )
    return credit_for_tier_min, detail


def confirmed_tier_footprint_q456(
    board_snapshot: Dict[str, Any],
) -> Tuple[int, int, int]:
    t0 = time.perf_counter()
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    s4 = s5 = s6 = 0.0
    for _uid, it in items.items():
        if not isinstance(it, dict):
            continue
        bid_raw = it.get("box_id")
        if bid_raw is None:
            continue
        try:
            int(bid_raw)
        except (TypeError, ValueError):
            continue
        q_raw = it.get("quality")
        try:
            q = int(q_raw) if q_raw is not None else None
        except (TypeError, ValueError):
            continue
        if q not in (4, 5, 6):
            continue
        fp = _geo_footprint_cells_from_shape_field(it.get("shape"))
        if fp is None:
            continue
        if q == 4:
            s4 += fp
        elif q == 5:
            s5 += fp
        else:
            s6 += fp
    result = int(round(s4)), int(round(s5)), int(round(s6))
    perf_log_elapsed(f"confirmed_tier_footprint_q456 (items={len(items)})", t0)
    return result


def tier_min_extra_value_and_cells(
    event_stats: Any,
    *,
    confirmed_q4: int,
    confirmed_q5: int,
    confirmed_q6: int,
    csv_cells: Dict[str, float],
    unknown_contour_excess_by_quality: Optional[Dict[int, float]] = None,
) -> Tuple[float, int]:
    if not isinstance(event_stats, dict):
        return 0.0, 0
    uc_by_q = unknown_contour_excess_by_quality or {}
    extra_val = 0.0
    extra_cells_f = 0.0
    for min_k, csv_k, confirmed, q in (
        ("q4_grid_min", "q4", confirmed_q4, 4),
        ("q5_grid_min", "q5", confirmed_q5, 5),
        ("q6_grid_min", "q6", confirmed_q6, 6),
    ):
        m = event_stat_grid_min_optional(event_stats, min_k)
        if m is None:
            continue
        need = int(m) - int(confirmed)
        if need <= 0:
            continue
        uc_q = float(uc_by_q.get(q, 0.0) or 0.0)
        eff_need = max(0.0, float(need) - uc_q)
        if eff_need <= 0:
            continue
        u = float(csv_cells.get(csv_k, 0.0))
        extra_val += eff_need * u
        extra_cells_f += eff_need
    return extra_val, int(round(extra_cells_f))


def event_stats_q14_grid_counts_all_known(raw: Any) -> bool:
    from ..raw_pricing import event_stats_q12_q3_q4_grids_all_known

    return event_stats_q12_q3_q4_grids_all_known(raw)


def local_board_snapshot_branch() -> Dict[str, Any]:
    try:
        from ...config.runtime import load_runtime

        raw = load_runtime().raw
        bs = raw.get("board_snapshot")
        return dict(bs) if isinstance(bs, dict) else {}
    except Exception:
        return {}


def self_player_hero_cid(
    board_snapshot: Dict[str, Any],
    *,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    from ...pricing._self_uid_inference import (
        apply_self_uid_inference_to_board_snapshot,
        resolve_effective_self_user_uid,
    )

    gs = board_snapshot.get("game_state")
    if not isinstance(gs, dict):
        return None
    players = gs.get("players")
    if not isinstance(players, dict) or not players:
        return None
    branch = (
        board_snapshot_config
        if board_snapshot_config is not None
        else local_board_snapshot_branch()
    )
    cfg_u = str(branch.get("self_user_uid") or "").strip()
    apply_self_uid_inference_to_board_snapshot(
        board_snapshot, config_self_user_uid=cfg_u
    )
    self_uid = resolve_effective_self_user_uid(
        board_snapshot, config_self_user_uid=cfg_u
    )
    pdata: Any = None
    if self_uid and self_uid in players:
        pdata = players.get(self_uid)
    if pdata is None and len(players) == 1:
        pdata = next(iter(players.values()))
    if not isinstance(pdata, dict):
        return None
    try:
        hc = int(pdata.get("hero_cid") or 0)
    except (TypeError, ValueError):
        return None
    return hc if hc > 0 else None


def _find_continuous_regions(
    vacant_cells: Set[Tuple[int, int]],
    occupied: Set[Tuple[int, int]],
) -> list[Set[Tuple[int, int]]]:
    t0 = time.perf_counter()
    if not vacant_cells:
        return []

    remaining = set(vacant_cells)
    regions: list[Set[Tuple[int, int]]] = []

    while remaining:
        seed = remaining.pop()
        region: Set[Tuple[int, int]] = {seed}
        queue = [seed]

        while queue:
            r, c = queue.pop(0)
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if (nr, nc) in remaining and (nr, nc) not in occupied:
                    remaining.discard((nr, nc))
                    region.add((nr, nc))
                    queue.append((nr, nc))

        regions.append(region)

    perf_log_elapsed(f"_find_continuous_regions (regions={len(regions)})", t0)
    return regions


def _get_bounding_box(cells: Set[Tuple[int, int]]) -> Tuple[int, int, int, int]:
    if not cells:
        return 0, 0, 0, 0
    rows = [r for r, c in cells]
    cols = [c for r, c in cells]
    min_r, max_r = min(rows), max(rows)
    min_c, max_c = min(cols), max(cols)
    return min_r, min_c, max_r - min_r + 1, max_c - min_c + 1


def _is_rectangular_region(cells: Set[Tuple[int, int]], height: int, width: int) -> bool:
    if len(cells) != height * width:
        return False
    min_r, min_c, h, w = _get_bounding_box(cells)
    if h != height or w != width:
        return False
    for r in range(min_r, min_r + height):
        for c in range(min_c, min_c + width):
            if (r, c) not in cells:
                return False
    return True


def detect_big_gold_regions(
    board_snapshot: Dict[str, Any],
) -> Tuple[int, int]:
    t0 = time.perf_counter()
    from ..grid_overlay_dims import GRID_COLS

    vb = _grid_overlay.vacant_block_from_board_snapshot(board_snapshot)
    vacant_num = int(vb.get("geometric") or 0)

    if vacant_num <= 0:
        return 0, 0

    occupied = _grid_overlay.snapshot_occupied_cells(board_snapshot)
    max_bid = _grid_overlay.max_anchor_box_id_merged(board_snapshot)
    limit = min(max_bid, _grid_overlay.GRID_MAX_BOX_ID)

    vacant_cells: Set[Tuple[int, int]] = set()
    for bid in range(limit + 1):
        row, col = bid // GRID_COLS, bid % GRID_COLS
        if (row, col) not in occupied:
            vacant_cells.add((row, col))

    if not vacant_cells:
        return 0, vacant_num

    regions = _find_continuous_regions(vacant_cells, occupied)

    big_gold_total = 0
    for region in regions:
        if len(region) < 6:
            continue

        min_r, min_c, h, w = _get_bounding_box(region)
        shape_match = (h, w) in _BIG_GOLD_SHAPES or (w, h) in _BIG_GOLD_SHAPES

        if shape_match and _is_rectangular_region(region, h, w):
            big_gold_total += len(region)

    perf_log_elapsed(
        f"detect_big_gold_regions (vacant={vacant_num}, big_gold={big_gold_total})", t0
    )
    return big_gold_total, vacant_num


def adjust_u_early_for_big_gold(
    u_early: float,
    u_orange: float,
    big_gold_cells: int,
    total_vacant: int,
) -> float:
    if total_vacant <= 0 or big_gold_cells <= 0:
        return u_early

    if big_gold_cells >= total_vacant:
        return (u_orange + u_early) / 2

    ratio_big = big_gold_cells / total_vacant
    ratio_other = (total_vacant - big_gold_cells) / total_vacant
    u_big_gold = (u_orange + u_early) / 2

    return ratio_big * u_big_gold + ratio_other * u_early
