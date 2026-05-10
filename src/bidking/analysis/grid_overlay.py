"""画板 ``grid_overlay``：空置/几何空置/诈骗格分析，以及快照 ``items`` 与 overlay 的合并。

合并后的物品表供 ``_board_pricing`` 等模块做总价与占位计算，规则与 UI 写入快照一致：

- ``phantom_items``：仅补充 ``game_state.items`` 中不存在的 uid；
- ``manual_shapes``：对尚无 ``shape`` 的条目写入 ``shape = w*10+h``；
- ``manual_confirm_item_id``：按 ``item_prices.csv`` 投影 ``item_cid`` / ``quality`` / ``shape`` / ``price``。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.state import GameState, ItemKnowledge
from . import unknown_value as _unknown_value
from .scan_inference import possible_qualities_from_scan_history

GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1

# 默认轮廓推断：相对权重期望价的价带（±20%），带内再按掉落概率选形。
_INFER_DEFAULT_PRICE_BAND_REL = 0.2

# 合并物品表上无任何 BoxId 时，几何前缀空置仍需要一个上界；与定价共用 ``max_anchor_box_id_merged``。
DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID = 30

# 快照 ``grid_overlay`` 中序列化的占位格（BoxId 列表，与 UI ``_build_occupied`` 一致）
OCCUPIED_CELL_BIDS = "occupied_cell_bids"

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
        row["_overlay_shape_origin"] = "game"


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
            row["_overlay_shape_origin"] = "manual"


def apply_infer_shapes_to_items(items: Dict[str, Any], infer_shapes: Any) -> None:
    """``infer_shapes`` 与 ``manual_shapes`` 同格式；仅填补仍为 ``shape is None`` 的行（不覆盖手动画框）。"""
    if not isinstance(infer_shapes, dict):
        return
    for uid, entry in infer_shapes.items():
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
            row["_overlay_shape_origin"] = "infer"


def merged_items_dict(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    ``game_state.items`` 与 ``grid_overlay`` 合并后的定价用物品表（浅拷贝各行 dict，可原地改投影字段）。

    ``grid_overlay.infer_shapes`` 会写入几何用 ``shape``，并标记 ``_overlay_shape_origin == "infer"``；
    定价侧对推断外形按未知轮廓做多候选加权（见 :mod:`_board_pricing`）。
    """
    gs = board_snapshot.get("game_state") or {}
    raw = gs.get("items") if isinstance(gs, dict) else None
    items: Dict[str, Any] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                row = dict(v)
                if row.get("shape") is not None:
                    row["_overlay_shape_origin"] = "game"
                items[str(k)] = row
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict):
        ph = overlay.get("phantom_items")
        if isinstance(ph, dict):
            for uid, it in ph.items():
                suid = str(uid)
                if suid not in items and isinstance(it, dict):
                    prow = dict(it)
                    if prow.get("shape") is not None:
                        prow["_overlay_shape_origin"] = "game"
                    items[suid] = prow
        apply_manual_shapes_to_items(items, overlay.get("manual_shapes"))
        apply_infer_shapes_to_items(items, overlay.get("infer_shapes"))
    csv_index, _csv_items = _load_item_prices_db()
    apply_manual_confirm_projection(items, csv_index)
    return items


