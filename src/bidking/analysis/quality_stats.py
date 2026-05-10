"""按品质 / 按类别 的统计：紫(Q4)、金(Q5)、红(Q6) 件数 / 总格 / 占用 / 未确认轮廓数。

便于 ui.totals_panel 直接展示。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .unknown_value import weighted_cell_equiv_for_unknown_contour_item
from ._shape_wh import shape_wh_from_snapshot


def _items_dict_from_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    return raw if isinstance(raw, dict) else {}


def sum_quality_footprint_cells(
    board_snapshot: Dict[str, Any],
    quality: int,
    *,
    csv_cells_raw: Optional[Dict[str, float]] = None,
    pricing: Optional[Dict[str, Any]] = None,
    map_id_normalized: Optional[int] = None,
) -> int:
    n = 0
    use_weighted_gr = quality in (5, 6) and csv_cells_raw is not None and pricing is not None
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        shape = it.get("shape")
        if shape is not None:
            w, h = shape_wh_from_snapshot(shape)
            n += w * h
        elif use_weighted_gr:
            w_eq = weighted_cell_equiv_for_unknown_contour_item(
                it, board_snapshot, csv_cells_raw, pricing or {}, map_id_normalized
            )
            if w_eq is not None:
                n += max(1, int(round(w_eq)))
            else:
                n += 1
        else:
            n += 1
    return n


def count_quality_items_all(board_snapshot: Dict[str, Any], quality: int) -> int:
    k = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) == quality:
                k += 1
        except (TypeError, ValueError):
            continue
    return k


def quality_has_unconfirmed_contour(board_snapshot: Dict[str, Any], quality: int) -> bool:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    for _uid, it in raw.items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed"):
            return True
        if it.get("shape") is None:
            return True
    return False


def sum_confirmed_contour_quality_price(board_snapshot: Dict[str, Any], quality: int) -> int:
    s = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed"):
            continue
        if it.get("shape") is None:
            continue
        pr = it.get("price")
        if pr is None:
            continue
        try:
            s += int(round(float(pr)))
        except (TypeError, ValueError):
            continue
    return s


def count_unconfirmed_contour_quality_items(board_snapshot: Dict[str, Any], quality: int) -> int:
    n = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed") or it.get("shape") is None:
            n += 1
    return n


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
