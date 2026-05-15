"""空置区计数、占位格集合与 ``grid_overlay["vacant"]`` 块计算。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Set, Tuple

from ._shape_wh import shape_wh_from_snapshot
from .fraud_empty_cells import (
    FraudPlacedItem,
    fraud_empty_cells_for_algorithm,
    fraud_placed_items_from_merged_items,
)
from .grid_overlay_dims import (
    DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID,
    GRID_COLS,
    GRID_MAX_BOX_ID,
    GRID_ROWS,
    OCCUPIED_CELL_BIDS,
)
from .grid_overlay_item_merge import merged_items_dict_from_snapshot


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
    是否对几何空置计数应用诈骗格过滤。

    当 200009 总格数已知且前缀区内占位尚未达到该总数时关闭（见
    :func:`empty_zone_ignore_fraud_filter`）；否则开启。
    """
    if not board_snapshot:
        return False
    if empty_zone_ignore_fraud_filter(occupied, limit, board_snapshot):
        return False
    return True


def compute_overlay_vacant_dict(
    *,
    occupied: set,
    max_box_id: int,
    vacant_manual_suppress: Set[Tuple[int, int]],
    board_snapshot: Optional[Dict[str, Any]] = None,
    placed_items: Optional[Sequence[FraudPlacedItem]] = None,
    fraud_empty_cells_algorithm: str = "tiling_strict",
    fraud_empty_cells_tiling_n: int = 0,
) -> Dict[str, Any]:
    """
    写入 ``grid_overlay["vacant"]`` 的块；定价与 UI 共用同一套逻辑。

    - **200009**：``raw_pricing.event_stats.total_grid_count`` 非空时，空置 = 总数 − ``len(occupied)``；
    - **几何前缀区**：否则数 0..max(BoxId) 内空格；
    - ``board_snapshot``：须含 ``raw_pricing``（200009 总格数）；``game_state`` 供合并物品表等。
    - ``placed_items``：非空时用于诈骗格判定（须与 ``occupied`` 同源）；缺省则从 ``board_snapshot`` 合并物品表构造。
    - ``fraud_empty_cells_algorithm`` / ``fraud_empty_cells_tiling_n``：见 :func:`bidking.analysis.fraud_empty_cells.fraud_empty_cells_for_algorithm`；运行时默认自 :func:`bidking.config.runtime.infer_fraud_empty_cells_algorithm_and_trim` 读取。
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
    apply_fraud_excl = fraud_zone_cell_exclusion_enabled(board_snapshot, occupied, limit)
    if apply_fraud_excl:
        if placed_items is not None:
            placed_for_fraud = list(placed_items)
        elif board_snapshot is not None:
            placed_for_fraud = fraud_placed_items_from_merged_items(
                merged_items_dict_from_snapshot(board_snapshot)
            )
        else:
            placed_for_fraud = []
        fraud_cells = fraud_empty_cells_for_algorithm(
            fraud_empty_cells_algorithm,
            occupied,
            limit,
            placed_for_fraud,
            fraud_empty_cells_tiling_n=fraud_empty_cells_tiling_n,
        )
    else:
        fraud_cells = set()
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


def _item_occupied_cells(box_id: int, shape: Any) -> set:
    w, h = shape_wh_from_snapshot(shape)
    col = box_id % GRID_COLS
    row = box_id // GRID_COLS
    cells: set = set()
    for dr in range(h):
        for dc in range(w):
            cells.add((row + dr, col + dc))
    return cells


def _occupied_cells_item_board_display(it: Dict[str, Any]) -> set:
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
            occ |= _occupied_cells_item_board_display(it)
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
    *,
    fraud_empty_cells_algorithm: Optional[str] = None,
    fraud_empty_cells_tiling_n: Optional[int] = None,
) -> Dict[str, Any]:
    """由完整画板快照计算 ``vacant`` 块；供 ``build_snapshot_pricing_dict`` 与工具链复用。"""
    from ..config.runtime import (
        infer_fraud_empty_cells_algorithm,
        infer_fraud_empty_cells_algorithm_and_trim,
        infer_fraud_empty_cells_tiling_n,
    )

    if fraud_empty_cells_algorithm is None and fraud_empty_cells_tiling_n is None:
        algo, tn = infer_fraud_empty_cells_algorithm_and_trim()
    else:
        algo = (
            fraud_empty_cells_algorithm
            if fraud_empty_cells_algorithm is not None
            else infer_fraud_empty_cells_algorithm()
        )
        tn = (
            fraud_empty_cells_tiling_n
            if fraud_empty_cells_tiling_n is not None
            else infer_fraud_empty_cells_tiling_n()
        )
    try:
        tn_i = max(0, int(tn))
    except (TypeError, ValueError):
        tn_i = 0
    return compute_overlay_vacant_dict(
        occupied=snapshot_occupied_cells(board_snapshot),
        max_box_id=max_anchor_box_id_merged(board_snapshot),
        vacant_manual_suppress=vacant_manual_suppress_cells_from_snapshot(board_snapshot),
        board_snapshot=board_snapshot,
        fraud_empty_cells_algorithm=algo,
        fraud_empty_cells_tiling_n=tn_i,
    )
