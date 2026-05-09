"""raw_pricing：从事件与 CSV 提取未加工全局统计。"""

from __future__ import annotations

import csv
import os
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..parsing import item_db
from ..parsing.constants import (
    MAP_SKILL_AVG_GOLD_CELLS,
    MAP_SKILL_AVG_GOLD_PRICE,
    MAP_SKILL_AVG_RED_CELLS,
    MAP_SKILL_AVG_RED_PRICE,
    MAP_SKILL_GOLD_ITEM_COUNT,
    MAP_SKILL_RANDOM3_AVG_PRICE,
    MAP_SKILL_RANDOM6_AVG_PRICE,
    MAP_SKILL_RANDOM9_AVG_PRICE,
    MAP_SKILL_RED_ITEM_COUNT,
    MAP_SKILL_TOTAL_PURPLE_CELLS,
    MAP_SKILL_TOTAL_GOLD_CELLS,
    MAP_SKILL_TOTAL_HIDDEN_CELLS,
    MAP_SKILL_TOTAL_RED_CELLS,
    OUTLINE_SKILL_QUALITY,
    SKILL_CID_ALL_ITEMS_AVG_GRID,
    SKILL_CID_Q4_AVG_GRID,
    SKILL_CID_Q4_AVG_PRICE,
    SKILL_CID_Q4_ITEM_COUNT,
    SKILL_CID_TOTAL_ITEM_COUNT,
    MAP_SKILL_GOLD_TOTAL_PRICE,
    MAP_SKILL_RED_TOTAL_PRICE,
)
from .map_avg_csv import (
    map_quality_csv_path_resolved,
)

_SKILL_Q12_COUNT = 1002044
_SKILL_Q3_GRID_AVG = 1002043


