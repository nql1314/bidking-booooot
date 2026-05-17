"""raw_pricing：从事件与 CSV 提取未加工全局统计。

技能日志 → ``event_stats`` **标量直读与轮廓补全**见 :mod:`bidking.analysis.skill_event_stats_from_logs`
（:func:`parse_skill_entries_to_event_stats_direct`、:data:`EVENT_STATS_ATTRIBUTE_SOURCES`）。

本模块负责 **已知字段上的推理**：随机均价下界、分档 count/grid/price 互推、金红总格守恒、
q12 汇总、分档零一致性等。
"""

from __future__ import annotations

import csv
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..parsing import item_db
from ..parsing.constants import *
from ..parsing.skill_bindings import (
    MAP_SKILL_RANDOM12_AVG_PRICE,
    MAP_SKILL_RANDOM3_AVG_PRICE,
    MAP_SKILL_RANDOM6_AVG_PRICE,
    MAP_SKILL_RANDOM9_AVG_PRICE,
)
from ..parsing.state import CsvItem
from .skill_event_stats_from_logs import (
    merge_latest_skill_entries,
    parse_skill_entries_to_event_stats_direct,
    round_computed_div_avg,
    safe_float_field,
    safe_int_field,
)
from .map_avg_csv import (
    map_quality_csv_path_resolved,
)
from .tier_combo_presolve import presolve_grid_sums


def _min_total_from_avg(avg: Optional[float]) -> Optional[int]:
    """浮点总价/乘积的整数化下界（四舍五入），不再用分数分子以免数值爆炸。"""
    if avg is None:
        return None
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return None
    if a <= 0 or a != a:
        return None
    return max(0, int(round(a)))

_RANDOM_AVG_DEFAULT_HIT_COUNT: Dict[int, int] = {
    MAP_SKILL_RANDOM3_AVG_PRICE: 3,
    MAP_SKILL_RANDOM6_AVG_PRICE: 6,
    MAP_SKILL_RANDOM9_AVG_PRICE: 9,
    MAP_SKILL_RANDOM12_AVG_PRICE: 12,
}


def _min_total_price_from_avg_times_hit_count(
    avg: Optional[float],
    hit_count: Optional[int],
    *,
    skill_cid: int,
) -> Optional[int]:
    """随机 3/6/9/12 均价 × ``HitItemIndex`` 命中件数 → 总价下界；件数缺失或非正时按技能默认 3/6/9。"""
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


_RATIO_INFER_TOL = 1e-4

# ``avg * n`` 与最近整数距离 ≤ delta 时，``n`` 的上限搜索范围（防极端无理数/浮点噪声死循环）。
_AVG_NEAR_INTEGER_MAX_MULTIPLIER = 200

# 地图分档（紫/金/红）组合反推：件数枚举上界（与预计算表 ``n``≤3 一致）；超过则不查表。
_TIER_COMBO_MAX_ITEM_COUNT = 3

# 放宽距离阈值时上限：任意正数 ``avg`` 在 ``n=1`` 下距离最近整数恒 ≤ 0.5。
_MAX_NEAR_INTEGER_DELTA = 0.5

# 地图技能 ``AllHitItemAvgPrice`` 等：在 ``1..N`` 内做件数启发式时 ``N`` 的缺省上界（可被 ``pricing.price_avg_infer_max_item_count`` 覆盖）。
_DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT = 30


def resolve_price_avg_infer_max_item_count(
    explicit: Optional[int] = None,
    *,
    pricing_dict: Optional[Dict[str, Any]] = None,
) -> int:
    """解析 ``pricing.price_avg_infer_max_item_count``（缺省 ``_DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT``，限制在 ``1..200``）。"""
    if explicit is not None:
        try:
            return max(1, min(200, int(explicit)))
        except (TypeError, ValueError):
            pass
    if isinstance(pricing_dict, dict):
        try:
            v = int(pricing_dict.get("price_avg_infer_max_item_count", _DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT))
            return max(1, min(200, v))
        except (TypeError, ValueError):
            pass
    return _DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT


