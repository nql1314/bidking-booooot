"""画板 ``grid_overlay``：空置/几何空置/诈骗格分析，以及快照 ``items`` 与 overlay 的合并。

合并后的物品表供 ``_board_pricing`` 等模块做总价与占位计算，规则与 UI 写入快照一致：

- ``phantom_items``：仅补充 ``game_state.items`` 中不存在的 uid；
- ``manual_shapes``：对尚无 ``shape`` 的条目写入 ``shape = w*10+h``；
- ``manual_confirm_item_id``：按 ``item_prices.csv`` 投影 ``item_cid`` / ``quality`` / ``shape`` / ``price``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.constants import MAP_SKILL_TOTAL_HIDDEN_CELLS
from . import unknown_value as _unknown_value

GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    path = _unknown_value._item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache


def _parse_manual_shape_entry(entry: Any) -> Optional[Tuple[int, int, int, int]]:
    if isinstance(entry, (list, tuple)) and len(entry) >= 4:
        try:
            return int(entry[0]), int(entry[1]), int(entry[2]), int(entry[3])
        except (TypeError, ValueError):
            return None
    if isinstance(entry, dict):
        try:
            return (
                int(entry["w"]),
                int(entry["h"]),
                int(entry["dc"]),
                int(entry["dr"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _shape_int_from_wh(w: int, h: int) -> Optional[int]:
    if 1 <= w <= 9 and 1 <= h <= 9:
        return w * 10 + h
    return None


def apply_manual_confirm_projection(
    items: Dict[str, Any],
    csv_index: Dict[int, Any],
) -> None:
    """将 ``manual_confirm_item_id`` 投影为定价用 ``item_cid`` / ``quality`` / ``shape`` / ``price``。"""
    for row in items.values():
        if not isinstance(row, dict):
            continue
        cid = row.get("manual_confirm_item_id")
        if not cid:
            continue
        try:
            item = csv_index.get(int(cid))
        except (TypeError, ValueError):
            item = None
        if item is None:
            continue
        row["item_cid"] = int(item.item_id)
        row["quality"] = int(item.quality)
        row["shape"] = int(item.shape)
        row["price"] = int(item.base_value)


def apply_manual_shapes_to_items(items: Dict[str, Any], manual_shapes: Any) -> None:
    if not isinstance(manual_shapes, dict):
        return
    for uid, entry in manual_shapes.items():
        uid_s = str(uid)
        tup = _parse_manual_shape_entry(entry)
        if tup is None:
            continue
        w, h = tup[0], tup[1]
        sh = _shape_int_from_wh(w, h)
        if sh is None:
            continue
        row = items.get(uid_s)
        if isinstance(row, dict) and row.get("shape") is None:
            row["shape"] = sh


def merged_items_dict(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    ``game_state.items`` 与 ``grid_overlay`` 合并后的定价用物品表（浅拷贝各行 dict，可原地改投影字段）。
    """
    gs = board_snapshot.get("game_state") or {}
    raw = gs.get("items") if isinstance(gs, dict) else None
    items: Dict[str, Any] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                items[str(k)] = dict(v)
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict):
        ph = overlay.get("phantom_items")
        if isinstance(ph, dict):
            for uid, it in ph.items():
                suid = str(uid)
                if suid not in items and isinstance(it, dict):
                    items[suid] = dict(it)
        apply_manual_shapes_to_items(items, overlay.get("manual_shapes"))
    csv_index, _csv_items = _load_item_prices_db()
    apply_manual_confirm_projection(items, csv_index)
    return items


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


def vacant_neighbor_occupied(row: int, col: int, occupied: set) -> bool:
    """邻居是否在网格外（视同阻挡）或已被物品/幽灵占用。"""
    if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
        return True
    return (row, col) in occupied


def vacant_side_effective_blocks(row: int, col: int, occupied: set, *, left: bool) -> bool:
    """中间空格某一侧是否构成「有效夹挡」（与 GridWindow 橘红层规则一致）。"""
    if left:
        if col <= 0:
            return True
        nc = col - 1
    else:
        if col >= GRID_COLS - 1:
            return True
        nc = col + 1
    if vacant_neighbor_occupied(row, nc, occupied):
        return True
    if row > 0 and not vacant_neighbor_occupied(row - 1, nc, occupied):
        return True
    return False