def merged_items_dict_from_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    优先使用 ``grid_overlay["merged_items_dict"]``（与 UI 写出一致），否则调用 :func:`merged_items_dict`。
    """
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict) and "merged_items_dict" in overlay:
        cached = overlay.get("merged_items_dict")
        if isinstance(cached, dict):
            out: Dict[str, Any] = {}
            for k, v in cached.items():
                out[str(k)] = dict(v) if isinstance(v, dict) else v
            return out
    return merged_items_dict(board_snapshot)


def total_grid_count_from_raw_pricing(raw_pricing: Any) -> Optional[int]:
    """``raw_pricing["event_stats"]["total_grid_count"]``：与技能 200009 同源，用于日志未附带时的空置总数。"""
    if not isinstance(raw_pricing, dict):
        return None
    st = raw_pricing.get("event_stats")
    if not isinstance(st, dict):
        return None
    v = st.get("total_grid_count")
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def map_skill_total_hidden_for_overlay(
    board_snapshot: Optional[Dict[str, Any]],
) -> Optional[int]:
    """
    200009 总藏品格数：仅读 ``board_snapshot["raw_pricing"].event_stats.total_grid_count``
    （由 :func:`raw_pricing.build_raw_pricing_dict` 从日志汇总；本模块不解析 ``skill_logs``）。
    """
    if not board_snapshot:
        return None
    return total_grid_count_from_raw_pricing(board_snapshot.get("raw_pricing"))


def map_skill_hidden_vacant(
    total_hidden_cells: Optional[int],
    *,
    occupied_cell_count: int,
) -> Optional[int]:
    """
    地图技能 200009 已给出总藏品格数时：空置 = 总数 − 占位（占位由调用方传入，UI 用几何格数、定价用权重格数）。
    ``total_hidden_cells`` 为空或非正时返回 ``None``（走几何前缀区逻辑）。
    """
    if total_hidden_cells is None:
        return None
    try:
        th = int(total_hidden_cells)
    except (TypeError, ValueError):
        return None
    if th <= 0:
        return None
    try:
        occ = int(occupied_cell_count)
    except (TypeError, ValueError):
        occ = 0
    occ = max(0, occ)
    return max(0, th - occ)


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


def fraud_exclusion_eligible_from_scan(board_snapshot: Dict[str, Any]) -> bool:
    """
    扫描推断下「剩余未知品质」是否仅为金红（Q5/Q6）。

    仅在此条件下对空置候选应用 ``fraud_empty_cells_in_zone_prefix`` 剔除（诈骗格）；
    若仍可能为 Q1–Q4，则不剔除，避免早期误判。
    """
    poss = possible_qualities_from_scan_history(board_snapshot)
    if not poss:
        return False
    return bool(poss <= frozenset({5, 6}))


def empty_zone_ignore_fraud_filter(
    occupied: set,
    limit: int,
    board_snapshot: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    200009 总格数已知，且前缀区 ``0..limit`` 内占位格数尚未达到该总数时：不应用诈骗格剔除。
    总数来自 ``board_snapshot["raw_pricing"]``（见 :func:`map_skill_total_hidden_for_overlay`）。
    """
    total_h = map_skill_total_hidden_for_overlay(board_snapshot)
    if total_h is None:
        return False
    return occupied_cells_in_empty_zone_prefix(occupied, limit) < total_h


def fraud_zone_cell_exclusion_enabled(
    board_snapshot: Optional[Dict[str, Any]],
    occupied: set,
    limit: int,
) -> bool:
    """
    是否对几何空置计数应用诈骗格过滤：200009 吃满后 **且** 扫描上仅剩金红候选时。
    """
    if not board_snapshot:
        return False
    if empty_zone_ignore_fraud_filter(occupied, limit, board_snapshot):
        return False
    return fraud_exclusion_eligible_from_scan(board_snapshot)


def _map_id_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    gs = board_snapshot.get("game_state")
    mid = None
    if isinstance(gs, dict):
        mid = gs.get("map_id")
    if mid is None:
        mid = board_snapshot.get("map_id")
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


def _parse_shape_int_overlay(shape: Any) -> Optional[int]:
    if shape is None:
        return None
    if isinstance(shape, int):
        return shape
    try:
        return int(shape)
    except (TypeError, ValueError):
        s = str(shape)
        if len(s) == 2 and s.isdigit():
            return int(s)
        return None


def _csv_cells_raw_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, float]:
    raw = board_snapshot.get("raw_pricing") if isinstance(board_snapshot, dict) else None
    raw_csv = raw.get("csv_quality_groups_avg_per_cell") if isinstance(raw, dict) else None
    out: Dict[str, float] = {}
    if isinstance(raw_csv, dict):
        try:
            out = {str(k): float(v) for k, v in raw_csv.items()}
        except (TypeError, ValueError):
            out = {}
    return out