# 均格：``grid_avg * 件数 ≈ 总格`` 的乘数上界缺省（``pricing.grid_avg_infer_max_item_count``）；
# 由均格反推**总格**唯一解时候选 ``G`` 上界缺省（``pricing.grid_avg_infer_max_grid_count``）。
_DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT = 30
_DEFAULT_GRID_AVG_INFER_MAX_GRID_COUNT = 60


def resolve_grid_avg_infer_max_item_count(
    explicit: Optional[int] = None,
    *,
    pricing_dict: Optional[Dict[str, Any]] = None,
) -> int:
    """解析 ``pricing.grid_avg_infer_max_item_count``（缺省 ``_DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT``，限制在 ``1..200``）。"""
    if explicit is not None:
        try:
            return max(1, min(200, int(explicit)))
        except (TypeError, ValueError):
            pass
    if isinstance(pricing_dict, dict):
        try:
            v = int(pricing_dict.get("grid_avg_infer_max_item_count", _DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT))
            return max(1, min(200, v))
        except (TypeError, ValueError):
            pass
    return _DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT


def resolve_grid_avg_infer_max_grid_count(
    explicit: Optional[int] = None,
    *,
    pricing_dict: Optional[Dict[str, Any]] = None,
) -> int:
    """解析 ``pricing.grid_avg_infer_max_grid_count``（缺省 ``_DEFAULT_GRID_AVG_INFER_MAX_GRID_COUNT``，限制在 ``1..500``）。"""
    if explicit is not None:
        try:
            return max(1, min(500, int(explicit)))
        except (TypeError, ValueError):
            pass
    if isinstance(pricing_dict, dict):
        try:
            v = int(pricing_dict.get("grid_avg_infer_max_grid_count", _DEFAULT_GRID_AVG_INFER_MAX_GRID_COUNT))
            return max(1, min(500, v))
        except (TypeError, ValueError):
            pass
    return _DEFAULT_GRID_AVG_INFER_MAX_GRID_COUNT


def _dist_to_nearest_integer_positive(x: float) -> float:
    """正有限 ``x`` 到最近整数的距离，取值 ``[0, 0.5]``。"""
    if x != x or x <= 0:
        return 0.5
    t = math.fmod(x, 1.0)
    if t < 0:
        t += 1.0
    return min(t, 1.0 - t)


def _min_positive_int_avg_product_near_integer(
    avg: Optional[float],
    *,
    delta: float = _RATIO_INFER_TOL,
    max_n: int = _AVG_NEAR_INTEGER_MAX_MULTIPLIER,
) -> Optional[int]:
    """最小正整数 ``n`` 使得 ``avg * n`` 与某整数相差不超过 ``delta``。

    用于均格/小数均价等「件数倍乘后应为整数总量」的启发式；找不到则返回 ``None``。
    """
    if avg is None:
        return None
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return None
    if a <= 0 or a != a:
        return None
    for n in range(1, max_n + 1):
        prod = a * n
        if prod != prod:
            return None
        if _dist_to_nearest_integer_positive(prod) <= delta:
            return n
    return None


def _min_positive_int_avg_product_near_integer_relaxed(
    avg: Optional[float],
    *,
    max_n: int = _AVG_NEAR_INTEGER_MAX_MULTIPLIER,
    reject_n_above: Optional[int] = None,
) -> Optional[int]:
    """在 ``1..max_n`` 内找最小 ``n`` 使 ``avg*n`` 接近整数；阈值从 ``_RATIO_INFER_TOL`` 起每次 ×10 放宽直至 ``_MAX_NEAR_INTEGER_DELTA``（此时 ``n=1`` 必成立）。

    ``reject_n_above``：若本档 ``delta`` 下得到的最小 ``n`` 大于该值，不采纳，继续放宽 ``delta`` 再找
    （用于均价侧件数启发式，避免如 ``38398.168`` 在极严阈值下先命中 ``n=125`` 之类不可信大倍数）。
    """
    delta = float(_RATIO_INFER_TOL)
    while delta <= _MAX_NEAR_INTEGER_DELTA + 1e-15:
        n = _min_positive_int_avg_product_near_integer(avg, delta=delta, max_n=max_n)
        if n is not None:
            if reject_n_above is not None and n > int(reject_n_above):
                n = None
            else:
                return n
        delta *= 10.0
    return None


