"""未知轮廓物品的几何推断（``grid_overlay.infer_shapes``）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from ._shape_wh import shape_wh_from_snapshot
from .grid_overlay_dims import GRID_COLS, GRID_ROWS, AISHA_VACANT_RECT_INFER_ROUND, rect_cells_wh
from .grid_overlay_item_merge import _load_item_prices_db
from .grid_overlay_vacant_zone import _live_shape_wh
from .phantom_pricing_ui_sync import PHANTOM_Q_INFER, phantom_quality_pref_explicit_quality


class InferShapesResult(NamedTuple):
    """``infer_shapes`` 推断结果及被日志物品吸收的品质未定幽灵 uid。"""

    shapes: Dict[str, List[int]]
    absorbed_phantom_uids: frozenset[str]


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


def _infer_restore_occupied_empty(
    occupied_cells: Set[Tuple[int, int]],
) -> InferShapesResult:
    base = set(occupied_cells)
    occupied_cells.clear()
    occupied_cells.update(base)
    return InferShapesResult({}, frozenset())


def _infer_phantom_absorbable(
    puid: str,
    phantom_rects: Mapping[str, Tuple[int, int, int, int]],
    *,
    inferred_occ: Set[Tuple[int, int]],
    rects: Mapping[str, Tuple[int, int, int, int]],
    uid: str,
) -> bool:
    """幽灵须未被先前品质批次推断占用，且未与他件当前推断矩形重叠。"""
    cells = rect_cells_wh(*phantom_rects[str(puid)])
    if cells & inferred_occ:
        return False
    for ouid, rect in rects.items():
        if ouid == uid:
            continue
        if cells & rect_cells_wh(*rect):
            return False
    return True


def _infer_sets_orthogonally_adjacent(
    a: Set[Tuple[int, int]],
    b: Set[Tuple[int, int]],
) -> bool:
    for r, c in a:
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if (r + dr, c + dc) in b:
                return True
    return False


def _infer_anchor_inside_rect(
    ar: int,
    ac: int,
    rect: Tuple[int, int, int, int],
    *,
    box_id_confirmed: bool,
) -> bool:
    w, h, dc, dr = rect
    if box_id_confirmed:
        return int(dr) == int(ar) and int(dc) == int(ac)
    return int(dr) <= int(ar) < int(dr) + int(h) and int(dc) <= int(ac) < int(dc) + int(w)


def _infer_filt_has_shape_wh(filt: List[Any], w: int, h: int) -> bool:
    wh = (int(w), int(h))
    for c in filt:
        cwh = shape_wh_from_snapshot(c.shape)
        if cwh == wh:
            return True
    return False


def _infer_phantom_quality_undetermined(
    uid: str,
    k: ItemKnowledge,
    phantom_quality_pref: Mapping[str, Any],
) -> bool:
    """手画幽灵品质未定时（推断笔或无显式档位）可与日志物品合并扩充。"""
    pref = phantom_quality_pref.get(uid)
    if pref == PHANTOM_Q_INFER:
        return True
    if isinstance(pref, str) and pref.strip() == PHANTOM_Q_INFER:
        return True
    if phantom_quality_pref_explicit_quality(pref) is not None:
        return False
    return k.quality is None


def _infer_undetermined_phantom_peer_rects(
    phantom_items: Mapping[str, ItemKnowledge],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Mapping[str, Any],
) -> Dict[str, Tuple[int, int, int, int]]:
    out: Dict[str, Tuple[int, int, int, int]] = {}
    for uid, k in phantom_items.items():
        suid = str(uid)
        if suid not in manual_shapes:
            continue
        if not _infer_phantom_quality_undetermined(suid, k, phantom_quality_pref):
            continue
        rect = manual_shapes[suid]
        out[suid] = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    return out


def _infer_merge_expand_options(
    ar: int,
    ac: int,
    *,
    box_id_confirmed: bool,
    w: int,
    h: int,
    dc: int,
    dr: int,
    vacant: Set[Tuple[int, int]],
    peer_rects: Mapping[str, Tuple[int, int, int, int]],
    phantom_peer_rects: Mapping[str, Tuple[int, int, int, int]],
) -> List[Tuple[Tuple[int, int, int, int], Set[str], Set[str]]]:
    """
    从当前矩形出发，尝试与一侧空置条带、同品质邻接矩形或品质未定幽灵格合并。
    返回 ``(新矩形, 被吸收的同品质 uid, 被吸收的品质未定幽灵 uid)``。
    """
    cur = rect_cells_wh(w, h, dc, dr)
    opts: List[Tuple[Tuple[int, int, int, int], Set[str], Set[str]]] = []

    def _try_strip(
        edge: Set[Tuple[int, int]],
        new_rect: Tuple[int, int, int, int],
    ) -> None:
        if not edge or not all(cell in vacant for cell in edge):
            return
        if not _infer_anchor_inside_rect(ar, ac, new_rect, box_id_confirmed=box_id_confirmed):
            return
        opts.append((new_rect, set(), set()))

    def _try_peer_union(
        puid: str,
        peer: Tuple[int, int, int, int],
        *,
        as_phantom: bool,
    ) -> None:
        pw, ph, pdc, pdr = peer
        pcells = rect_cells_wh(pw, ph, pdc, pdr)
        if not _infer_sets_orthogonally_adjacent(cur, pcells):
            return
        bbox = _infer_solid_rectangle_bbox(cur | pcells)
        if bbox is None:
            return
        if not _infer_anchor_inside_rect(ar, ac, bbox, box_id_confirmed=box_id_confirmed):
            return
        if as_phantom:
            opts.append((bbox, set(), {str(puid)}))
        else:
            opts.append((bbox, {str(puid)}, set()))

    if int(dc) + int(w) < GRID_COLS:
        _try_strip(
            {(r, int(dc) + int(w)) for r in range(int(dr), int(dr) + int(h))},
            (int(w) + 1, int(h), int(dc), int(dr)),
        )
    if int(dc) > 0:
        _try_strip(
            {(r, int(dc) - 1) for r in range(int(dr), int(dr) + int(h))},
            (int(w) + 1, int(h), int(dc) - 1, int(dr)),
        )
    if int(dr) + int(h) < GRID_ROWS:
        _try_strip(
            {(int(dr) + int(h), c) for c in range(int(dc), int(dc) + int(w))},
            (int(w), int(h) + 1, int(dc), int(dr)),
        )
    if int(dr) > 0:
        _try_strip(
            {(int(dr) - 1, c) for c in range(int(dc), int(dc) + int(w))},
            (int(w), int(h) + 1, int(dc), int(dr) - 1),
        )

    for puid, peer in peer_rects.items():
        _try_peer_union(puid, peer, as_phantom=False)

    for puid, peer in phantom_peer_rects.items():
        _try_peer_union(puid, peer, as_phantom=True)

    return opts


def _infer_merge_rect_feasible(
    new_rect: Tuple[int, int, int, int],
    *,
    uid: str,
    absorbed_uids: Set[str],
    absorbed_phantom_uids: Set[str],
    phantom_rects: Mapping[str, Tuple[int, int, int, int]],
    rects: Mapping[str, Tuple[int, int, int, int]],
    anchors: Mapping[str, Tuple[int, int]],
    baseline_occ: Set[Tuple[int, int]],
    inferred_occ: Set[Tuple[int, int]],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    items_by_uid: Mapping[str, ItemKnowledge],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> bool:
    w, h, dc, dr = new_rect
    new_cells = rect_cells_wh(w, h, dc, dr)
    blocked = set(baseline_occ) | set(inferred_occ)
    for ouid, rect in rects.items():
        if ouid == uid or ouid in absorbed_uids:
            continue
        blocked |= rect_cells_wh(*rect)
    for puid in absorbed_uids:
        ar_p, ac_p = anchors[str(puid)]
        blocked.add((int(ar_p), int(ac_p)))
    for puid in absorbed_phantom_uids:
        pw, ph, pdc, pdr = phantom_rects[str(puid)]
        ph_cells = rect_cells_wh(pw, ph, pdc, pdr)
        blocked -= ph_cells - inferred_occ

    k = items_by_uid[str(uid)]
    self_base = _infer_base_occupied_cells_for_uid(uid, k, manual_shapes)
    allowed = set(self_base)
    for puid in absorbed_uids:
        ar_p, ac_p = anchors[str(puid)]
        allowed.add((int(ar_p), int(ac_p)))
    for puid in absorbed_phantom_uids:
        pw, ph, pdc, pdr = phantom_rects[str(puid)]
        allowed.add((int(pdr), int(pdc)))
    pseudo = _infer_pseudo_blocked(blocked, set(), allowed)
    return _infer_rect_feasible(
        int(dr),
        int(dc),
        int(dr) + int(h) - 1,
        int(dc) + int(w) - 1,
        pseudo,
        suppress,
        max_bid,
    )


def _infer_iterative_merge_expand_batch(
    batch: List[Tuple[str, ItemKnowledge, List[Any], int, int, bool]],
    *,
    baseline_occ: Set[Tuple[int, int]],
    inferred_occ: Set[Tuple[int, int]],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_peer_rects: Mapping[str, Tuple[int, int, int, int]],
    consumed_phantoms: Set[str],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Dict[str, Tuple[int, int, int, int]]:
    """
    第 4 回合后：各件自 1×1 起，反复与空置格、同品质邻接矩形或品质未定幽灵格合并，直至无法扩大。
    """
    if not batch:
        return {}
    rects: Dict[str, Tuple[int, int, int, int]] = {}
    anchors: Dict[str, Tuple[int, int]] = {}
    confirmed: Dict[str, bool] = {}
    filts: Dict[str, List[Any]] = {}
    items_by_uid: Dict[str, ItemKnowledge] = {}
    for uid, k, filt, ar, ac, confirmed_tl in batch:
        suid = str(uid)
        rects[suid] = (1, 1, int(ac), int(ar))
        anchors[suid] = (int(ar), int(ac))
        confirmed[suid] = bool(confirmed_tl)
        filts[suid] = filt
        items_by_uid[suid] = k

    phantoms_absorbed_by: Dict[str, Set[str]] = {}
    phantom_rects = dict(phantom_peer_rects)

    while True:
        occ_rects: Set[Tuple[int, int]] = set()
        for rect in rects.values():
            occ_rects |= rect_cells_wh(*rect)
        vacant = _infer_free_cells_in_prefix(
            baseline_occ | inferred_occ | occ_rects,
            suppress,
            max_bid,
        )

        best_key: Optional[Tuple[int, ...]] = None
        best_apply: Optional[
            Tuple[str, Tuple[int, int, int, int], Set[str], Set[str]]
        ] = None

        active_phantoms = {
            u: r for u, r in phantom_rects.items() if u not in consumed_phantoms
        }

        for uid in sorted(rects.keys()):
            w, h, dc, dr = rects[uid]
            ar, ac = anchors[uid]
            peers = {u: r for u, r in rects.items() if u != uid}
            for new_rect, absorbed, absorbed_ph in _infer_merge_expand_options(
                ar,
                ac,
                box_id_confirmed=confirmed[uid],
                w=w,
                h=h,
                dc=dc,
                dr=dr,
                vacant=vacant,
                peer_rects=peers,
                phantom_peer_rects=active_phantoms,
            ):
                if any(
                    not _infer_phantom_absorbable(
                        puid,
                        phantom_rects,
                        inferred_occ=inferred_occ,
                        rects=rects,
                        uid=uid,
                    )
                    for puid in absorbed_ph
                ):
                    continue
                nw, nh, _, _ = new_rect
                if not _infer_filt_has_shape_wh(filts[uid], nw, nh):
                    continue
                if not _infer_merge_rect_feasible(
                    new_rect,
                    uid=uid,
                    absorbed_uids=absorbed,
                    absorbed_phantom_uids=absorbed_ph,
                    phantom_rects=phantom_rects,
                    rects=rects,
                    anchors=anchors,
                    baseline_occ=baseline_occ,
                    inferred_occ=inferred_occ,
                    manual_shapes=manual_shapes,
                    items_by_uid=items_by_uid,
                    suppress=suppress,
                    max_bid=max_bid,
                ):
                    continue
                gain = int(nw) * int(nh) - int(w) * int(h)
                key = (int(gain), int(nw) * int(nh), uid)
                if best_key is None or key > best_key:
                    best_key = key
                    best_apply = (uid, new_rect, absorbed, absorbed_ph)

        if best_apply is None:
            break
        uid, new_rect, absorbed, absorbed_ph = best_apply
        rects[uid] = new_rect
        for puid in absorbed:
            ar_p, ac_p = anchors[puid]
            rects[puid] = (1, 1, int(ac_p), int(ar_p))
        if absorbed_ph:
            consumed_phantoms |= absorbed_ph
            phantoms_absorbed_by.setdefault(uid, set()).update(absorbed_ph)

    out: Dict[str, Tuple[int, int, int, int]] = {}
    for uid, rect in rects.items():
        w, h, dc, dr = rect
        if not _infer_filt_has_shape_wh(filts[uid], w, h):
            continue
        if not _infer_merge_rect_feasible(
            rect,
            uid=uid,
            absorbed_uids=set(),
            absorbed_phantom_uids=phantoms_absorbed_by.get(uid, set()),
            phantom_rects=phantom_rects,
            rects=rects,
            anchors=anchors,
            baseline_occ=baseline_occ,
            inferred_occ=inferred_occ,
            manual_shapes=manual_shapes,
            items_by_uid=items_by_uid,
            suppress=suppress,
            max_bid=max_bid,
        ):
            continue
        out[uid] = rect
    return out


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
    矩形左上角 ``(dr, dc)``（行、列）候选（供 UI 扩展等复用）。

    ``box_id_confirmed=True`` 时 BoxId 为顶左格，仅 ``(ar, ac)``；
    否则枚举所有使 ``(ar,ac)`` 落在 ``w×h`` 矩形内的顶左。
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


_MERGE_EXPAND_QUALITY_ORDER: Tuple[int, ...] = (5, 6, 4, 3, 2, 1)


def compute_grid_overlay_infer_shapes(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    occupied_cells: Set[Tuple[int, int]],
    vacant_manual_suppress: Set[Tuple[int, int]],
    max_box_id: int,
    raw_pricing: Dict[str, Any],
    phantom_items: Optional[Mapping[str, ItemKnowledge]] = None,
    phantom_quality_pref: Optional[Mapping[str, Any]] = None,
    infer_unknown_contour_shapes: bool = True,
    current_round: int = 1,
) -> InferShapesResult:
    """
    对 **品质已知、轮廓未知** 且未手动画框的日志物品，估计 ``[w,h,dc,dr]``（与 ``manual_shapes`` 同形）。

    第 4 回合前不做任何轮廓扩充。第 4 回合起与空格自动填充共用开关（``pricing.infer_vacant_rect_phantoms``）；
    须在空格填充占位已并入 ``occupied_cells`` 之后再调用本函数。

    ``infer_unknown_contour_shapes=False`` 时（与空置自动填充开关一致）返回空 ``InferShapesResult``。

    当 ``raw_pricing.event_stats`` 低档总格齐备、扫描史已覆盖 Q1–Q4 且低阶轮廓已锁定时：
    各件自 **1×1** 锚格起，按品质批次（金 → 红 → 紫 → …）反复与四邻空置格、同品质邻接推断矩形或
    品质未定幽灵格合并；仅当合并后外形在 CSV 候选中且几何可行时才采纳，直至全局无法再扩大。
    """
    if not infer_unknown_contour_shapes:
        return _infer_restore_occupied_empty(occupied_cells)
    if int(current_round) < AISHA_VACANT_RECT_INFER_ROUND:
        return _infer_restore_occupied_empty(occupied_cells)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return {}

    use_merge_expand = _event_stats_q14_grid_counts_all_known(raw_pricing) and _infer_q1234_scan_and_q14_contours_ready(
        game_state, manual_shapes
    )
    if not use_merge_expand:
        return _infer_restore_occupied_empty(occupied_cells)

    sup = set(vacant_manual_suppress)
    mx = int(max_box_id)
    baseline_occ: Set[Tuple[int, int]] = set(occupied_cells)
    inferred_occ: Set[Tuple[int, int]] = set()
    phantom_peer_rects = _infer_undetermined_phantom_peer_rects(
        phantom_items or {},
        manual_shapes,
        phantom_quality_pref or {},
    )
    consumed_phantoms: Set[str] = set()

    targets: List[Tuple[str, ItemKnowledge, int]] = []
    for uid, k in game_state.items.items():
        if not _infer_unknown_contour_item_eligible(k, uid, manual_shapes):
            continue
        try:
            q = int(k.quality or 0)
        except (TypeError, ValueError):
            continue
        targets.append((str(uid), k, q))

    quality_batches: Dict[int, List[Tuple[str, ItemKnowledge, List[Any], int, int, bool]]] = {}
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
        confirmed_tl = bool(getattr(k, "box_id_confirmed", False))
        quality_batches.setdefault(int(q), []).append(
            (uid, k, filt, int(ar), int(ac), confirmed_tl)
        )

    out: Dict[str, List[int]] = {}
    ordered_qualities = list(_MERGE_EXPAND_QUALITY_ORDER) + sorted(
        q for q in quality_batches if q not in _MERGE_EXPAND_QUALITY_ORDER
    )
    for qq in ordered_qualities:
        batch = quality_batches.get(int(qq))
        if not batch:
            continue
        merged = _infer_iterative_merge_expand_batch(
            batch,
            baseline_occ=baseline_occ,
            inferred_occ=inferred_occ,
            manual_shapes=manual_shapes,
            phantom_peer_rects=phantom_peer_rects,
            consumed_phantoms=consumed_phantoms,
            suppress=sup,
            max_bid=mx,
        )
        for uid, (w, h, dc, dr) in merged.items():
            out[uid] = [w, h, int(dc), int(dr)]
            for ddr in range(h):
                for ddc in range(w):
                    inferred_occ.add((dr + ddr, dc + ddc))

    occupied_cells.clear()
    occupied_cells.update(baseline_occ)
    occupied_cells.update(inferred_occ)
    return InferShapesResult(out, frozenset(consumed_phantoms))
