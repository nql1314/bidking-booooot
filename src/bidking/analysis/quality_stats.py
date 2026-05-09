"""按品质 / 按类别 的统计：紫(Q4)、金(Q5)、红(Q6) 件数 / 总格 / 占用 / 未确认轮廓数。

便于 ui.totals_panel 直接展示。
"""

from __future__ import annotations

from typing import Any, Dict

from ._board_pricing import (
    _count_quality_items_all as count_quality_items_all,
    _count_unconfirmed_contour_quality_items as count_unconfirmed_contour_quality_items,
    _quality_has_unconfirmed_contour as quality_has_unconfirmed_contour,
    _sum_confirmed_contour_quality_price as sum_confirmed_contour_quality_price,
    _sum_quality_footprint_cells as sum_quality_footprint_cells,
)


def per_quality_summary(board_snapshot: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """汇总 Q4/Q5/Q6 的件数 / 占用格 / 未确认轮廓件数。"""
    out: Dict[int, Dict[str, Any]] = {}
    for q in (4, 5, 6):
        out[q] = {
            "count": count_quality_items_all(board_snapshot, q),
            "footprint_cells": sum_quality_footprint_cells(board_snapshot, q),
            "unconfirmed_contour_count": count_unconfirmed_contour_quality_items(board_snapshot, q),
            "has_unconfirmed_contour": quality_has_unconfirmed_contour(board_snapshot, q),
            "confirmed_contour_total_price": sum_confirmed_contour_quality_price(board_snapshot, q),
        }
    return out


__all__ = [
    "count_quality_items_all",
    "count_unconfirmed_contour_quality_items",
    "quality_has_unconfirmed_contour",
    "sum_confirmed_contour_quality_price",
    "sum_quality_footprint_cells",
    "per_quality_summary",
]