def _unique_n_price_avg_in_relaxed_band(avg: float, band_max: int) -> Optional[int]:
    """在 ``1..min(band_max, _AVG_NEAR_INTEGER_MAX_MULTIPLIER)`` 内，按与 ``_min_positive_int_avg_product_near_integer_relaxed`` 相同的 ``delta`` 序列扫描：
    第一次出现**恰好一个** ``n`` 使 ``avg*n`` 到最近整数距离 ≤ ``delta`` 时返回该 ``n``；否则 ``None``。

    整数均价（``_near_int(avg)``）下任意 ``n`` 的乘积常为整数，件数不唯一，返回 ``None``。
    """
    if avg <= 0 or avg != avg:
        return None
    if _near_int(avg):
        return None
    cap = max(1, min(int(band_max), int(_AVG_NEAR_INTEGER_MAX_MULTIPLIER)))
    delta = float(_RATIO_INFER_TOL)
    while delta <= _MAX_NEAR_INTEGER_DELTA + 1e-15:
        hits: List[int] = []
        for n in range(1, cap + 1):
            prod = avg * float(n)
            if prod != prod:
                continue
            if _dist_to_nearest_integer_positive(prod) <= delta:
                hits.append(n)
        if len(hits) == 1:
            return int(hits[0])
        delta *= 10.0
    return None


def _unique_grid_total_from_grid_avg_relaxed_band(ag: float, band_max_grid: int) -> Optional[int]:
    """在 ``1..band_max_grid``（上限再夹到 500）内，按与均价唯一解相同的 ``delta`` 序列扫描：
    第一次出现**恰好一个** ``G`` 使 ``G / grid_avg``（隐含件数）到最近整数距离 ≤ ``delta`` 时返回 ``G``；否则 ``None``。

    整数均格下 ``G/ag`` 常为整数，多 ``G`` 同时成立，返回 ``None``。
    """
    if ag <= 0 or ag != ag:
        return None
    if _near_int(ag):
        return None
    cap = max(1, min(int(band_max_grid), 500))
    delta = float(_RATIO_INFER_TOL)
    while delta <= _MAX_NEAR_INTEGER_DELTA + 1e-15:
        hits: List[int] = []
        for G in range(1, cap + 1):
            rat = float(G) / ag
            if rat != rat:
                continue
            if _dist_to_nearest_integer_positive(rat) <= delta:
                hits.append(G)
        if len(hits) == 1:
            return int(hits[0])
        delta *= 10.0
    return None


def _try_infer_unique_count_from_price_avg(
    d: Dict[str, Any],
    *,
    count_k: str,
    total_price_k: Optional[str],
    avg_price_k: str,
    band_max: int,
) -> None:
    """若件数未知且均价已知：在 ``1..band_max`` 内找「唯一倍数」则写入件数；总价缺失时补 ``round(avg*n)``。

    若日志已有总价且与 ``round(avg*n)`` 偏差 > 0.5，则不写入（避免与已知总量矛盾）。
    """
    if _as_int_count(d.get(count_k)) is not None:
        return
    ap = d.get(avg_price_k)
    if not _is_positive_finite_float(ap):
        return
    a = float(ap)
    n_u = _unique_n_price_avg_in_relaxed_band(a, band_max)
    if n_u is None:
        return
    t_round = int(round(a * float(n_u)))
    if total_price_k:
        t0 = _as_int_count(d.get(total_price_k))
        if t0 is not None and t0 > 0 and abs(float(t0) - float(t_round)) > 0.51:
            return
    d[count_k] = int(n_u)
    if total_price_k and d.get(total_price_k) is None:
        d[total_price_k] = int(t_round)


