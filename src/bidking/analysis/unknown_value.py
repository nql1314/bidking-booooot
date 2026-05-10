"""未知物品权重估价 / 未知格子等效预估。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db

_DEFAULT_UNIT_Q234 = 874.5672
_DEFAULT_UNIT_Q4 = 2444.4747
_DEFAULT_UNIT_Q5 = 9587.4375
_DEFAULT_UNIT_Q6 = 64551.3821
_DEFAULT_AVG_CELL_Q1 = 118.4634
_DEFAULT_AVG_CELL_Q2 = 291.5937
_DEFAULT_AVG_CELL_Q3 = 917.4746
ITEM_PRICES_CSV_RELPATHS = (
    ("..", "..", "..", "data", "item_prices.csv"),
    ("..", "..", "data", "item_prices.csv"),
)
_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None


def _item_prices_csv_path_resolved() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for parts in ITEM_PRICES_CSV_RELPATHS:
        p = os.path.normpath(os.path.join(here, *parts))
        if os.path.isfile(p):
            return p
    return ""


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    path = _item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache


def vacant_cell_unit(
    csv_by_group: Optional[Dict[str, float]],
    quality_group: str,
    pricing: Dict[str, Any],
    pricing_key: str,
    default: float,
) -> int:
    if csv_by_group and quality_group in csv_by_group:
        return int(round(csv_by_group[quality_group]))
    raw = pricing.get(pricing_key)
    if raw is not None:
        return int(round(float(raw)))
    return int(round(default))


def avg_cell_price_for_quality(
    quality: int,
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
) -> float:
    key = f"q{quality}"
    if csv_cells_raw and key in csv_cells_raw:
        return float(csv_cells_raw[key])
    pk = f"vacant_unit_q{quality}"
    raw = pricing.get(pk)
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    defaults = {
        1: _DEFAULT_AVG_CELL_Q1,
        2: _DEFAULT_AVG_CELL_Q2,
        3: _DEFAULT_AVG_CELL_Q3,
        4: _DEFAULT_UNIT_Q4,
        5: _DEFAULT_UNIT_Q5,
        6: _DEFAULT_UNIT_Q6,
    }
    return float(defaults.get(quality, _DEFAULT_UNIT_Q234))


def _int_set_from_snapshot_field(raw: Any) -> Set[int]:
    out: Set[int] = set()
    if not isinstance(raw, list):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def weighted_cell_equiv_for_unknown_contour_item(
    it: Dict[str, Any],
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
    map_id_normalized: Optional[int],
    *,
    require_box_id_confirmed: bool = True,
) -> Optional[float]:
    """品质已知、快照无外形时：按 CSV 期望价与档内 ``u_cell`` 得加权格数。

    默认要求 ``box_id_confirmed``（与定价占位一致）。空置扣减等场景可传
    ``require_box_id_confirmed=False``。
    """
    _ = board_snapshot
    if it.get("shape") is not None:
        return None
    if require_box_id_confirmed and not it.get("box_id_confirmed"):
        return None
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return None
    try:
        q = int(it["quality"])
    except (KeyError, TypeError, ValueError):
        return None
    if q < 1 or q > 6:
        return None
    try:
        cid_raw = it.get("item_cid")
        item_cid_i = int(cid_raw) if cid_raw is not None else None
    except (TypeError, ValueError):
        item_cid_i = None
    categories = _int_set_from_snapshot_field(it.get("categories"))
    excl_q = _int_set_from_snapshot_field(it.get("excluded_qualities"))
    excl_c = _int_set_from_snapshot_field(it.get("excluded_categories"))
    best, count, unique, est, _ql = item_db.query_item(
        shape=None,
        quality=q,
        categories=categories,
        item_cid=item_cid_i,
        csv_index=csv_index,
        csv_items=csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
        max_shape_wh=None,
        map_category_weights=None,
        map_id=map_id_normalized,
    )
    if best is None or count == 0:
        return None
    price = float(est) if est is not None else float(best.base_value)
    u_cell = avg_cell_price_for_quality(q, csv_cells_raw, pricing)
    if u_cell <= 0:
        return None
    return price / u_cell


def unknown_contour_vacant_weighted_excess(
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
    map_id_normalized: Optional[int],
) -> Tuple[float, Dict[str, Any]]:
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0, {}
    raw_items = ((board_snapshot.get("game_state") or {}).get("items") or {})
    per_item: List[Dict[str, Any]] = []
    total_excess = 0.0
    n_uc = 0
    for uid, it in raw_items.items():
        if not isinstance(it, dict):
            continue
        if not it.get("box_id_confirmed"):
            continue
        if it.get("shape") is not None:
            continue
        try:
            q = int(it["quality"])
        except (KeyError, TypeError, ValueError):
            continue
        if q < 1 or q > 6:
            continue
        n_uc += 1
        w_cells = weighted_cell_equiv_for_unknown_contour_item(
            it, board_snapshot, csv_cells_raw, pricing, map_id_normalized
        )
        if w_cells is None:
            continue
        price = w_cells * avg_cell_price_for_quality(q, csv_cells_raw, pricing)
        ex = max(0.0, w_cells - 1.0)
        total_excess += ex
        if len(per_item) < 48:
            per_item.append(
                {
                    "uid": str(uid),
                    "quality": q,
                    "price_used": round(price, 4),
                    "price_label": "weighted_equiv",
                    "avg_cell_unit": round(avg_cell_price_for_quality(q, csv_cells_raw, pricing), 4),
                    "weighted_cell_equiv": round(w_cells, 6),
                    "excess_over_one_cell": round(ex, 6),
                }
            )
    if n_uc == 0:
        return 0.0, {}
    return total_excess, {
        "early_unknown_contour_vacant_linear_adjust": True,
        "unknown_contour_items": n_uc,
        "weighted_cell_excess_sum": round(total_excess, 6),
        "detail_per_item": per_item,
    }

__all__ = [
    "avg_cell_price_for_quality",
    "unknown_contour_vacant_weighted_excess",
    "vacant_cell_unit",
    "weighted_cell_equiv_for_unknown_contour_item",
]
