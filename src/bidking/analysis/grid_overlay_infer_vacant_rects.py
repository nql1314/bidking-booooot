"""品质 1–4 扫描与低阶轮廓齐备后：由空置区「近似实心矩形」推断幽灵物品（手动画框 + 候选约束）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from ._shape_wh import shape_wh_from_snapshot
from .grid_overlay_dims import (
    GRID_COLS,
    GRID_ROWS,
    AISHA_VACANT_RECT_INFER_ROUND,
    rect_cells_wh,
    vacant_rect_phantom_infer_round_active,
)
from .grid_overlay_item_merge import _load_item_prices_db
from .grid_overlay_vacant_zone import _live_shape_wh
from .phantom_pricing_ui_sync import PHANTOM_Q_INFER, phantom_quality_pref_explicit_quality
from .scan_inference import census_absent_qualities_from_board_snapshot
from .strategy.common import _find_continuous_regions

AUTO_VACANT_RECT_PHANTOM_PREFIX = "phantom_vac_"
DEFAULT_VACANT_RECT_MAX_HOLE_CELLS = 2
DEFAULT_VACANT_RECT_MIN_BBOX_AREA = 1

_ORTHO_DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))


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


class VacantRectInferResult(NamedTuple):
    """
    空置矩形幽灵推断结果。

    ``inferred_log_shapes``：步骤 0 释放的 1×1 锚格被 ``phantom_vac_*`` 覆盖时，源物品扩至该矩形；
    ``absorbed_phantom_uids``：被吸收的 ``phantom_vac_*``。
    """

    specs: List[VacantRectPhantomSpec]
    inferred_log_shapes: Dict[str, Tuple[int, int, int, int]]
    absorbed_phantom_uids: frozenset[str]


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


def _collect_prefix_geometric_vacant_cells(
    *,
    occupied: Set[Tuple[int, int]],
    max_box_id: int,
    vacant_manual_suppress: Set[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    """前缀区内仅按占位/手动画板剔除的几何空置（含后续会被标为诈骗格的格）。"""
    limit = min(int(max_box_id), GRID_COLS * GRID_ROWS - 1)
    if limit < 0:
        return set()
    out: Set[Tuple[int, int]] = set()
    for bid in range(limit + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if not (0 <= r < GRID_ROWS and 0 <= c < GRID_COLS):
            continue
        if (r, c) in occupied:
            continue
        if (r, c) in vacant_manual_suppress:
            continue
        out.add((r, c))
    return out


def _collect_prefix_vacant_cells(
    *,
    occupied: Set[Tuple[int, int]],
    max_box_id: int,
    vacant_manual_suppress: Set[Tuple[int, int]],
    fraud_cells: Optional[Set[Tuple[int, int]]],
) -> Set[Tuple[int, int]]:
    """与画板橘红空置候选一致：前缀区内未占位、未手动画板剔除、非诈骗格。"""
    geo = _collect_prefix_geometric_vacant_cells(
        occupied=occupied,
        max_box_id=max_box_id,
        vacant_manual_suppress=vacant_manual_suppress,
    )
    fraud = fraud_cells or set()
    return {cell for cell in geo if cell not in fraud}


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
    vacant_avail = ctx.vacant - ctx.taken
    if not block_temp_ghost:
        vacant_avail |= ctx.temp_ghost_1x1 - ctx.taken
    if cells - vacant_avail:
        return False
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
            fraud_cells=None,
            max_hole_cells=0,
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


def _trim_rect_edges_fully_fraud(
    w: int,
    h: int,
    dc: int,
    dr: int,
    fraud_cells: Set[Tuple[int, int]],
) -> Tuple[int, int, int, int]:
    """裁掉矩形四边上「整行/整列均在诈骗格内」的边条。"""
    w_i, h_i, dc_i, dr_i = int(w), int(h), int(dc), int(dr)
    while h_i > 0:
        bottom_r = dr_i + h_i - 1
        if all((bottom_r, c) in fraud_cells for c in range(dc_i, dc_i + w_i)):
            h_i -= 1
        else:
            break
    while h_i > 0:
        if all((dr_i, c) in fraud_cells for c in range(dc_i, dc_i + w_i)):
            dr_i += 1
            h_i -= 1
        else:
            break
    while w_i > 0 and h_i > 0:
        right_c = dc_i + w_i - 1
        if all((r, right_c) in fraud_cells for r in range(dr_i, dr_i + h_i)):
            w_i -= 1
        else:
            break
    while w_i > 0 and h_i > 0:
        if all((r, dc_i) in fraud_cells for r in range(dr_i, dr_i + h_i)):
            dc_i += 1
            w_i -= 1
        else:
            break
    return w_i, h_i, dc_i, dr_i


def _shrink_rect_phantom_bbox_excluding_fraud(
    bbox: Tuple[int, int, int, int],
    fraud_cells: Set[Tuple[int, int]],
    *,
    min_bbox_area: int,
) -> Optional[Tuple[int, int, int, int]]:
    """
    若矩形 footprint 与诈骗格相交，尝试缩回仍不含诈骗格的实心矩形；
    无法缩回则返回 ``None``（调用方应剔除该幽灵）。
    """
    w, h, dc, dr = bbox
    cells = _rect_cells(dr, dc, w, h)
    if not fraud_cells or not (cells & fraud_cells):
        return bbox

    good = cells - fraud_cells
    if not good:
        return None

    tw, th, tdc, tdr = _trim_rect_edges_fully_fraud(w, h, dc, dr, fraud_cells)
    if tw > 0 and th > 0:
        trimmed = _rect_cells(tdr, tdc, tw, th)
        if not (trimmed & fraud_cells) and tw * th >= min_bbox_area:
            return (tw, th, tdc, tdr)

    solid = _vacant_infer_solid_rectangle_bbox(good)
    if solid is not None:
        sw, sh, sdc, sdr = solid
        scells = _rect_cells(sdr, sdc, sw, sh)
        if not (scells & fraud_cells) and sw * sh >= min_bbox_area:
            return solid
    return None


def _pass_post4_trim_specs_for_fraud_cells(
    ctx: _VacantRectInferCtx,
    fraud_cells: Optional[Set[Tuple[int, int]]],
) -> None:
    """步骤 2–4 用几何空置推断；输出后剔除或缩回不含诈骗格的实心矩形幽灵。"""
    fraud = fraud_cells or set()
    if not fraud:
        return
    kept: List[VacantRectPhantomSpec] = []
    for spec in ctx.out:
        old_cells = _phantom_spec_cells(spec)
        shrunk_bbox = _shrink_rect_phantom_bbox_excluding_fraud(
            (spec.w, spec.h, spec.dc, spec.dr),
            fraud,
            min_bbox_area=ctx.min_bbox_area,
        )
        if shrunk_bbox is None:
            ctx.taken -= old_cells
            ctx.vacant |= old_cells
            _vacant_phantom_apply_quality_count_delta(ctx, spec, -1)
            continue

        if shrunk_bbox == (spec.w, spec.h, spec.dc, spec.dr):
            kept.append(spec)
            continue

        _vacant_phantom_apply_quality_count_delta(ctx, spec, -1)
        new_spec = _vacant_rect_phantom_spec_from_bbox(
            shrunk_bbox, ctx=ctx, quality_counts=ctx.quality_counts
        )
        if new_spec is None:
            ctx.taken -= old_cells
            ctx.vacant |= old_cells
            continue

        new_cells = _phantom_spec_cells(new_spec)
        ctx.taken = (ctx.taken - old_cells) | new_cells
        ctx.vacant |= old_cells - new_cells
        _vacant_phantom_apply_quality_count_delta(ctx, new_spec, 1)
        kept.append(new_spec)
    ctx.out = kept


def _pass_three_sided_rect_fill(ctx: _VacantRectInferCtx) -> None:
    """不规则剩余区：逐点双向贪心扩展取最大矩形推断幽灵，移除后重复。"""
    work = ctx.vacant - ctx.taken
    if not work:
        return

    work_regions = _find_continuous_regions(work, ctx.infer_occupied)
    work_regions.sort(key=lambda reg: -len(reg))
    for scope in work_regions:
        _three_sided_fill_scope_recursive(ctx, set(scope))


_MERGE_EXPAND_QUALITY_ORDER: Tuple[int, ...] = (5, 6, 4, 3, 2, 1)


def _unknown_contour_rect_feasible(
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


def _unknown_contour_pseudo_blocked(
    baseline_occ: Set[Tuple[int, int]],
    inferred_occ: Set[Tuple[int, int]],
    self_base: Set[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    return inferred_occ | (baseline_occ - self_base)


def _unknown_contour_free_cells_in_prefix(
    pseudo_blocked: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Set[Tuple[int, int]]:
    free: Set[Tuple[int, int]] = set()
    mx = int(max_bid)
    for bid in range(mx + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if (r, c) in pseudo_blocked or (r, c) in suppress:
            continue
        free.add((r, c))
    return free


def _unknown_contour_phantom_absorbable(
    puid: str,
    phantom_rects: Mapping[str, Tuple[int, int, int, int]],
    *,
    inferred_occ: Set[Tuple[int, int]],
    rects: Mapping[str, Tuple[int, int, int, int]],
    uid: str,
) -> bool:
    cells = rect_cells_wh(*phantom_rects[str(puid)])
    if cells & inferred_occ:
        return False
    for ouid, rect in rects.items():
        if ouid == uid:
            continue
        if cells & rect_cells_wh(*rect):
            return False
    return True


def _unknown_contour_sets_orthogonally_adjacent(
    a: Set[Tuple[int, int]],
    b: Set[Tuple[int, int]],
) -> bool:
    for r, c in a:
        for dr, dc in _ORTHO_DELTAS:
            if (r + dr, c + dc) in b:
                return True
    return False


def _unknown_contour_anchor_inside_rect(
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


def _unknown_contour_filt_has_shape_wh(filt: List[Any], w: int, h: int) -> bool:
    wh = (int(w), int(h))
    for c in filt:
        cwh = shape_wh_from_snapshot(c.shape)
        if cwh == wh:
            return True
    return False


def _unknown_contour_phantom_quality_undetermined(
    uid: str,
    k: ItemKnowledge,
    phantom_quality_pref: Mapping[str, Any],
) -> bool:
    pref = phantom_quality_pref.get(uid)
    if pref == PHANTOM_Q_INFER:
        return True
    if isinstance(pref, str) and pref.strip() == PHANTOM_Q_INFER:
        return True
    if phantom_quality_pref_explicit_quality(pref) is not None:
        return False
    return k.quality is None


def _unknown_contour_undetermined_phantom_peer_rects(
    phantom_items: Mapping[str, ItemKnowledge],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Mapping[str, Any],
) -> Dict[str, Tuple[int, int, int, int]]:
    out: Dict[str, Tuple[int, int, int, int]] = {}
    for uid, k in phantom_items.items():
        suid = str(uid)
        if suid not in manual_shapes:
            continue
        if not _unknown_contour_phantom_quality_undetermined(suid, k, phantom_quality_pref):
            continue
        rect = manual_shapes[suid]
        out[suid] = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    return out


def _unknown_contour_phantom_peer_rects_for_merge(
    phantom_items: Mapping[str, ItemKnowledge],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Mapping[str, Any],
    phantom_specs: List[VacantRectPhantomSpec],
) -> Dict[str, Tuple[int, int, int, int]]:
    """
    可与日志件做邻接并集的幽灵矩形。

    - 手画幽灵：仅品质未定（显式 Q1–Q6 不被动吸收）；
    - 本轮 ``phantom_vac_*``：凡已写入 ``phantom_specs``、尚未落盘的自动幽灵均可参与几何合并
      （含推断出唯一品质的 ``phantom_vac``，以便与下方已扩大的日志轮廓叠成更大实心矩形）。
    """
    out = _unknown_contour_undetermined_phantom_peer_rects(
        phantom_items, manual_shapes, phantom_quality_pref
    )
    for spec in phantom_specs:
        if spec.manual_confirm_item_id is not None:
            continue
        suid = str(spec.uid)
        if not is_auto_vacant_rect_phantom_uid(suid):
            continue
        out[suid] = (int(spec.w), int(spec.h), int(spec.dc), int(spec.dr))
    return out


def _unknown_contour_merge_expand_options(
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
    cur = rect_cells_wh(w, h, dc, dr)
    opts: List[Tuple[Tuple[int, int, int, int], Set[str], Set[str]]] = []

    def _try_strip(
        edge: Set[Tuple[int, int]],
        new_rect: Tuple[int, int, int, int],
    ) -> None:
        if not edge or not all(cell in vacant for cell in edge):
            return
        if not _unknown_contour_anchor_inside_rect(
            ar, ac, new_rect, box_id_confirmed=box_id_confirmed
        ):
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
        if not _unknown_contour_sets_orthogonally_adjacent(cur, pcells):
            return
        bbox = _vacant_infer_solid_rectangle_bbox(cur | pcells)
        if bbox is None:
            return
        if not _unknown_contour_anchor_inside_rect(
            ar, ac, bbox, box_id_confirmed=box_id_confirmed
        ):
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


def _unknown_contour_base_occupied_cells_for_uid(
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


def _unknown_contour_merge_rect_feasible(
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
    self_base = _unknown_contour_base_occupied_cells_for_uid(uid, k, manual_shapes)
    allowed = set(self_base)
    for puid in absorbed_uids:
        ar_p, ac_p = anchors[puid]
        allowed.add((int(ar_p), int(ac_p)))
    for puid in absorbed_phantom_uids:
        pw, ph, pdc, pdr = phantom_rects[puid]
        allowed.add((int(pdr), int(pdc)))
    pseudo = _unknown_contour_pseudo_blocked(blocked, set(), allowed)
    return _unknown_contour_rect_feasible(
        int(dr),
        int(dc),
        int(dr) + int(h) - 1,
        int(dc) + int(w) - 1,
        pseudo,
        suppress,
        max_bid,
    )


def _unknown_contour_merge_baseline_occ(
    base_occupied: Set[Tuple[int, int]],
    phantom_specs: List[VacantRectPhantomSpec],
    consumed_phantoms: Set[str],
) -> Set[Tuple[int, int]]:
    """合并占位基底：日志/手画占位 + 尚未被日志件吸收的 ``phantom_vac_*``。"""
    out = set(base_occupied)
    consumed = {str(u) for u in consumed_phantoms}
    for spec in phantom_specs:
        if str(spec.uid) in consumed:
            continue
        out |= rect_cells_wh(spec.w, spec.h, spec.dc, spec.dr)
    return out


def _unknown_contour_iterative_merge_expand_batch(
    batch: List[Tuple[str, ItemKnowledge, List[Any], int, int, bool]],
    *,
    base_occupied: Set[Tuple[int, int]],
    phantom_specs: List[VacantRectPhantomSpec],
    inferred_occ: Set[Tuple[int, int]],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_peer_rects: Mapping[str, Tuple[int, int, int, int]],
    consumed_phantoms: Set[str],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Dict[str, Tuple[int, int, int, int]]:
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
        baseline_occ = _unknown_contour_merge_baseline_occ(
            base_occupied, phantom_specs, consumed_phantoms
        )
        occ_rects: Set[Tuple[int, int]] = set()
        for rect in rects.values():
            occ_rects |= rect_cells_wh(*rect)
        vacant = _unknown_contour_free_cells_in_prefix(
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
            for new_rect, absorbed, absorbed_ph in _unknown_contour_merge_expand_options(
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
                    not _unknown_contour_phantom_absorbable(
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
                if not _unknown_contour_filt_has_shape_wh(filts[uid], nw, nh):
                    continue
                if not _unknown_contour_merge_rect_feasible(
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
        if not _unknown_contour_filt_has_shape_wh(filts[uid], w, h):
            continue
        if not _unknown_contour_merge_rect_feasible(
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


def _unknown_contour_log_item_eligible(
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


def _release_1x1_unknown_contour_items_to_vacant(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_items: Mapping[str, ItemKnowledge],
    phantom_quality_pref: Mapping[str, Any],
    base_occupied: Set[Tuple[int, int]],
) -> Dict[Tuple[int, int], str]:
    """
    将场上 1×1 锚格的轮廓未知日志件、以及 1×1 品质未定手画幽灵，从占位中剥离。

    返回锚格 ``(row, col) → 源物品 uid``，供推断结束后与覆盖该格的 ``phantom_vac_*`` 做替换。
    """
    cell_source: Dict[Tuple[int, int], str] = {}

    for uid, k in game_state.items.items():
        suid = str(uid)
        if not _unknown_contour_log_item_eligible(k, suid, manual_shapes):
            continue
        cells = _unknown_contour_base_occupied_cells_for_uid(suid, k, manual_shapes)
        if len(cells) != 1:
            continue
        cell = next(iter(cells))
        cell_source[cell] = suid
        base_occupied.discard(cell)

    for uid, k in phantom_items.items():
        suid = str(uid)
        if is_auto_vacant_rect_phantom_uid(suid):
            continue
        if suid not in manual_shapes:
            continue
        w, h, dc, dr = manual_shapes[suid]
        if int(w) != 1 or int(h) != 1:
            continue
        if not _unknown_contour_phantom_quality_undetermined(suid, k, phantom_quality_pref):
            continue
        cell = (int(dr), int(dc))
        cell_source[cell] = suid
        base_occupied.discard(cell)

    return cell_source


def _pick_source_uid_for_phantom_replacement(
    spec: VacantRectPhantomSpec,
    hit_cells: List[Tuple[int, int]],
    cell_source: Mapping[Tuple[int, int], str],
    log_uids: Set[str],
) -> Optional[str]:
    """同一推断矩形覆盖多个记录锚格时，优先日志件，其次矩形左上角锚格。"""
    sources = {cell_source[c] for c in hit_cells}
    if not sources:
        return None
    if len(sources) == 1:
        return next(iter(sources))
    log_sources = sorted(s for s in sources if s in log_uids)
    if len(log_sources) == 1:
        return log_sources[0]
    anchor = (int(spec.dr), int(spec.dc))
    if anchor in cell_source:
        return cell_source[anchor]
    return cell_source[hit_cells[0]]


def _replace_recorded_anchors_with_covering_phantoms(
    specs: List[VacantRectPhantomSpec],
    cell_source: Mapping[Tuple[int, int], str],
    *,
    log_uids: Set[str],
) -> Tuple[
    List[VacantRectPhantomSpec],
    Dict[str, Tuple[int, int, int, int]],
    frozenset[str],
]:
    """
    记录锚格被 ``phantom_vac_*`` 覆盖时：源物品扩至该幽灵矩形，并移除对应幽灵规格。
    """
    if not cell_source:
        return specs, {}, frozenset()

    inferred: Dict[str, Tuple[int, int, int, int]] = {}
    absorbed: Set[str] = set()
    claimed_sources: Set[str] = set()
    keep: List[VacantRectPhantomSpec] = []

    for spec in specs:
        cells = _phantom_spec_cells(spec)
        hit_cells = [c for c in cells if c in cell_source]
        if not hit_cells:
            keep.append(spec)
            continue
        src = _pick_source_uid_for_phantom_replacement(
            spec, hit_cells, cell_source, log_uids
        )
        if src is None or src in claimed_sources:
            keep.append(spec)
            continue
        claimed_sources.add(src)
        inferred[src] = (int(spec.w), int(spec.h), int(spec.dc), int(spec.dr))
        absorbed.add(str(spec.uid))

    return keep, inferred, frozenset(absorbed)


def _unknown_contour_merge_expand_log_shapes(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    phantom_items: Mapping[str, ItemKnowledge],
    phantom_quality_pref: Mapping[str, Any],
    occupied_cells: Set[Tuple[int, int]],
    vacant_manual_suppress: Set[Tuple[int, int]],
    max_box_id: int,
    phantom_specs: List[VacantRectPhantomSpec],
) -> Tuple[Dict[str, Tuple[int, int, int, int]], frozenset[str]]:
    """
    空置 ``phantom_vac_*`` 推断完成后：对品质已知、轮廓未知且未手动画框的日志物品做合并扩充。

    ``occupied_cells`` 须已含场上占位；本函数会把 ``phantom_specs`` 与推断矩形写回该集合。
    """
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return {}, frozenset()

    sup = set(vacant_manual_suppress)
    mx = int(max_box_id)
    base_occupied: Set[Tuple[int, int]] = set(occupied_cells)

    inferred_occ: Set[Tuple[int, int]] = set()
    phantom_peer_rects = _unknown_contour_phantom_peer_rects_for_merge(
        phantom_items,
        manual_shapes,
        phantom_quality_pref,
        phantom_specs,
    )
    consumed_phantoms: Set[str] = set()

    targets: List[Tuple[str, ItemKnowledge, int]] = []
    for uid, k in game_state.items.items():
        if not _unknown_contour_log_item_eligible(k, uid, manual_shapes):
            continue
        try:
            q = int(k.quality or 0)
        except (TypeError, ValueError):
            continue
        targets.append((str(uid), k, q))

    quality_batches: Dict[
        int, List[Tuple[str, ItemKnowledge, List[Any], int, int, bool]]
    ] = {}
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

    out: Dict[str, Tuple[int, int, int, int]] = {}
    ordered_qualities = list(_MERGE_EXPAND_QUALITY_ORDER) + sorted(
        q for q in quality_batches if q not in _MERGE_EXPAND_QUALITY_ORDER
    )
    for qq in ordered_qualities:
        batch = quality_batches.get(int(qq))
        if not batch:
            continue
        merged = _unknown_contour_iterative_merge_expand_batch(
            batch,
            base_occupied=base_occupied,
            phantom_specs=phantom_specs,
            inferred_occ=inferred_occ,
            manual_shapes=manual_shapes,
            phantom_peer_rects=phantom_peer_rects,
            consumed_phantoms=consumed_phantoms,
            suppress=sup,
            max_bid=mx,
        )
        for uid, (w, h, dc, dr) in merged.items():
            out[uid] = (int(w), int(h), int(dc), int(dr))
            for ddr in range(h):
                for ddc in range(w):
                    inferred_occ.add((dr + ddr, dc + ddc))

    occupied_cells.clear()
    occupied_cells.update(
        _unknown_contour_merge_baseline_occ(
            base_occupied, phantom_specs, consumed_phantoms
        )
    )
    occupied_cells.update(inferred_occ)
    return out, frozenset(consumed_phantoms)


def _filter_phantom_specs_absorbed_by_log_merge(
    specs: List[VacantRectPhantomSpec],
    absorbed_phantom_uids: Set[str],
) -> List[VacantRectPhantomSpec]:
    if not absorbed_phantom_uids:
        return specs
    absorbed = {str(u) for u in absorbed_phantom_uids}
    return [sp for sp in specs if str(sp.uid) not in absorbed]


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
) -> VacantRectInferResult:
    """
    品质 1–4 全量扫描已发生、且场上 Q1–Q4 轮廓与锚格均已可靠锁定时，
    在剩余空置区多轮推断 ``phantom_vac_*``。

    步骤 1–4 使用**几何空置**（仅剔除占位与手动画板 suppress），不在推断中剔除诈骗格；
    步骤 4 之后若提供 ``fraud_cells``，则丢弃 footprint **完全**落在诈骗格内的幽灵。
    诈骗格剔除在画板橘红空置与定价计数中另行生效。

    0. 将场上 1×1 锚格的轮廓未知日志件、1×1 品质未定手画幽灵从占位中剥离为前置空置格，
       并记录锚格品质（手画幽灵仅在手选显式 Q 时记录）；
    1. 三面/四面围住的 1×1 → 临时幽灵占格（不立即输出）；
    2. 连通区实心矩形；
    3. 不规则剩余区：逐点 H/V 双向贪心扩展 → 取最大矩形（方度 tie-break），移除后重复；
    4. 第 1 步临时占格、仍未被 2/3 步吸收的 1×1 → 输出对应幽灵；
    4b. 若 ``fraud_cells`` 非空：完全落在诈骗格内的幽灵剔除；与诈骗格相交者先裁边条或取非诈骗实心外包矩形缩回（须仍有 CSV 候选），否则剔除；
    5. 相邻幽灵并集为实心矩形时合并，直至稳定；
    6. 覆盖步骤 0 记录锚格的 ``phantom_vac_*`` → 源物品扩至该矩形，并删除对应幽灵。

    - 须有 CSV 候选（扫描负向 + ``event_stats`` 件数配额）；
    - 候选品质唯一 → 写入 ``quality``；
    - 候选物品唯一 → 写入 ``manual_confirm_item_id``。

    ``max_hole_cells`` 仅写入上下文（第 2 步已不做诈骗空洞容错）。
    """
    empty = VacantRectInferResult([], {}, frozenset())
    if not enabled:
        return empty
    if int(current_round) < AISHA_VACANT_RECT_INFER_ROUND:
        return empty
    if not _vacant_infer_q1234_scan_and_q14_contours_ready(game_state, manual_shapes):
        return empty

    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return empty

    excl_q, excl_c = _scan_exclusions_for_vacant_phantom(game_state, raw_pricing)
    quality_counts = _count_quality_items(
        game_state, phantom_items, phantom_quality_pref
    )

    base_occupied = set(occupied_cells)
    recorded_cell_source = _release_1x1_unknown_contour_items_to_vacant(
        game_state=game_state,
        manual_shapes=manual_shapes,
        phantom_items=phantom_items,
        phantom_quality_pref=phantom_quality_pref,
        base_occupied=base_occupied,
    )
    log_uids = {str(u) for u in game_state.items}
    vacant = _collect_prefix_geometric_vacant_cells(
        occupied=base_occupied,
        max_box_id=int(max_box_id),
        vacant_manual_suppress=set(vacant_manual_suppress),
    )

    specs: List[VacantRectPhantomSpec] = []
    ctx: Optional[_VacantRectInferCtx] = None
    if vacant:
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
            max_box_id=int(max_box_id),
            max_hole_cells=int(max_hole_cells),
            min_bbox_area=int(min_bbox_area),
        )

        _pass_full_rect_fill(ctx)
        _pass_three_sided_rect_fill(ctx)
        _pass4_emit_deferred_temp_1x1_phantoms(ctx)
        _pass_post4_trim_specs_for_fraud_cells(ctx, fraud_cells)
        specs = ctx.out
        if specs and ctx is not None:
            ctx.out = specs
            _pass5_merge_adjacent_phantom_rects(ctx)
            specs = ctx.out

    specs, inferred, absorbed = _replace_recorded_anchors_with_covering_phantoms(
        specs,
        recorded_cell_source,
        log_uids=log_uids,
    )
    return VacantRectInferResult(specs, inferred, absorbed)


__all__ = [
    "vacant_rect_phantom_infer_round_active",
    "AUTO_VACANT_RECT_PHANTOM_PREFIX",
    "DEFAULT_VACANT_RECT_MAX_HOLE_CELLS",
    "DEFAULT_VACANT_RECT_MIN_BBOX_AREA",
    "VacantRectInferResult",
    "VacantRectPhantomSpec",
    "auto_vacant_rect_phantom_cell_count_from_snapshot",
    "compute_vacant_rect_phantom_specs",
    "is_auto_vacant_rect_phantom_uid",
]
