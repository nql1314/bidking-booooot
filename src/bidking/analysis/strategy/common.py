# -*- coding: utf-8 -*-
"""画板快照定价流水线公共辅助（非角色专用）。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Set, Tuple

from .. import grid_overlay as _grid_overlay
from .. import scan_inference as _scan_inference
from .. import unknown_value as _unknown_value
from .._shape_wh import shape_wh_from_snapshot
from ...logsys.perf_log import perf_log_elapsed

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


def event_stat_q4_grid_avg_optional(st: Any) -> Optional[float]:
    if not isinstance(st, dict):
        return None
    v = st.get("q4_grid_avg")
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def scan_q123_all_revealed(board_snapshot: Dict[str, Any]) -> bool:
    hits = _scan_inference.quality_scan_hit_uids_by_value(board_snapshot)
    return all(q in hits for q in (1, 2, 3))


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
    q4_grid_min = event_stat_grid_min_optional(event_stats, "q4_grid_min")
    if (
        scan_q123_all_revealed(board_snapshot)
        and event_stat_q4_grid_avg_optional(event_stats) is not None
        and q4_grid_min is not None
        and q4_grid_min > 10
        and 4 in pq0
        and csv_cells_for_est
    ):
        u456 = csv_cells_for_est.get("q4+q5+q6")
        u56 = csv_cells_for_est.get("q5+q6")
        if u456 is not None and u56 is not None:
            u = int(round((float(u456) + float(u56)) / 2))
            perf_log_elapsed("_vacant_early_unit_q4_min_blend (adjusted)", t0)
            return u, "q4+q5+q6~q5+q6", pq0
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
) -> Tuple[float, int]:
    if not isinstance(event_stats, dict):
        return 0.0, 0
    extra_val = 0.0
    extra_cells = 0
    for min_k, csv_k, confirmed in (
        ("q4_grid_min", "q4", confirmed_q4),
        ("q5_grid_min", "q5", confirmed_q5),
        ("q6_grid_min", "q6", confirmed_q6),
    ):
        m = event_stat_grid_min_optional(event_stats, min_k)
        if m is None:
            continue
        need = int(m) - int(confirmed)
        if need <= 0:
            continue
        u = float(csv_cells.get(csv_k, 0.0))
        extra_val += float(need) * u
        extra_cells += need
    return extra_val, extra_cells


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


def sum_known_contour_weighted_price_and_geo_cells(
    board_snapshot: Dict[str, Any],
    *,
    csv_cells_raw: Dict[str, float],
    pricing_shape_int_for_csv,
    load_item_prices_db,
    map_id_from_board_snapshot,
) -> Tuple[float, int]:
    """已知轮廓、品质未知、多候选权重价物品的 (权重价之和, 几何格数之和)。"""
    from ...parsing import item_db
    from ...parsing.item_db import _weighted_est_price, map_category_ratios, query_item

    t0 = time.perf_counter()
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    csv_index, csv_items = load_item_prices_db()
    if not csv_items:
        return 0.0, 0
    weights = map_category_ratios(mid) or {}
    sum_val = 0.0
    sum_geo = 0

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

        sh_geo = _parse_shape_int(it.get("shape"))
        if sh_geo is None:
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
        if q is not None:
            continue

        cats = _int_set_from_field(it.get("categories"))
        cats_any = _int_set_from_field(it.get("categories_any"))
        excl_q = _int_set_from_field(it.get("excluded_qualities"))
        excl_c = _int_set_from_field(it.get("excluded_categories"))

        sh_csv = pricing_shape_int_for_csv(it)

        best, count, unique, est, _label = query_item(
            sh_csv,
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
            categories_any=cats_any if cats_any else None,
        )
        if best is None or count == 0 or unique:
            continue

        w_est = est
        if w_est is None and csv_items:
            cand = list(csv_items)
            if sh_csv is not None:
                cand = [i for i in cand if i.shape == sh_csv]
            if q is not None:
                cand = [i for i in cand if i.quality == q]
            if excl_q:
                cand = [i for i in cand if i.quality not in excl_q]
            if cats:
                wc = [i for i in cand if all(c in i.category_tags for c in cats)]
                if wc:
                    cand = wc
            if cats_any:
                wa = [i for i in cand if cats_any.intersection(i.category_tags)]
                if wa:
                    cand = wa
            if excl_c:
                cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
            w_est = _weighted_est_price(cand, weights if weights else None, mid_n)
        val = float(w_est) if w_est is not None else float(best.base_value)

        w, h = shape_wh_from_snapshot(sh_geo)
        geo = max(1, int(w) * int(h))
        sum_val += val
        sum_geo += geo
    perf_log_elapsed("sum_known_contour_weighted_price_and_geo_cells", t0)
    return sum_val, sum_geo


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
