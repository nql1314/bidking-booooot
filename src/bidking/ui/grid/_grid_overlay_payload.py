# -*- coding: utf-8 -*-
"""画板 ``grid_overlay`` 字段的序列化（与 ``GridWindow`` 解耦，供快照写出与测试复用）。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple, Union

from ...analysis import grid_overlay as _grid_overlay
from ...analysis.snapshot import game_state_to_json, item_knowledge_to_json
from ...parsing.state import GameState, ItemKnowledge

GRID_COLS = _grid_overlay.GRID_COLS


def max_anchor_box_id_from_overlay_ui(
    items: Dict[str, ItemKnowledge],
    phantom_items: Dict[str, ItemKnowledge],
) -> int:
    """
    画板空置前缀上界：与 ``analysis.grid_overlay.max_anchor_box_id_merged`` 一致——
    任意有效日志/幽灵锚格（不要求 ``box_id_confirmed``）；全无锚点时退回
    ``DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID``。
    """
    max_box_id = -1
    for k in items.values():
        if k.box_id is None:
            continue
        max_box_id = max(max_box_id, int(k.box_id))
    for k in phantom_items.values():
        if k.box_id is None:
            continue
        max_box_id = max(max_box_id, int(k.box_id))
    if max_box_id < 0:
        return int(_grid_overlay.DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID)
    return max_box_id

def build_grid_overlay_export_dict(
    *,
    game_state: GameState,
    raw_pricing: Dict[str, Any],
    phantom_items: Dict[str, ItemKnowledge],
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Dict[str, Union[int, str]],
    unknown_cell_quality_pref: Dict[str, int],
    vacant_manual_suppress: Set[Tuple[int, int]],
    occupied_cells: set,
    max_box_id: int,
    infer_unknown_contour_shapes: bool = True,
    infer_suppress_uids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """组装写入 ``grid_overlay`` 的字段；不含 ``vacant``（须用全量占位格在 :meth:`GridWindow._grid_overlay_to_json` 中计算）。"""
    ph = {uid: item_knowledge_to_json(k) for uid, k in phantom_items.items()}
    manual = {uid: [int(x) for x in tup] for uid, tup in manual_shapes.items()}
    pref: Dict[str, Union[int, str]] = {}
    for uid, v in phantom_quality_pref.items():
        pref[uid] = v if isinstance(v, int) else str(v)
    uq_pref = {
        uid: int(q)
        for uid, q in unknown_cell_quality_pref.items()
        if isinstance(q, int) and 1 <= q <= 6
    }
    vacant_bids = sorted(r * GRID_COLS + c for r, c in vacant_manual_suppress)
    occ_bids = sorted(r * GRID_COLS + c for r, c in occupied_cells)

    infer = _grid_overlay.compute_grid_overlay_infer_shapes(
        game_state=game_state,
        manual_shapes=manual_shapes,
        occupied_cells=set(occupied_cells),
        vacant_manual_suppress=set(vacant_manual_suppress),
        max_box_id=int(max_box_id),
        raw_pricing=raw_pricing,
        infer_unknown_contour_shapes=infer_unknown_contour_shapes,
    )
    sup = infer_suppress_uids or set()
    if sup:
        infer = {uid: t for uid, t in infer.items() if str(uid) not in sup}
    infer_out = {uid: [int(x) for x in tup] for uid, tup in infer.items()}
    overlay_for_merged = {
        "phantom_items": ph,
        "manual_shapes": manual,
        "infer_shapes": infer_out,
        "phantom_quality_pref": pref,
    }
    snap_merged = {
        "game_state": game_state_to_json(game_state),
        "grid_overlay": overlay_for_merged,
    }
    merged_items = _grid_overlay.merged_items_dict(snap_merged)
    return {
        "phantom_items": ph,
        "manual_shapes": manual,
        "phantom_quality_pref": pref,
        "unknown_cell_quality_pref": uq_pref,
        "vacant_manual_suppress_bids": vacant_bids,
        _grid_overlay.OCCUPIED_CELL_BIDS: occ_bids,
        "infer_shapes": infer_out,
        "merged_items_dict": merged_items,
    }
