#!/usr/bin/env python3
"""艾哈迈德溢价（ahmad_premium）约束求解与输入校验所需的最小公共逻辑。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

COLOR_LABELS = {"blue": "蓝色", "purple": "紫色", "gold": "橙色", "red": "红色"}
ROLE_LABELS = {"ahmad": "艾哈迈德", "aisha": "艾莎", "none": "未知/通用"}
ROLE_ALIASES = {
    "ahmed": "ahmad",
    "raven": "ahmad",
    "lavin": "ahmad",
    "victor": "ahmad",
    "elsa": "aisha",
}


@dataclass
class ColorConstraint:
    avg: Optional[float] = None
    count: Optional[int] = None
    grid: Optional[int] = None
    min_count: Optional[int] = None


@dataclass
class PairSolution:
    counts: List[int]
    pair_map: Dict[int, List[int]]
    warns: List[str]


def normalize_role(role: object) -> str:
    raw = str(role or "none").strip().lower()
    raw = ROLE_ALIASES.get(raw, raw)
    return raw if raw in ROLE_LABELS else "ahmad"


def as_non_neg_int(value: object) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("布尔值不能作为整数输入")
    number = int(value)
    if number < 0:
        raise ValueError("数字必须是非负整数")
    return number


def as_non_neg_float(value: object) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("布尔值不能作为数字输入")
    number = float(value)
    if number < 0:
        raise ValueError("数字必须是非负数")
    return number


def raw_price_to_w(value: object) -> Optional[float]:
    number = as_non_neg_float(value)
    if number is None:
        return None
    return number / 10000.0


def avg_match(grid: int, count: int, avg: Optional[float], tolerance: float) -> bool:
    if avg is None:
        return True
    key = math.floor(avg * 100 + 1e-9)
    if count == 0:
        return grid == 0 and key == 0
    return math.floor((grid * 100) / count + 1e-9) == key


def uniq_sorted(values: Iterable) -> List:
    return sorted(set(values))


def get_color_constraint(data: dict, color: str) -> ColorConstraint:
    color_data = dict(data.get("constraints", {}).get(color, {}))
    return ColorConstraint(
        avg=as_non_neg_float(color_data.get("avg")),
        count=as_non_neg_int(color_data.get("count")),
        grid=as_non_neg_int(color_data.get("grid")),
        min_count=as_non_neg_int(color_data.get("min_count")),
    )


def solve_color(
    label: str, constraint: ColorConstraint, max_count: int, high_total: int, avg_tolerance: float
) -> PairSolution:
    warns: List[str] = []
    count_min = (
        constraint.count
        if constraint.count is not None
        else (constraint.min_count if constraint.min_count is not None else 0)
    )
    count_max = constraint.count if constraint.count is not None else min(max_count, high_total)
    pairs: List[Tuple[int, int]] = []

    for count in range(count_min, count_max + 1):
        if constraint.grid is not None:
            grid_min = constraint.grid
            grid_max = constraint.grid
        elif count == 0:
            grid_min = 0
            grid_max = 0
        else:
            grid_min = count
            grid_max = 18 * count

        for grid in range(grid_min, grid_max + 1):
            if count == 0 and grid != 0:
                continue
            if count > 0 and (grid < count or grid > 18 * count):
                continue
            if not avg_match(grid, count, constraint.avg, avg_tolerance):
                continue
            pairs.append((count, grid))

    if constraint.count is not None and constraint.grid is not None and not pairs:
        warns.append(f"{label}的总件数、总格数与平均格子不一致")
    elif not pairs:
        warns.append(f"{label}在当前输入下无可行解")
    if constraint.min_count is not None and constraint.count is not None and constraint.count < constraint.min_count:
        warns.append(f"{label}的总件数小于你设置的最少件数")

    pair_map: Dict[int, List[int]] = {}
    for count, grid in pairs:
        pair_map.setdefault(count, []).append(grid)

    return PairSolution(
        counts=uniq_sorted(count for count, _ in pairs),
        pair_map={count: sorted(grids) for count, grids in pair_map.items()},
        warns=warns,
    )


def solve_color_lexicographic_min(
    label: str, constraint: ColorConstraint, max_count: int, avg_tolerance: float
) -> PairSolution:
    """与 ``solve_color`` 相同的 ``avg_match`` / 格界规则，但只保留字典序最小的 ``(count, grid)`` 一条。"""
    warns: List[str] = []
    count_min = (
        constraint.count
        if constraint.count is not None
        else (constraint.min_count if constraint.min_count is not None else 0)
    )
    count_max = constraint.count if constraint.count is not None else max_count
    first: Optional[Tuple[int, int]] = None

    for count in range(count_min, count_max + 1):
        if constraint.grid is not None:
            grid_min = constraint.grid
            grid_max = constraint.grid
        elif count == 0:
            grid_min = 0
            grid_max = 0
        else:
            grid_min = count
            grid_max = 18 * count

        for grid in range(grid_min, grid_max + 1):
            if count == 0 and grid != 0:
                continue
            if count > 0 and (grid < count or grid > 18 * count):
                continue
            if not avg_match(grid, count, constraint.avg, avg_tolerance):
                continue
            first = (count, grid)
            break
        if first is not None:
            break

    if constraint.count is not None and constraint.grid is not None and first is None:
        warns.append(f"{label}的总件数、总格数与平均格子不一致")
    elif first is None:
        warns.append(f"{label}在当前输入下无可行解")
    if constraint.min_count is not None and constraint.count is not None and constraint.count < constraint.min_count:
        warns.append(f"{label}的总件数小于你设置的最少件数")

    if first is None:
        return PairSolution(counts=[], pair_map={}, warns=warns)
    c, g = first
    return PairSolution(counts=[c], pair_map={c: [g]}, warns=warns)


def color_has_feasible_positive_count(
    constraint: ColorConstraint, max_count: int, avg_tolerance: float
) -> bool:
    """是否存在件数 >= 1 的可行 (count, grid)（件数上界仅用 ``max_count``）。"""
    count_min = (
        constraint.count
        if constraint.count is not None
        else (constraint.min_count if constraint.min_count is not None else 0)
    )
    count_max = constraint.count if constraint.count is not None else max_count
    if count_max < 1:
        return False
    start = max(1, count_min)
    for count in range(start, count_max + 1):
        if constraint.grid is not None:
            grid_min = constraint.grid
            grid_max = constraint.grid
        else:
            grid_min = count
            grid_max = 18 * count
        for grid in range(grid_min, grid_max + 1):
            if count > 0 and (grid < count or grid > 18 * count):
                continue
            if not avg_match(grid, count, constraint.avg, avg_tolerance):
                continue
            return True
    return False


def green_white_total(data: dict) -> Optional[int]:
    green = as_non_neg_int(data.get("count_green"))
    white = as_non_neg_int(data.get("count_white"))
    direct = as_non_neg_int(data.get("wg_total"))
    if green is not None and white is not None:
        return green + white
    if direct is not None:
        return direct
    return None


def green_white_lower_bound(data: dict) -> int:
    green = as_non_neg_int(data.get("count_green"))
    white = as_non_neg_int(data.get("count_white"))
    green_min = as_non_neg_int(data.get("min_count_green")) or 0
    white_min = as_non_neg_int(data.get("min_count_white")) or 0
    return (green if green is not None else green_min) + (white if white is not None else white_min)


def derive_total_grid_all(data: dict) -> Optional[int]:
    direct = as_non_neg_int(data.get("total_grid_all"))
    if direct is not None:
        return direct
    total_all = as_non_neg_int(data.get("total_all"))
    avg_grid_all = as_non_neg_float(data.get("avg_grid_all"))
    if total_all is None or avg_grid_all is None:
        return None
    rounding = str(data.get("total_grid_rounding", "round")).strip().lower()
    product = total_all * avg_grid_all
    if rounding == "floor":
        return int(math.floor(product))
    if rounding == "ceil":
        return int(math.ceil(product))
    return int(round(product))


def enumerate_green_white_splits(data: dict, wg_total: int) -> List[Tuple[int, int]]:
    exact_green = as_non_neg_int(data.get("count_green"))
    exact_white = as_non_neg_int(data.get("count_white"))
    min_green = as_non_neg_int(data.get("min_count_green")) or 0
    min_white = as_non_neg_int(data.get("min_count_white")) or 0

    splits: List[Tuple[int, int]] = []
    if exact_green is not None and exact_white is not None:
        if exact_green + exact_white == wg_total and exact_green >= min_green and exact_white >= min_white:
            splits.append((exact_green, exact_white))
        return splits

    if exact_green is not None:
        white = wg_total - exact_green
        if white >= min_white and white >= 0 and exact_green >= min_green:
            splits.append((exact_green, white))
        return splits

    if exact_white is not None:
        green = wg_total - exact_white
        if green >= min_green and green >= 0 and exact_white >= min_white:
            splits.append((green, exact_white))
        return splits

    for green in range(min_green, wg_total - min_white + 1):
        white = wg_total - green
        if white < min_white:
            continue
        splits.append((green, white))
    return splits


def enumerate_high_totals(data: dict) -> List[Tuple[int, int]]:
    total_all = as_non_neg_int(data.get("total_all"))
    wg_total = green_white_total(data)
    wg_min_total = green_white_lower_bound(data)
    if total_all is None:
        return []
    if wg_total is not None:
        high_total = total_all - wg_total
        return [(high_total, wg_total)] if high_total >= 0 and wg_total >= wg_min_total else []

    counts = []
    for color in ("blue", "purple", "gold", "red"):
        count_value = as_non_neg_int(data.get("constraints", {}).get(color, {}).get("count"))
        if count_value is None:
            counts = []
            break
        counts.append(count_value)
    if len(counts) == 4:
        high_total = sum(counts)
        inferred_wg = total_all - high_total
        return [(high_total, inferred_wg)] if inferred_wg >= wg_min_total else []

    return [(total_all - candidate_wg, candidate_wg) for candidate_wg in range(wg_min_total, total_all + 1)]


def empty_solved() -> Dict[str, dict]:
    return {color: {"counts": [], "pair_map": {}, "warns": []} for color in ("blue", "purple", "gold", "red")}


def normalize_solved(solved: Dict[str, dict]) -> Dict[str, dict]:
    for color in solved:
        solved[color]["counts"] = uniq_sorted(solved[color]["counts"])
        solved[color]["warns"] = sorted(set(solved[color]["warns"]))
        solved[color]["pair_map"] = {count: uniq_sorted(grids) for count, grids in solved[color]["pair_map"].items()}
    return solved


def validate_input(data: dict) -> List[str]:
    warns = []
    total_all = as_non_neg_int(data.get("total_all"))
    total_grid_all = derive_total_grid_all(data)
    wg_total = green_white_total(data)
    green_count = as_non_neg_int(data.get("count_green"))
    white_count = as_non_neg_int(data.get("count_white"))
    green_min = as_non_neg_int(data.get("min_count_green"))
    white_min = as_non_neg_int(data.get("min_count_white"))
    max_count = as_non_neg_int(data.get("max_count"))
    max_show = as_non_neg_int(data.get("max_show"))
    round_no = as_non_neg_int(data.get("round"))
    avg_tolerance = as_non_neg_float(data.get("avg_tolerance"))
    for color in ("green", "white", "blue", "purple", "gold", "red"):
        try:
            as_non_neg_float(data.get(f"grid_price_{color}"))
        except Exception as exc:
            warns.append(f"{color} 单格价格输入非法: {exc}")

    if total_all is None:
        warns.append("缺少 total_all（总藏品数）")
    if max_count is None or max_count < 1:
        warns.append("max_count 必须是正整数")
    if max_show is None or max_show < 1:
        warns.append("max_show 必须是正整数")
    if round_no is None or round_no < 1 or round_no > 5:
        warns.append("round 必须是 1 到 5 之间的整数")
    if avg_tolerance is None:
        warns.append("缺少 avg_tolerance（平均格容差）")
    elif avg_tolerance < 0 or avg_tolerance > 0.2:
        warns.append("avg_tolerance 建议在 0 到 0.2 之间")
    if total_all is not None and wg_total is not None and wg_total > total_all:
        warns.append("绿白总数量不能大于总藏品数")
    if green_count is not None and green_min is not None and green_count < green_min:
        warns.append("绿色数量不能小于绿色至少件数")
    if white_count is not None and white_min is not None and white_count < white_min:
        warns.append("白色数量不能小于白色至少件数")
    if total_grid_all is not None and total_all is not None and total_grid_all < total_all:
        warns.append("全部总格子数不能小于总藏品数")

    candidates = enumerate_high_totals(data)
    if not candidates:
        warns.append("当前信息不足以确定高品质总数（蓝紫橙红总数）")

    for color in ("blue", "purple", "gold", "red"):
        try:
            get_color_constraint(data, color)
        except Exception as exc:
            warns.append(f"{COLOR_LABELS[color]}输入非法: {exc}")

    return warns
