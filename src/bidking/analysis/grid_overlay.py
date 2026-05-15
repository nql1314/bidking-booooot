"""画板 ``grid_overlay``：空置/几何空置/诈骗格分析，以及快照 ``items`` 与 overlay 的合并。

实现已按职责拆至子模块（``grid_overlay_*``）；本模块保留对外 API 与历史导入路径 ``bidking.analysis.grid_overlay``。

合并后的物品表供 ``_board_pricing`` 等模块做总价与占位计算，规则与 UI 写入快照一致：

- ``phantom_items``：仅补充 ``game_state.items`` 中不存在的 uid；
- ``phantom_quality_pref``：显式 Q1–Q6 写入合并行的 ``quality``（幽灵 JSON 常为 ``quality: null``）；
- ``manual_shapes``：对尚无 ``shape`` 的条目写入 ``shape = w*10+h``；
- ``manual_confirm_item_id``：按 ``item_prices.csv`` 投影 ``item_cid`` / ``quality`` / ``shape`` / ``price``。

诈骗格剔除算法由 ``grid_view.fraud_empty_cells_algorithm`` 选择（``tiling_strict`` / ``tiling_n`` / ``none``）；
``tiling_n`` 另读 ``grid_view.fraud_empty_cells_tiling_n``（整数 n），见 :func:`bidking.analysis.fraud_empty_cells.fraud_empty_cells_for_algorithm`。
"""

from __future__ import annotations

from .fraud_empty_cells import (
    FraudPlacedItem,
    fraud_empty_cells_for_algorithm,
    fraud_empty_cells_in_zone_prefix,
    fraud_placed_items_from_build_occupied_like,
    fraud_placed_items_from_merged_items,
)
from .grid_overlay_dims import (
    DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID,
    GRID_COLS,
    GRID_MAX_BOX_ID,
    GRID_ROWS,
    OCCUPIED_CELL_BIDS,
)
from .grid_overlay_infer_shapes import (
    _infer_default_placement_candidates,
    _infer_pseudo_blocked,
    compute_grid_overlay_infer_shapes,
)
from .grid_overlay_item_merge import (
    apply_infer_shapes_to_items,
    apply_manual_confirm_projection,
    apply_manual_shapes_to_items,
    apply_phantom_default_quality_for_phantom_rows,
    apply_phantom_quality_pref_to_items,
    merged_items_dict,
    merged_items_dict_from_snapshot,
    sync_phantom_row_quality_from_overlay,
)
from .grid_overlay_vacant_zone import (
    board_display_occupied_cells_merged,
    build_occupied_cells,
    compute_overlay_vacant_dict,
    empty_zone_ignore_fraud_filter,
    fraud_zone_cell_exclusion_enabled,
    map_skill_hidden_vacant,
    map_skill_total_hidden_for_overlay,
    max_anchor_box_id_merged,
    occupied_cells_in_empty_zone_prefix,
    snapshot_occupied_cells,
    total_grid_count_from_raw_pricing,
    vacant_block_from_board_snapshot,
    vacant_dict_from_board_snapshot,
    vacant_manual_suppress_cells_from_snapshot,
)

__all__ = [
    "DEFAULT_GEOMETRIC_PREFIX_ANCHOR_BOX_ID",
    "OCCUPIED_CELL_BIDS",
    "apply_infer_shapes_to_items",
    "apply_phantom_default_quality_for_phantom_rows",
    "apply_phantom_quality_pref_to_items",
    "sync_phantom_row_quality_from_overlay",
    "apply_manual_confirm_projection",
    "apply_manual_shapes_to_items",
    "board_display_occupied_cells_merged",
    "build_occupied_cells",
    "compute_overlay_vacant_dict",
    "compute_grid_overlay_infer_shapes",
    "empty_zone_ignore_fraud_filter",
    "fraud_empty_cells_for_algorithm",
    "fraud_empty_cells_in_zone_prefix",
    "fraud_placed_items_from_build_occupied_like",
    "fraud_placed_items_from_merged_items",
    "fraud_zone_cell_exclusion_enabled",
    "FraudPlacedItem",
    "map_skill_hidden_vacant",
    "map_skill_total_hidden_for_overlay",
    "max_anchor_box_id_merged",
    "merged_items_dict",
    "merged_items_dict_from_snapshot",
    "occupied_cells_in_empty_zone_prefix",
    "snapshot_occupied_cells",
    "total_grid_count_from_raw_pricing",
    "vacant_block_from_board_snapshot",
    "vacant_dict_from_board_snapshot",
    "vacant_manual_suppress_cells_from_snapshot",
    "GRID_COLS",
    "GRID_ROWS",
    "GRID_MAX_BOX_ID",
]
