"""空置/几何空置/有效空置/可能诈骗格分析。

facade，把 :mod:`._board_pricing` 中 vacant 相关函数以稳定 API 暴露给上层。
"""

from __future__ import annotations

from ._board_pricing import (
    _confirmed_items_from_snapshot as confirmed_items_from_snapshot,
    _scam_span_vacant_deduction as scam_span_vacant_deduction,
    _early_round_vacant_metrics as early_round_vacant_metrics,
    _board_display_occupied_cells_from_snapshot as board_display_occupied_cells,
    map_skill_total_hidden_cells_from_logs,
    map_skill_hidden_cell_reserve_from_snapshot,
    vacant_cells_from_map_skill_total_hidden,
)

__all__ = [
    "confirmed_items_from_snapshot",
    "scam_span_vacant_deduction",
    "early_round_vacant_metrics",
    "board_display_occupied_cells",
    "map_skill_total_hidden_cells_from_logs",
    "map_skill_hidden_cell_reserve_from_snapshot",
    "vacant_cells_from_map_skill_total_hidden",
]
