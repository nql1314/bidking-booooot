"""未知轮廓日志物品轮廓推断：权重价合理外形（早期）与金红阶段由 merge_expand 接管。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from ._shape_wh import shape_wh_from_snapshot
from .grid_overlay_dims import (
    GRID_COLS,
    GRID_ROWS,
    INFER_DEFAULT_PRICE_BAND_REL,
    rect_cells_wh,
)
from .grid_overlay_item_merge import _load_item_prices_db
from .grid_overlay_vacant_zone import _live_shape_wh


def use_aggressive_unknown_contour_log_expand(raw_pricing: Dict[str, Any]) -> bool:
    """低档总格（q12+q3+q4）齐备时：日志轮廓用 merge_expand 尽量扩；否则用权重价单次选形。"""
    from .strategy.common import event_stats_q14_grid_counts_all_known

    return event_stats_q14_grid_counts_all_known(raw_pricing)


def _log_item_eligible(
    k: ItemKnowledge,
    uid: str,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
) -> bool:
    if uid in manual_shapes:
        return False
    if k.shape is not None:
        return False
    if k.box_id is None:
        return False
    if k.quality is None:
        return False
    try:
        q = int(k.quality)
    except (TypeError, ValueError):
        return False
    if not (1 <= q <= 6):
        return False
    if k.item_cid is not None and k.price is not None:
        return False
    return True


def _rect_feasible(
    r1: int,
    c1: int,
    r2: int,
    c2: int,
    occupied: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> bool:
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            if r * GRID_COLS + c > max_bid:
                return False
            if (r, c) in occupied:
                return False
            if (r, c) in suppress:
                return False
    return True


def _pseudo_blocked(
    baseline_occ: Set[Tuple[int, int]],
    inferred_occ: Set[Tuple[int, int]],
    self_base: Set[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    return inferred_occ | (baseline_occ - self_base)


def _base_occupied_cells_for_uid(
    uid: str,
    k: ItemKnowledge,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
) -> Set[Tuple[int, int]]:
    bid = getattr(k, "box_id", None)
    if bid is None:
        return set()
    try:
        ib = int(bid)
    except (TypeError, ValueError):
        return set()
    dc = ib % GRID_COLS
    dr = ib // GRID_COLS
    suid = str(uid)
    out: Set[Tuple[int, int]] = set()
    if suid in manual_shapes:
        w, h, dc_m, dr_m = manual_shapes[suid]
        for ddr in range(h):
            for ddc in range(w):
                out.add((dr_m + ddr, dc_m + ddc))
        return out
    if getattr(k, "box_id_confirmed", False):
        w, h = _live_shape_wh(getattr(k, "shape", None))
        for ddr in range(h):
            for ddc in range(w):
                out.add((dr + ddr, dc + ddc))
        return out
    out.add((dr, dc))
    return out


def _placement_candidates(
    ar: int,
    ac: int,
    w: int,
    h: int,
    *,
    box_id_confirmed: bool,
) -> List[Tuple[int, int]]:
    if box_id_confirmed:
        return [(ar, ac)]
    opts: List[Tuple[int, int]] = []
    for dr in range(ar - h + 1, ar + 1):
        for dc in range(ac - w + 1, ac + 1):
            if dr < 0 or dc < 0:
                continue
            if dr + h > GRID_ROWS or dc + w > GRID_COLS:
                continue
            opts.append((dr, dc))
    opts.sort(key=lambda t: (t[0], t[1]))
    return opts


def _pick_wh_from_candidates(
    candidates: List[Any],
    map_category_weights: Optional[Dict[int, float]],
    map_id_n: Optional[int],
) -> Optional[Tuple[int, int]]:
    if not candidates:
        return None
    if len(candidates) == 1:
        return shape_wh_from_snapshot(candidates[0].shape)
    est = item_db._weighted_est_price(candidates, map_category_weights, map_id_n)
    probs = item_db.candidate_probabilities(candidates, map_category_weights, map_id_n)

    def _pick_best(pool: List[Any]) -> Any:
        best_c: Any = None
        best_key: Optional[Tuple[float, float, int]] = None
        for c in pool:
            p = float(probs.get(c.item_id, 0.0))
            dist = (
                abs(float(c.base_value) - float(est))
                if est is not None and float(est) > 0
                else 0.0
            )
            key = (-p, dist, int(c.item_id))
            if best_key is None or key < best_key:
                best_key = key
                best_c = c
        return best_c

    if est is not None and float(est) > 0:
        e = float(est)
        band = INFER_DEFAULT_PRICE_BAND_REL
        lo, hi = e * (1.0 - band), e * (1.0 + band)
        in_band = [c for c in candidates if lo <= float(c.base_value) <= hi]
        if in_band:
            best = _pick_best(in_band)
            if best is not None:
                return shape_wh_from_snapshot(best.shape)

    best = _pick_best(candidates)
    if best is None:
        return None
    return shape_wh_from_snapshot(best.shape)


def _ordered_wh_for_infer(
    filt: List[Any],
    map_category_weights: Optional[Dict[int, float]],
    map_id_n: Optional[int],
) -> List[Tuple[int, int]]:
    primary = _pick_wh_from_candidates(filt, map_category_weights, map_id_n)
    probs = item_db.candidate_probabilities(filt, map_category_weights, map_id_n)
    by_wh: Dict[Tuple[int, int], float] = {}
    for c in filt:
        wh = shape_wh_from_snapshot(c.shape)
        if wh is None:
            continue
        p = float(probs.get(c.item_id, 0.0))
        by_wh[wh] = max(by_wh.get(wh, 0.0), p)
    ranked = sorted(by_wh.keys(), key=lambda wh: (-by_wh[wh], wh))
    out: List[Tuple[int, int]] = []
    if primary is not None:
        out.append(primary)
    for wh in ranked:
        if wh not in out:
            out.append(wh)
    return out


def infer_unknown_contour_log_shapes_weighted(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    occupied_cells: Set[Tuple[int, int]],
    vacant_manual_suppress: Set[Tuple[int, int]],
    max_box_id: int,
    raw_pricing: Dict[str, Any],
    skip_uids: Optional[Set[str]] = None,
) -> Dict[str, Tuple[int, int, int, int]]:
    """
    品质已知、轮廓未知且未手动画框的日志物品：按 CSV 权重期望价 ±价带选外形，再取首个可行放置。

    金/红在 ``use_aggressive_unknown_contour_log_expand`` 为真时由 merge_expand 处理，此处仍对
    非金红件生效；金红在未走 aggressive 路径时按面积优先尝试（与旧 ``use_rect_q56`` 分支一致）。
    """
    _ = raw_pricing
    skip = {str(u) for u in (skip_uids or set())}
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return {}
    mid_raw = int(game_state.map_id or 0) or None
    mid_n = item_db.normalize_map_id(mid_raw)
    map_w = item_db.map_category_ratios(mid_raw) if mid_raw else None
    if not map_w:
        map_w = None

    aggressive = use_aggressive_unknown_contour_log_expand(
        raw_pricing if isinstance(raw_pricing, dict) else {}
    )
    sup = set(vacant_manual_suppress)
    mx = int(max_box_id)
    baseline_occ: Set[Tuple[int, int]] = set(occupied_cells)
    inferred_occ: Set[Tuple[int, int]] = set()

    targets: List[Tuple[str, ItemKnowledge, int]] = []
    for uid, k in game_state.items.items():
        suid = str(uid)
        if suid in skip:
            continue
        if not _log_item_eligible(k, suid, manual_shapes):
            continue
        try:
            q = int(k.quality or 0)
        except (TypeError, ValueError):
            continue
        if aggressive and q in (5, 6):
            continue
        targets.append((suid, k, q))

    targets.sort(key=lambda t: (int(t[2]), int(t[1].box_id or 0), t[0]))
    out: Dict[str, Tuple[int, int, int, int]] = {}
    for uid, k, q in targets:
        try:
            item_cid_i = int(k.item_cid) if k.item_cid is not None else None
        except (TypeError, ValueError):
            item_cid_i = None
        filt = item_db.filter_csv_candidates_for_query(
            None,
            int(k.quality),
            set(k.categories),
            item_cid_i,
            csv_index,
            csv_items,
            excluded_categories=k.excluded_categories if k.excluded_categories else None,
            excluded_qualities=k.excluded_qualities if k.excluded_qualities else None,
            max_shape_wh=None,
            categories_any=k.categories_any if k.categories_any else None,
        )
        if not filt:
            continue
        bid_i = int(k.box_id)
        ar, ac = bid_i // GRID_COLS, bid_i % GRID_COLS
        self_base = _base_occupied_cells_for_uid(uid, k, manual_shapes)
        pseudo_blocked = _pseudo_blocked(baseline_occ, inferred_occ, self_base)
        confirmed_tl = bool(getattr(k, "box_id_confirmed", False))

        chosen: Optional[Tuple[int, int, int, int]] = None
        for w, h in _ordered_wh_for_infer(filt, map_w, mid_n):
            for dr, dc in _placement_candidates(
                ar, ac, w, h, box_id_confirmed=confirmed_tl
            ):
                if _rect_feasible(
                    dr, dc, dr + h - 1, dc + w - 1, pseudo_blocked, sup, mx
                ):
                    chosen = (w, h, dr, dc)
                    break
            if chosen is not None:
                break

        if chosen is None:
            continue
        w, h, dr, dc = chosen
        out[uid] = (int(w), int(h), int(dc), int(dr))
        for ddr in range(h):
            for ddc in range(w):
                inferred_occ.add((dr + ddr, dc + ddc))

    return out


__all__ = [
    "infer_unknown_contour_log_shapes_weighted",
    "use_aggressive_unknown_contour_log_expand",
]
