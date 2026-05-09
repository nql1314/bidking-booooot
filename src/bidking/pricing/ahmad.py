#!/usr/bin/env python3
"""艾哈迈德溢价（ahmad_premium）估价与价值锚上限逻辑。"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from ..logsys.perf_log import perf_log, perf_log_elapsed

from ._constraint_solver import (
    COLOR_LABELS,
    ColorConstraint,
    as_non_neg_float,
    as_non_neg_int,
    color_has_feasible_positive_count,
    empty_solved,
    enumerate_green_white_splits,
    get_color_constraint,
    green_white_total,
    normalize_role,
    normalize_solved,
    raw_price_to_w,
    solve_color,
    solve_color_lexicographic_min,
    validate_input,
)

# ---------------------------------------------------------------------------
# 算法配置（与 price_config.json 中 ahmad_premium 段默认值一致的可调项）
# ---------------------------------------------------------------------------

# JSON 中 ahmad_premium 配置节名称
AHMAD_PREMIUM_CONFIG_KEY = "ahmad_premium"

# 与回合相关的嵌套表：按回合键合并其内部的紫/金/红等子键
_AHMAD_PREMIUM_ROUND_TABLE_KEYS = frozenset({"grid_rate_w_by_round", "grid_rate_w_ceiling_by_round"})
# 单色表：整表深度合并
_AHMAD_PREMIUM_COLOR_TABLE_KEYS = frozenset({"grid_rate_w", "grid_rate_w_ceiling"})

# resolve_ahmad_premium_config：除数上界、单件底价（万）、蓝/紫/橙/红默认格单价（万/格）
DEFAULT_DIVISOR_FRAC_MAX = 1000
DEFAULT_BASE_ITEM_PER_PIECE_W = 0.1
DEFAULT_GRID_RATE_W_BLUE = 0
DEFAULT_GRID_RATE_W_PURPLE = 0.1
DEFAULT_GRID_RATE_W_GOLD = 1.0
DEFAULT_GRID_RATE_W_RED = 4.0

# 格单价上限回退（与 manual 中 DEFAULT_GRID_PRICES 一致；蓝默认可为 0）
# GRID_CEILING_FALLBACK_BLUE = 0
# GRID_CEILING_FALLBACK_PURPLE = 0.25
# GRID_CEILING_FALLBACK_GOLD = 1
# GRID_CEILING_FALLBACK_RED = 4.7
GRID_CEILING_FALLBACK_BLUE = 0
GRID_CEILING_FALLBACK_PURPLE = 0.22
GRID_CEILING_FALLBACK_GOLD = 1
GRID_CEILING_FALLBACK_RED = 4.6
# ahmad_premium_round_bucket：回合分桶上限（≥ 此回合合并为一档）
PREMIUM_ROUND_BUCKET_MAX = 5

# 第 5 档且已知绿白总数时的 base 系数（万口径）
R5_BASE_NON_GW_COEF = 0.2
R5_BASE_GW_COEF = 0.05

# total_all 分档与对应 base 相对 unit_w 的倍率
TOTAL_ALL_TIER_HIGH = 22
TOTAL_ALL_TIER_MID = 16
BASE_MULT_FULL = 1.0
BASE_MULT_MID = 1.0
BASE_MULT_LOW = 1.0

# 第 1 档 base 倍率（JSON：ahmad_premium.round1_base_factor；可按 by_map 覆盖）；第 3 档起且溢价为 0 时的总价折扣
DEFAULT_ROUND1_BASE_FACTOR = 1.1
ROUND3_PLUS_ZERO_PREMIUM_FACTOR = 0.9

# 候选里「最低 OCR 价」相对 base 的加减项（万）
CANDIDATE_MIN_PRICE_PREMIUM_OFFSET_W = 0.3
VALUE_ANCHOR_MIN_PRICE_OFFSET_W = 0.5

# 占位组合里单件最大格数假设
MAX_GRID_PER_PIECE = 18

# 扁平 solve 四色顺序；溢价累加含蓝（与紫同套 total/avg/grid 规则）
COLORS_BPGR = ("blue", "purple", "gold", "red")
COLORS_PREM = ("blue", "purple", "gold", "red")
# R5 base 公式中的 x 仍为紫/橙/红件数加总，不含蓝（蓝计入 rest 项）
COLORS_PREM_RGB = ("purple", "gold", "red")


def _ahmad_price_divisor_from_avg_w(avg_for_frac: float, frac_max: int) -> int:
    """由均价**原始数值**的小数部分推除数（与 data.avg_price_* 同单位，一般为点数）。
    勿传入已 /10000 的万口径，否则整数点价（如 25875）会被当成 2.5875 的小数而误判除数。"""
    frac = abs(avg_for_frac) - math.floor(abs(avg_for_frac) + 1e-12)
    if frac < 1e-9:
        return 1
    inv = 1.0 / frac
    d = int(round(inv))
    return max(1, min(int(frac_max), d))


def _ahmad_color_premium_w(
    color: str,
    data: dict,
    local_solved: Dict[str, dict],
    rates_w: Dict[str, float],
    unit_w: float,
    divisor_frac_max: int,
    *,
    grid_rates_w: Optional[Dict[str, float]] = None,
) -> Tuple[float, Tuple[str, str, int]]:
    """Per-color premium for ahmad_premium. Priority: total_price > avg_price > grid (min count 的最小格数 × 格单价)。"""
    total_raw = data.get(f"total_price_{color}")
    tw = raw_price_to_w(total_raw)
    if tw is not None and tw > 0:
        return float(tw), (color, "total", int(as_non_neg_float(total_raw) or 0))

    avg_raw = data.get(f"avg_price_{color}")
    if avg_raw is not None and avg_raw != "":
        try:
            avg_f = float(avg_raw)
        except (TypeError, ValueError):
            avg_f = float("nan")
        if not math.isfinite(avg_f) or avg_f < 0:
            pass
        elif avg_f == 0.0:
            return 0.0, (color, "none", 0)
        else:
            avg_w = raw_price_to_w(avg_raw)
            if avg_w is not None:
                divisor = _ahmad_price_divisor_from_avg_w(avg_f, divisor_frac_max)
                sol_counts = local_solved.get(color, {}).get("counts") or []
                pos_counts = [c for c in sol_counts if c > 0]
                count_pick = min(pos_counts) if pos_counts else None
                if sol_counts:
                    mults = [k for k in sol_counts if k > 0 and k % divisor == 0]
                    if mults:
                        k0 = min(mults)
                        k = max(k0, count_pick) if count_pick is not None else k0
                        return max(0.0, k * float(avg_w) - k * unit_w), (color, "avg_k", int(k))
                d0 = divisor
                d = max(d0, count_pick) if count_pick is not None else d0
                return max(0.0, d * float(avg_w) - d * unit_w), (color, "avg_div", int(d))

    sol = local_solved.get(color, {})
    counts = sol.get("counts") or []
    if not counts:
        return 0.0, (color, "none", 0)
    count_pick = min(counts)
    grids = sol.get("pair_map", {}).get(count_pick) or []
    if not grids:
        return 0.0, (color, "none", 0)
    lo = min(grids)
    rate_src = grid_rates_w if grid_rates_w is not None else rates_w
    rate = float(rate_src.get(color, 0.0))
    sig_mode = "grid_ceiling" if grid_rates_w is not None else "grid"
    return float(lo) * rate, (color, sig_mode, int(lo))


def _ahmad_color_needs_full_solve_counts(color: str, data: dict) -> bool:
    """该色在溢价里会走均价除数分支时，必须保留全部可行件数集合（不能只用字典序最小一对）。"""
    total_raw = data.get(f"total_price_{color}")
    tw = raw_price_to_w(total_raw)
    if tw is not None and tw > 0:
        return False
    avg_raw = data.get(f"avg_price_{color}")
    if avg_raw is None or avg_raw == "":
        return False
    try:
        avg_f = float(avg_raw)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(avg_f) or avg_f < 0 or avg_f == 0.0:
        return False
    return raw_price_to_w(avg_raw) is not None


def solved_ahmad_flat_solve(
    data: dict,
    high_total: int,
    constraints: Dict[str, ColorConstraint],
    max_count: int,
    avg_tolerance: float,
) -> Tuple[Dict[str, dict], List[str]]:
    """固定 high_total 下对四色各求一次可行解。

    无有效均价总价路径、或均价不会进入除数分支时，用 ``solve_color_lexicographic_min`` 只保留
    字典序最小 (count, grid)；否则 ``solve_color`` 全枚举。
    """
    t0 = time.perf_counter()
    out = empty_solved()
    warns: List[str] = []
    for color in COLORS_BPGR:
        label = COLOR_LABELS[color]
        cst = constraints[color]
        if _ahmad_color_needs_full_solve_counts(color, data):
            solution = solve_color(label, cst, max_count, high_total, avg_tolerance)
        else:
            solution = solve_color_lexicographic_min(label, cst, max_count, avg_tolerance)
        out[color] = {"counts": solution.counts, "pair_map": solution.pair_map, "warns": solution.warns}
        warns.extend(solution.warns)
    perf_log_elapsed("ahmad.solved_ahmad_flat_solve(high_total=%s)" % (high_total,), t0)
    return normalize_solved(out), warns


def _ahmad_premium_rgb_x_sum(
    constraints: Dict[str, ColorConstraint],
    local_solved: Dict[str, dict],
    *,
    max_count: int,
    high_total: int,
    avg_tolerance: float,
) -> int:
    """紫/橙/红件数加总 x：公共信息有精确 count 或 min_count 时用该 n；否则有可行正件数计 1，否则 0。"""
    s = 0
    for color in COLORS_PREM_RGB:
        c = constraints[color]
        if c.count is not None:
            s += int(c.count)
            continue
        if c.min_count is not None:
            s += int(c.min_count)
            continue
        counts = local_solved.get(color, {}).get("counts") or []
        if any(n > 0 for n in counts):
            s += 1
        elif color_has_feasible_positive_count(c, max_count, avg_tolerance):
            s += 1
    return s


def ahmad_premium_placeholder_combo(
    data: dict,
    total_all: int,
    high_total: int,
    solved: Dict[str, dict],
) -> dict:
    """供 build_summary/estimate_combo 用的一条占位组合，仅展示，不保证件数可拼满。"""
    b = min(solved["blue"]["counts"] or [0])
    p = min(solved["purple"]["counts"] or [0])
    g = min(solved["gold"]["counts"] or [0])
    r = max(0, int(high_total) - b - p - g)
    wg = green_white_total(data)
    if wg is None:
        wg = 0
    splits = enumerate_green_white_splits(data, wg) or [(0, 0)]
    green_c, white_c = splits[0]

    def cell_range(color: str, count: int) -> Tuple[int, int]:
        if count <= 0:
            return 0, 0
        gs = solved[color]["pair_map"].get(count)
        if gs:
            return min(gs), max(gs)
        return count, MAX_GRID_PER_PIECE * count

    b_range = cell_range("blue", b)
    p_range = cell_range("purple", p)
    g_range = cell_range("gold", g)
    r_range = cell_range("red", r)

    t_low = b_range[0] + p_range[0] + g_range[0] + r_range[0] + (green_c + white_c)
    t_high = b_range[1] + p_range[1] + g_range[1] + r_range[1] + (MAX_GRID_PER_PIECE * max(green_c + white_c, 0))
    return {
        "blue": b,
        "purple": p,
        "gold": g,
        "red": r,
        "green": green_c,
        "white": white_c,
        "wg_total": wg,
        "ranges": {
            "blue": b_range,
            "purple": p_range,
            "gold": g_range,
            "red": r_range,
        },
        "total_grid_range": (t_low, t_high),
    }


def _ahmad_flat_premium_bundle(
    data: dict,
    high_total: int,
    constraints: Dict[str, ColorConstraint],
    max_count: int,
    avg_tolerance: float,
    rates_w: Dict[str, float],
    unit_w: float,
    divisor_frac_max: int,
    *,
    local_solved: Optional[Dict[str, dict]] = None,
) -> Tuple[float, Tuple[Tuple[str, str, int], ...], List[str]]:
    """不做四色组合枚举：固定 high_total 下各颜色 solve_color，蓝紫金红溢价按 _ahmad_color_premium_w 累加。"""
    if local_solved is None:
        local_solved, warns = solved_ahmad_flat_solve(
            data, high_total, constraints, max_count, avg_tolerance
        )
    else:
        warns = []
    total_p = 0.0
    sig_parts: List[Tuple[str, str, int]] = []
    for color in COLORS_PREM:
        p, sig = _ahmad_color_premium_w(color, data, local_solved, rates_w, unit_w, divisor_frac_max)
        total_p += p
        sig_parts.append(sig)
    return total_p, tuple(sorted(sig_parts)), warns


def ahmad_premium_round_bucket(round_no: int | None) -> int:
    """1–4 用对应回合；5 及以后合并为第 5 档。"""
    r = int(round_no) if round_no is not None else 1
    if r < 1:
        r = 1
    return min(PREMIUM_ROUND_BUCKET_MAX, r)


def _deep_merge_ahmad_premium_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """将 overlay 合并进 base 的副本。by_map 不参与合并。"""
    out: Dict[str, Any] = dict(base)
    for key, val in overlay.items():
        if key == "by_map":
            continue
        if key in _AHMAD_PREMIUM_COLOR_TABLE_KEYS and isinstance(val, dict):
            merged = dict(out.get(key) or {})
            merged.update(val)
            out[key] = merged
        elif key in _AHMAD_PREMIUM_ROUND_TABLE_KEYS and isinstance(val, dict):
            merged_br: Dict[str, Any] = dict(out.get(key) or {})
            for rk, rv in val.items():
                sk = str(rk)
                if isinstance(rv, dict):
                    slot = dict(merged_br.get(sk) or {})
                    slot.update(rv)
                    merged_br[sk] = slot
                else:
                    merged_br[sk] = rv
            out[key] = merged_br
        else:
            out[key] = val
    return out


def materialize_ahmad_premium_section(price_config: dict, map_key: str | None) -> dict:
    """读取 ``ahmad_premium`` 根配置；若存在 ``by_map[map_key]`` 则与其深度合并（回合表按回合再按颜色合并）。"""
    root = dict(price_config.get(AHMAD_PREMIUM_CONFIG_KEY) or {})
    by_map = root.get("by_map")
    base = dict(root)
    base.pop("by_map", None)
    if not map_key or not isinstance(by_map, dict):
        return base
    mk = str(map_key).strip()
    if not mk:
        return base
    overlay = by_map.get(mk)
    if overlay is None:
        try:
            overlay = by_map.get(int(mk))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            overlay = None
    if not isinstance(overlay, dict):
        return base
    return _deep_merge_ahmad_premium_dict(base, overlay)


def resolve_ahmad_premium_config(
    price_config: dict, round_no: int | None = None, map_key: str | None = None
) -> Dict[str, object]:
    raw = materialize_ahmad_premium_section(price_config, map_key)
    div_max = int(raw.get("divisor_frac_max", DEFAULT_DIVISOR_FRAC_MAX))
    grid = dict(raw.get("grid_rate_w") or {})
    for key, default in (
        ("blue", DEFAULT_GRID_RATE_W_BLUE),
        ("purple", DEFAULT_GRID_RATE_W_PURPLE),
        ("gold", DEFAULT_GRID_RATE_W_GOLD),
        ("red", DEFAULT_GRID_RATE_W_RED),
    ):
        grid.setdefault(key, default)
    if round_no is not None:
        bucket = ahmad_premium_round_bucket(int(round_no))
        by_r = raw.get("grid_rate_w_by_round")
        if isinstance(by_r, dict) and by_r:
            overlay = by_r.get(str(bucket))
            if overlay is None and bucket in by_r:
                overlay = by_r.get(bucket)  # type: ignore[call-overload]
            if isinstance(overlay, dict):
                for color, val in overlay.items():
                    if val is not None and val != "":
                        try:
                            grid[str(color)] = float(val)
                        except (TypeError, ValueError):
                            pass
    base_item = raw.get("base_item_per_piece_w")
    gp = dict(price_config.get("grid_prices") or {})
    grid_ceiling: Dict[str, float] = {}
    for key, fb in (
        ("blue", GRID_CEILING_FALLBACK_BLUE),
        ("purple", GRID_CEILING_FALLBACK_PURPLE),
        ("gold", GRID_CEILING_FALLBACK_GOLD),
        ("red", GRID_CEILING_FALLBACK_RED),
    ):
        v = gp.get(key)
        try:
            vf = float(v) if v is not None and v != "" else float("nan")
        except (TypeError, ValueError):
            vf = float("nan")
        grid_ceiling[key] = vf if math.isfinite(vf) and vf >= 0 else float(fb)
    ceil_raw = dict(raw.get("grid_rate_w_ceiling") or {})
    for ck, val in ceil_raw.items():
        if val is not None and val != "":
            try:
                grid_ceiling[str(ck)] = float(val)
            except (TypeError, ValueError):
                pass
    if round_no is not None:
        bucket_c = ahmad_premium_round_bucket(int(round_no))
        by_c = raw.get("grid_rate_w_ceiling_by_round")
        if isinstance(by_c, dict) and by_c:
            oc = by_c.get(str(bucket_c))
            if oc is None and bucket_c in by_c:
                oc = by_c.get(bucket_c)  # type: ignore[call-overload]
            if isinstance(oc, dict):
                for ck, val in oc.items():
                    if val is not None and val != "":
                        try:
                            grid_ceiling[str(ck)] = float(val)
                        except (TypeError, ValueError):
                            pass
    r1_raw = raw.get("round1_base_factor")
    try:
        round1_base_factor = float(r1_raw) if r1_raw is not None and r1_raw != "" else DEFAULT_ROUND1_BASE_FACTOR
    except (TypeError, ValueError):
        round1_base_factor = DEFAULT_ROUND1_BASE_FACTOR
    if not math.isfinite(round1_base_factor):
        round1_base_factor = DEFAULT_ROUND1_BASE_FACTOR
    return {
        "divisor_frac_max": max(1, div_max),
        "grid_rate_w": grid,
        "grid_rate_w_ceiling": grid_ceiling,
        "base_item_per_piece_w": base_item,
        "round1_base_factor": round1_base_factor,
    }


def compute_ahmad_premium_w(
    data: dict,
    price_config: dict,
    *,
    min_price_points: Optional[int] = None,
    local_solved: Optional[Dict[str, dict]] = None,
) -> Tuple[Optional[float], str, Tuple[Tuple[str, str, int], ...], List[str], Optional[float]]:
    """Ahmad-only total estimate in **w** (万). 无组合枚举：单一 high_total + 各颜色 solve，蓝紫金红溢价按最小可行件数对应的最小格数等规则。

    若调用方已通过 ``solved_ahmad_flat_solve`` 或与当前 ``data``、``high_total`` 一致的 ``local_solved``（例如出价流程里的预解），传入可跳过重复 solve（显著降低 CPU）。

    估价取以下候选（凡有数据则参与）中的 **最大值**：
    - ``base + 蓝紫金红溢价``
    - ``base + 最少价值``（``min_price_points`` 为界面 OCR 点数时换算为万后与 base 相加）
    - ``n * avg_w + base - n * unit_w``（中央信息出现「随机选择 n 件藏品平均价值约 a」时，``a`` 按点数转万）

    第 5 档且已知绿白总数 ``wg_total``（或绿、白件数可推）时，``base`` 改为
    ``(total_all - gw - x) * R5_BASE_NON_GW_COEF + gw * R5_BASE_GW_COEF``（万），其中 ``x`` 为紫/橙/红件数加总：
    约束里若有 ``count`` 或 ``min_count`` 则用该 n，否则该色有正件数可行解计 1、否则 0。

    成功时第五项为与总价同口径的 **base** 分量（万）；失败时为 None。
    """
    t_all = time.perf_counter()
    validation_msgs = validate_input(data)
    if validation_msgs:
        return None, "输入校验未通过", tuple(), list(validation_msgs), None
    warns: List[str] = []
    role = normalize_role(data.get("my_role", "ahmad"))
    if role == "none":
        role = "ahmad"
    if role != "ahmad":
        return None, "ahmad_premium 仅支持艾哈迈德", tuple(), [f"当前角色为 {role}"], None

    max_count = as_non_neg_int(data.get("max_count")) or 60
    avg_tolerance = as_non_neg_float(data.get("avg_tolerance")) or 0.05
    constraints = {color: get_color_constraint(data, color) for color in COLORS_BPGR}
    total_all = as_non_neg_int(data.get("total_all"))
    if total_all is None:
        return None, "缺少 total_all", tuple(), ["缺少 total_all（总藏品数）"], None

    round_bucket = ahmad_premium_round_bucket(as_non_neg_int(data.get("round")) or 1)
    map_k = data.get("selected_map")
    map_key = str(map_k).strip() if map_k is not None and str(map_k).strip() else None
    ap_cfg = resolve_ahmad_premium_config(price_config, round_no=int(round_bucket), map_key=map_key)
    unit_w = float(ap_cfg.get("base_item_per_piece_w", DEFAULT_BASE_ITEM_PER_PIECE_W))
    rates_w = ap_cfg["grid_rate_w"]  # type: ignore[assignment]
    div_max = int(ap_cfg["divisor_frac_max"])  # type: ignore[arg-type]
    round1_base_factor = float(ap_cfg.get("round1_base_factor", DEFAULT_ROUND1_BASE_FACTOR))

    high_total = int(total_all)
    if local_solved is not None:
        local_solved = normalize_solved(local_solved)
    if local_solved is None:
        local_solved, solve_warns = solved_ahmad_flat_solve(
            data, high_total, constraints, max_count, avg_tolerance
        )
        warns.extend(solve_warns)
    else:
        perf_log("ahmad.compute_ahmad_premium_w flat_solve 跳过(复用 local_solved)")
    gw = green_white_total(data)
    use_r5_gw_base = int(round_bucket) >= PREMIUM_ROUND_BUCKET_MAX and gw is not None
    if use_r5_gw_base:
        rest = max(0, int(total_all) - int(gw))
        base = float(rest) * R5_BASE_NON_GW_COEF + float(gw) * R5_BASE_GW_COEF
    elif total_all >= TOTAL_ALL_TIER_HIGH:
        base = float(total_all) * unit_w * BASE_MULT_FULL
    elif total_all >= TOTAL_ALL_TIER_MID:
        base = float(total_all) * unit_w * BASE_MULT_MID
    else:
        base = float(total_all) * unit_w * BASE_MULT_LOW
    if round_bucket == 1:
        base = base * round1_base_factor
    t_bundle = time.perf_counter()
    prem, best_sig, bundle_warns = _ahmad_flat_premium_bundle(
        data, high_total, constraints, max_count, avg_tolerance, rates_w, unit_w, div_max, local_solved=local_solved
    )
    perf_log_elapsed("ahmad.compute_ahmad_premium_w _ahmad_flat_premium_bundle", t_bundle)
    warns.extend(bundle_warns)
    classic_lbl = f"base+prem={base:.4f}+{prem:.4f}"
    classic_w = base + prem
    if round_bucket >= 3 and prem == 0:
        classic_w = classic_w * ROUND3_PLUS_ZERO_PREMIUM_FACTOR
    candidates: List[Tuple[float, str]] = [(classic_w, classic_lbl)]

    mp = as_non_neg_int(min_price_points)
    if mp is not None and mp > 0:
        min_w = float(mp) / 10000.0
        candidates.append(
            (base + min_w - CANDIDATE_MIN_PRICE_PREMIUM_OFFSET_W, f"base+min_ocr={base:.4f}+{min_w:.4f}(pts={mp})")
        )

    pick_n = as_non_neg_int(data.get("random_pick_count"))
    pick_avg_raw = data.get("random_pick_avg_price")
    if pick_n is not None and pick_n > 0 and pick_avg_raw is not None:
        avg_w = raw_price_to_w(pick_avg_raw)
        if avg_w is not None and avg_w >= 0:
            random_w = float(pick_n) * float(avg_w) + base - float(pick_n) * unit_w
            random_w = max(0.0, random_w)
            candidates.append((random_w, f"random_avg(n={pick_n},a_pts={pick_avg_raw})"))

    best = max(c[0] for c in candidates)
    parts = "; ".join(f"{lbl}={val:.4f}w" for val, lbl in candidates)
    tied = [lbl for val, lbl in candidates if abs(val - best) < 1e-9]
    picked = tied[0] if tied else "?"
    reason = (
        f"ahmad_premium r{round_bucket} "
        f"grid_b/p/g/r={rates_w.get('blue', 0):.3f}/{rates_w.get('purple', 0):.3f}/"
        f"{rates_w.get('gold', 0):.3f}/{rates_w.get('red', 0):.3f} "
        f"high_total={high_total} [{parts}] -> max={best:.4f}w ({picked})"
    )
    perf_log_elapsed("ahmad.compute_ahmad_premium_w 总计", t_all)
    return best, reason, best_sig, warns, float(base)


def compute_value_anchor_ceiling_w(
    data: dict,
    price_config: dict,
    *,
    min_price_points: Optional[int] = None,
    local_solved: Optional[Dict[str, dict]] = None,
) -> Optional[float]:
    """价值锚上限（万）。与 ahmad_premium 同口径 base + 扁平解；蓝紫金红溢价路径与 _ahmad_color_premium_w 一致，
    仅落到 grid 分支时用 grid_rate_w_ceiling（默认同 price_config.grid_prices）作乘数，仍用 min(grids)。
    取 max(A,B,C)。非艾哈迈德或缺 total_all 时返回 None。
    传入与当前输入一致的 ``local_solved`` 可避免重复 ``solved_ahmad_flat_solve``。"""
    t_all = time.perf_counter()
    validation_msgs = validate_input(data)
    if validation_msgs:
        return None
    role = normalize_role(data.get("my_role", "ahmad"))
    if role == "none":
        role = "ahmad"
    if role != "ahmad":
        return None
    max_count = as_non_neg_int(data.get("max_count")) or 60
    avg_tolerance = as_non_neg_float(data.get("avg_tolerance")) or 0.05
    constraints = {color: get_color_constraint(data, color) for color in COLORS_BPGR}
    total_all = as_non_neg_int(data.get("total_all"))
    if total_all is None:
        return None

    round_bucket = ahmad_premium_round_bucket(as_non_neg_int(data.get("round")) or 1)
    map_k = data.get("selected_map")
    map_key = str(map_k).strip() if map_k is not None and str(map_k).strip() else None
    ap_cfg = resolve_ahmad_premium_config(price_config, round_no=int(round_bucket), map_key=map_key)
    unit_w = float(ap_cfg.get("base_item_per_piece_w", DEFAULT_BASE_ITEM_PER_PIECE_W))
    rates_w = ap_cfg["grid_rate_w"]  # type: ignore[assignment]
    rates_grid_ceiling = ap_cfg["grid_rate_w_ceiling"]  # type: ignore[assignment]
    div_max = int(ap_cfg["divisor_frac_max"])  # type: ignore[arg-type]
    high_total = int(total_all)
    if local_solved is not None:
        local_solved = normalize_solved(local_solved)
    if local_solved is None:
        local_solved, _ = solved_ahmad_flat_solve(data, high_total, constraints, max_count, avg_tolerance)
    else:
        perf_log("ahmad.compute_value_anchor_ceiling_w flat_solve 跳过(复用 local_solved)")
    gw = green_white_total(data)
    use_r5_gw_base = int(round_bucket) >= PREMIUM_ROUND_BUCKET_MAX and gw is not None
    if use_r5_gw_base:
        rest = max(0, int(total_all) - int(gw))
        base = float(rest) * R5_BASE_NON_GW_COEF + float(gw) * R5_BASE_GW_COEF
    else:
        base = float(total_all) * unit_w
    prem_hi = 0.0
    t_prem = time.perf_counter()
    for color in COLORS_PREM:
        pc, _ = _ahmad_color_premium_w(
            color,
            data,
            local_solved,
            rates_w,
            unit_w,
            div_max,
            grid_rates_w=rates_grid_ceiling,
        )
        prem_hi += float(pc)
    perf_log_elapsed("ahmad.compute_value_anchor_ceiling_w 四色溢价(ceiling)", t_prem)
    term_a = base + prem_hi
    mp = as_non_neg_int(min_price_points)
    min_w = float(mp) / 10000.0 if mp else 0.0
    term_b = base + min_w - VALUE_ANCHOR_MIN_PRICE_OFFSET_W
    terms: List[float] = [term_a, term_b]

    pick_n = as_non_neg_int(data.get("random_pick_count"))
    pick_avg_raw = data.get("random_pick_avg_price")
    if pick_n is not None and pick_n > 0 and pick_avg_raw is not None:
        avg_w = raw_price_to_w(pick_avg_raw)
        if avg_w is not None and avg_w >= 0:
            term_c = float(pick_n) * float(avg_w) + base - float(pick_n) * unit_w
            terms.append(max(0.0, term_c))

    perf_log_elapsed("ahmad.compute_value_anchor_ceiling_w 总计", t_all)
    return max(terms)
