# -*- coding: utf-8 -*-
"""
画板快照定价：由 ``game_state.items`` 与 ``grid_overlay`` 合并后的有效物品表汇总总价、
权重占位与空置格，再结合扫描推断与地图 CSV 格均价给出 ``points`` / ``est_*``。

``items`` 合并优先使用快照 ``grid_overlay["merged_items_dict"]``（见 :func:`grid_overlay.merged_items_dict_from_snapshot`），否则由 :func:`grid_overlay.merged_items_dict` 计算（含 ``infer_shapes`` 几何补全；推断外形的计价仍按未知轮廓加权）。

不再维护独立的「艾莎 bid」分支；策略层直接消费 ``pricing.points`` / ``points_floor`` /
``points_ceiling``。

当本地配置（``configs/runtime.json`` 与 ``configs/config.json`` 深合并）中
``board_snapshot.self_user_uid`` 对应玩家 ``hero_cid`` 为 204（Ahmad）时，上述三字段与
``pricing.ahmad_points`` 一致（由 ``raw_pricing.event_stats`` 多候选取 max）；通用画板空置主价仍写入
``pricing.generic_points*`` 供 UI 对照。``pricing.ahmad_points_detail`` 含各候选分解。

当 ``raw_pricing.event_stats`` 提供 ``q4_grid_min`` / ``q5_grid_min`` / ``q6_grid_min`` 时，
对 ``max(0, 最少格 - 已确认该档占位格)`` 按 CSV 单档 ``q4``/``q5``/``q6`` 格均价计入总价，
并对空置单价项使用扣减后的有效空置格数（``pricing.vacant`` 仍为几何/有效空置原值）。

已知轮廓且品质未知、CSV 为多候选（权重价）的物品（含仅日志未确认的锚格）：几何占位格在边际上视同空置，参与 ``空置格 × 空置单价``；
但 ``total`` / ``compute_items_total`` 已含该件权重价，故在 ``points`` / ``est_*`` 基底中扣除对应权重价，避免重复计价。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.item_db import _weighted_est_price, map_category_ratios, query_item
from . import scan_inference as _scan_inference
from . import unknown_value as _unknown_value
from . import grid_overlay as _grid_overlay
from ._shape_wh import shape_wh_from_snapshot

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None

# 仅 ``not q14_grid_known`` 早期回合：当 ``random_avg_price_min`` 超过本算 ``points`` 的 50% 时，
# 用 ``(points + random_avg_price_min) / 2`` 与事件下界取中，缓和随机均价事件对总估价的拉扯。
_RANDOM_AVG_MIN_DOMINANCE_RATIO = 0.5


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    path = _unknown_value._item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache


def map_id_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    gs = board_snapshot.get("game_state")
    mid = None
    if isinstance(gs, dict):
        mid = gs.get("map_id")
    if mid is None:
        mid = board_snapshot.get("map_id")
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


def current_round_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    r = board_snapshot.get("current_round")
    if r is None:
        r = (board_snapshot.get("game_state") or {}).get("current_round")
    try:
        v = int(r)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


def _int_set_from_field(raw: Any) -> Set[int]:
    out: Set[int] = set()
    if not isinstance(raw, list):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _event_stat_grid_min_optional(st: Any, key: str) -> Optional[int]:
    """``event_stats`` 中 ``q*_grid_min``：有值且非负时返回 int，否则不参与最少格扣减。"""
    if not isinstance(st, dict):
        return None
    v = st.get(key)
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _confirmed_tier_footprint_q456(
    board_snapshot: Dict[str, Any],
) -> Tuple[int, int, int]:
    """
    合并物品表上 Q4/Q5/Q6、含有效 ``box_id`` 且快照 ``shape`` 已知的几何占位格数之和。
    """
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    s4 = s5 = s6 = 0.0
    for _uid, it in items.items():
        if not isinstance(it, dict):
            continue
        bid_raw = it.get("box_id")
        if bid_raw is None:
            continue
        try:
            int(bid_raw)
        except (TypeError, ValueError):
            continue
        q_raw = it.get("quality")
        try:
            q = int(q_raw) if q_raw is not None else None
        except (TypeError, ValueError):
            continue
        if q not in (4, 5, 6):
            continue
        fp = _geo_footprint_cells_from_shape_field(it.get("shape"))
        if fp is None:
            continue
        if q == 4:
            s4 += fp
        elif q == 5:
            s5 += fp
        else:
            s6 += fp
    return int(round(s4)), int(round(s5)), int(round(s6))


def _tier_min_extra_value_and_cells(
    event_stats: Any,
    *,
    confirmed_q4: int,
    confirmed_q5: int,
    confirmed_q6: int,
    csv_cells: Dict[str, float],
) -> Tuple[float, int]:
    """
    当 ``event_stats`` 给出紫/金/红 ``q*_grid_min`` 时：

    - 每档额外价值 ``max(0, grid_min - 已计入该档占位格) * CSV 单档 q4/q5/q6 格均价``；
    - ``grid_min`` 缺失（None）则该档不参与；``grid_min <= 已确认`` 则该档为 0。

    返回 ``(extra_value_sum, cells_to_subtract_from_vacant_estimate)``。
    """
    if not isinstance(event_stats, dict):
        return 0.0, 0
    extra_val = 0.0
    extra_cells = 0
    for min_k, csv_k, confirmed in (
        ("q4_grid_min", "q4", confirmed_q4),
        ("q5_grid_min", "q5", confirmed_q5),
        ("q6_grid_min", "q6", confirmed_q6),
    ):
        m = _event_stat_grid_min_optional(event_stats, min_k)
        if m is None:
            continue
        need = int(m) - int(confirmed)
        if need <= 0:
            continue
        u = float(csv_cells.get(csv_k, 0.0))
        extra_val += float(need) * u
        extra_cells += need
    return extra_val, extra_cells


def _event_stats_q14_grid_counts_all_known(raw: Any) -> bool:
    """
    ``raw_pricing.event_stats`` 中 q1–q4 各档占用总格数均已得到（非 None）时，
    可认为已由公共信息划定紫档及此前档位，空置金红估价区间与后期回合一致。
    """
    if not isinstance(raw, dict):
        return False
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return False
    for k in ("q1_grid_count", "q2_grid_count", "q3_grid_count", "q4_grid_count"):
        if st.get(k) is None:
            return False
    return True


def _parse_shape_int(shape: Any) -> Optional[int]:
    if shape is None:
        return None
    if isinstance(shape, int):
        return shape
    try:
        return int(shape)
    except (TypeError, ValueError):
        s = str(shape)
        if len(s) == 2 and s.isdigit():
            return int(s)
        return None


def _pricing_shape_int_for_csv(it: Dict[str, Any]) -> Optional[int]:
    """推断外形仅用于几何占位；CSV 计价匹配仍按未知外形做多候选加权。"""
    if it.get("_overlay_shape_origin") == "infer":
        return None
    return _parse_shape_int(it.get("shape"))


def _pricing_work_board_snapshot(board_snapshot: Dict[str, Any], items: Dict[str, Any]) -> Dict[str, Any]:
    gs = board_snapshot.get("game_state")
    if not isinstance(gs, dict):
        gs = {}
    gs2 = dict(gs)
    gs2["items"] = items
    out = dict(board_snapshot)
    out["game_state"] = gs2
    return out


def _local_board_snapshot_branch() -> Dict[str, Any]:
    """``config.json`` 覆盖后的 ``board_snapshot`` 段（含 ``self_user_uid``）。"""
    try:
        from ..config.runtime import load_runtime

        raw = load_runtime().raw
        bs = raw.get("board_snapshot")
        return dict(bs) if isinstance(bs, dict) else {}
    except Exception:
        return {}


def _self_player_hero_cid(
    board_snapshot: Dict[str, Any],
    *,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """用本地配置 ``board_snapshot.self_user_uid`` 在 ``game_state.players`` 中解析己方 ``hero_cid``。"""
    gs = board_snapshot.get("game_state")
    if not isinstance(gs, dict):
        return None
    players = gs.get("players")
    if not isinstance(players, dict) or not players:
        return None
    branch = (
        board_snapshot_config
        if board_snapshot_config is not None
        else _local_board_snapshot_branch()
    )
    self_uid = str(branch.get("self_user_uid") or "").strip()
    pdata: Any = None
    if self_uid and self_uid in players:
        pdata = players.get(self_uid)
    elif len(players) == 1:
        pdata = next(iter(players.values()))
    if not isinstance(pdata, dict):
        return None
    try:
        hc = int(pdata.get("hero_cid") or 0)
    except (TypeError, ValueError):
        return None
    return hc if hc > 0 else None


def _ahmad_pricing_detail_from_raw_pricing(
    raw: Any,
    *,
    items_total: Optional[float] = None,
    vacant_adj: Optional[int] = None,
) -> Dict[str, Any]:
    """Ahmad 估价算法（点数口径）及候选分解，由 ``raw_pricing`` 实现，多候选取最大值。

    返回 dict：``ahmad_points``、``candidates``（每项含 ``id``/``label``/``points`` 及算式用中间量）、``winner``。

    ``items_total`` / ``vacant_adj``：可选；二者皆给出时增加候选
    ``total + vacant_adj × q1234 格均价``（``q1234`` 取自 CSV 格均价键 ``\"q1234\"``）。

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

    **候选 E — total + 空置调整 × q1234 格均价**（仅当调用方传入 ``items_total`` 与 ``vacant_adj`` 时）：

    .. code-block:: text

        pts = total + vacant_adj × q1234_格均价

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
        csv_base = tc * q123_per_item
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
        split_base = q12_count * per_item_q12 + q3_count * per_item_q3
        split_prem = _marginal_premium(per_cell_q3) if per_cell_q3 is not None else 0.0
        pts_d = int(round(split_base + split_prem))
        candidates_rows.append(
            {
                "id": "split_q12_q3",
                "label": "q12 / q3 分组件均价 + 紫/金/红边际溢价",
                "points": pts_d,
                "q12_count": int(q12_count),
                "q3_count": int(q3_count),
                "base_q12": float(q12_count * per_item_q12),
                "base_q3": float(q3_count * per_item_q3),
                "marginal_premium": float(split_prem),
                "ref_per_cell_q3": float(per_cell_q3) if per_cell_q3 is not None else None,
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

    pts_b = tc * _UNIT_PTS + prem_pts
    candidates_rows.append(
        {
            "id": "classic_base_premium",
            "label": "Ahmad 经典：total_count×1000 + 紫/金/红溢价",
            "points": int(round(pts_b)),
            "base_total_count_pts": int(tc * _UNIT_PTS),
            "premium_total": int(prem_pts),
            "grid_rate_used": dict(grid_rate),
            "tier_breakdown": tier_detail,
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

    # ── 候选 E：total + vacant_adj × q1234 格均价（需快照侧传入 items_total / vacant_adj）──
    if items_total is not None and vacant_adj is not None:
        u_early_q1234 = _csv_f(csv_per_cell, "q1+q2+q3+q4")
        u_early_f = float(u_early_q1234) if u_early_q1234 is not None else 0.0
        pts_e = float(items_total) + float(vacant_adj) * u_early_f
        candidates_rows.append(
            {
                "id": "total_plus_vacant_adj_times_q1234_cell_avg",
                "label": "物品 total + 有效空置调整 × q1234 格均价",
                "points": int(round(pts_e)),
                "items_total": float(items_total),
                "vacant_adj": int(vacant_adj),
                "u_early_q1234": u_early_f,
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


def _ahmad_points_from_raw_pricing(raw: Any) -> int:
    """兼容入口：等价于 ``_ahmad_pricing_detail_from_raw_pricing(raw)["ahmad_points"]``。"""
    return int(_ahmad_pricing_detail_from_raw_pricing(raw).get("ahmad_points") or 0)


def _item_value(
    it: Dict[str, Any],
    *,
    csv_index: Dict[int, Any],
    csv_items: List[Any],
    map_id_normalized: Optional[int],
    map_category_weights: Dict[int, float],
) -> float:
    bid_raw = it.get("box_id")
    if bid_raw is None:
        return 0.0
    try:
        int(bid_raw)
    except (TypeError, ValueError):
        return 0.0

    cid_raw = it.get("item_cid")
    try:
        item_cid_i = int(cid_raw) if cid_raw is not None else None
    except (TypeError, ValueError):
        item_cid_i = None
    price_raw = it.get("price")
    if item_cid_i is not None and price_raw is not None:
        try:
            return float(price_raw)
        except (TypeError, ValueError):
            pass

    q_raw = it.get("quality")
    try:
        q = int(q_raw) if q_raw is not None else None
    except (TypeError, ValueError):
        q = None

    sh = _pricing_shape_int_for_csv(it)
    cats = _int_set_from_field(it.get("categories"))
    excl_q = _int_set_from_field(it.get("excluded_qualities"))
    excl_c = _int_set_from_field(it.get("excluded_categories"))

    best, count, unique, est, _label = query_item(
        sh,
        q,
        cats,
        item_cid_i,
        csv_index,
        csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
        max_shape_wh=None,
        map_category_weights=map_category_weights if map_category_weights else None,
        map_id=map_id_normalized,
    )
    if best is None or count == 0:
        return 0.0

    if unique:
        return float(best.base_value)
    w_est = est
    if w_est is None and csv_items:
        cand = list(csv_items)
        if sh is not None:
            cand = [i for i in cand if i.shape == sh]
        if q is not None:
            cand = [i for i in cand if i.quality == q]
        if excl_q:
            cand = [i for i in cand if i.quality not in excl_q]
        if cats:
            wc = [i for i in cand if all(c in i.category_tags for c in cats)]
            if wc:
                cand = wc
        if excl_c:
            cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
        w_est = _weighted_est_price(cand, map_category_weights or None, map_id_normalized)
    return float(w_est) if w_est is not None else float(best.base_value)


def _sum_known_contour_weighted_price_and_geo_cells(
    board_snapshot: Dict[str, Any],
    *,
    csv_cells_raw: Dict[str, float],
) -> Tuple[float, int]:
    """
    已知轮廓（``shape`` 非空）、品质仍未知（``quality`` 为空），且 ``query_item`` 为多候选（权重价）的物品：

    返回 ``(sum(权重价), sum(几何格数))``，用于空置边际扩容并从 ``points`` 基底扣除权重价。
    不要求 ``box_id_confirmed``，与 :func:`_item_value` 对未确认物品的计价一致。
    已确认品质的多候选不再计入，避免误扣 ``vacant_pts_base``、错抬空置格倍数。
    """
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0, 0
    weights = map_category_ratios(mid) or {}
    sum_val = 0.0
    sum_geo = 0
    for _uid, it in items.items():
        if not isinstance(it, dict):
            continue
        bid_raw = it.get("box_id")
        if bid_raw is None:
            continue
        try:
            int(bid_raw)
        except (TypeError, ValueError):
            continue

        sh_geo = _parse_shape_int(it.get("shape"))
        if sh_geo is None:
            continue

        cid_raw = it.get("item_cid")
        try:
            item_cid_i = int(cid_raw) if cid_raw is not None else None
        except (TypeError, ValueError):
            item_cid_i = None
        price_raw = it.get("price")
        if item_cid_i is not None and price_raw is not None:
            continue

        q_raw = it.get("quality")
        try:
            q = int(q_raw) if q_raw is not None else None
        except (TypeError, ValueError):
            q = None
        if q is not None:
            continue

        cats = _int_set_from_field(it.get("categories"))
        excl_q = _int_set_from_field(it.get("excluded_qualities"))
        excl_c = _int_set_from_field(it.get("excluded_categories"))

        sh_csv = _pricing_shape_int_for_csv(it)

        best, count, unique, est, _label = query_item(
            sh_csv,
            q,
            cats,
            item_cid_i,
            csv_index,
            csv_items,
            excluded_categories=excl_c if excl_c else None,
            excluded_qualities=excl_q if excl_q else None,
            max_shape_wh=None,
            map_category_weights=weights if weights else None,
            map_id=mid_n,
        )
        if best is None or count == 0 or unique:
            continue

        w_est = est
        if w_est is None and csv_items:
            cand = list(csv_items)
            if sh_csv is not None:
                cand = [i for i in cand if i.shape == sh_csv]
            if q is not None:
                cand = [i for i in cand if i.quality == q]
            if excl_q:
                cand = [i for i in cand if i.quality not in excl_q]
            if cats:
                wc = [i for i in cand if all(c in i.category_tags for c in cats)]
                if wc:
                    cand = wc
            if excl_c:
                cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
            w_est = _weighted_est_price(cand, weights if weights else None, mid_n)
        val = float(w_est) if w_est is not None else float(best.base_value)

        w, h = shape_wh_from_snapshot(sh_geo)
        geo = max(1, int(w) * int(h))
        sum_val += val
        sum_geo += geo
    return sum_val, sum_geo


def _geo_footprint_cells_from_shape_field(shape_val: Any) -> Optional[float]:
    """仅从外形编码得到几何占位格数；无法解析时返回 None。"""
    sh = _parse_shape_int(shape_val)
    if sh is None:
        return None
    w, h = shape_wh_from_snapshot(sh)
    return float(max(1, w * h))


def estimate_snapshot_item_price(
    it: Dict[str, Any],
    *,
    board_snapshot: Dict[str, Any],
) -> Optional[float]:
    """单件展示用估价（与画板汇总逻辑同源）。"""
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return None
    weights = map_category_ratios(mid) or {}
    v = _item_value(
        it,
        csv_index=csv_index,
        csv_items=csv_items,
        map_id_normalized=mid_n,
        map_category_weights=weights,
    )
    return v if v > 0 else None


def estimate_snapshot_item_price_for_uid(
    board_snapshot: Dict[str, Any],
    uid: str,
) -> Optional[float]:
    """按 uid 取合并后的物品行再估价（含 ``grid_overlay`` 手动画框与手动确认投影）。"""
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    it = items.get(str(uid))
    if not isinstance(it, dict):
        return None
    work = _pricing_work_board_snapshot(board_snapshot, items)
    return estimate_snapshot_item_price(it, board_snapshot=work)


def compute_items_total(board_snapshot: Dict[str, Any]) -> float:
    """对所有带有效 ``box_id`` 的物品求标价之和（合并 ``grid_overlay`` 投影）。"""
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0
    weights = map_category_ratios(mid) or {}
    total = 0.0
    for _uid, it in items.items():
        if not isinstance(it, dict):
            continue
        total += _item_value(
            it,
            csv_index=csv_index,
            csv_items=csv_items,
            map_id_normalized=mid_n,
            map_category_weights=weights,
        )
    return total


def build_snapshot_pricing_dict(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    组装 ``board_snapshot.json`` 的 ``pricing`` 字段。

    从 ``board_snapshot`` 合并后的有效物品表（``game_state.items`` + ``grid_overlay``）
    计算 ``total``（不做外部覆盖）。
    有效空置 ``pricing.vacant`` 与快照 ``grid_overlay.vacant`` 一致时优先直接读取后者，
    否则由 :func:`grid_overlay.vacant_dict_from_board_snapshot` 计算；
    占位格优先 ``grid_overlay.occupied_cell_bids``。

    ``board_snapshot_config``：可选，形状同应用配置里的 ``board_snapshot`` 段；省略时从
    本地 ``configs``（runtime + config 深合并）读取。用于判定己方 ``hero_cid``（Ahmad 主价等）。
    """
    game_state_json = board_snapshot.get("game_state") or {}
    skill_logs = list(board_snapshot.get("skill_logs") or [])
    map_id = int(board_snapshot.get("map_id") or (game_state_json.get("map_id") or 0))
    cr = board_snapshot.get("current_round")
    if cr is None:
        cr = game_state_json.get("current_round")
    current_round = int(cr or 1)
    raw = board_snapshot.get("raw_pricing")
    if not isinstance(raw, dict):
        from .raw_pricing import build_raw_pricing_dict

        raw = build_raw_pricing_dict(
            map_id=int(map_id or 0),
            skill_logs=list(skill_logs or []),
            snapshot_path_hint=snapshot_path_hint,
        )

    snap_full = dict(board_snapshot)
    snap_full["game_state"] = game_state_json
    snap_full["skill_logs"] = skill_logs
    snap_full["map_id"] = map_id
    snap_full["current_round"] = current_round
    snap_full["raw_pricing"] = raw

    raw_csv_cells = raw.get("csv_quality_groups_avg_per_cell") if isinstance(raw, dict) else None
    if isinstance(raw_csv_cells, dict):
        try:
            csv_cells_for_est = {str(k): float(v) for k, v in raw_csv_cells.items()}
        except (TypeError, ValueError):
            csv_cells_for_est = {}
    else:
        csv_cells_for_est = {}

    total_f = float(compute_items_total(snap_full))

    vb = _grid_overlay.vacant_block_from_board_snapshot(snap_full)
    vacant_num = int(vb.get("geometric") or 0)
    vacant_src = str(vb.get("source") or "")

    u_orange = int(round(float(csv_cells_for_est.get("q5", 0.0))))
    u_gr = int(round(float(csv_cells_for_est.get("q5+q6", 0.0))))
    u_red = int(round(float(csv_cells_for_est.get("q6", 0.0))))

    u_early, qg_early, pq_early = _scan_inference.vacant_early_unit_from_exclusions(
        board_snapshot=snap_full,
        csv_cells_raw=csv_cells_for_est if csv_cells_for_est else None,
        pricing={},
    )

    st_ev = raw.get("event_stats") if isinstance(raw, dict) else None
    cq4, cq5, cq6 = _confirmed_tier_footprint_q456(snap_full)
    tier_extra_val, tier_extra_cells = _tier_min_extra_value_and_cells(
        st_ev,
        confirmed_q4=cq4,
        confirmed_q5=cq5,
        confirmed_q6=cq6,
        csv_cells=csv_cells_for_est,
    )
    kcw_val, kcw_geo = _sum_known_contour_weighted_price_and_geo_cells(
        snap_full, csv_cells_raw=csv_cells_for_est
    )
    vacant_adj = max(0, int(vacant_num) + int(kcw_geo) - int(tier_extra_cells))
    vacant_pts_base = float(total_f) - float(kcw_val) + float(tier_extra_val)

    est_orange = vacant_pts_base + float(vacant_adj) * float(u_orange)
    est_gold_red = vacant_pts_base + float(vacant_adj) * float(u_gr)
    est_red = vacant_pts_base + float(vacant_adj) * float(u_red)

    q14_grid_known = _event_stats_q14_grid_counts_all_known(raw)
    early_pts_blended_with_random_avg = False
    if not q14_grid_known:
        pts = vacant_pts_base + float(vacant_adj) * float(u_early)
        pts_floor = pts
        pts_ceiling = pts
        rnd_min: Optional[int] = None
        if isinstance(st_ev, dict):
            rv = st_ev.get("random_avg_price_min")
            if rv is not None:
                try:
                    rnd_min = int(rv)
                except (TypeError, ValueError):
                    rnd_min = None
        if (
            rnd_min is not None
            and rnd_min > 0
            and pts > 0
            and float(rnd_min) > _RANDOM_AVG_MIN_DOMINANCE_RATIO * float(pts)
        ):
            pts = int((pts + rnd_min) / 2)
            pts_floor = pts
            pts_ceiling = pts
            early_pts_blended_with_random_avg = True
    else:
        pts = vacant_pts_base + float(vacant_adj) * float(u_orange)
        pts_floor = vacant_pts_base + float(vacant_adj) * float(u_orange)
        pts_ceiling = vacant_pts_base + float(vacant_adj) * float(u_early)

    ahmad_detail = _ahmad_pricing_detail_from_raw_pricing(
        raw, items_total=float(vacant_pts_base), vacant_adj=int(vacant_adj)
    )
    ahmad_points = int(ahmad_detail.get("ahmad_points") or 0)

    generic_pts = int(round(pts))
    generic_floor = int(round(pts_floor))
    generic_ceil = int(round(pts_ceiling))
    self_hc = _self_player_hero_cid(snap_full, board_snapshot_config=board_snapshot_config)
    _AHMAD_HERO_CID = 204
    ahmad_pricing_active = self_hc == _AHMAD_HERO_CID

    if ahmad_pricing_active:
        pts_out = pts_floor_out = pts_ceiling_out = ahmad_points
    else:
        pts_out, pts_floor_out, pts_ceiling_out = generic_pts, generic_floor, generic_ceil

    pricing: Dict[str, Any] = {
        "total": float(total_f),
        "points": pts_out,
        "points_floor": pts_floor_out,
        "points_ceiling": pts_ceiling_out,
        "vacant": int(vacant_num),
        "est_orange": int(round(est_orange)),
        "est_gold_red": int(round(est_gold_red)),
        "est_red": int(round(est_red)),
        "vacant_unit_all_orange": u_orange,
        "vacant_unit_gold_red": u_gr,
        "vacant_unit_all_red": u_red,
        "vacant_source": vacant_src,
        "early_vacant_unit_from_scan": int(u_early),
        "early_vacant_csv_group": str(qg_early or ""),
        "early_vacant_possible_qualities": sorted(int(x) for x in pq_early),
        "map_quality_avg_hit": bool(csv_cells_for_est),
        "map_quality_avg_csv": str(raw.get("map_quality_avg_csv") or "") if isinstance(raw, dict) else "",
        "known_contour_weighted_cells": int(kcw_geo),
        "known_contour_weighted_price": float(kcw_val),
        "early_points_blended_with_random_avg": bool(early_pts_blended_with_random_avg),
        "ahmad_points": ahmad_points,
        "ahmad_points_detail": ahmad_detail,
        "ahmad_pricing_active": bool(ahmad_pricing_active),
    }
    if ahmad_pricing_active:
        pricing["generic_points"] = generic_pts
        pricing["generic_points_floor"] = generic_floor
        pricing["generic_points_ceiling"] = generic_ceil
    return pricing