def _try_infer_unique_grid_from_grid_avg(
    d: Dict[str, Any],
    *,
    count_k: str,
    grid_k: str,
    avg_grid_k: str,
    band_max_grid: int,
) -> None:
    """若总格未知且均格已知：在 ``1..band_max_grid`` 内找唯一 ``G`` 使 ``G/grid_avg`` 接近整数件数，则写入 ``grid_count``；件数缺失时补 ``round(G/ag)``。

    若日志已有件数且与 ``round(G/ag)`` 偏差 > 0.5，则不写入。
    """
    if _as_int_count(d.get(grid_k)) is not None:
        return
    ag = d.get(avg_grid_k)
    if not _is_positive_finite_float(ag):
        return
    a = float(ag)
    g_u = _unique_grid_total_from_grid_avg_relaxed_band(a, band_max_grid)
    if g_u is None:
        return
    c_round = int(round(float(g_u) / a))
    if c_round <= 0:
        return
    c0 = _as_int_count(d.get(count_k))
    if c0 is not None and c0 > 0 and abs(float(c0) - float(c_round)) > 0.51:
        return
    d[grid_k] = int(g_u)
    if _as_int_count(d.get(count_k)) is None:
        d[count_k] = int(c_round)


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


def _min_merge_bound_from_price_avg(avg: Optional[float], *, max_item_count: int) -> Optional[int]:
    """与 ``count_min`` / ``grid_min`` 合并用的均价侧下界：整数均价为 ``1``；否则取最小倍数 ``n``（阈值逐级放宽，见 ``_min_positive_int_avg_product_near_integer_relaxed``）。

    若当前 ``delta`` 下最小 ``n`` 大于 ``max_item_count``，不采纳该解，继续放宽距离阈值直至得到不超过该上界的 ``n``。
    """
    if avg is None:
        return None
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return None
    if a <= 0 or a != a:
        return None
    if _near_int(a):
        return 1
    return _min_positive_int_avg_product_near_integer_relaxed(
        avg,
        reject_n_above=max(1, min(200, int(max_item_count))),
    )


def _merge_with_min_from_avg(
    existing: Optional[int],
    avg: Optional[float],
    *,
    from_price: bool = False,
    from_grid_avg: bool = False,
    price_avg_infer_max_item_count: int = _DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT,
    grid_avg_infer_max_item_count: int = _DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT,
) -> Optional[int]:
    """由均格/均价推算的下界与 ``existing`` 取较大者。

    均格侧与均价侧数学形式相同（``avg*n`` 接近整数），均格合并到 ``count_min`` 时使用独立上界
    ``grid_avg_infer_max_item_count``（见 ``_min_merge_bound_from_price_avg``）。
    """
    if from_price:
        inferred = _min_merge_bound_from_price_avg(avg, max_item_count=price_avg_infer_max_item_count)
    elif from_grid_avg:
        inferred = _min_merge_bound_from_price_avg(avg, max_item_count=grid_avg_infer_max_item_count)
    else:
        inferred = _min_positive_int_avg_product_near_integer_relaxed(avg)
    return _max_optional_int(existing, inferred)


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
            d[avg_grid_k] = round_computed_div_avg(float(G) / float(n))
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
                d[avg_price_k] = round_computed_div_avg(float(T) / float(n))
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
    price_avg_infer_max_item_count: int = _DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT,
    grid_avg_infer_max_item_count: int = _DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT,
) -> None:
    """合并 ``count_min`` / ``grid_min``。

    ``count_min``：在观测件数/总格基础上，与均价、均格启发式下界取大（均价为整数时侧下界为 ``1``；
    否则取最小正整数使 ``avg*n`` 接近整数；均价侧若严阈值下最小 ``n`` 超过 ``price_avg_infer_max_item_count``
    则继续放宽距离阈值再找，见 ``_min_merge_bound_from_price_avg``；
    均格侧形式相同但使用独立上界 ``grid_avg_infer_max_item_count``；无均格观测时仍可用宽松 ``delta`` 启发式）。

    ``grid_min``：若观测总格 ``G``（``grid_k``）已为整数，则 **等于 ``G``**（与启发式下界脱钩）。
    否则：有均格 ``ag`` 时为 ``ag * count_min``（乘积四舍五入）；无均格时为 ``count_min``；
    再与 ``base_grid``（件数、总格观测）取大。
    """
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
        _merge_with_min_from_avg(
            n,
            ap,
            from_price=True,
            price_avg_infer_max_item_count=price_avg_infer_max_item_count,
        ),
    )
    cm = _merge_with_min_from_avg(
        cm,
        ag,
        from_price=False,
        from_grid_avg=True,
        price_avg_infer_max_item_count=price_avg_infer_max_item_count,
        grid_avg_infer_max_item_count=grid_avg_infer_max_item_count,
    )

    gm: Optional[int]
    if cm is not None and _is_positive_finite_float(ag):
        gm = int(round(float(ag) * float(cm)))
        if gm < 1:
            gm = 1
    elif cm is not None:
        gm = int(cm)
    else:
        gm = None
    gm = _max_optional_int(base_grid, gm)

    d[count_min_k] = cm
    if G is not None:
        d[grid_min_k] = int(G)
    else:
        d[grid_min_k] = gm


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


