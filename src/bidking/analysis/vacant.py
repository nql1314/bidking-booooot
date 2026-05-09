"""空置/几何空置/有效空置/可能诈骗格分析。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..parsing.constants import MAP_SKILL_TOTAL_HIDDEN_CELLS

GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1


def _merge_latest_map_skill_entries(skill_logs: List[dict]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for block in skill_logs or []:
        if not isinstance(block, dict):
            continue
        gd = block.get("game_data") or {}
        if not isinstance(gd, dict):
            continue
        for entry in gd.get("MapSkillLog") or []:
            if not isinstance(entry, dict):
                continue
            try:
                cid = int(entry.get("SkillCid") or 0)
            except (TypeError, ValueError):
                continue
            if cid:
                out[cid] = entry
    return out


def _ms_int_field(entry: dict, *keys: str) -> Optional[int]:
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def map_skill_total_hidden_cells_from_logs(skill_logs: List[dict]) -> Optional[int]:
    ent = _merge_latest_map_skill_entries(skill_logs or []).get(MAP_SKILL_TOTAL_HIDDEN_CELLS)
    if not ent:
        return None
    v = _ms_int_field(ent, "TotalHitBoxIndex", "HitItemIndex")
    return v if v is not None and v > 0 else None


def vacant_cells_from_map_skill_total_hidden(
    skill_logs: List[dict],
    *,
    occupied_cell_count: int,
) -> Optional[int]:
    total_h = map_skill_total_hidden_cells_from_logs(skill_logs)
    if total_h is None:
        return None
    try:
        occ = int(occupied_cell_count)
    except (TypeError, ValueError):
        occ = 0
    occ = max(0, occ)
    return max(0, total_h - occ)


def map_skill_hidden_cell_reserve_from_snapshot(board_snapshot: Dict[str, Any]) -> int:
    _ = board_snapshot
    return 0


def _shape_wh_from_snapshot(shape: Any) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1


def _item_occupied_cells(box_id: int, shape: Any) -> set:
    w, h = _shape_wh_from_snapshot(shape)
    col = box_id % GRID_COLS
    row = box_id // GRID_COLS
    cells: set = set()
    for dr in range(h):
        for dc in range(w):
            cells.add((row + dr, col + dc))
    return cells


def _occupied_cells_item_board_display(it: Dict[str, Any], board_snapshot: Dict[str, Any]) -> set:
    _ = board_snapshot
    bid_raw = it.get("box_id")
    if bid_raw is None:
        return set()
    try:
        bid = int(bid_raw)
    except (TypeError, ValueError):
        return set()
    if it.get("shape") is not None:
        return _item_occupied_cells(bid, it.get("shape"))
    return {(bid // GRID_COLS, bid % GRID_COLS)}


def confirmed_items_from_snapshot(board_snapshot: Dict[str, Any]) -> List[dict]:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    out: List[dict] = []
    for _uid, it in raw.items():
        if not isinstance(it, dict) or not it.get("box_id_confirmed"):
            continue
        bid = it.get("box_id")
        if bid is None:
            continue
        try:
            int(bid)
        except (TypeError, ValueError):
            continue
        out.append(it)
    return out


def board_display_occupied_cells(board_snapshot: Dict[str, Any]) -> set:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    if not isinstance(raw, dict):
        return set()
    occ: set = set()
    for it in raw.values():
        if not isinstance(it, dict) or it.get("box_id") is None:
            continue
        try:
            int(it["box_id"])
        except (TypeError, ValueError):
            continue
        if it.get("box_id_confirmed"):
            occ |= _occupied_cells_item_board_display(it, board_snapshot)
    for it in raw.values():
        if not isinstance(it, dict) or it.get("box_id") is None:
            continue
        try:
            bid = int(it["box_id"])
        except (TypeError, ValueError):
            continue
        if it.get("box_id_confirmed"):
            continue
        occ.add((bid // GRID_COLS, bid % GRID_COLS))
    return occ


def early_round_vacant_metrics(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    items = confirmed_items_from_snapshot(board_snapshot)
    if not items:
        return {
            "max_anchor_box_id": -1,
            "vacant_round_1_2": 0,
            "vacant_round_3": 0,
            "round_3_anchor_floor_exclusive": 0,
            "known_quality_cell_count": 0,
            "all_occupied_cell_count": 0,
        }
    all_occ = board_display_occupied_cells(board_snapshot)
    max_anchor = max(int(it["box_id"]) for it in items)
    known_cells: set = set()
    for it in items:
        cells = _occupied_cells_item_board_display(it, board_snapshot)
        q = it.get("quality")
        if q is None:
            continue
        try:
            int(q)
        except (TypeError, ValueError):
            continue
        known_cells |= cells
    span_hi = min(max_anchor, GRID_MAX_BOX_ID)
    vacant_12 = 0
    if span_hi >= 0:
        for b in range(span_hi + 1):
            r, c = b // GRID_COLS, b % GRID_COLS
            if (r, c) not in all_occ:
                vacant_12 += 1
    r3_cap = (max_anchor // 10) * 10 if max_anchor >= 0 else 0
    vacant_3 = 0
    r3_hi = min(r3_cap, GRID_MAX_BOX_ID + 1)
    for b in range(r3_hi):
        r, c = b // GRID_COLS, b % GRID_COLS
        if (r, c) not in all_occ:
            vacant_3 += 1
    return {
        "max_anchor_box_id": max_anchor,
        "vacant_round_1_2": vacant_12,
        "vacant_round_3": vacant_3,
        "round_3_anchor_floor_exclusive": r3_cap,
        "known_quality_cell_count": len(known_cells),
        "all_occupied_cell_count": len(all_occ),
    }


def scam_span_vacant_deduction(board_snapshot: Dict[str, Any]) -> int:
    items = confirmed_items_from_snapshot(board_snapshot)
    if not items:
        return 1
    all_occ = board_display_occupied_cells(board_snapshot)
    max_anchor = max(int(it["box_id"]) for it in items)
    if max_anchor < 0:
        return 1
    col = max_anchor % GRID_COLS
    span_lo = max(0, max_anchor - col - GRID_COLS)
    span_hi = min(max_anchor, GRID_MAX_BOX_ID)
    n = 0
    for b in range(span_lo, span_hi + 1):
        r, c = b // GRID_COLS, b % GRID_COLS
        if (r, c) not in all_occ:
            n += 1
    return n

__all__ = [
    "confirmed_items_from_snapshot",
    "scam_span_vacant_deduction",
    "early_round_vacant_metrics",
    "board_display_occupied_cells",
    "map_skill_total_hidden_cells_from_logs",
    "map_skill_hidden_cell_reserve_from_snapshot",
    "vacant_cells_from_map_skill_total_hidden",
]
