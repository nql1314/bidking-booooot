"""空置前缀区内「疑似诈骗格」判定（铺板可解释性等）。

与画板 ``grid_overlay`` 共用棋盘尺寸常量（须与 :data:`bidking.analysis.grid_overlay.GRID_COLS` /
:data:`~bidking.analysis.grid_overlay.GRID_ROWS` 一致）；本模块在部分入口使用对 ``grid_overlay`` 的
惰性 import，以避免与 ``grid_overlay`` 的相互引用形成循环依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ._shape_wh import shape_wh_from_snapshot

# 须与 bidking.analysis.grid_overlay 中 GRID_COLS / GRID_ROWS 保持一致
_GRID_COLS = 10
_GRID_ROWS = 30


@dataclass(frozen=True)
class FraudPlacedItem:
    """与画板占位同源的已放置物品矩形，供诈骗格可解释性判定。"""

    cells: frozenset[tuple[int, int]]
    w: int
    h: int
    min_bid: int
    anchor_bid: int  # 盘面 ``box_id``（顶左锚格 bid），与 ``manual_shapes`` 顶左或合并表一致


def fraud_placed_items_from_merged_items(
    items: Mapping[str, Any],
) -> List[FraudPlacedItem]:
    """由合并物品表行（快照/UI 同源）构造 :class:`FraudPlacedItem` 列表。"""
    from . import grid_overlay_dims as _dims
    from . import grid_overlay_vacant_zone as _gv

    out: List[FraudPlacedItem] = []
    for row in items.values():
        if not isinstance(row, dict):
            continue
        cell_set = _gv._occupied_cells_item_board_display(row)
        if not cell_set:
            continue
        w, h = shape_wh_from_snapshot(row.get("shape"))
        cells = frozenset(cell_set)
        min_bid = min(r * _dims.GRID_COLS + c for r, c in cells)
        bid_raw = row.get("box_id")
        try:
            anchor_bid = int(bid_raw) if bid_raw is not None else min_bid
        except (TypeError, ValueError):
            anchor_bid = min_bid
        out.append(
            FraudPlacedItem(
                cells=cells, w=w, h=h, min_bid=min_bid, anchor_bid=anchor_bid
            )
        )
    return out


def fraud_placed_items_from_build_occupied_like(
    *,
    items: Mapping[str, Any],
    phantom_items: Mapping[str, Any],
    manual_shapes: Mapping[str, Tuple[int, int, int, int]],
    exclude_uid: str = "",
    item_shape_wh: Optional[Callable[[str, Any], Tuple[int, int]]] = None,
    item_origin: Optional[Callable[[str, Any], Tuple[int, int]]] = None,
) -> List[FraudPlacedItem]:
    """与 :func:`bidking.analysis.grid_overlay.build_occupied_cells` 相同规则，按件输出矩形（用于与 ``occupied`` 严格一致）。"""
    from . import grid_overlay_dims as _dims
    from . import grid_overlay_vacant_zone as _gv

    gc = _dims.GRID_COLS
    out: List[FraudPlacedItem] = []
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
                w, h = _gv._live_shape_wh(getattr(k, "shape", None))
            if item_origin is not None:
                dc, dr = item_origin(uid, k)
            else:
                ib = int(bid)
                dc, dr = ib % gc, ib // gc
        cells = frozenset((dr + ddr, dc + ddc) for ddr in range(h) for ddc in range(w))
        min_bid = min(r * gc + c for r, c in cells)
        anchor_bid = int(bid)
        out.append(
            FraudPlacedItem(
                cells=cells, w=w, h=h, min_bid=min_bid, anchor_bid=anchor_bid
            )
        )
    for phid in phantom_items:
        if phid == exclude_uid or phid not in manual_shapes:
            continue
        w, h, dc, dr = manual_shapes[phid]
        pk = phantom_items[phid]
        cells = frozenset((dr + ddr, dc + ddc) for ddr in range(h) for ddc in range(w))
        min_bid = min(r * gc + c for r, c in cells)
        bph = getattr(pk, "box_id", None)
        if bph is not None:
            anchor_bid = int(bph)
        else:
            anchor_bid = dr * gc + dc
        out.append(
            FraudPlacedItem(
                cells=cells, w=w, h=h, min_bid=min_bid, anchor_bid=anchor_bid
            )
        )
    for uid, k in items.items():
        if uid == exclude_uid:
            continue
        bid = getattr(k, "box_id", None)
        if bid is None:
            continue
        if getattr(k, "box_id_confirmed", False) or uid in manual_shapes:
            continue
        b = int(bid)
        r, c = b // gc, b % gc
        cells = frozenset({(r, c)})
        out.append(FraudPlacedItem(cells=cells, w=1, h=1, min_bid=b, anchor_bid=b))
    return out


def fraud_empty_cells_in_zone_prefix(
    occupied: set,
    limit: int,
    placed_items: Optional[Sequence[FraudPlacedItem]] = None,
) -> Set[Tuple[int, int]]:
    """
    BoxId 0..limit 内应排除的空置候选（诈骗格）集合。

    铺板可解释性（顶左画形、不做 BFS 空域）：候选空格 ``C``（坐标 ``(r,c)``，bid ``b``）
    若存在物品 ``A`` 满足 ``A.min_bid > b``，将 ``A`` 的 ``w×h`` 以 ``C`` 为顶左得到占格集合
    ``P``；若 ``P`` 完全落在棋盘内（仅受 ``_GRID_ROWS``/``_GRID_COLS`` 约束，不对 ``P`` 内
    bid 设上界），且 ``P`` 与所有满足 ``B.min_bid < A.min_bid`` 的 ``B.cells`` 之并 无交集，则 ``C``
    可由 ``A`` 的铺法解释（非诈骗格）。解释物 ``A`` 的锚格可大于 ``limit``。与更晚物品的占位
    相交不阻挡。无 ``placed_items`` 时返回空集。
    """
    gc, gr = _GRID_COLS, _GRID_ROWS
    if not placed_items:
        return set()
    placed_list = list(placed_items)
    fraud: Set[Tuple[int, int]] = set()
    for bid in range(limit + 1):
        r, c = bid // gc, bid % gc
        if (r, c) in occupied:
            continue
        explained = False
        for A in placed_list:
            if A.min_bid <= bid:
                continue
            early_occ: Set[Tuple[int, int]] = set()
            for B in placed_list:
                if B.min_bid < A.min_bid:
                    early_occ |= B.cells
            if r + A.h > gr or c + A.w > gc:
                continue
            paint: Set[Tuple[int, int]] = set()
            for ddr in range(A.h):
                for ddc in range(A.w):
                    paint.add((r + ddr, c + ddc))
            if not paint:
                continue
            if paint & early_occ:
                continue
            explained = True
            break
        if not explained:
            fraud.add((r, c))
    return fraud


def fraud_empty_cells_for_algorithm(
    algorithm: str,
    occupied: set,
    limit: int,
    placed_items: Optional[Sequence[FraudPlacedItem]] = None,
    *,
    fraud_empty_cells_tiling_n: int = 0,
) -> Set[Tuple[int, int]]:
    """
    按配置的诈骗格算法计算前缀区内「疑似诈骗」空置格集合。

    - ``tiling_strict``：铺板可解释性（顶左画形），即 :func:`fraud_empty_cells_in_zone_prefix`；
      兼容旧名 ``tiling`` / ``tile`` / ``explainability``。
    - ``tiling_n``：先算 ``tiling_strict`` 基底，再**去掉** BoxId ``b <= limit - n`` 的格（这些格不再视为诈骗格）；
      ``n`` 由参数 ``fraud_empty_cells_tiling_n`` 传入（来自 :func:`bidking.config.runtime.infer_fraud_empty_cells_algorithm_and_trim` 或兼容配置）；``n <= 0`` 时与 ``tiling_strict`` 相同。
    - ``none``：不做诈骗判断，恒返回空集（几何空置不因诈骗格剔除）。

    未知算法名时回退为 ``tiling_strict``，与旧行为一致。
    """
    a = (algorithm or "").strip().lower().replace(" ", "_").replace("-", "_")
    if a in ("none", "off", "disabled", "false", "0"):
        return set()
    gc = _GRID_COLS
    base = fraud_empty_cells_in_zone_prefix(occupied, limit, placed_items)
    if a in ("tiling_n", "tilingn"):
        try:
            n = int(fraud_empty_cells_tiling_n)
        except (TypeError, ValueError):
            n = 0
        n = max(0, n)
        if n <= 0:
            return base
        thr = int(limit) - n
        out: Set[Tuple[int, int]] = set()
        for cell in base:
            r, c = cell
            b = r * gc + c
            if b > thr:
                out.add(cell)
        return out
    return base


__all__ = [
    "FraudPlacedItem",
    "fraud_empty_cells_for_algorithm",
    "fraud_empty_cells_in_zone_prefix",
    "fraud_placed_items_from_build_occupied_like",
    "fraud_placed_items_from_merged_items",
]
