# -*- coding: utf-8 -*-
"""画板 ``grid_overlay`` 字段的序列化（与 ``GridWindow`` 解耦，供快照写出与测试复用）。"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple, Union

from ...analysis import grid_overlay as _grid_overlay
from ...analysis.snapshot import item_knowledge_to_json
from ...parsing.state import ItemKnowledge

GRID_COLS = _grid_overlay.GRID_COLS


def max_confirmed_box_id_from_items(items: Dict[str, ItemKnowledge]) -> int:
    max_box_id = -1
    for k in items.values():
        if k.box_id is None or not k.box_id_confirmed:
            continue
        max_box_id = max(max_box_id, k.box_id)
    return max_box_id


def build_grid_overlay_export_dict(
    *,
    phantom_items: Dict[str, ItemKnowledge],
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Dict[str, Union[int, str]],
    unknown_cell_quality_pref: Dict[str, int],
    vacant_manual_suppress: Set[Tuple[int, int]],
    current_round: int,
    min_round_show_empty: int,
    skill_logs: List[dict],
    occupied_cells: set,
    max_box_id: int,
) -> Dict[str, Any]:
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
    vacant_block = _grid_overlay.compute_overlay_vacant_dict(
        current_round=int(current_round),
        min_round_show_empty=int(min_round_show_empty),
        skill_logs=list(skill_logs),
        occupied=occupied_cells,
        max_box_id=int(max_box_id),
        vacant_manual_suppress=set(vacant_manual_suppress),
    )
    return {
        "phantom_items": ph,
        "manual_shapes": manual,
        "phantom_quality_pref": pref,
        "unknown_cell_quality_pref": uq_pref,
        "vacant_manual_suppress_bids": vacant_bids,
        "vacant": vacant_block,
    }
