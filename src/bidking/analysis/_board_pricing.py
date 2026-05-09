# -*- coding: utf-8 -*-
"""
画板快照定价：由 ``game_state.items`` 与 ``grid_overlay`` 合并后的有效物品表汇总总价、
权重占位与空置格，再结合扫描推断与地图 CSV 格均价给出 ``points`` / ``est_*``。

``items`` 与 ``grid_overlay`` 的合并由 :mod:`grid_overlay` 的 :func:`grid_overlay.merged_items_dict` 完成。

不再维护独立的「艾莎 bid」分支；策略层直接消费 ``pricing.points`` / ``points_floor`` /
``points_ceiling``。

当 ``raw_pricing.event_stats`` 提供 ``q4_grid_min`` / ``q5_grid_min`` / ``q6_grid_min`` 时，
对 ``max(0, 最少格 - 已确认该档占位格)`` 按 CSV 单档 ``q4``/``q5``/``q6`` 格均价计入总价，
并对空置单价项使用扣减后的有效空置格数（``pricing.vacant`` 仍为几何/有效空置原值）。

已知轮廓且 CSV 为多候选（权重价）的物品：几何占位格在边际上视同空置，参与 ``空置格 × 空置单价``；
但 ``total`` 已含该件权重价，故在 ``points`` / ``est_*`` 基底中扣除对应权重价，避免重复计价。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.item_db import _weighted_est_price, map_category_ratios, query_item
from . import scan_inference as _scan_inference
from . import unknown_value as _unknown_value
from . import grid_overlay as _grid_overlay

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    path = _unknown_value._item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache


def map_id_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
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


def current_round_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    r = board_snapshot.get("current_round")
    if r is None:
        r = (board_snapshot.get("game_state") or {}).get("current_round")
    try:
        v = int(r)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


def _shape_wh_from_snapshot(shape: Any) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1

def _int_set_from_field(raw: Any) -> Set[int]:
    out: Set[int] = set()
    if not isinstance(raw, list):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _event_stat_grid_min_optional(st: Any, key: str) -> Optional[int]:
    """``event_stats`` 中 ``q*_grid_min``：有值且非负时返回 int，否则不参与最少格扣减。"""
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


def _confirmed_tier_footprint_q456(
    board_snapshot: Dict[str, Any],
    *,
    csv_cells_raw: Dict[str, float],
) -> Tuple[int, int, int]:
    """
    合并物品表上 Q4/Q5/Q6 且 ``box_id_confirmed`` 的占位格数（与 :func:`_footprint_cells` 同源）。
    """
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict(board_snapshot)
    work = _pricing_work_board_snapshot(board_snapshot, items)
    s4 = s5 = s6 = 0.0
    for _uid, it in items.items():
        if not isinstance(it, dict) or not it.get("box_id_confirmed"):
            continue
        q_raw = it.get("quality")
        try:
            q = int(q_raw) if q_raw is not None else None
        except (TypeError, ValueError):
            continue
        if q not in (4, 5, 6):
            continue
        fp = _footprint_cells(it, work, csv_cells_raw, mid_n)
        if q == 4:
            s4 += fp
        elif q == 5:
            s5 += fp
        else:
            s6 += fp
    return int(round(s4)), int(round(s5)), int(round(s6))


def _tier_min_extra_value_and_cells(
    event_stats: Any,
    *,
    confirmed_q4: int,
    confirmed_q5: int,
    confirmed_q6: int,
    csv_cells: Dict[str, float],
) -> Tuple[float, int]:
    """
    当 ``event_stats`` 给出紫/金/红 ``q*_grid_min`` 时：

    - 每档额外价值 ``max(0, grid_min - 已确认占位格) * CSV 单档 q4/q5/q6 格均价``；
    - ``grid_min`` 缺失（None）则该档不参与；``grid_min <= 已确认`` 则该档为 0。

    返回 ``(extra_value_sum, cells_to_subtract_from_vacant_estimate)``。
    """
    if not isinstance(event_stats, dict):
        return 0.0, 0
    extra_val = 0.0
    extra_cells = 0
    for min_k, csv_k, confirmed in (
        ("q4_grid_min", "q4", confirmed_q4),
        ("q5_grid_min", "q5", confirmed_q5),
        ("q6_grid_min", "q6", confirmed_q6),
    ):
        m = _event_stat_grid_min_optional(event_stats, min_k)
        if m is None:
            continue
        need = int(m) - int(confirmed)
        if need <= 0:
            continue
        u = float(csv_cells.get(csv_k, 0.0))
        extra_val += float(need) * u
        extra_cells += need
    return extra_val, extra_cells


def _event_stats_q14_grid_counts_all_known(raw: Any) -> bool:
    """
    ``raw_pricing.event_stats`` 中 q1–q4 各档占用总格数均已得到（非 None）时，
    可认为已由公共信息划定紫档及此前档位，空置金红估价区间与后期回合一致。
    """
    if not isinstance(raw, dict):
        return False
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return False
    for k in ("q1_grid_count", "q2_grid_count", "q3_grid_count", "q4_grid_count"):
        if st.get(k) is None:
            return False
    return True


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


def _pricing_work_board_snapshot(board_snapshot: Dict[str, Any], items: Dict[str, Any]) -> Dict[str, Any]:
    gs = board_snapshot.get("game_state")
    if not isinstance(gs, dict):
        gs = {}
    gs2 = dict(gs)
    gs2["items"] = items
    out = dict(board_snapshot)
    out["game_state"] = gs2
    return out


def _ahmad_points_from_raw_pricing(raw: Any) -> int:
    """
    由 ``raw_pricing.event_stats`` 简单汇总（与画板快照中该段字段一致）。
    缺失或非数字字段按 0。
    """
    if not isinstance(raw, dict):
        return 0
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return 0

    def _nz(key: str) -> int:
        v = st.get(key)
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    tc = _nz("total_count")
    q4 = _nz("q4_grid_min")
    q5 = _nz("q5_grid_min")
    q6 = _nz("q6_grid_min")
    return tc * 1000 + q4 * 1000 + q5 * 10000 + q6 * 56000


def _item_value_and_footprint(
    it: Dict[str, Any],
    *,
    board_snapshot: Dict[str, Any],
    csv_index: Dict[int, Any],
    csv_items: List[Any],
    csv_cells_raw: Dict[str, float],
    map_id_normalized: Optional[int],
    map_category_weights: Dict[int, float],
) -> Tuple[float, float]:
    if not it.get("box_id_confirmed"):
        return 0.0, 0.0
    bid_raw = it.get("box_id")
    if bid_raw is None:
        return 0.0, 0.0
    try:
        int(bid_raw)
    except (TypeError, ValueError):
        return 0.0, 0.0

    cid_raw = it.get("item_cid")
    try:
        item_cid_i = int(cid_raw) if cid_raw is not None else None
    except (TypeError, ValueError):
        item_cid_i = None
    price_raw = it.get("price")
    if item_cid_i is not None and price_raw is not None:
        try:
            return float(price_raw), float(_shape_area_from_item(it))
        except (TypeError, ValueError):
            pass

    q_raw = it.get("quality")
    try:
        q = int(q_raw) if q_raw is not None else None
    except (TypeError, ValueError):
        q = None

    sh = _parse_shape_int(it.get("shape"))
    cats = _int_set_from_field(it.get("categories"))
    excl_q = _int_set_from_field(it.get("excluded_qualities"))
    excl_c = _int_set_from_field(it.get("excluded_categories"))

    best, count, unique, est, _label = query_item(
        sh,
        q,
        cats,
        item_cid_i,
        csv_index,
        csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
        max_shape_wh=None,
        map_category_weights=map_category_weights if map_category_weights else None,
        map_id=map_id_normalized,
    )
    if best is None or count == 0:
        return 0.0, 0.0

    if unique:
        val = float(best.base_value)
    else:
        w_est = est
        if w_est is None and csv_items:
            cand = list(csv_items)
            if sh is not None:
                cand = [i for i in cand if i.shape == sh]
            if q is not None:
                cand = [i for i in cand if i.quality == q]
            if excl_q:
                cand = [i for i in cand if i.quality not in excl_q]
            if cats:
                wc = [i for i in cand if all(c in i.category_tags for c in cats)]
                if wc:
                    cand = wc
            if excl_c:
                cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
            w_est = _weighted_est_price(cand, map_category_weights or None, map_id_normalized)
        val = float(w_est) if w_est is not None else float(best.base_value)

    fp = _footprint_cells(it, board_snapshot, csv_cells_raw, map_id_normalized)
    return val, fp


def _sum_known_contour_weighted_price_and_geo_cells(
    board_snapshot: Dict[str, Any],
    *,
    csv_cells_raw: Dict[str, float],
) -> Tuple[float, int]:
    """
    已知轮廓（``shape`` 非空）且 ``query_item`` 为多候选（权重价）的物品：

    返回 ``(sum(权重价), sum(几何格数))``，用于空置边际扩容并从 ``points`` 基底扣除权重价。
    """
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict(board_snapshot)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0, 0
    weights = map_category_ratios(mid) or {}
    sum_val = 0.0
    sum_geo = 0
    for _uid, it in items.items():
        if not isinstance(it, dict):
            continue
        if not it.get("box_id_confirmed"):
            continue
        bid_raw = it.get("box_id")
        if bid_raw is None:
            continue
        try:
            int(bid_raw)
        except (TypeError, ValueError):
            continue

        sh = _parse_shape_int(it.get("shape"))
        if sh is None:
            continue

        cid_raw = it.get("item_cid")
        try:
            item_cid_i = int(cid_raw) if cid_raw is not None else None
        except (TypeError, ValueError):
            item_cid_i = None
        price_raw = it.get("price")
        if item_cid_i is not None and price_raw is not None:
            continue

        q_raw = it.get("quality")
        try:
            q = int(q_raw) if q_raw is not None else None
        except (TypeError, ValueError):
            q = None

        cats = _int_set_from_field(it.get("categories"))
        excl_q = _int_set_from_field(it.get("excluded_qualities"))
        excl_c = _int_set_from_field(it.get("excluded_categories"))

        best, count, unique, est, _label = query_item(
            sh,
            q,
            cats,
            item_cid_i,
            csv_index,
            csv_items,
            excluded_categories=excl_c if excl_c else None,
            excluded_qualities=excl_q if excl_q else None,
            max_shape_wh=None,
            map_category_weights=weights if weights else None,
            map_id=mid_n,
        )
        if best is None or count == 0 or unique:
            continue

        w_est = est
        if w_est is None and csv_items:
            cand = list(csv_items)
            cand = [i for i in cand if i.shape == sh]
            if q is not None:
                cand = [i for i in cand if i.quality == q]
            if excl_q:
                cand = [i for i in cand if i.quality not in excl_q]
            if cats:
                wc = [i for i in cand if all(c in i.category_tags for c in cats)]
                if wc:
                    cand = wc
            if excl_c:
                cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
            w_est = _weighted_est_price(cand, weights if weights else None, mid_n)
        val = float(w_est) if w_est is not None else float(best.base_value)

        w, h = _shape_wh_from_snapshot(sh)
        geo = max(1, int(w) * int(h))
        sum_val += val
        sum_geo += geo
    return sum_val, sum_geo


def _shape_area_from_item(it: Dict[str, Any]) -> int:
    sh = _parse_shape_int(it.get("shape"))
    if sh is not None:
        w, h = _shape_wh_from_snapshot(sh)
        return max(1, w * h)
    return 1


def _footprint_cells(
    it: Dict[str, Any],
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Dict[str, float],
    map_id_normalized: Optional[int],
) -> float:
    sh = _parse_shape_int(it.get("shape"))
    if sh is not None:
        w, h = _shape_wh_from_snapshot(sh)
        return float(max(1, w * h))
    q_raw = it.get("quality")
    try:
        q = int(q_raw) if q_raw is not None else None
    except (TypeError, ValueError):
        q = None
    if q is not None and 1 <= q <= 6:
        wcells = _unknown_value.weighted_cell_equiv_for_unknown_contour_item(
            it, board_snapshot, csv_cells_raw or None, {}, map_id_normalized
        )
        if wcells is not None and wcells > 0:
            return float(wcells)
    return 1.0


def estimate_snapshot_item_price(
    it: Dict[str, Any],
    *,
    board_snapshot: Dict[str, Any],
) -> Optional[float]:
    """单件展示用估价（与画板汇总逻辑同源）。"""
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    raw_block = board_snapshot.get("raw_pricing") if isinstance(board_snapshot, dict) else None
    raw_csv = raw_block.get("csv_quality_groups_avg_per_cell") if isinstance(raw_block, dict) else None
    csv_cells: Dict[str, float] = {}
    if isinstance(raw_csv, dict):
        try:
            csv_cells = {str(k): float(v) for k, v in raw_csv.items()}
        except (TypeError, ValueError):
            csv_cells = {}
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return None
    weights = map_category_ratios(mid) or {}
    v, _fp = _item_value_and_footprint(
        it,
        board_snapshot=board_snapshot,
        csv_index=csv_index,
        csv_items=csv_items,
        csv_cells_raw=csv_cells,
        map_id_normalized=mid_n,
        map_category_weights=weights,
    )
    return v if v > 0 else None


def estimate_snapshot_item_price_for_uid(
    board_snapshot: Dict[str, Any],
    uid: str,
) -> Optional[float]:
    """按 uid 取合并后的物品行再估价（含 ``grid_overlay`` 手动画框与手动确认投影）。"""
    items = _grid_overlay.merged_items_dict(board_snapshot)
    it = items.get(str(uid))
    if not isinstance(it, dict):
        return None
    work = _pricing_work_board_snapshot(board_snapshot, items)
    return estimate_snapshot_item_price(it, board_snapshot=work)


def compute_items_total_and_footprint(
    board_snapshot: Dict[str, Any],
    *,
    csv_cells_raw: Dict[str, float],
) -> Tuple[float, float]:
    """对所有已确认 box 的物品求和：总价与权重占位（格）。"""
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict(board_snapshot)
    work = _pricing_work_board_snapshot(board_snapshot, items)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0, 0.0
    weights = map_category_ratios(mid) or {}
    total = 0.0
    footprint = 0.0
    for _uid, it in items.items():
        if not isinstance(it, dict):
            continue
        v, fp = _item_value_and_footprint(
            it,
            board_snapshot=work,
            csv_index=csv_index,
            csv_items=csv_items,
            csv_cells_raw=csv_cells_raw,
            map_id_normalized=mid_n,
            map_category_weights=weights,
        )
        total += v
        footprint += fp
    return total, footprint


def build_snapshot_pricing_dict(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    组装 ``board_snapshot.json`` 的 ``pricing`` 字段。

    从 ``board_snapshot`` 合并后的有效物品表（``game_state.items`` + ``grid_overlay``）
    计算 ``total``（不做外部覆盖）。
    有效空置 ``pricing.vacant`` 与快照 ``grid_overlay.vacant`` 同源，由
    :func:`grid_overlay.vacant_dict_from_board_snapshot` / :func:`grid_overlay.compute_overlay_vacant_dict`
    统一计算；占位格优先 ``grid_overlay.occupied_cell_bids``。
    """
    game_state_json = board_snapshot.get("game_state") or {}
    skill_logs = list(board_snapshot.get("skill_logs") or [])
    map_id = int(board_snapshot.get("map_id") or (game_state_json.get("map_id") or 0))
    cr = board_snapshot.get("current_round")
    if cr is None:
        cr = game_state_json.get("current_round")
    current_round = int(cr or 1)
    raw = board_snapshot.get("raw_pricing")
    if not isinstance(raw, dict):
        from .raw_pricing import build_raw_pricing_dict

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

    raw_csv_cells = raw.get("csv_quality_groups_avg_per_cell") if isinstance(raw, dict) else None
    if isinstance(raw_csv_cells, dict):
        try:
            csv_cells_for_est = {str(k): float(v) for k, v in raw_csv_cells.items()}
        except (TypeError, ValueError):
            csv_cells_for_est = {}
    else:
        csv_cells_for_est = {}

    computed_total, footprint_sum = compute_items_total_and_footprint(
        snap_full, csv_cells_raw=csv_cells_for_est
    )
    total_f = float(computed_total)

    vb = _grid_overlay.vacant_dict_from_board_snapshot(
        snap_full,
    )
    ec_raw = vb.get("effective_count")
    if ec_raw is None:
        vacant_num = 0
    else:
        try:
            vacant_num = max(0, int(ec_raw))
        except (TypeError, ValueError):
            vacant_num = 0
    geo_raw = vb.get("geometric")
    try:
        vacant_geo = int(geo_raw) if geo_raw is not None else None
    except (TypeError, ValueError):
        vacant_geo = None
    vacant_src = str(vb.get("source") or "")

    u_orange = int(round(float(csv_cells_for_est.get("q5", 0.0))))
    u_gr = int(round(float(csv_cells_for_est.get("q5+q6", 0.0))))
    u_red = int(round(float(csv_cells_for_est.get("q6", 0.0))))

    u_early, qg_early, pq_early = _scan_inference.vacant_early_unit_from_exclusions(
        board_snapshot=snap_full,
        csv_cells_raw=csv_cells_for_est if csv_cells_for_est else None,
        pricing={},
    )

    st_ev = raw.get("event_stats") if isinstance(raw, dict) else None
    cq4, cq5, cq6 = _confirmed_tier_footprint_q456(snap_full, csv_cells_raw=csv_cells_for_est)
    tier_extra_val, tier_extra_cells = _tier_min_extra_value_and_cells(
        st_ev,
        confirmed_q4=cq4,
        confirmed_q5=cq5,
        confirmed_q6=cq6,
        csv_cells=csv_cells_for_est,
    )
    kcw_val, kcw_geo = _sum_known_contour_weighted_price_and_geo_cells(
        snap_full, csv_cells_raw=csv_cells_for_est
    )
    vacant_adj = max(0, int(vacant_num) + int(kcw_geo) - int(tier_extra_cells))
    vacant_pts_base = float(total_f) - float(kcw_val) + float(tier_extra_val)

    est_orange = vacant_pts_base + float(vacant_adj) * float(u_orange)
    est_gold_red = vacant_pts_base + float(vacant_adj) * float(u_gr)
    est_red = vacant_pts_base + float(vacant_adj) * float(u_red)

    q14_grid_known = _event_stats_q14_grid_counts_all_known(raw)
    if not q14_grid_known:
        pts = vacant_pts_base + float(vacant_adj) * float(u_early)
        pts_floor = pts
        pts_ceiling = pts
    else:
        pts = vacant_pts_base + float(vacant_adj) * float(u_early)
        pts_floor = vacant_pts_base + float(vacant_adj) * float(u_orange)
        pts_ceiling = vacant_pts_base + float(vacant_adj) * float(u_red)

    ahmad_points = _ahmad_points_from_raw_pricing(raw)

    pricing: Dict[str, Any] = {
        "total": float(total_f),
        "points": int(round(pts)),
        "points_floor": int(round(pts_floor)),
        "points_ceiling": int(round(pts_ceiling)),
        "vacant": int(vacant_num),
        "est_orange": int(round(est_orange)),
        "est_gold_red": int(round(est_gold_red)),
        "est_red": int(round(est_red)),
        "vacant_unit_all_orange": u_orange,
        "vacant_unit_gold_red": u_gr,
        "vacant_unit_all_red": u_red,
        "vacant_geometric": vacant_geo,
        "vacant_effective_count": int(vacant_num),
        "footprint_cells_weighted": float(footprint_sum),
        "vacant_source": vacant_src,
        "early_vacant_unit_from_scan": int(u_early),
        "early_vacant_csv_group": str(qg_early or ""),
        "early_vacant_possible_qualities": sorted(int(x) for x in pq_early),
        "map_quality_avg_hit": bool(csv_cells_for_est),
        "map_quality_avg_csv": str(raw.get("map_quality_avg_csv") or "") if isinstance(raw, dict) else "",
        "ahmad_points": int(ahmad_points),
        "known_contour_weighted_cells": int(kcw_geo),
        "known_contour_weighted_price": float(kcw_val),
    }
    return pricing