def event_stats_q12_q3_q4_grids_all_known(raw: Any) -> bool:
    """``event_stats`` 中低档占用总格是否齐备：``q12_grid_count``、``q3_grid_count``、``q4_grid_count``。

    若无 ``q12_grid_count`` 但 ``q1_grid_count`` 与 ``q2_grid_count`` 均已给出，亦视为绿白总格已知
    （与 ``q12_grid_count = q1+q2`` 语义一致）。
    """
    if not isinstance(raw, dict):
        return False
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return False
    if st.get("q3_grid_count") is None or st.get("q4_grid_count") is None:
        return False
    if st.get("q12_grid_count") is not None:
        return True
    return st.get("q1_grid_count") is not None and st.get("q2_grid_count") is not None


def _infer_q56_grid_from_total_and_q14(d: Dict[str, Any]) -> None:
    """由 ``total_grid_count`` 与低档总格（**q12+q3+q4** 或等价的 q1–q4）推出金/红缺失档。

    恒等式：总数 = q12 + q3 + q4 + q5 + q6（其中 q12 = q1+q2 总格）。若 ``q12_grid_count`` 未写，
    但 ``q1_grid_count`` 与 ``q2_grid_count`` 已知，则在此用二者之和参与守恒。
    若 q5、q6 中至少有一档总格已由日志给出（或该档件数为 0 可视为 0 格），则可推算另一档的精确总格。
    仅填补仍为 ``None`` 的 ``q5_grid_count`` / ``q6_grid_count``，不覆盖已有整数。
    """
    T = _as_int_count(d.get("total_grid_count"))
    if T is None:
        return
    g12 = _as_int_count(d.get("q12_grid_count"))
    if g12 is None:
        g1 = _as_int_count(d.get("q1_grid_count"))
        g2 = _as_int_count(d.get("q2_grid_count"))
        if g1 is not None and g2 is not None:
            g12 = int(g1) + int(g2)
    g3 = _as_int_count(d.get("q3_grid_count"))
    g4 = _as_int_count(d.get("q4_grid_count"))
    if g12 is None or g3 is None or g4 is None:
        return

    sum124 = int(g12) + int(g3) + int(g4)
    remainder = int(T) - sum124
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


_item_prices_cache: Optional[Tuple[Dict[int, CsvItem], List[CsvItem]]] = None


def _load_item_prices_for_combo() -> List[CsvItem]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache[1]
    if not os.path.isfile(CSV_PATH):
        _item_prices_cache = ({}, [])
        return []
    try:
        _item_prices_cache = item_db.load_csv(CSV_PATH)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache[1]


