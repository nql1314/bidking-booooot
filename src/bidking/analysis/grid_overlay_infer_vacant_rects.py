"""艾莎第 4 回合及之后：由空置区「近似实心矩形」推断幽灵物品（手动画框 + 候选约束）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from .grid_overlay_dims import GRID_COLS, GRID_ROWS
from .grid_overlay_infer_shapes import (
    _infer_q1234_scan_and_q14_contours_ready,
    _infer_solid_rectangle_bbox,
)
from .grid_overlay_item_merge import _load_item_prices_db
from .scan_inference import census_absent_qualities_from_board_snapshot
from .strategy.common import _find_continuous_regions

AUTO_VACANT_RECT_PHANTOM_PREFIX = "phantom_vac_"
AISHA_VACANT_RECT_INFER_ROUND = 4  # 自该回合起（含第 4 回合及以后）启用
DEFAULT_VACANT_RECT_MAX_HOLE_CELLS = 2
DEFAULT_VACANT_RECT_MIN_BBOX_AREA = 1

_ORTHO_DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def vacant_rect_phantom_infer_round_active(current_round: int) -> bool:
    """第 4 回合及之后才做空置矩形自动幽灵推断。"""
    return int(current_round) >= AISHA_VACANT_RECT_INFER_ROUND


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
    return {(dr + ddr, dc + ddc) for ddr in range(h) for ddc in range(w)}


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
    solid = _infer_solid_rectangle_bbox(region)
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


def _pass1_temp_ghost_1x1(vacant: Set[Tuple[int, int]]) -> Set[Tuple[int, int]]:
    """三面或四面被围住的 1×1 空格 → 临时占位（最终不输出幽灵）。"""
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
) -> bool:
    w, h, dc, dr = bbox
    if _skip_bottom_boundary_1xn_vacant_phantom(
        w, h, dr, max_box_id=ctx.max_box_id
    ):
        return False
    cells = _rect_cells(dr, dc, w, h)
    if cells & ctx.temp_ghost_1x1:
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
    """连通空置区 → 近似实心矩形幽灵（原第二轮 / 第四轮逻辑）。"""
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


def _pass_three_sided_rect_fill(ctx: _VacantRectInferCtx) -> None:
    """不规则剩余区：三面被围住的空格簇外接成矩形后再推断幽灵。"""
    work = ctx.vacant - ctx.taken
    if not work:
        return
    seeds = {
        cell
        for cell in work
        if _vacant_blocked_sides(cell[0], cell[1], work) >= 3
    }
    if not seeds:
        return

    components = _find_continuous_regions(seeds, ctx.infer_occupied)
    components.sort(key=lambda reg: -len(reg))

    for comp in components:
        comp = set(comp) & seeds
        if not comp:
            continue
        rows = [r for r, _ in comp]
        cols = [c for _, c in comp]
        min_r, max_r = min(rows), max(rows)
        min_c, max_c = min(cols), max(cols)
        region = {
            (r, c)
            for r in range(min_r, max_r + 1)
            for c in range(min_c, max_c + 1)
            if (r, c) in work
        }
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
    艾莎第 4 回合及之后、且 Q1–Q4 轮廓已齐时：多轮在剩余空置区推断 ``phantom_vac_*``。

    1. 三面/四面围住的 1×1 → 临时幽灵占格（不输出）；
    2. 连通区近似实心矩形（原逻辑）；
    3. 不规则剩余区：三面围住簇 → 外接矩形；
    4. 再次做第 2 轮矩形填充；
    5. 临时 1×1 占格还原为空置（不出现在返回列表中）。

    - 须有 CSV 候选（扫描负向 + ``event_stats`` 件数配额）；
    - 候选品质唯一 → 写入 ``quality``；
    - 候选物品唯一 → 写入 ``manual_confirm_item_id``。
    """
    if not enabled:
        return []
    if not vacant_rect_phantom_infer_round_active(current_round):
        return []
    if not _infer_q1234_scan_and_q14_contours_ready(game_state, manual_shapes):
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

    temp_ghost_1x1 = _pass1_temp_ghost_1x1(vacant)
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
    _pass_full_rect_fill(ctx)

    return ctx.out


__all__ = [
    "AISHA_VACANT_RECT_INFER_ROUND",
    "vacant_rect_phantom_infer_round_active",
    "AUTO_VACANT_RECT_PHANTOM_PREFIX",
    "DEFAULT_VACANT_RECT_MAX_HOLE_CELLS",
    "DEFAULT_VACANT_RECT_MIN_BBOX_AREA",
    "VacantRectPhantomSpec",
    "auto_vacant_rect_phantom_cell_count_from_snapshot",
    "compute_vacant_rect_phantom_specs",
    "is_auto_vacant_rect_phantom_uid",
]