def cell_four_cardinal_neighbors_unoccupied(row: int, col: int, occupied: set) -> bool:
    """上下左右四格均在网内且未被物品/幽灵占用。"""
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = row + dr, col + dc
        if not (0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS):
            return False
        if (nr, nc) in occupied:
            return False
    return True


def column_downward_all_vacant(row: int, col: int, occupied: set) -> bool:
    """自 (row+1,col) 起至网格底，同列是否全部未占位。"""
    for rr in range(row + 1, GRID_ROWS):
        if (rr, col) in occupied:
            return False
    return True


def fraud_empty_cells_in_zone_prefix(occupied: set, limit: int) -> Set[Tuple[int, int]]:
    """BoxId 0..limit 内应排除的空置候选（诈骗格）集合。"""
    fraud: Set[Tuple[int, int]] = set()
    last_bid = limit

    for bid in range(last_bid + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if (r, c) in occupied:
            continue
        if c != 0 and c != GRID_COLS - 1:
            continue
        inward_occ = (
            (c == 0 and (r, 1) in occupied)
            or (c == GRID_COLS - 1 and (r, GRID_COLS - 2) in occupied)
        )
        if not inward_occ:
            continue
        if not column_downward_all_vacant(r, c, occupied):
            continue
        for rr in range(r, GRID_ROWS):
            if rr * GRID_COLS + c > last_bid:
                break
            if (rr, c) not in occupied:
                fraud.add((rr, c))

    for bid in range(last_bid + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if (r, c) in occupied:
            continue
        if not cell_four_cardinal_neighbors_unoccupied(r, c, occupied):
            continue
        if not column_downward_all_vacant(r, c, occupied):
            continue
        fraud.add((r, c))

    for bid in range(last_bid + 1):
        r, c = bid // GRID_COLS, bid % GRID_COLS
        if (r, c) in occupied:
            continue
        if not (r > 0 and (r - 1, c) in occupied):
            continue
        if r >= GRID_ROWS - 1:
            continue
        bid_below = (r + 1) * GRID_COLS + c
        if bid_below <= last_bid:
            continue
        if not (
            vacant_side_effective_blocks(r, c, occupied, left=True)
            and vacant_side_effective_blocks(r, c, occupied, left=False)
        ):
            continue
        fraud.add((r, c))

    return fraud


def occupied_cells_in_empty_zone_prefix(occupied: set, limit: int) -> int:
    """BoxId 0..limit（含）内已被物品/幽灵占用的格数。"""
    n = 0
    for (r, c) in occupied:
        if not (0 <= r < GRID_ROWS and 0 <= c < GRID_COLS):
            continue
        if r * GRID_COLS + c > limit:
            continue
        n += 1
    return n


def empty_zone_ignore_fraud_filter(skill_logs: List[dict], occupied: set, limit: int) -> bool:
    """
    地图技能 200009 已揭示，且已知区内占位尚未达到该总数时，
    空置计数与橘红层不应用诈骗格过滤；吃满后恢复诈骗规则。
    """
    n = map_skill_total_hidden_cells_from_logs(skill_logs)
    if n is None:
        return False
    o_zone = occupied_cells_in_empty_zone_prefix(occupied, limit)
    return o_zone < n


def compute_overlay_vacant_dict(
    *,
    current_round: int,
    min_round_show_empty: int,
    skill_logs: List[dict],
    occupied: set,
    max_box_id: int,
    vacant_manual_suppress: Set[Tuple[int, int]],
) -> Dict[str, Any]:
    """
    写入 ``grid_overlay["vacant"]`` 的块；由 UI 在刷新 overlay 时调用。

    - ``effective_count``：与画板「空置」提示一致的有效格数；未到起始回合或无锚点时为 ``null``。
    - ``geometric``：与 effective 相同含义下的几何值（技能路径与 effective 一致）。
    - ``source``：``map_skill_total_hidden_minus_occupied`` | ``geometric_empty_zone`` | …
    """
    if current_round < min_round_show_empty:
        return {
            "effective_count": None,
            "geometric": None,
            "source": "before_min_round",
        }
    skill_vacant = vacant_cells_from_map_skill_total_hidden(
        skill_logs, occupied_cell_count=len(occupied)
    )
    if skill_vacant is not None:
        sv = int(skill_vacant)
        return {
            "effective_count": sv,
            "geometric": sv,
            "source": "map_skill_total_hidden_minus_occupied",
        }
    if max_box_id < 0:
        return {
            "effective_count": None,
            "geometric": None,
            "source": "no_confirmed_anchor",
        }
    limit = min(max_box_id, GRID_MAX_BOX_ID)
    apply_fraud = not empty_zone_ignore_fraud_filter(skill_logs, occupied, limit)
    fraud_cells = fraud_empty_cells_in_zone_prefix(occupied, limit)
    count = 0
    for bid in range(limit + 1):
        row, col = bid // GRID_COLS, bid % GRID_COLS
        if (row, col) not in occupied:
            if (row, col) in vacant_manual_suppress:
                continue
            if apply_fraud and (row, col) in fraud_cells:
                continue
            count += 1
    return {
        "effective_count": int(count),
        "geometric": int(count),
        "source": "geometric_empty_zone",
    }


def resolve_pricing_vacant(
    board_snapshot: Dict[str, Any],
    *,
    occupied_cell_count: int,
) -> Tuple[int, Optional[int], str]:
    """
    供 ``build_snapshot_pricing_dict`` 使用：优先地图技能 200009，其次 ``grid_overlay.vacant``，
    再次历史 ``pricing.vacant_geometric``，否则 0。逻辑集中在 :mod:`grid_overlay` 模块。
    """
    skill_logs = list(board_snapshot.get("skill_logs") or [])
    skill_v = vacant_cells_from_map_skill_total_hidden(
        skill_logs, occupied_cell_count=occupied_cell_count
    )
    if skill_v is not None:
        sv = int(skill_v)
        return sv, sv, "map_skill_total_hidden_minus_occupied"

    overlay = board_snapshot.get("grid_overlay") or {}
    vb = overlay.get("vacant")
    if isinstance(vb, dict):
        ec = vb.get("effective_count")
        if ec is None:
            ec = vb.get("count")
        if ec is not None:
            try:
                n = max(0, int(ec))
            except (TypeError, ValueError):
                n = 0
            geo = vb.get("geometric")
            try:
                geo_i = int(geo) if geo is not None else n
            except (TypeError, ValueError):
                geo_i = n
            return n, geo_i, str(vb.get("source") or "grid_overlay")

    prev = board_snapshot.get("pricing") if isinstance(board_snapshot.get("pricing"), dict) else {}
    raw_g = prev.get("vacant_geometric")
    try:
        n = max(0, int(raw_g or 0))
    except (TypeError, ValueError):
        n = 0
    geo_out: Optional[int]
    try:
        geo_out = int(raw_g) if raw_g is not None else None
    except (TypeError, ValueError):
        geo_out = None
    return n, geo_out, "snapshot_pricing_fallback"


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
    "apply_manual_confirm_projection",
    "apply_manual_shapes_to_items",
    "cell_four_cardinal_neighbors_unoccupied",
    "column_downward_all_vacant",
    "compute_overlay_vacant_dict",
    "confirmed_items_from_snapshot",
    "empty_zone_ignore_fraud_filter",
    "fraud_empty_cells_in_zone_prefix",
    "early_round_vacant_metrics",
    "board_display_occupied_cells",
    "map_skill_total_hidden_cells_from_logs",
    "map_skill_hidden_cell_reserve_from_snapshot",
    "merged_items_dict",
    "occupied_cells_in_empty_zone_prefix",
    "resolve_pricing_vacant",
    "scam_span_vacant_deduction",
    "vacant_cells_from_map_skill_total_hidden",
    "vacant_neighbor_occupied",
    "vacant_side_effective_blocks",
]