def _tier_candidate_nt_list(d: Dict[str, Any], pfx: str) -> List[Tuple[int, int]]:
    """由均价（及可选总价、件数）枚举与数值关系一致的 ``(n, 总价 T)``；不参与总格、均格约束。"""
    ap = d.get(f"{pfx}price_avg")
    if not _is_positive_finite_float(ap):
        return []
    apf = float(ap)
    n_obs = _as_int_count(d.get(f"{pfx}count"))
    T_obs = _as_int_count(d.get(f"{pfx}price_total"))

    seen: Set[Tuple[int, int]] = set()
    out: List[Tuple[int, int]] = []

    def push(n: int, T: int) -> None:
        if n <= 0 or T <= 0:
            return
        if abs(float(T) / float(n) - apf) > _RATIO_INFER_TOL:
            return
        if T_obs is not None and int(T_obs) != int(T):
            return
        key = (n, T)
        if key not in seen:
            seen.add(key)
            out.append(key)

    if n_obs is not None and n_obs > 0:
        n = int(n_obs)
        if T_obs is not None:
            T = int(T_obs)
        elif _near_int(float(n) * apf):
            T = int(round(float(n) * apf))
        else:
            return []
        push(n, T)
        return out

    for n in range(1, _TIER_COMBO_MAX_ITEM_COUNT + 1):
        if not _near_int(float(n) * apf):
            continue
        T = int(round(float(n) * apf))
        if T_obs is not None and int(T_obs) != T:
            continue
        push(n, T)

    if T_obs is not None and (n_obs is None or n_obs <= 0):
        n0 = max(1, int(round(float(T_obs) / apf)))
        if n0 <= _TIER_COMBO_MAX_ITEM_COUNT and _near_int(float(T_obs) / float(n0) - apf):
            push(n0, int(T_obs))

    return out


def _tier_combo_grid_sums(quality: int, n: int, *, T_need: int) -> Set[int]:
    """``(品质, n, 总价)`` 下可达总格：仅 ``tier_combo_presolve_q456.json``；无表项则为空集。"""
    looked = presolve_grid_sums(quality, n, int(T_need))
    return set(looked) if looked is not None else set()


def _apply_tier_item_combo_from_csv(
    d: Dict[str, Any],
    pfx: str,
    quality: int,
    csv_items: Sequence[CsvItem],
    *,
    price_avg_infer_max_item_count: int = _DEFAULT_PRICE_AVG_INFER_MAX_ITEM_COUNT,
    grid_avg_infer_max_item_count: int = _DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT,
) -> None:
    """在有效 ``price_avg`` 且该档 ``*_grid_count`` 仍未知时，用 CSV 无重复子集解释件数与总价。

    不在此用总格作约束；技能已给出总格时跳过（由其它路径维护）。无有效均价时不运行。

    件数枚举不超过 ``_TIER_COMBO_MAX_ITEM_COUNT``；**件数仍未知**且 ``count_min`` 大于该上界时不做组合枚举（避免离谱下界）。

    若日志/均价唯一推理已给出 ``count``，即使 ``count_min`` 较大仍可用预计算表尝试补全 ``grid_count``。

    唯一 ``(总价, 总格)`` 时写入 ``count`` / ``price_total`` / ``grid_count`` 并刷新均价、均格；
    否则仅强化 ``count_min`` / ``grid_min``。
    """
    pool = [it for it in csv_items if it.quality == quality]
    if not pool:
        return

    count_k = f"{pfx}count"
    grid_k = f"{pfx}grid_count"
    avg_grid_k = f"{pfx}grid_avg"
    avg_price_k = f"{pfx}price_avg"
    total_k = f"{pfx}price_total"
    count_min_k = f"{pfx}count_min"
    grid_min_k = f"{pfx}grid_min"

    if not _is_positive_finite_float(d.get(avg_price_k)):
        return
    if _as_int_count(d.get(grid_k)) is not None:
        return
    n_locked = _as_int_count(d.get(count_k))
    cm0 = _as_int_count(d.get(count_min_k))
    if n_locked is None and cm0 is not None and cm0 > _TIER_COMBO_MAX_ITEM_COUNT:
        return
    triples = _tier_candidate_nt_list(d, pfx)
    if not triples:
        return

    triples.sort(key=lambda x: (x[0], x[1]))

    feasible: List[Tuple[int, int, Set[int]]] = []
    n_min: Optional[int] = None
    for n, T in triples:
        if n_min is not None and n > n_min:
            break
        gs = _tier_combo_grid_sums(quality, n, T_need=T)
        if not gs:
            continue
        if n_min is None:
            n_min = n
        if n == n_min:
            feasible.append((n, T, gs))

    if not feasible or n_min is None:
        return

    outcomes: Set[Tuple[int, int]] = set()
    for _n, T, gs in feasible:
        for g in gs:
            outcomes.add((T, int(g)))

    if len(outcomes) == 1:
        T_u, G_u = next(iter(outcomes))
        n_u = int(n_min)
        d[count_k] = n_u
        d[total_k] = int(T_u)
        d[grid_k] = int(G_u)
        d[avg_grid_k] = round_computed_div_avg(float(G_u) / float(n_u))
        d[avg_price_k] = round_computed_div_avg(float(T_u) / float(n_u))
        _finalize_tier_min_bounds(
            d,
            count_k=count_k,
            grid_k=grid_k,
            avg_grid_k=avg_grid_k,
            avg_price_k=avg_price_k,
            count_min_k=count_min_k,
            grid_min_k=grid_min_k,
            price_avg_infer_max_item_count=price_avg_infer_max_item_count,
            grid_avg_infer_max_item_count=grid_avg_infer_max_item_count,
        )
        return

    cm = _as_int_count(d.get(count_min_k))
    cm = _max_optional_int(cm, int(n_min))
    d[count_min_k] = cm

    grid_mins: List[int] = []
    for _n, T, gs in feasible:
        grid_mins.extend(int(g) for g in gs)
    if grid_mins:
        gm = min(grid_mins)
        ex = _as_int_count(d.get(grid_min_k))
        d[grid_min_k] = _max_optional_int(ex, gm)


