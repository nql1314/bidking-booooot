# -*- coding: utf-8 -*-
"""手画网格覆盖层与日志状态同步（从 ``GridWindow`` 拆出，避免 UI 内嵌占位/幽灵算法）。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple, Union

from ...analysis.scan_inference import apply_census_absent_qualities_from_raw_pricing
from ...parsing.state import GameState, ItemKnowledge

GRID_COLS = 10


def _shape_wh(shape: object) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1


def effective_display_origin(
    uid: str,
    k: ItemKnowledge,
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
) -> Tuple[int, int]:
    if uid in manual_shapes:
        _, _, dc, dr = manual_shapes[uid]
        return dc, dr
    if k.box_id is None:
        return 0, 0
    return k.box_id % GRID_COLS, k.box_id // GRID_COLS


def effective_shape_wh(
    uid: str,
    k: ItemKnowledge,
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
) -> Tuple[int, int]:
    if k.shape is not None:
        return _shape_wh(k.shape)
    if uid in manual_shapes:
        w, h, _, _ = manual_shapes[uid]
        return w, h
    return 1, 1


def strip_manual_shapes_when_log_locked(
    items: Dict[str, ItemKnowledge],
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
) -> None:
    for uid, k in items.items():
        if k.shape is not None:
            manual_shapes.pop(uid, None)


def remove_phantoms_overlapping_confirmed_log(
    state_items: Dict[str, ItemKnowledge],
    phantom_items: Dict[str, ItemKnowledge],
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Dict[str, Union[int, str]],
) -> None:
    confirmed_occ: Set[Tuple[int, int]] = set()
    for uid, k in state_items.items():
        if k.box_id is None or not k.box_id_confirmed:
            continue
        dc, dr = effective_display_origin(uid, k, manual_shapes)
        w, h = effective_shape_wh(uid, k, manual_shapes)
        for ddr in range(h):
            for ddc in range(w):
                confirmed_occ.add((dr + ddr, dc + ddc))
    to_del: list = []
    for phid in phantom_items:
        if phid not in manual_shapes:
            continue
        w, h, dc, dr = manual_shapes[phid]
        if any(
            (dr + ddr, dc + ddc) in confirmed_occ
            for ddr in range(h)
            for ddc in range(w)
        ):
            to_del.append(phid)
    for phid in to_del:
        phantom_items.pop(phid, None)
        manual_shapes.pop(phid, None)
        phantom_quality_pref.pop(phid, None)


def apply_scan_history_to_phantom_items(
    phantom_items: Dict[str, ItemKnowledge],
    state: GameState,
) -> None:
    hist = getattr(state, "_scan_history", None) or []
    for phid, pk in phantom_items.items():
        for scan_type, value, hit_uids in hist:
            if phid in hit_uids:
                continue
            if scan_type == "category":
                pk.excluded_categories.add(value)
            else:
                pk.excluded_qualities.add(value)


def reconcile_overlay_after_refresh(
    state: GameState,
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
    phantom_items: Dict[str, ItemKnowledge],
    phantom_quality_pref: Dict[str, Union[int, str]],
    *,
    raw_pricing: Optional[Dict[str, Any]] = None,
) -> None:
    """日志刷新后：清掉已由协议锁外形的手动矩形、删掉与已确认物品重叠的幽灵、同步扫描负向约束。"""
    strip_manual_shapes_when_log_locked(state.items, manual_shapes)
    remove_phantoms_overlapping_confirmed_log(
        state.items, phantom_items, manual_shapes, phantom_quality_pref
    )
    apply_scan_history_to_phantom_items(phantom_items, state)
    apply_census_absent_qualities_from_raw_pricing(state.items, phantom_items, raw_pricing)