def compute_overlay_vacant_dict(
    *,
    occupied: set,
    max_box_id: int,
    vacant_manual_suppress: Set[Tuple[int, int]],
    board_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    写入 ``grid_overlay["vacant"]`` 的块；定价与 UI 共用同一套逻辑。

    - **200009**：``raw_pricing.event_stats.total_grid_count`` 非空时，空置 = 总数 − ``len(occupied)``；
    - **几何前缀区**：否则数 0..max(BoxId) 内空格；
    - ``board_snapshot``：须含 ``raw_pricing``（及 ``game_state.scan_history`` 供金红候选判断）。
    """
    total_h = map_skill_total_hidden_for_overlay(board_snapshot)
    if total_h is not None:
        sv = map_skill_hidden_vacant(total_h, occupied_cell_count=len(occupied))
        if sv is not None:
            sv_i = int(sv)
            return {
                "geometric": sv_i,
                "source": "map_skill_total_hidden_minus_occupied",
            }
    if max_box_id < 0:
        return {
            "geometric": None,
            "source": "no_confirmed_anchor",
        }
    limit = min(max_box_id, GRID_MAX_BOX_ID)
    fraud_cells = fraud_empty_cells_in_zone_prefix(occupied, limit)
    apply_fraud_excl = fraud_zone_cell_exclusion_enabled(board_snapshot, occupied, limit)
    count = 0
    for bid in range(limit + 1):
        row, col = bid // GRID_COLS, bid % GRID_COLS
        if (row, col) not in occupied:
            if (row, col) in vacant_manual_suppress:
                continue
            if apply_fraud_excl and (row, col) in fraud_cells:
                continue
            count += 1
    return {
        "geometric": int(count),
        "source": "geometric_empty_zone",
    }


def _live_shape_wh(shape: Any) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1


def build_occupied_cells(
    *,
    items: Mapping[str, Any],
    phantom_items: Mapping[str, Any],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    exclude_uid: str = "",
    item_shape_wh: Optional[Callable[[str, Any], Tuple[int, int]]] = None,
    item_origin: Optional[Callable[[str, Any], Tuple[int, int]]] = None,
) -> Set[Tuple[int, int]]:
    """
    与 ``GridWindow._build_occupied`` 相同规则：已确认或手动画框的日志物品占矩形，
    幽灵占手动矩形，未确认且无手动画框的日志物品至少占锚格。
    若传入 ``item_shape_wh`` / ``item_origin``（界面侧 ``_effective_*``），则与画板绘制完全一致；
    否则仅用 ``shape`` 字段与 BoxId 推断（快照回放等）。
    """
    occupied: Set[Tuple[int, int]] = set()
    for uid, k in items.items():
        if uid == exclude_uid:
            continue
        bid = getattr(k, "box_id", None)
        if bid is None:
            continue
        if not getattr(k, "box_id_confirmed", False) and uid not in manual_shapes:
            continue
        if uid in manual_shapes:
            w, h, dc, dr = manual_shapes[uid]
        else:
            if item_shape_wh is not None:
                w, h = item_shape_wh(uid, k)
            else:
                w, h = _live_shape_wh(getattr(k, "shape", None))
            if item_origin is not None:
                dc, dr = item_origin(uid, k)
            else:
                ib = int(bid)
                dc, dr = ib % GRID_COLS, ib // GRID_COLS
        for ddr in range(h):
            for ddc in range(w):
                occupied.add((dr + ddr, dc + ddc))
    for phid in phantom_items:
        if phid == exclude_uid or phid not in manual_shapes:
            continue
        w, h, dc, dr = manual_shapes[phid]
        for ddr in range(h):
            for ddc in range(w):
                occupied.add((dr + ddr, dc + ddc))
    for uid, k in items.items():
        if uid == exclude_uid:
            continue
        bid = getattr(k, "box_id", None)
        if bid is None:
            continue
        if getattr(k, "box_id_confirmed", False) or uid in manual_shapes:
            continue
        b = int(bid)
        occupied.add((b // GRID_COLS, b % GRID_COLS))
    return occupied


def snapshot_occupied_cells(board_snapshot: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """
    画板占位格：优先 ``grid_overlay[occupied_cell_bids]``（快照写出时与 UI 一致），
    否则回退 ``board_display_occupied_cells_merged``（兼容旧快照）。
    """
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict) and OCCUPIED_CELL_BIDS in overlay:
        bids = overlay.get(OCCUPIED_CELL_BIDS)
        if isinstance(bids, list):
            out: Set[Tuple[int, int]] = set()
            for b in bids:
                try:
                    bid = int(b)
                except (TypeError, ValueError):
                    continue
                if bid < 0 or bid > GRID_MAX_BOX_ID:
                    continue
                out.add((bid // GRID_COLS, bid % GRID_COLS))
            return out
    return board_display_occupied_cells_merged(board_snapshot)


def board_display_occupied_cells_merged(board_snapshot: Dict[str, Any]) -> set:
    """
    画板几何占位（与空置区计数一致）：基于 ``merged_items_dict``，
    含手动画框补全的 ``shape``、幽灵物品等。
    """
    items = merged_items_dict_from_snapshot(board_snapshot)
    if not isinstance(items, dict) or not items:
        return set()
    occ: set = set()
    for it in items.values():
        if not isinstance(it, dict) or it.get("box_id") is None:
            continue
        try:
            int(it["box_id"])
        except (TypeError, ValueError):
            continue
        if it.get("box_id_confirmed"):
            occ |= _occupied_cells_item_board_display(it, board_snapshot)
    for it in items.values():
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


def max_anchor_box_id_merged(board_snapshot: Dict[str, Any]) -> int:
    """
    合并物品表上任意有效 BoxId 的最大锚点（含仅日志未确认的锚格）。

    无任何有效 ``box_id`` 时返回 :data:`DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID`（30），供几何前缀空置
    与定价管线使用，避免 ``max_box_id < 0`` 无法数格。
    """
    items = merged_items_dict_from_snapshot(board_snapshot)
    max_b = -1
    for it in items.values():
        if not isinstance(it, dict):
            continue
        bid = it.get("box_id")
        if bid is None:
            continue
        try:
            b = int(bid)
        except (TypeError, ValueError):
            continue
        max_b = max(max_b, b)
    if max_b < 0:
        return int(DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID)
    return max_b


def vacant_block_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """优先使用快照已写出的 ``grid_overlay["vacant"]``，否则由 :func:`vacant_dict_from_board_snapshot` 计算。"""
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict):
        vb = overlay.get("vacant")
        if isinstance(vb, dict) and "source" in vb:
            return vb
    return vacant_dict_from_board_snapshot(board_snapshot)


def vacant_manual_suppress_cells_from_snapshot(board_snapshot: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """``grid_overlay.vacant_manual_suppress_bids`` → ``(row, col)`` 集合。"""
    overlay = board_snapshot.get("grid_overlay") or {}
    bids = overlay.get("vacant_manual_suppress_bids") or []
    out: Set[Tuple[int, int]] = set()
    if not isinstance(bids, list):
        return out
    for b in bids:
        try:
            bid = int(b)
        except (TypeError, ValueError):
            continue
        r, c = bid // GRID_COLS, bid % GRID_COLS
        out.add((r, c))
    return out


def vacant_dict_from_board_snapshot(
    board_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """由完整画板快照计算 ``vacant`` 块；供 ``build_snapshot_pricing_dict`` 与工具链复用。"""
    return compute_overlay_vacant_dict(
        occupied=snapshot_occupied_cells(board_snapshot),
        max_box_id=max_anchor_box_id_merged(board_snapshot),
        vacant_manual_suppress=vacant_manual_suppress_cells_from_snapshot(board_snapshot),
        board_snapshot=board_snapshot,
    )


def _event_stats_q14_grid_counts_all_known(raw: Any) -> bool:
    """与 ``_board_pricing._event_stats_q14_grid_counts_all_known`` 一致（避免循环 import）。"""
    if not isinstance(raw, dict):
        return False
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return False
    for k in ("q1_grid_count", "q2_grid_count", "q3_grid_count", "q4_grid_count"):
        if st.get(k) is None:
            return False
    return True


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


def _infer_greedy_rect_ud_then_lr(
    ar: int,
    ac: int,
    occupied: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Tuple[int, int, int, int]:
    """先上下扩至最大，再左右扩至最大（锚格 ``(ar,ac)`` 含于矩形内）。"""
    r1, r2 = ar, ar
    while r1 > 0 and _infer_rect_feasible(r1 - 1, ac, r2, ac, occupied, suppress, max_bid):
        r1 -= 1
    while r2 + 1 < GRID_ROWS and _infer_rect_feasible(r1, ac, r2 + 1, ac, occupied, suppress, max_bid):
        r2 += 1
    c1, c2 = ac, ac
    while c1 > 0 and _infer_rect_feasible(r1, c1 - 1, r2, c2, occupied, suppress, max_bid):
        c1 -= 1
    while c2 + 1 < GRID_COLS and _infer_rect_feasible(r1, c1, r2, c2 + 1, occupied, suppress, max_bid):
        c2 += 1
    return r1, c1, r2, c2


def _infer_greedy_rect_lr_then_ud(
    ar: int,
    ac: int,
    occupied: Set[Tuple[int, int]],
    suppress: Set[Tuple[int, int]],
    max_bid: int,
) -> Tuple[int, int, int, int]:
    """先左右扩至最大，再上下扩至最大。"""
    c1, c2 = ac, ac
    while c1 > 0 and _infer_rect_feasible(ar, c1 - 1, ar, c2, occupied, suppress, max_bid):
        c1 -= 1
    while c2 + 1 < GRID_COLS and _infer_rect_feasible(ar, c1, ar, c2 + 1, occupied, suppress, max_bid):
        c2 += 1
    r1, r2 = ar, ar
    while r1 > 0 and _infer_rect_feasible(r1 - 1, c1, r2, c2, occupied, suppress, max_bid):
        r1 -= 1
    while r2 + 1 < GRID_ROWS and _infer_rect_feasible(r1, c1, r2 + 1, c2, occupied, suppress, max_bid):
        r2 += 1
    return r1, c1, r2, c2


def _infer_pick_wh_from_candidates(
    candidates: List[Any],
    map_category_weights: Optional[Dict[int, float]],
    map_id_n: Optional[int],
) -> Optional[Tuple[int, int]]:
    """
    多候选时：先在权重期望价 ±:data:`_INFER_DEFAULT_PRICE_BAND_REL` 价带内的候选中取掉落概率最高者；
    价带内无候选（或无法得到正期望价）时，回退为在全候选中按概率选优（概率相同则价更接近期望、再 ``item_id``）。
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return _shape_wh_from_snapshot(candidates[0].shape)
    est = item_db._weighted_est_price(candidates, map_category_weights, map_id_n)
    probs = item_db.candidate_probabilities(candidates, map_category_weights, map_id_n)

    def _pick_best(pool: List[Any]) -> Any:
        best_c: Any = None
        best_key: Optional[Tuple[float, float, int]] = None
        for c in pool:
            p = float(probs.get(c.item_id, 0.0))
            dist = (
                abs(float(c.base_value) - float(est))
                if est is not None and float(est) > 0
                else 0.0
            )
            key = (-p, dist, int(c.item_id))
            if best_key is None or key < best_key:
                best_key = key
                best_c = c
        return best_c

    if est is not None and float(est) > 0:
        e = float(est)
        band = _INFER_DEFAULT_PRICE_BAND_REL
        lo, hi = e * (1.0 - band), e * (1.0 + band)
        in_band = [c for c in candidates if lo <= float(c.base_value) <= hi]
        if in_band:
            best = _pick_best(in_band)
            if best is not None:
                return _shape_wh_from_snapshot(best.shape)

    best = _pick_best(candidates)
    if best is None:
        return None
    return _shape_wh_from_snapshot(best.shape)


def _infer_ordered_wh_for_default_infer(
    filt: List[Any],
    map_category_weights: Optional[Dict[int, float]],
    map_id_n: Optional[int],
) -> List[Tuple[int, int]]:
    """
    默认推断路径下依次尝试的 ``(w,h)``：
    先 :func:`_infer_pick_wh_from_candidates`，再按各外形对应候选的最高掉落概率降序尝试其余外形。
    """
    primary = _infer_pick_wh_from_candidates(filt, map_category_weights, map_id_n)
    probs = item_db.candidate_probabilities(filt, map_category_weights, map_id_n)
    by_wh: Dict[Tuple[int, int], float] = {}
    for c in filt:
        wh = _shape_wh_from_snapshot(c.shape)
        if wh is None:
            continue
        p = float(probs.get(c.item_id, 0.0))
        by_wh[wh] = max(by_wh.get(wh, 0.0), p)
    ranked = sorted(by_wh.keys(), key=lambda wh: (-by_wh[wh], wh))
    out: List[Tuple[int, int]] = []
    if primary is not None:
        out.append(primary)
    for wh in ranked:
        if wh not in out:
            out.append(wh)
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
    默认推断路径下矩形左上角 ``(dr, dc)``（行、列）候选。

    ``box_id_confirmed=True`` 时 BoxId 为顶左格，仅 ``(ar, ac)``；
    否则 BoxId 仅为占格内某一命中格（见 :class:`ItemKnowledge`），枚举所有使 ``(ar,ac)``
    落在 ``w×h`` 矩形内的顶左，按 ``(dr, dc)`` 字典序优先以便稳定输出。
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


def compute_grid_overlay_infer_shapes(
    *,
    game_state: GameState,
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    occupied_cells: Set[Tuple[int, int]],
    vacant_manual_suppress: Set[Tuple[int, int]],
    max_box_id: int,
    raw_pricing: Dict[str, Any],
) -> Dict[str, List[int]]:
    """
    对 **品质已知、轮廓未知** 且未手动画框的日志物品，估计 ``[w,h,dc,dr]``（与 ``manual_shapes`` 同形）。

    - 默认：在权重期望价 ±20% 价带内的 CSV 候选中取掉落概率最高者定 ``(w,h)``；
      价带为空时回退为全候选按概率。
      **原点**：``box_id_confirmed`` 时 BoxId 即顶左；**未确认** 时 BoxId 仅为占格内某一命中格，
      枚举所有包含该格的 ``w×h`` 顶左位置，再按阻挡约束取可行解（``(dr,dc)`` 字典序优先）。
      矩形须完全落在 ``max_box_id`` 前缀区内，且不与 ``vacant_manual_suppress`` 相交；
      与其它物品的冲突：基底占位中他人的锚格/已确认格 **以及** 本轮中先前物品已推断出的矩形并集；
      仅允许覆盖当前物品自身的基底占位格（通常为锚格），但若该格已被先前推断占用则不可再放。
      首选外形不满足时按掉落概率依次尝试其余候选外形，仍无解则跳过该件推断。
    - 当 ``raw_pricing.event_stats`` 中 q1–q4 各档 ``q*_grid_count`` 均已给出，且扫描史已覆盖品质
      1–4、场上 Q1–Q4 物品轮廓与锚格均已锁定时：对 **金 (5)、红 (6)** 用两种贪心延展矩形
      （先上下后左右 / 先左右后上下），在上述阻挡语义与 ``max_box_id`` 约束下取 **面积较大** 者；
      金优先于红；每推断成功一件即将其矩形并入后续件的阻挡集。
    """
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return {}
    mid_raw = int(game_state.map_id or 0) or None
    mid_n = item_db.normalize_map_id(mid_raw)
    map_w = item_db.map_category_ratios(mid_raw) if mid_raw else None
    if not map_w:
        map_w = None

    use_rect_q56 = _event_stats_q14_grid_counts_all_known(raw_pricing) and _infer_q1234_scan_and_q14_contours_ready(
        game_state, manual_shapes
    )
    sup = set(vacant_manual_suppress)
    mx = int(max_box_id)
    baseline_occ: Set[Tuple[int, int]] = set(occupied_cells)
    inferred_occ: Set[Tuple[int, int]] = set()

    targets: List[Tuple[str, ItemKnowledge, int]] = []
    for uid, k in game_state.items.items():
        if not _infer_unknown_contour_item_eligible(k, uid, manual_shapes):
            continue
        try:
            q = int(k.quality or 0)
        except (TypeError, ValueError):
            continue
        targets.append((str(uid), k, q))

    def _sort_key(t: Tuple[str, ItemKnowledge, int]) -> Tuple[int, int, str]:
        u, k, qq = t
        bid = int(k.box_id or 0)
        if use_rect_q56 and qq == 5:
            return (0, bid, u)
        if use_rect_q56 and qq == 6:
            return (1, bid, u)
        return (2, qq, bid, u)

    targets.sort(key=_sort_key)
    out: Dict[str, List[int]] = {}
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
        )
        if not filt:
            continue
        bid_i = int(k.box_id)
        ar, ac = bid_i // GRID_COLS, bid_i % GRID_COLS
        self_base = _infer_base_occupied_cells_for_uid(uid, k, manual_shapes)
        pseudo_blocked = _infer_pseudo_blocked(baseline_occ, inferred_occ, self_base)
        if use_rect_q56 and q in (5, 6):
            r1a, c1a, r2a, c2a = _infer_greedy_rect_ud_then_lr(ar, ac, pseudo_blocked, sup, mx)
            r1b, c1b, r2b, c2b = _infer_greedy_rect_lr_then_ud(ar, ac, pseudo_blocked, sup, mx)
            area_a = (r2a - r1a + 1) * (c2a - c1a + 1)
            area_b = (r2b - r1b + 1) * (c2b - c1b + 1)
            if area_a >= area_b:
                r1, c1, r2, c2 = r1a, c1a, r2a, c2a
            else:
                r1, c1, r2, c2 = r1b, c1b, r2b, c2b
            w = c2 - c1 + 1
            h = r2 - r1 + 1
            out[uid] = [w, h, int(c1), int(r1)]
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    inferred_occ.add((r, c))
        else:
            confirmed_tl = bool(getattr(k, "box_id_confirmed", False))
            chosen_tpl: Optional[Tuple[int, int, int, int]] = None
            for w, h in _infer_ordered_wh_for_default_infer(filt, map_w, mid_n):
                for dr, dc in _infer_default_placement_candidates(
                    ar, ac, w, h, box_id_confirmed=confirmed_tl
                ):
                    if _infer_rect_feasible(dr, dc, dr + h - 1, dc + w - 1, pseudo_blocked, sup, mx):
                        chosen_tpl = (w, h, dr, dc)
                        break
                if chosen_tpl is not None:
                    break
            if chosen_tpl is None:
                continue
            w, h, dr, dc = chosen_tpl
            out[uid] = [w, h, int(dc), int(dr)]
            for ddr in range(h):
                for ddc in range(w):
                    inferred_occ.add((dr + ddr, dc + ddc))
    occupied_cells.clear()
    occupied_cells.update(baseline_occ)
    occupied_cells.update(inferred_occ)
    return out


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
    "DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID",
    "OCCUPIED_CELL_BIDS",
    "apply_infer_shapes_to_items",
    "apply_manual_confirm_projection",
    "apply_manual_shapes_to_items",
    "board_display_occupied_cells",
    "board_display_occupied_cells_merged",
    "build_occupied_cells",
    "cell_four_cardinal_neighbors_unoccupied",
    "column_downward_all_vacant",
    "compute_overlay_vacant_dict",
    "compute_grid_overlay_infer_shapes",
    "confirmed_items_from_snapshot",
    "empty_zone_ignore_fraud_filter",
    "fraud_empty_cells_in_zone_prefix",
    "fraud_exclusion_eligible_from_scan",
    "fraud_zone_cell_exclusion_enabled",
    "map_skill_hidden_vacant",
    "map_skill_hidden_cell_reserve_from_snapshot",
    "map_skill_total_hidden_for_overlay",
    "max_anchor_box_id_merged",
    "merged_items_dict",
    "merged_items_dict_from_snapshot",
    "occupied_cells_in_empty_zone_prefix",
    "scam_span_vacant_deduction",
    "snapshot_occupied_cells",
    "total_grid_count_from_raw_pricing",
    "vacant_block_from_board_snapshot",
    "vacant_dict_from_board_snapshot",
    "vacant_manual_suppress_cells_from_snapshot",
    "vacant_neighbor_occupied",
    "vacant_side_effective_blocks",
]