def build_raw_pricing_dict(
    *,
    map_id: int,
    skill_logs: List[dict],
    snapshot_path_hint: Optional[str] = None,
    price_avg_infer_max_item_count: Optional[int] = None,
    grid_avg_infer_max_item_count: Optional[int] = None,
    grid_avg_infer_max_grid_count: Optional[int] = None,
) -> Dict[str, Any]:
    """构建 raw_pricing（仅保存原始全局信息，不做策略估算）。

    返回含 ``event_stats``、``census_absent_qualities``（分档零一致性整理后 ``qK_count==0`` 的品质列表，
    供 :mod:`.scan_inference` 与 UI 负向合并）等。

    ``price_avg_infer_max_item_count``：紫/金/红 ``AllHitItemAvgPrice`` 件数启发式上界（``1..200``）；
    省略时读取合并配置 ``pricing.price_avg_infer_max_item_count``。

    ``grid_avg_infer_max_item_count`` / ``grid_avg_infer_max_grid_count``：均格侧合并到 ``count_min`` 的乘数上界、
    以及由均格反推总格唯一解时的候选 ``G`` 上界（``1..500``）；省略时读 ``pricing.*`` 缺省分别为
    ``_DEFAULT_GRID_AVG_INFER_MAX_ITEM_COUNT`` / ``_DEFAULT_GRID_AVG_INFER_MAX_GRID_COUNT``。
    """

    _pd: Dict[str, Any] = {}
    try:
        from ..config.runtime import load_runtime

        _p = load_runtime().raw.get("pricing")
        if isinstance(_p, dict):
            _pd = _p
    except Exception:
        pass

    if price_avg_infer_max_item_count is not None:
        mic = resolve_price_avg_infer_max_item_count(explicit=price_avg_infer_max_item_count)
    else:
        mic = resolve_price_avg_infer_max_item_count(pricing_dict=_pd)

    if grid_avg_infer_max_item_count is not None:
        gmic = resolve_grid_avg_infer_max_item_count(explicit=grid_avg_infer_max_item_count)
    else:
        gmic = resolve_grid_avg_infer_max_item_count(pricing_dict=_pd)

    if grid_avg_infer_max_grid_count is not None:
        gmgc = resolve_grid_avg_infer_max_grid_count(explicit=grid_avg_infer_max_grid_count)
    else:
        gmgc = resolve_grid_avg_infer_max_grid_count(pricing_dict=_pd)

    skill_merged = merge_latest_skill_entries(list(skill_logs or []))
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

    # ── 1) 随机均价下界（多地图技能聚合推理）────────────────────────────
    random_avg_price_min: Optional[int] = None
    for _rnd_cid in (
        MAP_SKILL_RANDOM3_AVG_PRICE,
        MAP_SKILL_RANDOM6_AVG_PRICE,
        MAP_SKILL_RANDOM9_AVG_PRICE,
        MAP_SKILL_RANDOM12_AVG_PRICE,
    ):
        ent = skill_merged.by_skill_cid.get(_rnd_cid)
        avg_f = safe_float_field(ent, "AllHitItemAvgPrice") if isinstance(ent, dict) else None
        hc = safe_int_field(ent, "HitItemIndex") if isinstance(ent, dict) else None
        inferred = _min_total_price_from_avg_times_hit_count(
            avg_f, hc, skill_cid=_rnd_cid
        )
        random_avg_price_min = _max_optional_int(random_avg_price_min, inferred)

    direct = parse_skill_entries_to_event_stats_direct(skill_merged)
    direct["random_avg_price_min"] = random_avg_price_min

    # ── 2) 已知字段上的推理（分档互推、CSV 组合、零一致性、q12 汇总等）──
    _infer_tier_count_grid_price(
        direct,
        count_k="total_count",
        grid_k="total_grid_count",
        avg_grid_k="total_grid_avg",
        avg_price_k=None,
        total_price_k=None,
    )

    csv_items_combo = _load_item_prices_for_combo()
    for _pfx, _q in (("q4_", 4), ("q5_", 5), ("q6_", 6)):
        _infer_tier_count_grid_price(
            direct,
            count_k=f"{_pfx}count",
            grid_k=f"{_pfx}grid_count",
            avg_grid_k=f"{_pfx}grid_avg",
            avg_price_k=f"{_pfx}price_avg",
            total_price_k=f"{_pfx}price_total",
        )
        _try_infer_unique_count_from_price_avg(
            direct,
            count_k=f"{_pfx}count",
            total_price_k=f"{_pfx}price_total",
            avg_price_k=f"{_pfx}price_avg",
            band_max=mic,
        )
        _try_infer_unique_grid_from_grid_avg(
            direct,
            count_k=f"{_pfx}count",
            grid_k=f"{_pfx}grid_count",
            avg_grid_k=f"{_pfx}grid_avg",
            band_max_grid=gmgc,
        )
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
            price_avg_infer_max_item_count=mic,
            grid_avg_infer_max_item_count=gmic,
        )
        _apply_tier_item_combo_from_csv(
            direct,
            _pfx,
            _q,
            csv_items_combo,
            price_avg_infer_max_item_count=mic,
            grid_avg_infer_max_item_count=gmic,
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

    census_absent_qualities = sorted(q for q in range(1, 7) if direct.get(f"q{q}_count") == 0)

    _infer_q56_grid_from_total_and_q14(direct)

    if direct["q1_count"] is not None and direct["q2_count"] is not None:
        direct["q12_count"] = direct["q1_count"] + direct["q2_count"]

    g1_q12 = _as_int_count(direct.get("q1_grid_count"))
    g2_q12 = _as_int_count(direct.get("q2_grid_count"))
    if g1_q12 is not None and g2_q12 is not None:
        direct["q12_grid_count"] = int(g1_q12) + int(g2_q12)

    gc12 = _as_int_count(direct.get("q12_grid_count"))
    nc12 = _as_int_count(direct.get("q12_count"))
    if gc12 is not None and nc12 is not None and nc12 > 0:
        direct["q12_grid_avg"] = round_computed_div_avg(float(gc12) / float(nc12))

    p1_q12 = _as_int_count(direct.get("q1_price_total"))
    p2_q12 = _as_int_count(direct.get("q2_price_total"))
    if p1_q12 is not None and p2_q12 is not None:
        direct["q12_price_total"] = int(p1_q12) + int(p2_q12)

    return {
        "csv_quality_groups_avg_per_cell": csv_groups_per_cell,
        "csv_quality_groups_avg_per_item": csv_groups_per_item,
        "map_quality_avg_csv": map_quality_csv_path_resolved(snapshot_path_hint),
        "map_quality_avg_hit": bool(csv_groups_full),
        "event_stats": direct,
        "census_absent_qualities": census_absent_qualities,
    }
