"""品质 1–4 扫描与低阶轮廓齐备后：由空置区「近似实心矩形」推断幽灵物品（手动画框 + 候选约束）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from .grid_overlay_dims import GRID_COLS, GRID_ROWS, AISHA_VACANT_RECT_INFER_ROUND, rect_cells_wh
from .grid_overlay_item_merge import _load_item_prices_db
from .scan_inference import census_absent_qualities_from_board_snapshot
from .strategy.common import _find_continuous_regions

AUTO_VACANT_RECT_PHANTOM_PREFIX = "phantom_vac_"
DEFAULT_VACANT_RECT_MAX_HOLE_CELLS = 2
DEFAULT_VACANT_RECT_MIN_BBOX_AREA = 1

_ORTHO_DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def vacant_rect_phantom_infer_round_active(current_round: int) -> bool:
    """第 4 回合及之后才做空置矩形自动幽灵推断。"""
    return int(current_round) >= AISHA_VACANT_RECT_INFER_ROUND


def _vacant_infer_q1234_scan_and_q14_contours_ready(
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


def _vacant_infer_solid_rectangle_bbox(
    cells: Set[Tuple[int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    """若 ``cells`` 恰为实心矩形，返回 ``(w, h, dc, dr)``；否则 ``None``。"""
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


@dataclass(frozen=True)
class VacantRectPhantomSpec:
    """与手画幽灵一致：顶左锚 + ``manual_shapes`` 矩形；可选品质 / 唯一候选确认。"""

    uid: str
    w: int
    h: int
    dc: int
    dr: int
    quality: Optional[int] = None
    manual_confirm_item_id: Optional[int] = None


def is_auto_vacant_rect_phantom_uid(uid: str) -> bool:
    return str(uid).startswith(AUTO_VACANT_RECT_PHANTOM_PREFIX)


def auto_vacant_rect_phantom_cell_count_from_snapshot(
    board_snapshot: Mapping[str, Any],
) -> int:
    """快照中自动 ``phantom_vac_*`` 在 ``manual_shapes`` 上的 footprint 格数之和。"""
    overlay = board_snapshot.get("grid_overlay")
    if not isinstance(overlay, dict):
        return 0
    phantom_items = overlay.get("phantom_items")
    manual_shapes = overlay.get("manual_shapes")
    if not isinstance(phantom_items, dict) or not isinstance(manual_shapes, dict):
        return 0
    total = 0
    for uid in phantom_items:
        if not is_auto_vacant_rect_phantom_uid(str(uid)):
            continue
        entry = manual_shapes.get(uid)
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        try:
            w, h = int(entry[0]), int(entry[1])
        except (TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            total += w * h
    return int(total)


def _scan_exclusions_for_vacant_phantom(
    game_state: GameState,
    raw_pricing: Dict[str, Any],
) -> Tuple[Set[int], Set[int]]:
    """空置区推断幽灵视为未命中任何扫描：并入负向品质/类别。"""
    excl_q: Set[int] = set()
    excl_c: Set[int] = set()
    hist = getattr(game_state, "_scan_history", []) or []
    for ent in hist:
        if not ent or len(ent) < 2:
            continue
        stype, val = ent[0], ent[1]
        if stype == "category":
            try:
                excl_c.add(int(val))
            except (TypeError, ValueError):
                pass
        elif stype == "quality":
            try:
                excl_q.add(int(val))
            except (TypeError, ValueError):
                pass
    snap_stub = {"raw_pricing": raw_pricing}
    for q in census_absent_qualities_from_board_snapshot(snap_stub):
        excl_q.add(int(q))
    return excl_q, excl_c


def _count_quality_items(
    game_state: GameState,
    phantom_items: Mapping[str, ItemKnowledge],
    phantom_quality_pref: Mapping[str, Any],
) -> Dict[int, int]:
    """场上已占位物品按品质计数（不含即将重算的 ``phantom_vac_``）。"""
    out: Dict[int, int] = {q: 0 for q in range(1, 7)}
    for k in game_state.items.values():
        if k.box_id is None or k.quality is None:
            continue
        try:
            qi = int(k.quality)
        except (TypeError, ValueError):
            continue
        if 1 <= qi <= 6:
            out[qi] = out.get(qi, 0) + 1
    for phid, pk in phantom_items.items():
        if is_auto_vacant_rect_phantom_uid(phid):
            continue
        if pk.box_id is None:
            continue
        q: Optional[int] = None
        pref = phantom_quality_pref.get(phid)
        if isinstance(pref, int) and 1 <= pref <= 6:
            q = pref
        elif pk.quality is not None:
            try:
                q = int(pk.quality)
            except (TypeError, ValueError):
                q = None
        if q is not None and 1 <= q <= 6:
            out[q] = out.get(q, 0) + 1
    return out


def _event_stats_allows_quality(
    quality: int,
    *,
    raw_pricing: Dict[str, Any],
    quality_counts: Dict[int, int],
    add_items: int = 1,
) -> bool:
    """``event_stats.qK_count`` 已知时，新增件数不得超过剩余配额。"""
    st = raw_pricing.get("event_stats")
    if not isinstance(st, dict):
        return True
    cap = st.get(f"q{int(quality)}_count")
    if cap is None:
        return True
    try:
        cap_i = int(cap)
    except (TypeError, ValueError):
        return True
    cur = int(quality_counts.get(int(quality), 0))
    return cur + int(add_items) <= cap_i


def _rect_cells(dr: int, dc: int, w: int, h: int) -> Set[Tuple[int, int]]:
    return rect_cells_wh(w, h, dc, dr)


def _skip_bottom_boundary_1xn_vacant_phantom(
    w: int,
    h: int,
    dr: int,
    *,
    max_box_id: int,
) -> bool:
    """
    空置前缀区底边 ``1×n`` 横条（``h==1``）外形易误判，不参与自动 ``phantom_vac_*`` 推断。

    「贴底」指矩形下边落在当前空置前缀上界 ``max_box_id`` 所在行（含该行）。
    """
    if int(h) != 1 or int(w) < 1:
        return False
    prefix_limit = min(int(max_box_id), GRID_COLS * GRID_ROWS - 1)
    prefix_bottom_row = prefix_limit // GRID_COLS
    bottom_row = int(dr) + int(h) - 1
    return bottom_row >= prefix_bottom_row


def _region_to_bbox_or_none(
    region: Set[Tuple[int, int]],
    *,
    fraud_cells: Optional[Set[Tuple[int, int]]],
    max_hole_cells: int,
    min_bbox_area: int,
) -> Optional[Tuple[int, int, int, int]]:
    """
    若连通空置区为实心矩形，或外接矩形内仅少量空洞（优先为诈骗格误判），
    返回 ``(w, h, dc, dr)``。
    """
    solid = _vacant_infer_solid_rectangle_bbox(region)
    if solid is not None:
        w, h, dc, dr = solid
        if w * h < min_bbox_area:
            return None
        return solid

    rows = [r for r, _ in region]
    cols = [c for _, c in region]
    min_r, max_r = min(rows), max(rows)
    min_c, max_c = min(cols), max(cols)
    h = max_r - min_r + 1
    w = max_c - min_c + 1
    area = w * h
    if area < min_bbox_area:
        return None

    holes: List[Tuple[int, int]] = []
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            if (r, c) not in region:
                holes.append((r, c))
    if not holes:
        return (w, h, min_c, min_r)
    if len(holes) > max_hole_cells:
        return None
    if fraud_cells:
        if not all(h in fraud_cells for h in holes):
            return None
    return (w, h, min_c, min_r)


def _collect_prefix_vacant_cells(
    *,
    occupied: Set[Tuple[int, int]],
    max_box_id: int,
    vacant_manual_suppress: Set[Tuple[int, int]],
    fraud_cells: Optional[Set[Tuple[int, int]]],
) -> Set[Tuple[int, int]]:
    """与画板橘红空置候选一致：前缀区内未占位、未手动画板剔除、非诈骗格。"""
    limit = min(int(max_box_id), GRID_COLS * GRID_ROWS - 1)
    if limit < 0:
        return set()
    fraud = fraud_cells or set()
    out: Set[Tuple[int, int]] = set()
    for bid in range(limit + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if not (0 <= r < GRID_ROWS and 0 <= c < GRID_COLS):
            continue
        if (r, c) in occupied:
            continue
        if (r, c) in vacant_manual_suppress:
            continue
        if (r, c) in fraud:
            continue
        out.add((r, c))
    return out


def _vacant_blocked_sides(r: int, c: int, vacant: Set[Tuple[int, int]]) -> int:
    """四邻中有几格不在当前空置集合内（含棋盘外缘）。"""
    n = 0
    for dr, dc in _ORTHO_DELTAS:
        nr, nc = r + dr, c + dc
        if not (0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS):
            n += 1
        elif (nr, nc) not in vacant:
            n += 1
    return n


def _pass1_collect_temp_ghost_1x1(vacant: Set[Tuple[int, int]]) -> Set[Tuple[int, int]]:
    """三面或四面被围住的 1×1 空格 → 临时占位（第 4 步再输出幽灵）。"""
    out: Set[Tuple[int, int]] = set()
    for cell in vacant:
        if _vacant_blocked_sides(cell[0], cell[1], vacant) >= 3:
            out.add(cell)
    return out


def _candidates_for_vacant_rect(
    w: int,
    h: int,
    *,
    excl_q: Set[int],
    excl_c: Set[int],
    csv_index: Dict[int, Any],
    csv_items: List[Any],
    raw_pricing: Dict[str, Any],
    quality_counts: Dict[int, int],
) -> List[Any]:
    virtual_shape = int(w) * 10 + int(h)
    filt = item_db.filter_csv_candidates_for_query(
        virtual_shape,
        None,
        set(),
        None,
        csv_index,
        csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
    )
    if not filt:
        return []
    return [
        c
        for c in filt
        if _event_stats_allows_quality(
            int(c.quality),
            raw_pricing=raw_pricing,
            quality_counts=quality_counts,
            add_items=1,
        )
    ]


@dataclass
class _VacantRectInferCtx:
    vacant: Set[Tuple[int, int]]
    base_occupied: Set[Tuple[int, int]]
    infer_occupied: Set[Tuple[int, int]]
    temp_ghost_1x1: Set[Tuple[int, int]]
    taken: Set[Tuple[int, int]]
    out: List[VacantRectPhantomSpec]
    excl_q: Set[int]
    excl_c: Set[int]
    csv_index: Dict[int, Any]
    csv_items: List[Any]
    raw_pricing: Dict[str, Any]
    quality_counts: Dict[int, int]
    fraud_cells: Optional[Set[Tuple[int, int]]]
    max_box_id: int
    max_hole_cells: int
    min_bbox_area: int


def _try_emit_rect_phantom(
    ctx: _VacantRectInferCtx,
    bbox: Tuple[int, int, int, int],
    *,
    block_temp_ghost: bool = True,
) -> bool:
    w, h, dc, dr = bbox
    if _skip_bottom_boundary_1xn_vacant_phantom(
        w, h, dr, max_box_id=ctx.max_box_id
    ):
        return False
    cells = _rect_cells(dr, dc, w, h)
    if block_temp_ghost and cells & ctx.temp_ghost_1x1:
        return False
    if cells & ctx.base_occupied:
        return False
    if cells & ctx.taken:
        return False

    filt = _candidates_for_vacant_rect(
        w,
        h,
        excl_q=ctx.excl_q,
        excl_c=ctx.excl_c,
        csv_index=ctx.csv_index,
        csv_items=ctx.csv_items,
        raw_pricing=ctx.raw_pricing,
        quality_counts=ctx.quality_counts,
    )
    if not filt:
        return False

    qualities = {int(c.quality) for c in filt}
    quality: Optional[int] = None
    if len(qualities) == 1:
        quality = next(iter(qualities))

    confirm_id: Optional[int] = None
    if len(filt) == 1:
        confirm_id = int(filt[0].item_id)

    uid = f"{AUTO_VACANT_RECT_PHANTOM_PREFIX}{dr:02d}{dc:02d}_{w}x{h}"
    ctx.out.append(
        VacantRectPhantomSpec(
            uid=uid,
            w=int(w),
            h=int(h),
            dc=int(dc),
            dr=int(dr),
            quality=quality,
            manual_confirm_item_id=confirm_id,
        )
    )
    ctx.taken |= cells
    ctx.vacant -= cells
    if quality is not None:
        ctx.quality_counts[int(quality)] = (
            ctx.quality_counts.get(int(quality), 0) + 1
        )
    return True


def _pass_full_rect_fill(ctx: _VacantRectInferCtx) -> None:
    """连通空置区 → 近似实心矩形幽灵。"""
    work = ctx.vacant - ctx.taken
    if not work:
        return
    regions = _find_continuous_regions(work, ctx.infer_occupied)
    regions.sort(key=lambda reg: -len(reg))

    for region in regions:
        region = set(region) & work
        if not region:
            continue
        bbox = _region_to_bbox_or_none(
            region,
            fraud_cells=ctx.fraud_cells,
            max_hole_cells=ctx.max_hole_cells,
            min_bbox_area=ctx.min_bbox_area,
        )
        if bbox is None:
            continue
        _try_emit_rect_phantom(ctx, bbox)


def _vacant_rect_rank_key(w: int, h: int) -> Tuple[int, int]:
    """``min(w,h)`` 更大者优先；同 min 时面积更大者优先（3×3 > 2×5/5×2，2×2 > 1×4）。"""
    wi, hi = int(w), int(h)
    return (min(wi, hi), wi * hi)


def _expand_max_rect_h_first(
    seed: Tuple[int, int],
    work: Set[Tuple[int, int]],
) -> Tuple[int, int, int, int]:
    """从 seed 先横向扩满，再纵向扩满，得最大内接矩形 ``(w, h, dc, dr)``。"""
    r, c = seed
    if seed not in work:
        return (0, 0, 0, 0)

    left, right = c, c
    while left > 0 and (r, left - 1) in work:
        left -= 1
    while right + 1 < GRID_COLS and (r, right + 1) in work:
        right += 1

    dc = left
    w = right - left + 1
    top, bottom = r, r

    while top > 0 and all((top - 1, col) in work for col in range(dc, dc + w)):
        top -= 1
    while bottom + 1 < GRID_ROWS and all(
        (bottom + 1, col) in work for col in range(dc, dc + w)
    ):
        bottom += 1

    dr = top
    h = bottom - top + 1
    return (w, h, dc, dr)


def _expand_max_rect_v_first(
    seed: Tuple[int, int],
    work: Set[Tuple[int, int]],
) -> Tuple[int, int, int, int]:
    """从 seed 先纵向扩满，再横向扩满，得最大内接矩形 ``(w, h, dc, dr)``。"""
    r, c = seed
    if seed not in work:
        return (0, 0, 0, 0)

    top, bottom = r, r
    while top > 0 and (top - 1, c) in work:
        top -= 1
    while bottom + 1 < GRID_ROWS and (bottom + 1, c) in work:
        bottom += 1

    dr = top
    h = bottom - top + 1
    left, right = c, c

    while left > 0 and all((row, left - 1) in work for row in range(dr, dr + h)):
        left -= 1
    while right + 1 < GRID_COLS and all(
        (row, right + 1) in work for row in range(dr, dr + h)
    ):
        right += 1

    dc = left
    w = right - left + 1
    return (w, h, dc, dr)


def _greedy_expand_rect_candidates(
    work: Set[Tuple[int, int]],
    local: Set[Tuple[int, int]],
    *,
    min_bbox_area: int,
) -> List[Tuple[int, int, int, int]]:
    """遍历 ``local`` 每格，收集 H/V 双向贪心扩展矩形，按方度与面积降序。"""
    if not local:
        return []

    seen: Set[Tuple[int, int, int, int]] = set()
    for cell in local:
        for bbox in (
            _expand_max_rect_h_first(cell, work),
            _expand_max_rect_v_first(cell, work),
        ):
            w, h, dc, dr = bbox
            if w <= 0 or h <= 0 or w * h < min_bbox_area:
                continue
            if not _rect_cells(dr, dc, w, h) <= work:
                continue
            seen.add(bbox)

    return sorted(
        seen,
        key=lambda b: _vacant_rect_rank_key(b[0], b[1]),
        reverse=True,
    )


def _three_sided_fill_scope_recursive(
    ctx: _VacantRectInferCtx,
    scope: Set[Tuple[int, int]],
) -> None:
    """单块不规则空置区：逐点双向贪心扩展取最大矩形，移除已覆盖格后重复。"""
    while True:
        work = ctx.vacant - ctx.taken
        local = scope & work
        if not local:
            return

        emitted = False
        for bbox in _greedy_expand_rect_candidates(
            work,
            local,
            min_bbox_area=ctx.min_bbox_area,
        ):
            if _try_emit_rect_phantom(ctx, bbox):
                emitted = True
                break
        if not emitted:
            return


def _phantom_spec_cells(spec: VacantRectPhantomSpec) -> Set[Tuple[int, int]]:
    return _rect_cells(spec.dr, spec.dc, spec.w, spec.h)


def _phantom_specs_orthogonally_adjacent(
    cells_a: Set[Tuple[int, int]],
    cells_b: Set[Tuple[int, int]],
) -> bool:
    for r, c in cells_a:
        for dr, dc in _ORTHO_DELTAS:
            if (r + dr, c + dc) in cells_b:
                return True
    return False


def _vacant_phantom_apply_quality_count_delta(
    ctx: _VacantRectInferCtx,
    spec: VacantRectPhantomSpec,
    delta: int,
) -> None:
    if spec.quality is None:
        return
    q = int(spec.quality)
    ctx.quality_counts[q] = max(0, ctx.quality_counts.get(q, 0) + int(delta))


def _project_quality_counts_without_specs(
    ctx: _VacantRectInferCtx,
    remove: List[VacantRectPhantomSpec],
) -> Dict[int, int]:
    qc = dict(ctx.quality_counts)
    for spec in remove:
        if spec.quality is None:
            continue
        q = int(spec.quality)
        qc[q] = max(0, qc.get(q, 0) - 1)
    return qc


def _vacant_rect_phantom_spec_from_bbox(
    bbox: Tuple[int, int, int, int],
    *,
    ctx: _VacantRectInferCtx,
    quality_counts: Dict[int, int],
) -> Optional[VacantRectPhantomSpec]:
    w, h, dc, dr = bbox
    if _skip_bottom_boundary_1xn_vacant_phantom(
        w, h, dr, max_box_id=ctx.max_box_id
    ):
        return None
    filt = _candidates_for_vacant_rect(
        w,
        h,
        excl_q=ctx.excl_q,
        excl_c=ctx.excl_c,
        csv_index=ctx.csv_index,
        csv_items=ctx.csv_items,
        raw_pricing=ctx.raw_pricing,
        quality_counts=quality_counts,
    )
    if not filt:
        return None
    qualities = {int(c.quality) for c in filt}
    quality: Optional[int] = None
    if len(qualities) == 1:
        quality = next(iter(qualities))
    confirm_id: Optional[int] = None
    if len(filt) == 1:
        confirm_id = int(filt[0].item_id)
    return VacantRectPhantomSpec(
        uid=f"{AUTO_VACANT_RECT_PHANTOM_PREFIX}{dr:02d}{dc:02d}_{w}x{h}",
        w=int(w),
        h=int(h),
        dc=int(dc),
        dr=int(dr),
        quality=quality,
        manual_confirm_item_id=confirm_id,
    )


def _try_merge_adjacent_phantom_pair(
    a: VacantRectPhantomSpec,
    b: VacantRectPhantomSpec,
    all_specs: List[VacantRectPhantomSpec],
    ctx: _VacantRectInferCtx,
) -> Optional[VacantRectPhantomSpec]:
    cells_a = _phantom_spec_cells(a)
    cells_b = _phantom_spec_cells(b)
    if not _phantom_specs_orthogonally_adjacent(cells_a, cells_b):
        return None
    union = cells_a | cells_b
    bbox = _vacant_infer_solid_rectangle_bbox(union)
    if bbox is None:
        return None
    for other in all_specs:
        if other is a or other is b:
            continue
        if _phantom_spec_cells(other) & union:
            return None
    qc = _project_quality_counts_without_specs(ctx, [a, b])
    return _vacant_rect_phantom_spec_from_bbox(bbox, ctx=ctx, quality_counts=qc)


def _pass5_merge_adjacent_phantom_rects(ctx: _VacantRectInferCtx) -> None:
    """相邻幽灵格并集为实心矩形时合并；合并后的矩形继续参与，直至无法再并。"""
    specs = ctx.out
    if len(specs) < 2:
        return
    while True:
        best_key: Optional[Tuple[int, int]] = None
        best_merged: Optional[VacantRectPhantomSpec] = None
        best_ij: Optional[Tuple[int, int]] = None
        for i in range(len(specs)):
            for j in range(i + 1, len(specs)):
                merged = _try_merge_adjacent_phantom_pair(
                    specs[i], specs[j], specs, ctx
                )
                if merged is None:
                    continue
                involves_1x1 = (
                    (specs[i].w == 1 and specs[i].h == 1)
                    or (specs[j].w == 1 and specs[j].h == 1)
                )
                key = (1 if involves_1x1 else 0, merged.w * merged.h)
                if best_key is None or key > best_key:
                    best_key = key
                    best_merged = merged
                    best_ij = (i, j)
        if best_ij is None or best_merged is None:
            break
        i, j = best_ij
        _vacant_phantom_apply_quality_count_delta(ctx, specs[i], -1)
        _vacant_phantom_apply_quality_count_delta(ctx, specs[j], -1)
        _vacant_phantom_apply_quality_count_delta(ctx, best_merged, 1)
        specs.pop(j)
        specs.pop(i)
        specs.append(best_merged)


def _pass4_emit_deferred_temp_1x1_phantoms(ctx: _VacantRectInferCtx) -> None:
    """第 1 步临时占格、仍未被 2/3 步吸收的 1×1 → 输出对应幽灵。"""
    for r, c in sorted(ctx.temp_ghost_1x1):
        if (r, c) in ctx.taken:
            continue
        _try_emit_rect_phantom(ctx, (1, 1, c, r), block_temp_ghost=False)


def _pass_three_sided_rect_fill(ctx: _VacantRectInferCtx) -> None:
    """不规则剩余区：逐点双向贪心扩展取最大矩形推断幽灵，移除后重复。"""
    work = ctx.vacant - ctx.taken
    if not work:
        return

    work_regions = _find_continuous_regions(work, ctx.infer_occupied)
    work_regions.sort(key=lambda reg: -len(reg))
    for scope in work_regions:
        _three_sided_fill_scope_recursive(ctx, set(scope))


def compute_vacant_rect_phantom_specs(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_items: Mapping[str, ItemKnowledge],
    phantom_quality_pref: Mapping[str, Any],
    occupied_cells: Set[Tuple[int, int]],
    vacant_manual_suppress: Set[Tuple[int, int]],
    max_box_id: int,
    raw_pricing: Dict[str, Any],
    current_round: int,
    fraud_cells: Optional[Set[Tuple[int, int]]] = None,
    max_hole_cells: int = DEFAULT_VACANT_RECT_MAX_HOLE_CELLS,
    min_bbox_area: int = DEFAULT_VACANT_RECT_MIN_BBOX_AREA,
    enabled: bool = True,
) -> List[VacantRectPhantomSpec]:
    """
    品质 1–4 全量扫描已发生、且场上 Q1–Q4 轮廓与锚格均已可靠锁定时：
    多轮在剩余空置区推断 ``phantom_vac_*``。

    1. 三面/四面围住的 1×1 → 临时幽灵占格（不立即输出）；
    2. 连通区近似实心矩形（原逻辑）；
    3. 不规则剩余区：逐点 H/V 双向贪心扩展 → 取最大矩形（3×3>2×5/5×2 等方度 tie-break），移除后重复；
    4. 第 1 步临时占格、仍未被 2/3 步吸收的 1×1 → 输出对应幽灵；
    5. 所有 1×1 幽灵与相邻幽灵并集为实心矩形时合并，合并结果继续重复直至稳定。

    - 须有 CSV 候选（扫描负向 + ``event_stats`` 件数配额）；
    - 候选品质唯一 → 写入 ``quality``；
    - 候选物品唯一 → 写入 ``manual_confirm_item_id``。
    """
    if not enabled:
        return []
    if not _vacant_infer_q1234_scan_and_q14_contours_ready(game_state, manual_shapes):
        return []

    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return []

    excl_q, excl_c = _scan_exclusions_for_vacant_phantom(game_state, raw_pricing)
    quality_counts = _count_quality_items(
        game_state, phantom_items, phantom_quality_pref
    )

    base_occupied = set(occupied_cells)
    vacant = _collect_prefix_vacant_cells(
        occupied=base_occupied,
        max_box_id=int(max_box_id),
        vacant_manual_suppress=set(vacant_manual_suppress),
        fraud_cells=fraud_cells,
    )
    if not vacant:
        return []

    temp_ghost_1x1 = _pass1_collect_temp_ghost_1x1(vacant)
    vacant -= temp_ghost_1x1
    infer_occupied = base_occupied | temp_ghost_1x1

    ctx = _VacantRectInferCtx(
        vacant=vacant,
        base_occupied=base_occupied,
        infer_occupied=infer_occupied,
        temp_ghost_1x1=temp_ghost_1x1,
        taken=set(),
        out=[],
        excl_q=excl_q,
        excl_c=excl_c,
        csv_index=csv_index,
        csv_items=csv_items,
        raw_pricing=raw_pricing,
        quality_counts=quality_counts,
        fraud_cells=fraud_cells,
        max_box_id=int(max_box_id),
        max_hole_cells=int(max_hole_cells),
        min_bbox_area=int(min_bbox_area),
    )

    _pass_full_rect_fill(ctx)
    _pass_three_sided_rect_fill(ctx)
    _pass4_emit_deferred_temp_1x1_phantoms(ctx)
    _pass5_merge_adjacent_phantom_rects(ctx)

    return ctx.out


__all__ = [
    "vacant_rect_phantom_infer_round_active",
    "AUTO_VACANT_RECT_PHANTOM_PREFIX",
    "DEFAULT_VACANT_RECT_MAX_HOLE_CELLS",
    "DEFAULT_VACANT_RECT_MIN_BBOX_AREA",
    "VacantRectPhantomSpec",
    "auto_vacant_rect_phantom_cell_count_from_snapshot",
    "compute_vacant_rect_phantom_specs",
    "is_auto_vacant_rect_phantom_uid",
]
