"""画板网格常量（与 UI / 快照 schema 一致）。"""

from __future__ import annotations

from typing import Any, Set

GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1

# 合并物品表上无任何 BoxId 时，几何前缀空置仍需要一个上界；与定价共用 ``max_anchor_box_id_merged``。
DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID = 30

# 艾莎第 4 回合起：空格自动填充 + 已知品质未知轮廓扩充（含第 4、5 回合及以后）。
AISHA_VACANT_RECT_INFER_ROUND = 4

# 快照 ``grid_overlay`` 中序列化的占位格（BoxId 列表，与 UI ``_build_occupied`` 一致）
OCCUPIED_CELL_BIDS = "occupied_cell_bids"

# 已被日志 ``infer_shapes`` 吸收、不再单独计占位的幽灵 uid（仍保留在 ``phantom_items`` 供撤销）
INFER_ABSORBED_PHANTOM_UIDS_KEY = "infer_absorbed_phantom_uids"


def infer_absorbed_phantom_uid_set(overlay: Any) -> Set[str]:
    if not isinstance(overlay, dict):
        return set()
    raw = overlay.get(INFER_ABSORBED_PHANTOM_UIDS_KEY)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return set()
    return {str(u) for u in raw}


def rect_cells_wh(w: int, h: int, dc: int, dr: int) -> set[tuple[int, int]]:
    """矩形 ``(w,h)`` 顶左 ``(dr,dc)`` 占用的全部格（行、列）。"""
    return {
        (int(dr) + ddr, int(dc) + ddc)
        for ddr in range(int(h))
        for ddc in range(int(w))
    }
