"""画板网格常量（与 UI / 快照 schema 一致）。"""

from __future__ import annotations

GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1

# 合并物品表上无任何 BoxId 时，几何前缀空置仍需要一个上界；与定价共用 ``max_anchor_box_id_merged``。
DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID = 30

# 艾莎第 4 回合起：空置区近似矩形 → 自动 ``phantom_vac_*`` 幽灵（手动画框 + 候选约束）。
AISHA_VACANT_RECT_INFER_ROUND = 4

# 未知轮廓默认推断：CSV 权重期望价 ± 该比例价带内选外形（见 ``grid_overlay_infer_log_shapes``）。
INFER_DEFAULT_PRICE_BAND_REL = 0.20


def vacant_rect_phantom_infer_round_active(current_round: int) -> bool:
    """第 4 回合及之后才做空置矩形自动幽灵推断。"""
    return int(current_round) >= AISHA_VACANT_RECT_INFER_ROUND

# 快照 ``grid_overlay`` 中序列化的占位格（BoxId 列表，与 UI ``_build_occupied`` 一致）
OCCUPIED_CELL_BIDS = "occupied_cell_bids"


def rect_cells_wh(w: int, h: int, dc: int, dr: int) -> set[tuple[int, int]]:
    """矩形 ``(w,h)`` 顶左 ``(dr,dc)`` 占用的全部格（行、列）。"""
    return {
        (int(dr) + ddr, int(dc) + ddc)
        for ddr in range(int(h))
        for ddc in range(int(w))
    }
