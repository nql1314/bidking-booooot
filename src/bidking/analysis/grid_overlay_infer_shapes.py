"""未知轮廓物品的几何推断（``grid_overlay.infer_shapes``）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from ._shape_wh import shape_wh_from_snapshot
from .grid_overlay_dims import GRID_COLS, GRID_ROWS, _INFER_DEFAULT_PRICE_BAND_REL
from .grid_overlay_item_merge import _load_item_prices_db
from .grid_overlay_vacant_zone import _live_shape_wh


def _event_stats_q14_grid_counts_all_known(raw: Any) -> bool:
    """与 :func:`bidking.analysis.raw_pricing.event_stats_q12_q3_q4_grids_all_known` 一致（避免重复实现）。"""
    from .raw_pricing import event_stats_q12_q3_q4_grids_all_known

    return event_stats_q12_q3_q4_grids_all_known(raw)


def _infer_q1234_scan_and_q14_contours_ready(
    state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
) -> bool:
    """品质 1–4 的全量扫描均已发生，且场上 Q1–Q4 物品轮廓与锚格均已可靠锁定。"""
    hist = getattr(state, "_scan_history", []) or []
    need = {1, 2, 3, 4}
    seen: Set[int] = set()
    for ent in hist:
        if not ent or len(ent) < 2:
            continue
        stype, val = ent[0], ent[1]
        if stype == "quality":
            try:
                vi = int(val)
            except (TypeError, ValueError):
                continue
            if vi in need:
                seen.add(vi)
    if seen < need:
        return False
    for uid, k in state.items.items():
        q = k.quality
        if q is None:
            continue
        try:
            qi = int(q)
        except (TypeError, ValueError):
            continue
        if qi not in (1, 2, 3, 4):
            continue
        if k.box_id is None:
            continue
        su = str(uid)
        if k.shape is None and su not in manual_shapes:
            return False
        if not k.box_id_confirmed and su not in manual_shapes:
            return False
    return True


def _infer_rect_feasible(
    r1: int,
    c1: int,
    r2: int,
    c2: int,
    occupied: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> bool:
    """矩形内每格：不超 ``max_bid``、不在 ``suppress``、不在 ``occupied``。"""
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            if r * GRID_COLS + c > max_bid:
                return False
            if (r, c) in occupied:
                return False
            if (r, c) in suppress:
                return False
    return True


def _infer_pseudo_blocked(
    baseline_occ: Set[Tuple[int, int]],
    inferred_occ: Set[Tuple[int, int]],
    self_base: Set[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    """
    推断可行性用的阻挡格：先前几何推断占用的格 **并上** 基底占位里「非当前物品」的格。

    当前物品仅可在矩形内覆盖 ``self_base``（通常为自身锚格）；已被他人推断盖住的 ``self_base`` 格
    落在 ``inferred_occ`` 中，不得再放置。
    """
    return inferred_occ | (baseline_occ - self_base)


def _infer_pick_wh_from_candidates(
    candidates: List[Any],
    map_category_weights: Optional[Dict[int, float]],
    map_id_n: Optional[int],
) -> Optional[Tuple[int, int]]:
    """
    多候选时：先在权重期望价 ±:data:`_INFER_DEFAULT_PRICE_BAND_REL` 价带内的候选中取掉落概率最高者；
    价带内无候选（或无法得到正期望价）时，回退为在全候选中按概率选优（概率相同则价更接近期望、再 ``item_id``）。
    """
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
        band = _INFER_DEFAULT_PRICE_BAND_REL
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


def _infer_ordered_wh_for_default_infer(
    filt: List[Any],
    map_category_weights: Optional[Dict[int, float]],
    map_id_n: Optional[int],
) -> List[Tuple[int, int]]:
    """
    默认推断路径下依次尝试的 ``(w,h)``：
    先 :func:`_infer_pick_wh_from_candidates`，再按各外形对应候选的最高掉落概率降序尝试其余外形。
    """
    primary = _infer_pick_wh_from_candidates(filt, map_category_weights, map_id_n)
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


def _infer_free_cells_in_prefix(
    pseudo_blocked: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Set[Tuple[int, int]]:
    """``max_box_id`` 前缀区内、未被阻挡且未手动画板抑制的格。"""
    free: Set[Tuple[int, int]] = set()
    mx = int(max_bid)
    for bid in range(mx + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if (r, c) in pseudo_blocked or (r, c) in suppress:
            continue
        free.add((r, c))
    return free


def _infer_connected_free_region(
    ar: int,
    ac: int,
    free: Set[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    """与 ``(ar,ac)`` 四连通的 ``free`` 子集；锚不在 ``free`` 时返回空集。"""
    seed = (int(ar), int(ac))
    if seed not in free:
        return set()
    region: Set[Tuple[int, int]] = {seed}
    queue: List[Tuple[int, int]] = [seed]
    while queue:
        r, c = queue.pop()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            cell = (r + dr, c + dc)
            if cell in free and cell not in region:
                region.add(cell)
                queue.append(cell)
    return region


def _infer_solid_rectangle_bbox(
    cells: Set[Tuple[int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    """
    若 ``cells`` 恰为实心矩形，返回 ``(w, h, dc, dr)``（列宽、行高、顶左列、顶左行）；否则 ``None``。
    """
    if not cells:
        return None
    rows = [r for r, _ in cells]
    cols = [c for _, c in cells]
    min_r, max_r = min(rows), max(rows)
    min_c, max_c = min(cols), max(cols)
    h = max_r - min_r + 1
    w = max_c - min_c + 1
    if len(cells) != w * h:
        return None
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            if (r, c) not in cells:
                return None
    return (w, h, min_c, min_r)


def _infer_try_q56_rectangular_vacant_fill(
    ar: int,
    ac: int,
    *,
    box_id_confirmed: bool,
    cand_wh: Set[Tuple[int, int]],
    pseudo_blocked: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Optional[Tuple[int, int, int, int]]:
    """
    锚点所在四连通空置区为完整矩形、且 CSV 候选含该区 ``(w,h)`` 时，直接以该区外接矩形占领。

    ``box_id_confirmed`` 时顶左须为 ``(ar,ac)``；未确认时顶左为外接矩形左上角（锚必落在矩形内）。
    """
    free = _infer_free_cells_in_prefix(pseudo_blocked, suppress, max_bid)
    region = _infer_connected_free_region(ar, ac, free)
    if not region:
        return None
    bbox = _infer_solid_rectangle_bbox(region)
    if bbox is None:
        return None
    w, h, dc, dr = bbox
    if (w, h) not in cand_wh:
        return None
    if box_id_confirmed and (dr != ar or dc != ac):
        return None
    if not box_id_confirmed and not (dr <= ar < dr + h and dc <= ac < dc + w):
        return None
    if not _infer_rect_feasible(dr, dc, dr + h - 1, dc + w - 1, pseudo_blocked, suppress, max_bid):
        return None
    return (w, h, dr, dc)


def _q56_overlay_wh_sort_key(wh: Tuple[int, int]) -> Tuple[int, int, float, int, int]:
    """
    金红 ``use_rect_q56`` 路径下 ``(w,h)`` 的尝试顺序（升序 = 优先）。

    在面积基础上兼顾外形：同面积时更「方」的矩形优先于 ``1×n`` / ``n×1`` 长条；
    且 ``min(w,h)==1`` 且 ``max(w,h) > 4`` 的长条整段置后。
    """
    w, h = int(wh[0]), int(wh[1])
    a = w * h
    lo, hi = (w, h) if w <= h else (h, w)
    long_line = 1 if lo == 1 and hi > 4 else 0
    aspect_pen = (hi / lo) - 1.0 if lo > 0 else float("inf")
    return (long_line, -a, aspect_pen, w, h)


def _infer_unknown_contour_item_eligible(
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


def _infer_base_occupied_cells_for_uid(
    uid: str,
    k: ItemKnowledge,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
) -> Set[Tuple[int, int]]:
    """
    该 uid 在 infer 基底占位图中贡献的格（与 :func:`build_occupied_cells` 对该件物品的规则一致）。

    未确认物品仅占锚格；已确认且无 ``shape`` 时此处按 ``_live_shape_wh(None)`` → 1×1（与仅日志外形未知时 UI 默认一致）。
    可行性检测须从 ``occupied_cells`` 中去掉本集合，否则推断矩形含锚格时会与「自身占位」永远冲突。
    """
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


def _infer_default_placement_candidates(
    ar: int,
    ac: int,
    w: int,
    h: int,
    *,
    box_id_confirmed: bool,
) -> List[Tuple[int, int]]:
    """
    默认推断路径下矩形左上角 ``(dr, dc)``（行、列）候选。

    ``box_id_confirmed=True`` 时 BoxId 为顶左格，仅 ``(ar, ac)``；
    否则 BoxId 仅为占格内某一命中格（见 :class:`ItemKnowledge`），枚举所有使 ``(ar,ac)``
    落在 ``w×h`` 矩形内的顶左，按 ``(dr, dc)`` 字典序优先以便稳定输出。
    """
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


def compute_grid_overlay_infer_shapes(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    occupied_cells: Set[Tuple[int, int]],
    vacant_manual_suppress: Set[Tuple[int, int]],
    max_box_id: int,
    raw_pricing: Dict[str, Any],
    infer_unknown_contour_shapes: bool = True,
) -> Dict[str, List[int]]:
    """
    对 **品质已知、轮廓未知** 且未手动画框的日志物品，估计 ``[w,h,dc,dr]``（与 ``manual_shapes`` 同形）。

    ``infer_unknown_contour_shapes=False`` 时（可由 ``configs`` 里 ``pricing.infer_unknown_contour_shapes`` 关闭）
    不读价库、不做推断，返回 ``{}``；``occupied_cells`` 保持为传入的基底占位（与有推断时最终不含推断格的效果一致）。

    - 默认：在权重期望价 ±20% 价带内的 CSV 候选中取掉落概率最高者定 ``(w,h)``；
      价带为空时回退为全候选按概率。
      **原点**：``box_id_confirmed`` 时 BoxId 即顶左；**未确认** 时 BoxId 仅为占格内某一命中格，
      枚举所有包含该格的 ``w×h`` 顶左位置，再按阻挡约束取可行解（``(dr,dc)`` 字典序优先）。
      矩形须完全落在 ``max_box_id`` 前缀区内，且不与 ``vacant_manual_suppress`` 相交；
      与其它物品的冲突：基底占位中他人的锚格/已确认格 **以及** 本轮中先前物品已推断出的矩形并集；
      仅允许覆盖当前物品自身的基底占位格（通常为锚格），但若该格已被先前推断占用则不可再放。
      首选外形不满足时按掉落概率依次尝试其余候选外形，仍无解则跳过该件推断。
    - 当 ``raw_pricing.event_stats`` 中低档总格 **q12+q3+q4** 齐备（或 ``q1+q2+q3+q4`` 等价已知），且扫描史已覆盖品质
      1–4、场上 Q1–Q4 物品轮廓与锚格均已锁定时：对 **金 (5)、红 (6)** 在已有 CSV 候选（与默认路径相同的 ``filter_csv_candidates_for_query`` 结果非空）前提下，
      **优先**：锚点四连通空置区（相对当前 ``pseudo_blocked`` / 手动画板抑制 / ``max_box_id`` 前缀，无其它物品占位）若恰为实心矩形且候选含该区 ``(w,h)``，则直接以该外接矩形占领；
      否则将候选去重为 ``(w,h)`` 集合，再按 **面积与长宽比综合**（更大面积优先；同面积时更偏方块优先于 ``1×n``/``n×1`` 长条；``1×n``/``n×1`` 且 ``n>4`` 的长条整段置后；再 ``(w,h)`` 字典序稳定）在阻挡语义与 ``max_box_id`` 下尝试放置（与默认路径相同的 ``box_id_confirmed`` 顶左/枚举规则），
      取 **首个可行** 者；若均不可行则跳过该件（与低档件无解时一致）。
      金优先于红；每推断成功一件即将其矩形并入后续件的阻挡集。
    """
    if not infer_unknown_contour_shapes:
        base = set(occupied_cells)
        occupied_cells.clear()
        occupied_cells.update(base)
        return {}
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return {}
    mid_raw = int(game_state.map_id or 0) or None
    mid_n = item_db.normalize_map_id(mid_raw)
    map_w = item_db.map_category_ratios(mid_raw) if mid_raw else None
    if not map_w:
        map_w = None

    use_rect_q56 = _event_stats_q14_grid_counts_all_known(raw_pricing) and _infer_q1234_scan_and_q14_contours_ready(
        game_state, manual_shapes
    )
    sup = set(vacant_manual_suppress)
    mx = int(max_box_id)
    baseline_occ: Set[Tuple[int, int]] = set(occupied_cells)
    inferred_occ: Set[Tuple[int, int]] = set()

    targets: List[Tuple[str, ItemKnowledge, int]] = []
    for uid, k in game_state.items.items():
        if not _infer_unknown_contour_item_eligible(k, uid, manual_shapes):
            continue
        try:
            q = int(k.quality or 0)
        except (TypeError, ValueError):
            continue
        targets.append((str(uid), k, q))

    def _sort_key(t: Tuple[str, ItemKnowledge, int]) -> Tuple[Any, ...]:
        u, k, qq = t
        bid = int(k.box_id or 0)
        if use_rect_q56 and qq == 5:
            return (0, bid, u)
        if use_rect_q56 and qq == 6:
            return (1, bid, u)
        return (2, qq, bid, u)

    targets.sort(key=_sort_key)
    out: Dict[str, List[int]] = {}
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
        self_base = _infer_base_occupied_cells_for_uid(uid, k, manual_shapes)
        pseudo_blocked = _infer_pseudo_blocked(baseline_occ, inferred_occ, self_base)
        if use_rect_q56 and q in (5, 6):
            confirmed_tl = bool(getattr(k, "box_id_confirmed", False))
            cand_wh: Set[Tuple[int, int]] = set()
            for c in filt:
                wh = shape_wh_from_snapshot(c.shape)
                cand_wh.add(wh)
            ordered_wh = sorted(cand_wh, key=_q56_overlay_wh_sort_key)
            chosen_q56 = _infer_try_q56_rectangular_vacant_fill(
                ar,
                ac,
                box_id_confirmed=confirmed_tl,
                cand_wh=cand_wh,
                pseudo_blocked=pseudo_blocked,
                suppress=sup,
                max_bid=mx,
            )
            if chosen_q56 is None:
                for w, h in ordered_wh:
                    for dr, dc in _infer_default_placement_candidates(
                        ar, ac, w, h, box_id_confirmed=confirmed_tl
                    ):
                        if _infer_rect_feasible(dr, dc, dr + h - 1, dc + w - 1, pseudo_blocked, sup, mx):
                            chosen_q56 = (w, h, dr, dc)
                            break
                    if chosen_q56 is not None:
                        break
            if chosen_q56 is None:
                continue
            w, h, dr, dc = chosen_q56
            out[uid] = [w, h, int(dc), int(dr)]
            for ddr in range(h):
                for ddc in range(w):
                    inferred_occ.add((dr + ddr, dc + ddc))
        else:
            confirmed_tl = bool(getattr(k, "box_id_confirmed", False))
            chosen_tpl: Optional[Tuple[int, int, int, int]] = None
            for w, h in _infer_ordered_wh_for_default_infer(filt, map_w, mid_n):
                for dr, dc in _infer_default_placement_candidates(
                    ar, ac, w, h, box_id_confirmed=confirmed_tl
                ):
                    if _infer_rect_feasible(dr, dc, dr + h - 1, dc + w - 1, pseudo_blocked, sup, mx):
                        chosen_tpl = (w, h, dr, dc)
                        break
                if chosen_tpl is not None:
                    break
            if chosen_tpl is None:
                continue
            w, h, dr, dc = chosen_tpl
            out[uid] = [w, h, int(dc), int(dr)]
            for ddr in range(h):
                for ddc in range(w):
                    inferred_occ.add((dr + ddr, dc + ddc))
    occupied_cells.clear()
    occupied_cells.update(baseline_occ)
    occupied_cells.update(inferred_occ)
    return out