def _merge_latest_skill_entries(skill_logs: List[dict]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for block in skill_logs or []:
        if not isinstance(block, dict):
            continue
        gd = block.get("game_data") or {}
        if not isinstance(gd, dict):
            continue
        for key in ("HeroSkillLog", "MapSkillLog", "ItemSkillLog"):
            for entry in gd.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                try:
                    cid = int(entry.get("SkillCid") or 0)
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    out[cid] = entry
    return out


def _safe_int_field(entry: Optional[dict], *keys: str) -> Optional[int]:
    if not isinstance(entry, dict):
        return None
    for k in keys:
        v = entry.get(k)
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _safe_float_field(entry: Optional[dict], *keys: str) -> Optional[float]:
    if not isinstance(entry, dict):
        return None
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _skill_entry_for_any(skill_entries: Dict[int, dict], cids: Sequence[int]) -> Optional[dict]:
    for cid in cids:
        ent = skill_entries.get(cid)
        if isinstance(ent, dict):
            return ent
    return None


def _first_int_from_skills(
    skill_entries: Dict[int, dict], cids: Sequence[int], *keys: str
) -> Optional[int]:
    for cid in cids:
        v = _safe_int_field(skill_entries.get(cid), *keys)
        if v is not None:
            return v
    return None


def _first_float_from_skills(
    skill_entries: Dict[int, dict], cids: Sequence[int], *keys: str
) -> Optional[float]:
    for cid in cids:
        v = _safe_float_field(skill_entries.get(cid), *keys)
        if v is not None:
            return v
    return None


def _min_total_from_avg(avg: Optional[float]) -> Optional[int]:
    if avg is None:
        return None
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return None
    if a <= 0 or a != a:
        return None
    try:
        fr = Fraction(Decimal(str(a))).limit_denominator(512)
    except (ArithmeticError, ValueError, TypeError):
        return max(0, int(round(a)))
    return max(0, int(fr.numerator))


def _min_total_price_from_avg(avg: Optional[float]) -> Optional[int]:
    return _min_total_from_avg(avg)


_RANDOM_AVG_DEFAULT_HIT_COUNT: Dict[int, int] = {
    MAP_SKILL_RANDOM3_AVG_PRICE: 3,
    MAP_SKILL_RANDOM6_AVG_PRICE: 6,
    MAP_SKILL_RANDOM9_AVG_PRICE: 9,
}


def _min_total_price_from_avg_times_hit_count(
    avg: Optional[float],
    hit_count: Optional[int],
    *,
    skill_cid: int,
) -> Optional[int]:
    """随机 3/6/9 均价 × ``HitItemIndex`` 命中件数 → 总价下界；件数缺失或非正时按技能默认 3/6/9。"""
    if avg is None:
        return None
    n = hit_count
    if n is None or n <= 0:
        n = _RANDOM_AVG_DEFAULT_HIT_COUNT.get(int(skill_cid))
    if n is None or n <= 0:
        return None
    try:
        prod = float(avg) * float(n)
    except (TypeError, ValueError):
        return None
    if prod <= 0 or prod != prod:
        return None
    return _min_total_from_avg(prod)


def _max_optional_int(*vals: Optional[int]) -> Optional[int]:
    xs = [int(v) for v in vals if v is not None]
    return max(xs) if xs else None


def _merge_with_min_from_avg(
    existing: Optional[int],
    avg: Optional[float],
    *,
    from_price: bool = False,
) -> Optional[int]:
    """由均格/均价推算的最小整数件数（或总价下界）与 ``existing`` 取较大者。"""
    inferred = (
        _min_total_price_from_avg(avg) if from_price else _min_total_from_avg(avg)
    )
    return _max_optional_int(existing, inferred)


_RATIO_INFER_TOL = 1e-4


def _is_positive_finite_float(x: Any) -> bool:
    if not isinstance(x, (int, float)):
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return v > 0 and v == v


def _near_int(x: float, tol: float = _RATIO_INFER_TOL) -> bool:
    if x != x or x <= 0:
        return False
    r = round(x)
    return abs(x - r) <= tol


def _as_int_count(v: Any) -> Optional[int]:
    """非负件数/格数；``None`` 或非法为未知。"""
    if v is None:
        return None
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if i >= 0 else None


def _infer_tier_count_grid_price(
    d: Dict[str, Any],
    *,
    count_k: str,
    grid_k: str,
    avg_grid_k: str,
    avg_price_k: Optional[str],
    total_price_k: Optional[str],
) -> None:
    """在 ``count``、``grid_count``、``grid_avg``、``price_avg``、``price_total`` 间做保守补全（只填 ``None`` 缺项）。

    关系：``grid_count ≈ count * grid_avg``，``price_total ≈ count * price_avg``（与 HitBox 聚合一致）。
    除法仅在商接近正整数时写入，乘法在 ``round`` 后与乘积足够接近时写入整数总价/总格。
    """
    for _ in range(8):
        changed = False
        n = _as_int_count(d.get(count_k))
        G = _as_int_count(d.get(grid_k))
        ag = d.get(avg_grid_k)
        ap = d.get(avg_price_k) if avg_price_k else None
        T = _as_int_count(d.get(total_price_k)) if total_price_k else None

        if d.get(avg_grid_k) is None and n and G and n > 0:
            d[avg_grid_k] = float(G) / float(n)
            changed = True
            continue

        if d.get(grid_k) is None and n and n > 0 and _is_positive_finite_float(ag):
            prod = float(n) * float(ag)
            if _near_int(prod):
                d[grid_k] = int(round(prod))
                changed = True
                continue

        if d.get(count_k) is None and G and G > 0 and _is_positive_finite_float(ag):
            q = float(G) / float(ag)
            if _near_int(q) and int(round(q)) > 0:
                d[count_k] = int(round(q))
                changed = True
                continue

        if total_price_k and avg_price_k:
            if d.get(total_price_k) is None and n and n > 0 and _is_positive_finite_float(ap):
                prod = float(n) * float(ap)
                if _near_int(prod):
                    d[total_price_k] = int(round(prod))
                    changed = True
                    continue

            if d.get(avg_price_k) is None and n and n > 0 and T is not None and T > 0:
                d[avg_price_k] = float(T) / float(n)
                changed = True
                continue

            if d.get(count_k) is None and T is not None and T > 0 and _is_positive_finite_float(ap):
                q = float(T) / float(ap)
                if _near_int(q) and int(round(q)) > 0:
                    d[count_k] = int(round(q))
                    changed = True
                    continue

        if not changed:
            break


def _finalize_tier_min_bounds(
    d: Dict[str, Any],
    *,
    count_k: str,
    grid_k: str,
    avg_grid_k: str,
    avg_price_k: str,
    count_min_k: str,
    grid_min_k: str,
) -> None:
    """由已知件数、总格、均价/均格分数下界合并得到 ``count_min`` / ``grid_min``。"""
    n = _as_int_count(d.get(count_k))
    G = _as_int_count(d.get(grid_k))
    ag = d.get(avg_grid_k)
    ap = d.get(avg_price_k)

    base_grid: Optional[int] = None
    if n is not None and n > 0:
        if G is not None:
            base_grid = max(1, int(n), int(G))
        else:
            base_grid = max(1, int(n))

    base_count: Optional[int] = None
    if G is not None:
        if n is not None:
            base_count = max(1, int(n))
        else:
            base_count = 1

    cm = _max_optional_int(
        base_count,
        _merge_with_min_from_avg(n, ap, from_price=True),
    )
    cm = _merge_with_min_from_avg(cm, ag, from_price=False)

    gm = _max_optional_int(
        base_grid,
        _merge_with_min_from_avg(G, ag, from_price=False),
    )
    gm = _merge_with_min_from_avg(gm, ap, from_price=True)

    d[count_min_k] = cm
    d[grid_min_k] = gm


def _shape_cell_count(slot_type: Any) -> int:
    if slot_type is None:
        return 0
    try:
        s = str(int(slot_type))
    except (TypeError, ValueError):
        return 0
    if len(s) == 2:
        return max(0, int(s[0]) * int(s[1]))
    return max(0, int(s))


def _aggregate_hitbox_list(boxes: List[dict]) -> Dict[str, Any]:
    count = 0
    total_cells = 0
    total_price = 0
    priced_items = 0
    for box in boxes or []:
        if not isinstance(box, dict):
            continue
        if not box.get("ItemUid"):
            continue
        count += 1
        total_cells += _shape_cell_count(box.get("ItemSlotType"))
        if "ItemPrice" in box:
            try:
                total_price += int(box["ItemPrice"])
                priced_items += 1
            except (TypeError, ValueError):
                pass
    avg_cells = (total_cells / count) if count else None
    avg_price = (total_price / priced_items) if priced_items else None
    return {
        "count": count,
        "total_cells": total_cells,
        "total_price": total_price,
        "avg_cells": avg_cells,
        "avg_price": avg_price,
    }


def _best_outline_aggregate_for_quality(
    skill_entries: Dict[int, dict], quality: int
) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_n = -1
    for cid, q in OUTLINE_SKILL_QUALITY.items():
        if q != quality:
            continue
        entry = skill_entries.get(cid)
        if not isinstance(entry, dict):
            continue
        boxes = entry.get("HitBoxList") or []
        if not isinstance(boxes, list):
            continue
        agg = _aggregate_hitbox_list(boxes)
        if agg["count"] > best_n:
            best_n = agg["count"]
            best = agg
    return best


def _load_map_quality_groups_from_csv(map_id: int, snapshot_path_hint: Optional[str]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    path = map_quality_csv_path_resolved(snapshot_path_hint)
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    mid = int(row["map_id"])
                    qg = str(row["quality_group"]).strip()
                    cell = float(row["avg_price_per_cell"])
                    item = float(row["avg_price_per_item"])
                except (KeyError, TypeError, ValueError):
                    continue
                if mid != map_id or not qg:
                    continue
                out[qg] = {"avg_price_per_cell": cell, "avg_price_per_item": item}
    except OSError:
        return {}
    return out


def _apply_tier_zero_coherence(
    d: Dict[str, Any],
    *,
    count_k: str,
    grid_k: str,
    avg_grid_k: str,
    avg_price_k: Optional[str],
    total_price_k: Optional[str],
    also_zero: Tuple[str, ...] = (),
) -> None:
    """若件数、总格、均格、均价、总价中任一为数值 0，则该档相关数值全部置 0。"""
    keys: List[str] = [count_k, grid_k, avg_grid_k]
    if avg_price_k:
        keys.append(avg_price_k)
    if total_price_k:
        keys.append(total_price_k)
    vals: List[Any] = [d.get(k) for k in keys]
    if not any(v == 0 for v in vals if isinstance(v, (int, float))):
        return
    d[count_k] = 0
    d[grid_k] = 0
    d[avg_grid_k] = 0.0
    if avg_price_k:
        d[avg_price_k] = 0.0
    if total_price_k:
        d[total_price_k] = 0
    for ek in also_zero:
        if ek.endswith("_avg") or "_price_avg" in ek:
            d[ek] = 0.0
        else:
            d[ek] = 0


def _infer_q56_grid_from_total_and_q14(d: Dict[str, Any]) -> None:
    """由 ``total_grid_count`` 与 q1–q4 总格推出金/红缺失档（恒等式：总数 = q1+…+q6）。

    技能给出的总藏品格与分档格满足守恒：若 q1–q4 各档总格均已知，且 q5、q6 中至少有一档
    总格已由日志给出（或该档件数为 0 可视为 0 格），则可推算另一档的精确总格。
    仅填补仍为 ``None`` 的 ``q5_grid_count`` / ``q6_grid_count``，不覆盖已有整数。
    """
    T = _as_int_count(d.get("total_grid_count"))
    if T is None:
        return
    g1 = _as_int_count(d.get("q1_grid_count"))
    g2 = _as_int_count(d.get("q2_grid_count"))
    g3 = _as_int_count(d.get("q3_grid_count"))
    g4 = _as_int_count(d.get("q4_grid_count"))
    if any(x is None for x in (g1, g2, g3, g4)):
        return

    sum14 = int(g1) + int(g2) + int(g3) + int(g4)
    remainder = int(T) - sum14
    if remainder < 0:
        return

    if d.get("q5_count") == 0 and d.get("q5_grid_count") is None:
        d["q5_grid_count"] = 0
    if d.get("q6_count") == 0 and d.get("q6_grid_count") is None:
        d["q6_grid_count"] = 0

    g5 = _as_int_count(d.get("q5_grid_count"))
    g6 = _as_int_count(d.get("q6_grid_count"))

    if g5 is not None and g6 is None:
        rest = remainder - int(g5)
        if rest >= 0:
            d["q6_grid_count"] = rest
    elif g6 is not None and g5 is None:
        rest = remainder - int(g6)
        if rest >= 0:
            d["q5_grid_count"] = rest


def build_raw_pricing_dict(
    *,
    map_id: int,
    skill_logs: List[dict],
    snapshot_path_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 raw_pricing（仅保存原始全局信息，不做策略估算）。"""

    skill_entries = _merge_latest_skill_entries(list(skill_logs or []))
    normalized_mid = item_db.normalize_map_id(int(map_id or 0))
    csv_groups_full = (
        _load_map_quality_groups_from_csv(normalized_mid, snapshot_path_hint)
        if normalized_mid is not None
        else {}
    )
    csv_groups_per_cell = {
        k: float(v.get("avg_price_per_cell", 0.0))
        for k, v in sorted(csv_groups_full.items())
    }
    csv_groups_per_item = {
        k: float(v.get("avg_price_per_item", 0.0))
        for k, v in sorted(csv_groups_full.items())
    }

    # ── 1) 技能日志直接字段 ─────────────────────────────────────────────

    total_count = _first_int_from_skills(skill_entries, SKILL_CID_TOTAL_ITEM_COUNT, "HitItemIndex")
    q12_count = _safe_int_field(skill_entries.get(_SKILL_Q12_COUNT), "HitItemIndex")
    q4_count = _first_int_from_skills(skill_entries, SKILL_CID_Q4_ITEM_COUNT, "HitItemIndex")
    q5_count = _safe_int_field(skill_entries.get(MAP_SKILL_GOLD_ITEM_COUNT), "HitItemIndex")
    q6_count = _safe_int_field(skill_entries.get(MAP_SKILL_RED_ITEM_COUNT), "HitItemIndex")

    total_grid_count = _safe_int_field(skill_entries.get(MAP_SKILL_TOTAL_HIDDEN_CELLS), "TotalHitBoxIndex")
    ent_all_avg_grid = _skill_entry_for_any(skill_entries, SKILL_CID_ALL_ITEMS_AVG_GRID)
    total_grid_avg = _safe_float_field(ent_all_avg_grid, "AllHitItemAvgBoxIndex")

    total_price_min = _min_total_price_from_avg(
        _first_float_from_skills(skill_entries, SKILL_CID_TOTAL_ITEM_COUNT, "AllHitItemAvgPrice")
    )
    random_avg_price_min: Optional[int] = None
    for _rnd_cid in (
        MAP_SKILL_RANDOM3_AVG_PRICE,
        MAP_SKILL_RANDOM6_AVG_PRICE,
        MAP_SKILL_RANDOM9_AVG_PRICE,
    ):
        ent = skill_entries.get(_rnd_cid)
        avg_f = _safe_float_field(ent, "AllHitItemAvgPrice") if isinstance(ent, dict) else None
        hc = _safe_int_field(ent, "HitItemIndex") if isinstance(ent, dict) else None
        inferred = _min_total_price_from_avg_times_hit_count(
            avg_f, hc, skill_cid=_rnd_cid
        )
        random_avg_price_min = _max_optional_int(random_avg_price_min, inferred)
        total_price_min = _max_optional_int(
            total_price_min,
            inferred,
        )

    q3_grid_avg = _safe_float_field(skill_entries.get(_SKILL_Q3_GRID_AVG), "AllHitItemAvgBoxIndex")
    
    q4_grid_avg = _safe_float_field(_skill_entry_for_any(skill_entries, SKILL_CID_Q4_AVG_GRID), "AllHitItemAvgBoxIndex")
    q4_price_avg = _safe_float_field(_skill_entry_for_any(skill_entries, SKILL_CID_Q4_AVG_PRICE), "AllHitItemAvgPrice")
    q4_grid_count = _safe_int_field(skill_entries.get(MAP_SKILL_TOTAL_PURPLE_CELLS), "AllHitItemAvgBoxIndex")


    q5_grid_avg = _safe_float_field(skill_entries.get(MAP_SKILL_AVG_GOLD_CELLS), "AllHitItemAvgBoxIndex")
    q5_grid_count = _safe_int_field(skill_entries.get(MAP_SKILL_TOTAL_GOLD_CELLS), "TotalHitBoxIndex")
    q5_price_avg = _safe_float_field(skill_entries.get(MAP_SKILL_AVG_GOLD_PRICE), "AllHitItemAvgPrice")
    q5_price_total = _safe_int_field(skill_entries.get(MAP_SKILL_GOLD_TOTAL_PRICE), "HitItemTotalPrice")

    q6_grid_avg = _safe_float_field(skill_entries.get(MAP_SKILL_AVG_RED_CELLS), "AllHitItemAvgBoxIndex")
    q6_grid_count = _safe_int_field(skill_entries.get(MAP_SKILL_TOTAL_RED_CELLS), "TotalHitBoxIndex")
    q6_price_avg = _safe_float_field(skill_entries.get(MAP_SKILL_AVG_RED_PRICE), "AllHitItemAvgPrice")
    q6_price_total = _safe_int_field(skill_entries.get(MAP_SKILL_RED_TOTAL_PRICE), "HitItemTotalPrice")


    direct: Dict[str, Any] = {
        "total_count": total_count,
        "total_grid_count": total_grid_count,
        "total_grid_avg": total_grid_avg,
        "total_price_min": total_price_min,
        "random_avg_price_min": random_avg_price_min,
        "q1_count": None,
        "q1_grid_count": None,
        "q2_count": None,
        "q2_grid_count": None,
        "q12_count": q12_count,
        "q3_count": None,
        "q3_grid_count": None,
        "q3_grid_avg": q3_grid_avg,
        "q4_count": q4_count,
        "q4_grid_count": q4_grid_count,
        "q4_grid_avg": q4_grid_avg,
        "q4_count_min": None,
        "q4_grid_min": None,
        "q4_price_avg": q4_price_avg,
        "q4_price_total": None,
        "q5_count": q5_count,
        "q5_count_min": None,
        "q5_grid_count": q5_grid_count,
        "q5_grid_avg": q5_grid_avg,
        "q5_grid_min": None,
        "q5_price_avg": q5_price_avg,
        "q5_price_total": q5_price_total,
        "q6_count": q6_count,
        "q6_count_min": None,
        "q6_grid_count": q6_grid_count,
        "q6_grid_avg": q6_grid_avg,
        "q6_grid_min": None,
        "q6_price_avg": q6_price_avg,
        "q6_price_total": q6_price_total,
    }

    # ── 2) 由直接字段推导的模糊量 + 轮廓技能 HitBoxList 补全 ───────────────
    for q in (1, 2, 3, 4, 5, 6):
        agg = _best_outline_aggregate_for_quality(skill_entries, q)
        if agg is None or agg["count"] <= 0:
            continue
        if q == 1:
            if direct["q1_count"] in (None, 0):
                direct["q1_count"] = int(agg["count"])
            if not direct["q1_grid_count"] and agg["total_cells"]:
                direct["q1_grid_count"] = int(agg["total_cells"])
        if q == 2:
            if direct["q2_count"] in (None, 0):
                direct["q2_count"] = int(agg["count"])
            if not direct["q2_grid_count"] and agg["total_cells"]:
                direct["q2_grid_count"] = int(agg["total_cells"])
        if q == 3:
            if direct["q3_count"] in (None, 0):
                direct["q3_count"] = int(agg["count"])
            if not direct["q3_grid_count"] and agg["total_cells"]:
                direct["q3_grid_count"] = int(agg["total_cells"])
        if q == 4:
            if direct["q4_count"] in (None, 0):
                direct["q4_count"] = int(agg["count"])
            if not direct["q4_grid_count"] and agg["total_cells"]:
                direct["q4_grid_count"] = int(agg["total_cells"])
            if direct["q4_grid_avg"] is None and agg["avg_cells"] is not None:
                direct["q4_grid_avg"] = float(agg["avg_cells"])
            if direct["q4_price_total"] in (None, 0) and agg["total_price"]:
                direct["q4_price_total"] = int(agg["total_price"])
            if direct["q4_price_avg"] is None and agg["avg_price"] is not None:
                direct["q4_price_avg"] = float(agg["avg_price"])
        if q == 5:
            if direct["q5_count"] in (None, 0):
                direct["q5_count"] = int(agg["count"])
            if not direct["q5_grid_count"] and agg["total_cells"]:
                direct["q5_grid_count"] = int(agg["total_cells"])
            if direct["q5_grid_avg"] is None and agg["avg_cells"] is not None:
                direct["q5_grid_avg"] = float(agg["avg_cells"])
            if direct["q5_price_total"] in (None, 0) and agg["total_price"]:
                direct["q5_price_total"] = int(agg["total_price"])
            if direct["q5_price_avg"] is None and agg["avg_price"] is not None:
                direct["q5_price_avg"] = float(agg["avg_price"])
        if q == 6:
            if direct["q6_count"] in (None, 0):
                direct["q6_count"] = int(agg["count"])
            if not direct["q6_grid_count"] and agg["total_cells"]:
                direct["q6_grid_count"] = int(agg["total_cells"])
            if direct["q6_grid_avg"] is None and agg["avg_cells"] is not None:
                direct["q6_grid_avg"] = float(agg["avg_cells"])
            if direct["q6_price_total"] in (None, 0) and agg["total_price"]:
                direct["q6_price_total"] = int(agg["total_price"])
            if direct["q6_price_avg"] is None and agg["avg_price"] is not None:
                direct["q6_price_avg"] = float(agg["avg_price"])


    for _pfx in ("q4_", "q5_", "q6_"):
        _infer_tier_count_grid_price(
            direct,
            count_k=f"{_pfx}count",
            grid_k=f"{_pfx}grid_count",
            avg_grid_k=f"{_pfx}grid_avg",
            avg_price_k=f"{_pfx}price_avg",
            total_price_k=f"{_pfx}price_total",
        )
        _finalize_tier_min_bounds(
            direct,
            count_k=f"{_pfx}count",
            grid_k=f"{_pfx}grid_count",
            avg_grid_k=f"{_pfx}grid_avg",
            avg_price_k=f"{_pfx}price_avg",
            count_min_k=f"{_pfx}count_min",
            grid_min_k=f"{_pfx}grid_min",
        )

    # ── 3) 综合整理：分档零一致性 ─────────────────────────────────────────
    for count_k, grid_k, avg_grid_k, avg_price_k, total_price_k, also_zero in (
        ("q3_count", "q3_grid_count", "q3_grid_avg", None, None, ()),
        (
            "q4_count",
            "q4_grid_count",
            "q4_grid_avg",
            "q4_price_avg",
            "q4_price_total",
            ("q4_count_min", "q4_grid_min"),
        ),
        (
            "q5_count",
            "q5_grid_count",
            "q5_grid_avg",
            "q5_price_avg",
            "q5_price_total",
            ("q5_count_min", "q5_grid_min"),
        ),
        (
            "q6_count",
            "q6_grid_count",
            "q6_grid_avg",
            "q6_price_avg",
            "q6_price_total",
            ("q6_count_min", "q6_grid_min"),
        ),
    ):
        _apply_tier_zero_coherence(
            direct,
            count_k=count_k,
            grid_k=grid_k,
            avg_grid_k=avg_grid_k,
            avg_price_k=avg_price_k,
            total_price_k=total_price_k,
            also_zero=also_zero,
        )
        
    _infer_q56_grid_from_total_and_q14(direct)

    if direct["q1_count"] is not None and direct["q2_count"] is not None:
        direct["q12_count"] = direct["q1_count"] + direct["q2_count"]

    return {
        "csv_quality_groups_avg_per_cell": csv_groups_per_cell,
        "csv_quality_groups_avg_per_item": csv_groups_per_item,
        "map_quality_avg_csv": map_quality_csv_path_resolved(snapshot_path_hint),
        "map_quality_avg_hit": bool(csv_groups_full),
        "event_stats": direct,
    }
