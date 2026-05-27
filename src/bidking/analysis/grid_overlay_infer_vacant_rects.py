"""艾莎第 4 回合：由空置区「近似实心矩形」推断幽灵物品（手动画框 + 候选约束）。"""

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
AISHA_VACANT_RECT_INFER_ROUND = 4
DEFAULT_VACANT_RECT_MAX_HOLE_CELLS = 2
DEFAULT_VACANT_RECT_MIN_BBOX_AREA = 1


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
    艾莎第 4 回合且 Q1–Q4 轮廓已齐时：在剩余空置区中识别近似矩形空洞，
    生成 ``phantom_vac_*`` 规格（手动画框语义）。

    - 须有 CSV 候选（扫描负向 + ``event_stats`` 件数配额）；
    - 候选品质唯一 → 写入 ``quality``；
    - 候选物品唯一 → 写入 ``manual_confirm_item_id``。
    """
    if not enabled:
        return []
    if int(current_round) != AISHA_VACANT_RECT_INFER_ROUND:
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

    vacant = _collect_prefix_vacant_cells(
        occupied=set(occupied_cells),
        max_box_id=int(max_box_id),
        vacant_manual_suppress=set(vacant_manual_suppress),
        fraud_cells=fraud_cells,
    )
    if not vacant:
        return []

    regions = _find_continuous_regions(vacant, set(occupied_cells))
    # 大面积优先，避免小碎块占坑
    regions.sort(key=lambda reg: -len(reg))

    taken: Set[Tuple[int, int]] = set()
    out: List[VacantRectPhantomSpec] = []

    for region in regions:
        region = set(region) - taken
        if not region:
            continue
        bbox = _region_to_bbox_or_none(
            region,
            fraud_cells=fraud_cells,
            max_hole_cells=int(max_hole_cells),
            min_bbox_area=int(min_bbox_area),
        )
        if bbox is None:
            continue
        w, h, dc, dr = bbox
        cells = _rect_cells(dr, dc, w, h)
        if cells & set(occupied_cells):
            continue
        if cells & taken:
            continue

        filt = _candidates_for_vacant_rect(
            w,
            h,
            excl_q=excl_q,
            excl_c=excl_c,
            csv_index=csv_index,
            csv_items=csv_items,
            raw_pricing=raw_pricing,
            quality_counts=quality_counts,
        )
        if not filt:
            continue

        qualities = {int(c.quality) for c in filt}
        quality: Optional[int] = None
        if len(qualities) == 1:
            quality = next(iter(qualities))

        confirm_id: Optional[int] = None
        if len(filt) == 1:
            confirm_id = int(filt[0].item_id)

        uid = f"{AUTO_VACANT_RECT_PHANTOM_PREFIX}{dr:02d}{dc:02d}_{w}x{h}"
        out.append(
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
        taken |= cells
        if quality is not None:
            quality_counts[int(quality)] = quality_counts.get(int(quality), 0) + 1

    return out


__all__ = [
    "AISHA_VACANT_RECT_INFER_ROUND",
    "AUTO_VACANT_RECT_PHANTOM_PREFIX",
    "DEFAULT_VACANT_RECT_MAX_HOLE_CELLS",
    "DEFAULT_VACANT_RECT_MIN_BBOX_AREA",
    "VacantRectPhantomSpec",
    "compute_vacant_rect_phantom_specs",
    "is_auto_vacant_rect_phantom_uid",
]
