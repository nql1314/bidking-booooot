# -*- coding: utf-8 -*-
"""Ahmad 英雄专用估价策略。

本模块提供 Ahmad 角色的特殊定价算法，主要应用于快递站系列地图
（档键 ``210``，含 2101~2107 等子图）。

核心算法包含多候选估价模型（候选 A/B/C/D/E），最终取最大值作为 Ahmad 点数。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from ...parsing import item_db

_AHMAD_HERO_CID = 204

_EXPRESS_STATION_MAP_BUNDLE_KEY = "210"
_CONTAINER_MAP_BUNDLE_KEY = "230"


def map_bundle_is_express_station_series(map_id: int) -> bool:
    """当前 ``MapId`` 是否属快递站系列（与 :func:`item_db.map_bundle_key_for_automation` 档键 ``210``）."""
    mid = int(map_id or 0)
    if mid <= 0:
        return False
    return item_db.map_bundle_key_for_automation(mid) == _EXPRESS_STATION_MAP_BUNDLE_KEY


def map_bundle_is_container_series(map_id: int) -> bool:
    """当前 ``MapId`` 是否属集装箱地图系列（与 :func:`item_db.map_bundle_key_for_automation` 档键 ``230``）."""
    mid = int(map_id or 0)
    if mid <= 0:
        return False
    return item_db.map_bundle_key_for_automation(mid) == _CONTAINER_MAP_BUNDLE_KEY


def _local_board_snapshot_branch() -> Dict[str, Any]:
    """``config.json`` 覆盖后的 ``board_snapshot`` 段（含 ``self_user_uid``）."""
    try:
        from ...config.runtime import load_runtime

        raw = load_runtime().raw
        bs = raw.get("board_snapshot")
        return dict(bs) if isinstance(bs, dict) else {}
    except Exception:
        return {}


def resolve_ahmad_abde_scale(
    board_snapshot: Dict[str, Any],
    *,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> float:
    """与己方身份字段一致：快照根键 ``ahmad_abde_scale`` 优先，否则 ``board_snapshot_config`` / 运行时 ``board_snapshot`` 段。

    参数:
        board_snapshot: 画板快照数据
        board_snapshot_config: 可选的本地配置覆盖

    返回:
        Ahmad ABDE 缩放系数，缺省或非有限/负数时按 ``1.0``
    """
    branch = (
        board_snapshot_config
        if board_snapshot_config is not None
        else _local_board_snapshot_branch()
    )
    for d in (board_snapshot, branch):
        if not isinstance(d, dict) or "ahmad_abde_scale" not in d:
            continue
        v = d.get("ahmad_abde_scale")
        try:
            k = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(k) and k >= 0:
            return k
    return 1.0


def ahmad_pricing_detail_from_raw_pricing(
    raw: Any,
    *,
    items_total: Optional[float] = None,
    vacant_adj: Optional[int] = None,
    board_items_total: Optional[float] = None,
    ahmad_abde_scale: float = 1.0,
) -> Dict[str, Any]:
    """Ahmad 估价算法（点数口径）及候选分解，由 ``raw_pricing`` 实现，多候选取最大值。

    返回 dict：``ahmad_points``、``candidates``（每项含 ``id``/``label``/``points`` 及算式用中间量）、``winner``。

    ``ahmad_abde_scale``：对候选 A/B/D 的 **base** 部分与候选 E 中 **q123 格均价**（空置项乘子）统一乘该系数；
    紫/金/红边际溢价等仍按原 CSV 口径。缺省或非有限/负数时按 ``1.0``。

    ``items_total`` / ``vacant_adj`` / ``board_items_total``：可选；候选 E 仅在
    ``items_total``、``vacant_adj`` 与 ``board_items_total`` 均给出且 ``board_items_total != 0`` 时加入
    ``items_total + vacant_adj × q123 格均价``（``q123`` 取自 CSV 格均价键 ``"q1+q2+q3"``）。

    **候选 A — CSV 边际定价**（当 CSV 含 ``"all"`` 质量组时）：

    .. code-block:: text

        base   = total_count × q123456_件均价
        溢价   = Σ q*_格数 × (q*_格均价 − q123456_格均价)   （紫/金/红，格均价高于全档时）
        格数优先级：q*_grid_count（精确值）> q*_grid_min（推导下界）

    **候选 B — Ahmad 原算法**（base + 各色溢价，与 ``ahmad_premium.compute_ahmad_premium_w`` 一致）：

    .. code-block:: text

        base   = total_count × 1000（0.1万/件）
        各色溢价优先级：total_price > avg_price×count_min > grid_min×格单价
        格单价默认：紫 1000 / 金 10000 / 红 40000（点/格），有 CSV 数据时用 CSV 值

    **候选 D — q12/q3456 分组边际定价**（``q12_count`` 已知时，如第 5 回合后）：

    .. code-block:: text

        base   = q12_count × q12_件均价 + (total − q12_count) × q3456_件均价
        溢价   = Σ q*_格数 × (q*格均价 − q3456_格均价)   （紫/金/红）

    **候选 C — random_avg**：``random_avg_price_min``（n×均价总价下界）直接参与竞争。

    **候选 E — total + 空置调整 × q123 格均价**（仅当调用方传入 ``items_total`` 与 ``vacant_adj``，
    且 ``board_items_total``（画板物品标价和 ``pricing.total`` 同源）**非 0** 时参与 Ahmad max）：

    .. code-block:: text

        pts = items_total + vacant_adj × q123_格均价

    ``board_items_total`` 省略时不启用该候选（与旧行为兼容）；为 0 时不加入，避免无物品局仍靠空置项抬分。
    缺失或非数字字段按 0，不影响其他项。
    """
    empty: Dict[str, Any] = {
        "ahmad_points": 0,
        "candidates": [],
        "winner": "",
    }
    if not isinstance(raw, dict):
        return empty
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return empty

    try:
        k_abde = float(ahmad_abde_scale)
    except (TypeError, ValueError):
        k_abde = 1.0
    if not math.isfinite(k_abde) or k_abde < 0:
        k_abde = 1.0

    def _ni(key: str) -> Optional[int]:
        v = st.get(key)
        if v is None:
            return None
        try:
            i = int(v)
            return i if i >= 0 else None
        except (TypeError, ValueError):
            return None

    def _nf(key: str) -> Optional[float]:
        v = st.get(key)
        if v is None:
            return None
        try:
            f = float(v)
            return f if math.isfinite(f) and f >= 0 else None
        except (TypeError, ValueError):
            return None

    def _csv_f(d: Any, key: str) -> Optional[float]:
        if not isinstance(d, dict):
            return None
        v = d.get(key)
        if v is None:
            return None
        try:
            f = float(v)
            return f if math.isfinite(f) and f > 0 else None
        except (TypeError, ValueError):
            return None

    _UNIT_PTS = 1000
    _GRID_RATE_DEFAULT: Dict[str, int] = {"q4": 1000, "q5": 10000, "q6": 40000}

    csv_per_item = raw.get("csv_quality_groups_avg_per_item")
    csv_per_cell = raw.get("csv_quality_groups_avg_per_cell")

    tc = _ni("total_count") or 0
    candidates_rows: List[Dict[str, Any]] = []

    def _marginal_premium(ref_per_cell: float) -> float:
        """Σ q*格数 × (q*格均价 − ref_per_cell)，仅取正边际。格数优先精确值，次之下界。"""
        prem = 0.0
        for q in ("q4", "q5", "q6"):
            per_cell_q = _csv_f(csv_per_cell, q)
            if per_cell_q is None:
                continue
            delta = per_cell_q - ref_per_cell
            if delta <= 0:
                continue
            grid = _ni(f"{q}_grid_count") or _ni(f"{q}_grid_min")
            if not grid:
                continue
            prem += int(grid) * delta
        return prem

    # ── 候选 A：CSV 边际定价（q123件均价铺底）─────────────────────────────
    q123_per_item = _csv_f(csv_per_item, "q1+q2+q3")
    q123_per_cell = _csv_f(csv_per_cell, "q1+q2+q3")
    if tc > 0 and q123_per_item is not None:
        csv_base = tc * q123_per_item * k_abde
        csv_prem = _marginal_premium(q123_per_cell) if q123_per_cell is not None else 0.0
        pts_a = int(round(csv_base + csv_prem))
        candidates_rows.append(
            {
                "id": "csv_q123_marginal",
                "label": "CSV q123件均价 + 紫/金/红边际溢价",
                "points": pts_a,
                "base": float(csv_base),
                "marginal_premium": float(csv_prem),
                "ref_per_cell_q123": float(q123_per_cell) if q123_per_cell is not None else None,
                "ahmad_abde_scale": float(k_abde),
            }
        )

    # ── 候选 D：q12/q3 分组边际定价 ───────────────────────────────────
    q12_count = _ni("q12_count")
    per_item_q12 = _csv_f(csv_per_item, "q1+q2")
    per_item_q3 = _csv_f(csv_per_item, "q3")
    per_cell_q3 = _csv_f(csv_per_cell, "q3")
    if (
        tc > 0
        and q12_count is not None
        and per_item_q12 is not None
        and per_item_q3 is not None
    ):
        q3_count = max(0, tc - q12_count)
        base_q12 = float(q12_count * per_item_q12 * k_abde)
        base_q3 = float(q3_count * per_item_q3 * k_abde)
        split_base = base_q12 + base_q3
        split_prem = _marginal_premium(per_cell_q3) if per_cell_q3 is not None else 0.0
        pts_d = int(round(split_base + split_prem))
        candidates_rows.append(
            {
                "id": "split_q12_q3",
                "label": "q12 / q3 分组件均价 + 紫/金/红边际溢价",
                "points": pts_d,
                "q12_count": int(q12_count),
                "q3_count": int(q3_count),
                "base_q12": base_q12,
                "base_q3": base_q3,
                "marginal_premium": float(split_prem),
                "ref_per_cell_q3": float(per_cell_q3) if per_cell_q3 is not None else None,
                "ahmad_abde_scale": float(k_abde),
            }
        )

    # ── 候选 B：Ahmad 原算法（base + 各色溢价）────────────────────────────
    grid_rate: Dict[str, int] = {}
    for _q, _fb in _GRID_RATE_DEFAULT.items():
        _cv = _csv_f(csv_per_cell, _q)
        grid_rate[_q] = int(round(_cv)) if _cv is not None else _fb

    prem_pts = 0
    tier_detail: List[Dict[str, Any]] = []
    for q in ("q4", "q5", "q6"):
        price_total = _ni(f"{q}_price_total")
        if price_total is not None and price_total > 0:
            prem_pts += price_total
            tier_detail.append({"tier": q, "source": "price_total", "added": int(price_total)})
            continue
        price_avg = _nf(f"{q}_price_avg")
        count_min = _ni(f"{q}_count_min")
        if price_avg is not None and price_avg > 0 and count_min is not None and count_min > 0:
            add_b = max(0, int(round(int(count_min) * price_avg - int(count_min) * _UNIT_PTS)))
            prem_pts += add_b
            tier_detail.append(
                {
                    "tier": q,
                    "source": "avg_over_base",
                    "count_min": int(count_min),
                    "price_avg": float(price_avg),
                    "added": int(add_b),
                }
            )
            continue
        grid_min = _ni(f"{q}_grid_min")
        if grid_min is not None and grid_min > 0:
            add_g = int(grid_min) * grid_rate[q]
            prem_pts += add_g
            tier_detail.append(
                {
                    "tier": q,
                    "source": "grid_min_times_cell_rate",
                    "grid_min": int(grid_min),
                    "cell_rate": int(grid_rate[q]),
                    "added": int(add_g),
                }
            )

    base_b = float(tc * _UNIT_PTS) * k_abde
    pts_b = base_b + prem_pts
    candidates_rows.append(
        {
            "id": "classic_base_premium",
            "label": "Ahmad 经典：total_count×1000 + 紫/金/红溢价",
            "points": int(round(pts_b)),
            "base_total_count_pts": int(round(base_b)),
            "premium_total": int(prem_pts),
            "grid_rate_used": dict(grid_rate),
            "tier_breakdown": tier_detail,
            "ahmad_abde_scale": float(k_abde),
        }
    )

    # ── 候选 C：random_avg 总价下界 ───────────────────────────────────────
    rnd_min = _ni("random_avg_price_min")
    if rnd_min is not None and rnd_min > 0:
        candidates_rows.append(
            {
                "id": "random_avg_price_min",
                "label": "random_avg_price_min 事件下界",
                "points": int(rnd_min),
            }
        )

    # ── 候选 E：vacant_pts_base + vacant_adj × q123 格均价（须 board_items_total≠0，与 pricing.total 对齐）──
    _gate_tot = board_items_total
    if (
        items_total is not None
        and vacant_adj is not None
        and _gate_tot is not None
        and abs(float(_gate_tot)) > 1e-12
    ):
        u_early_q123 = _csv_f(csv_per_cell, "q1+q2+q3")
        u_early_raw = float(u_early_q123) if u_early_q123 is not None else 0.0
        u_early_f = u_early_raw * k_abde
        pts_e = float(items_total) + float(vacant_adj) * u_early_f
        candidates_rows.append(
            {
                "id": "total_plus_vacant_adj_times_q123_cell_avg",
                "label": "物品 total + 有效空置调整 × q123 格均价",
                "points": int(round(pts_e)),
                "items_total": float(items_total),
                "vacant_adj": int(vacant_adj),
                "u_early_q123": u_early_f,
                "u_early_q123_raw": u_early_raw,
                "ahmad_abde_scale": float(k_abde),
            }
        )

    if not candidates_rows:
        return empty

    best = max(int(c["points"]) for c in candidates_rows)
    winner = ""
    for c in candidates_rows:
        if int(c["points"]) == best:
            winner = str(c.get("id") or "")
            break
    return {
        "ahmad_points": best,
        "candidates": candidates_rows,
        "winner": winner,
    }


def ahmad_points_from_raw_pricing(raw: Any) -> int:
    """兼容入口：等价于 ``ahmad_pricing_detail_from_raw_pricing(raw)["ahmad_points"]``.

    参数:
        raw: raw_pricing 数据字典

    返回:
        Ahmad 估价点数
    """
    return int(ahmad_pricing_detail_from_raw_pricing(raw).get("ahmad_points") or 0)


def is_ahmad_pricing_active(
    board_snapshot: Dict[str, Any],
    map_id: int,
    *,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """判断 Ahmad 主价是否激活。

    Ahmad 主价激活条件：
    1. 当前英雄是 Ahmad (hero_cid == 204)
    2. 当前地图是快递站系列（档键 210）

    参数:
        board_snapshot: 画板快照数据
        map_id: 地图 ID
        board_snapshot_config: 可选的本地配置覆盖

    返回:
        True 如果 Ahmad 主价激活，否则 False
    """
    if not map_bundle_is_express_station_series(map_id):
        return False

    from . import common as _common

    self_hc = _common.self_player_hero_cid(
        board_snapshot, board_snapshot_config=board_snapshot_config
    )
    return self_hc == _AHMAD_HERO_CID


def enrich_ahmad_pricing(ctx, pricing: Dict[str, Any]) -> Dict[str, Any]:
    """写入 Ahmad 候选分解；激活时用 ``ahmad_points`` 覆盖主价。"""
    import time

    from ...logsys.perf_log import perf_log_elapsed
    from . import generic as _generic

    t0_ahmad = time.perf_counter()
    ahmad_abde_scale = resolve_ahmad_abde_scale(
        ctx.snap_full, board_snapshot_config=ctx.board_snapshot_config
    )
    ahmad_detail = ahmad_pricing_detail_from_raw_pricing(
        ctx.raw,
        items_total=float(ctx.vacant_pts_base),
        vacant_adj=int(ctx.vacant_adj),
        board_items_total=float(ctx.total_f),
        ahmad_abde_scale=float(ahmad_abde_scale),
    )
    ahmad_points = int(ahmad_detail.get("ahmad_points") or 0)
    perf_log_elapsed("build_snapshot_pricing_dict: ahmad_pricing", t0_ahmad)

    generic_pts = int(round(ctx.pts))
    generic_floor = int(round(ctx.pts_floor))
    generic_ceil = int(round(ctx.pts_ceiling))
    ahmad_pricing_active = is_ahmad_pricing_active(
        ctx.snap_full,
        ctx.map_id,
        board_snapshot_config=ctx.board_snapshot_config,
    )

    if ahmad_pricing_active:
        pricing["points"] = pricing["points_floor"] = pricing["points_ceiling"] = ahmad_points
        pricing["generic_points"] = generic_pts
        pricing["generic_points_floor"] = generic_floor
        pricing["generic_points_ceiling"] = generic_ceil
    elif "points" not in pricing:
        _generic.apply_generic_points(pricing, ctx)

    pricing["ahmad_points"] = ahmad_points
    pricing["ahmad_points_detail"] = ahmad_detail
    pricing["ahmad_abde_scale"] = float(ahmad_abde_scale)
    pricing["ahmad_pricing_active"] = bool(ahmad_pricing_active)
    return pricing
