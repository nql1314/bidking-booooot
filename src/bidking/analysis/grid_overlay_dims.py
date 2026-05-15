"""画板网格常量（与 UI / 快照 schema 一致）。"""

from __future__ import annotations

GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1

# 合并物品表上无任何 BoxId 时，几何前缀空置仍需要一个上界；与定价共用 ``max_anchor_box_id_merged``。
DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID = 30

# 快照 ``grid_overlay`` 中序列化的占位格（BoxId 列表，与 UI ``_build_occupied`` 一致）
OCCUPIED_CELL_BIDS = "occupied_cell_bids"

# 默认轮廓推断：相对权重期望价的价带（±20%），带内再按掉落概率选形。
_INFER_DEFAULT_PRICE_BAND_REL = 0.2
