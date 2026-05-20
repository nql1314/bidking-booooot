# -*- coding: utf-8 -*-
"""
画板快照定价：由 ``game_state.items`` 与 ``grid_overlay`` 合并后的有效物品表汇总总价、
权重占位与空置格，再结合扫描推断与地图 CSV 格均价给出 ``points`` / ``est_*``。

``items`` 合并优先使用快照 ``grid_overlay["merged_items_dict"]``（见 :func:`grid_overlay.merged_items_dict_from_snapshot`），否则由 :func:`grid_overlay.merged_items_dict` 计算（含 ``infer_shapes`` 几何补全；推算写入的 ``shape``（如 1×1→11）参与 CSV 轮廓匹配，避免「仅知档位」却按全轮廓候选加权）。

不再维护独立的「艾莎 bid」分支；策略层直接消费 ``pricing.points`` / ``points_floor`` /
``points_ceiling``。

当本地配置（``configs/runtime.json`` 与 ``configs/config.json`` 深合并）中
``board_snapshot.self_user_uid`` **出现在本局** ``players`` 中时直接使用；否则由进程内跨对局
UID 推断（``inferred_self_user_uid``，见 :mod:`bidking.pricing._self_uid_inference`）；唯一推断结果可写回
``configs/config.json`` 的 ``board_snapshot.self_user_uid``（可用环境变量
``BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST=1`` 关闭写盘，单测默认启用）。
快递站系列（档键 ``210``，与 ``automation.maps`` 中「快递盲盒堆」一致）时，上述三字段与
``pricing.ahmad_points`` 一致（由 ``raw_pricing.event_stats`` 多候选取 max）；其余地图仍走通用画板
空置主价；``pricing.generic_points*`` 仅在启用 Ahmad 主价时写入供 UI 对照。
``pricing.ahmad_points_detail`` 含各候选分解。可选 ``board_snapshot.ahmad_abde_scale``（或运行时配置同名字段）：
对 Ahmad 候选 A/B/D 的 base 与候选 E 的 q123 格均价乘该系数，并写入 ``pricing.ahmad_abde_scale``。

当 ``raw_pricing.event_stats`` 提供 ``q4_grid_min`` / ``q5_grid_min`` / ``q6_grid_min`` 时，
对 ``max(0, 最少格 - 已确认该档占位格)`` 按 CSV 单档 ``q4``/``q5``/``q6`` 格均价计入总价，
并对空置单价项使用扣减后的有效空置格数（``pricing.vacant`` 仍为几何/有效空置原值）。

当低档总格已齐备且 **仅** 公开 ``q5_grid_count`` 与 ``q6_grid_count`` 之一时，空置主价区间按
「余量必为红 / 必为金」分别用 CSV ``q6`` / ``q5`` 格均价；二者皆未公开或二者皆已公开时，
仍按金单价估计主价、早单价作上界（与原逻辑一致）。

当 ``event_stats`` 已给出明确的 ``q4_grid_count``（紫档总格已由公共信息划定）时，扫描推断的
早单价可能品质集合中不再保留 q4，改用去掉 q4 后的 CSV 组合键（如 ``q5+q6``）查格均价，
避免剩余空格再乘含紫档权重的混合单价。

合并物品上 **仍无 ``shape``、品质已知且已确认占位** 时，几何占位按锚格计；``pricing.total`` 已为该档
CSV 权重期望价。对 ``max(0, 加权等效格数 − 1)`` 之和从有效空置 ``vacant_adj`` 中扣减（见
:func:`unknown_value.unknown_contour_vacant_weighted_excess`），使 ``空置格 × 早/金红单价`` 不因多计空格外扩。

已知轮廓且品质未知、CSV 为多候选（权重价）的物品（含仅日志未确认的锚格）：几何占位格在边际上视同空置，参与 ``空置格 × 空置单价``；
但 ``total`` / ``compute_items_total`` 已含该件权重价，故在 ``points`` / ``est_*`` 基底中扣除对应权重价，避免重复计价。
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
from ..parsing.item_db import _weighted_est_price, map_category_ratios, query_item
from . import scan_inference as _scan_inference
from . import unknown_value as _unknown_value
from . import grid_overlay as _grid_overlay
from ._shape_wh import shape_wh_from_snapshot
from . import strategy as _strategy
from ..logsys.perf_log import perf_log, perf_log_elapsed

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None

# 仅 ``not q14_grid_known``（低档 **q12+q3+q4** 总格未齐，见 ``event_stats_q12_q3_q4_grids_all_known``）早期回合：当 ``random_avg_price_min`` 超过本算 ``points`` 的 50% 时，
# 用 ``(points + random_avg_price_min) / 2`` 与事件下界取中，缓和随机均价事件对总估价的拉扯。
_RANDOM_AVG_MIN_DOMINANCE_RATIO = 0.5


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    t0 = time.perf_counter()
    path = _unknown_value._item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        perf_log_elapsed("_load_item_prices_db (no path)", t0)
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
        perf_log_elapsed("_load_item_prices_db (load_csv)", t0)
    except OSError:
        _item_prices_cache = ({}, [])
        perf_log_elapsed("_load_item_prices_db (OSError)", t0)
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


def _event_stat_grid_count_optional(st: Any, key: str) -> Optional[int]:
    """``event_stats`` 中 ``*_grid_count``（如 ``q4_grid_count``）：有值且非负时返回 int，否则视为该档总格未公开。"""
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


def _event_stat_q4_grid_count_optional(st: Any) -> Optional[int]:
    """``event_stats`` 中 ``q4_grid_count``：有值且非负时返回 int，否则视为紫档总格未公开。"""
    return _event_stat_grid_count_optional(st, "q4_grid_count")


def _vacant_early_unit_excluding_q4_when_q4_total_known(
    *,
    board_snapshot: Dict[str, Any],
    csv_cells_for_est: Dict[str, float],
    event_stats: Any,
) -> Tuple[int, str, frozenset[int]]:
    """
    扫描负向约束得到 ``(u0, qg0, pq0)`` 后：若事件已公开 ``q4_grid_count``，且 ``pq0`` 仍含
    品质 4，则从可能集合去掉 4 并按新组合键查 CSV；缺键则退回原扫描早单价。
    """
    t0 = time.perf_counter()
    u0, qg0, pq0 = _scan_inference.vacant_early_unit_from_exclusions(
        board_snapshot=board_snapshot,
        csv_cells_raw=csv_cells_for_est if csv_cells_for_est else None,
        pricing={},
    )
    if _event_stat_q4_grid_count_optional(event_stats) is None:
        return u0, qg0, pq0
    if 4 not in pq0:
        return u0, qg0, pq0
    pq_ex = frozenset(q for q in pq0 if int(q) != 4)
    qg = _scan_inference.csv_quality_group_from_possible_set(pq_ex)
    if qg is None or not csv_cells_for_est or qg not in csv_cells_for_est:
        perf_log_elapsed("_vacant_early_unit_excluding_q4 (fallback)", t0)
        return u0, qg0, pq0
    u = int(round(float(csv_cells_for_est[qg])))
    perf_log_elapsed("_vacant_early_unit_excluding_q4 (adjusted)", t0)
    return u, str(qg), pq_ex


def _confirmed_tier_footprint_q456(
    board_snapshot: Dict[str, Any],
) -> Tuple[int, int, int]:
    """
    合并物品表上 Q4/Q5/Q6、含有效 ``box_id`` 且快照 ``shape`` 已知的几何占位格数之和。
    """
    t0 = time.perf_counter()
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
    result = int(round(s4)), int(round(s5)), int(round(s6))
    perf_log_elapsed(f"_confirmed_tier_footprint_q456 (items={len(items)})", t0)
    return result


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
    ``raw_pricing.event_stats`` 中低档占用总格已划定（**q12+q3+q4** 语义）时，
    可认为已由公共信息划定紫档及此前档位，空置金红估价区间与后期回合一致。

    等价于 :func:`bidking.analysis.raw_pricing.event_stats_q12_q3_q4_grids_all_known`。
    """
    from .raw_pricing import event_stats_q12_q3_q4_grids_all_known

    return event_stats_q12_q3_q4_grids_all_known(raw)


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
    """合并行上的 ``shape`` 用于 CSV 轮廓过滤（含 ``_overlay_shape_origin == "infer"`` 的推算行）。

    推算轮廓与几何占位同源（``w×h`` 编码为 ``shape``）；若此处再置 ``None``，则已知档位
    （如 Q6）会误匹配价表里**所有**同档外形，加权期望被人为抬高。无 ``shape`` 时仍为未知轮廓。
    """
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
    """用 ``self_user_uid``、``inferred_self_user_uid`` 或 ``board_snapshot_config`` 在 ``players`` 中解析己方 ``hero_cid``。

    身份字段来源：快照根键 ``self_user_uid``、再 ``board_snapshot_config``、再运行时
    ``load_runtime().raw["board_snapshot"]``；以上皆空时使用
    :func:`bidking.pricing._self_uid_inference.apply_self_uid_inference_to_board_snapshot`
    写入的 ``inferred_self_user_uid``。

    ``len(players)==1`` 时回落到唯一玩家。
    """
    from ..pricing._self_uid_inference import (
        apply_self_uid_inference_to_board_snapshot,
        resolve_effective_self_user_uid,
    )

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
    cfg_u = str(branch.get("self_user_uid") or "").strip()
    apply_self_uid_inference_to_board_snapshot(
        board_snapshot, config_self_user_uid=cfg_u
    )
    self_uid = resolve_effective_self_user_uid(
        board_snapshot, config_self_user_uid=cfg_u
    )
    pdata: Any = None
    if self_uid and self_uid in players:
        pdata = players.get(self_uid)
    if pdata is None and len(players) == 1:
        pdata = next(iter(players.values()))
    if not isinstance(pdata, dict):
        return None
    try:
        hc = int(pdata.get("hero_cid") or 0)
    except (TypeError, ValueError):
        return None
    return hc if hc > 0 else None


def _item_value(
    it: Dict[str, Any],
    *,
    csv_index: Dict[int, Any],
    csv_items: List[Any],
    map_id_normalized: Optional[int],
    map_category_weights: Dict[int, float],
) -> float:
    t0 = time.perf_counter()
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
    cats_any = _int_set_from_field(it.get("categories_any"))
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
        categories_any=cats_any if cats_any else None,
    )
    if best is None or count == 0:
        return 0.0

    if unique:
        result = float(best.base_value)
        perf_log_elapsed("_item_value (unique)", t0)
        return result
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
        if cats_any:
            wa = [i for i in cand if cats_any.intersection(i.category_tags)]
            if wa:
                cand = wa
        if excl_c:
            cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
        w_est = _weighted_est_price(cand, map_category_weights or None, map_id_normalized)
    result = float(w_est) if w_est is not None else float(best.base_value)
    perf_log_elapsed("_item_value (weighted)", t0)
    return result


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
    t0 = time.perf_counter()
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
        cats_any = _int_set_from_field(it.get("categories_any"))
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
            categories_any=cats_any if cats_any else None,
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
            if cats_any:
                wa = [i for i in cand if cats_any.intersection(i.category_tags)]
                if wa:
                    cand = wa
            if excl_c:
                cand = [i for i in cand if not any(c in excl_c for c in i.category_tags)]
            w_est = _weighted_est_price(cand, weights if weights else None, mid_n)
        val = float(w_est) if w_est is not None else float(best.base_value)

        w, h = shape_wh_from_snapshot(sh_geo)
        geo = max(1, int(w) * int(h))
        sum_val += val
        sum_geo += geo
    perf_log_elapsed("_sum_known_contour_weighted_price_and_geo_cells", t0)
    return sum_val, sum_geo


def _geo_footprint_cells_from_shape_field(shape_val: Any) -> Optional[float]:
    """仅从外形编码得到几何占位格数；无法解析时返回 None。"""
    sh = _parse_shape_int(shape_val)
    if sh is None:
        return None
    w, h = shape_wh_from_snapshot(sh)
    return float(max(1, w * h))


# 大金区域定义：(宽, 高) 或 (高, 宽) 都匹配
_BIG_GOLD_SHAPES = frozenset([
    (3, 4), (4, 3),  # 3x4, 4x3
    (4, 4),          # 4x4
    (3, 5), (5, 3),  # 3x5, 5x3
    (5, 2), (2, 5),  # 5x2, 2x5
])


def _find_continuous_regions(
    vacant_cells: Set[Tuple[int, int]],
    occupied: Set[Tuple[int, int]],
) -> List[Set[Tuple[int, int]]]:
    """
    在空置格中查找所有连续区域（4连通）。
    返回每个连续区域的格子集合列表。
    """
    t0 = time.perf_counter()
    if not vacant_cells:
        return []

    remaining = set(vacant_cells)
    regions: List[Set[Tuple[int, int]]] = []

    while remaining:
        # 从一个种子点开始BFS
        seed = remaining.pop()
        region: Set[Tuple[int, int]] = {seed}
        queue = [seed]

        while queue:
            r, c = queue.pop(0)
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if (nr, nc) in remaining and (nr, nc) not in occupied:
                    remaining.discard((nr, nc))
                    region.add((nr, nc))
                    queue.append((nr, nc))

        regions.append(region)

    perf_log_elapsed(f"_find_continuous_regions (regions={len(regions)})", t0)
    return regions


def _get_bounding_box(cells: Set[Tuple[int, int]]) -> Tuple[int, int, int, int]:
    """
    获取一组格子的包围盒。
    返回 (min_row, min_col, height, width)。
    """
    if not cells:
        return 0, 0, 0, 0
    rows = [r for r, c in cells]
    cols = [c for r, c in cells]
    min_r, max_r = min(rows), max(rows)
    min_c, max_c = min(cols), max(cols)
    return min_r, min_c, max_r - min_r + 1, max_c - min_c + 1


def _is_rectangular_region(cells: Set[Tuple[int, int]], height: int, width: int) -> bool:
    """
    检查区域是否是一个完整的矩形（没有空洞）。
    """
    if len(cells) != height * width:
        return False
    min_r, min_c, h, w = _get_bounding_box(cells)
    if h != height or w != width:
        return False
    # 检查是否填满整个矩形
    for r in range(min_r, min_r + height):
        for c in range(min_c, min_c + width):
            if (r, c) not in cells:
                return False
    return True


def _detect_big_gold_regions(
    board_snapshot: Dict[str, Any],
) -> Tuple[int, int]:
    """
    检测空置区域中可能为大金的连续区域。

    返回: (big_gold_cells, total_vacant_cells)
    - big_gold_cells: 符合大金尺寸（3x4,4x3,4x4,3x5,5x3,5x2,2x5）的连续区域总格数
    - total_vacant_cells: 总空置格数
    """
    t0 = time.perf_counter()
    from .grid_overlay_dims import GRID_ROWS, GRID_COLS

    # 获取空置格和占位格
    vb = _grid_overlay.vacant_block_from_board_snapshot(board_snapshot)
    vacant_num = int(vb.get("geometric") or 0)

    if vacant_num <= 0:
        return 0, 0

    occupied = _grid_overlay.snapshot_occupied_cells(board_snapshot)

    # 构建完整的空置格集合（基于几何前缀区）
    max_bid = _grid_overlay.max_anchor_box_id_merged(board_snapshot)
    limit = min(max_bid, _grid_overlay.GRID_MAX_BOX_ID)

    vacant_cells: Set[Tuple[int, int]] = set()
    for bid in range(limit + 1):
        row, col = bid // GRID_COLS, bid % GRID_COLS
        if (row, col) not in occupied:
            vacant_cells.add((row, col))

    if not vacant_cells:
        return 0, vacant_num

    # 查找所有连续区域
    regions = _find_continuous_regions(vacant_cells, occupied)

    big_gold_total = 0
    for region in regions:
        if len(region) < 6:  # 最小的大金区域是 2x5=10 格，但检查所有>=6的区域
            continue

        min_r, min_c, h, w = _get_bounding_box(region)

        # 检查是否匹配大金形状（考虑旋转）
        shape_match = (h, w) in _BIG_GOLD_SHAPES or (w, h) in _BIG_GOLD_SHAPES

        if shape_match and _is_rectangular_region(region, h, w):
            big_gold_total += len(region)

    perf_log_elapsed(f"_detect_big_gold_regions (vacant={vacant_num}, big_gold={big_gold_total})", t0)
    return big_gold_total, vacant_num


def _adjust_u_early_for_big_gold(
    u_early: float,
    u_orange: float,
    big_gold_cells: int,
    total_vacant: int,
) -> float:
    """
    根据大金区域调整 u_early，避免大金过大导致的估价偏高。

    公式: u_early_adj = (big_gold_cells/vac) * (u_orange+u_early)/2 + (vac-big_gold)/vac * u_early
    """
    if total_vacant <= 0 or big_gold_cells <= 0:
        return u_early

    if big_gold_cells >= total_vacant:
        return (u_orange + u_early) / 2

    ratio_big = big_gold_cells / total_vacant
    ratio_other = (total_vacant - big_gold_cells) / total_vacant

    # 大金区域使用较低的单价 (u_orange+u_early)/2
    u_big_gold = (u_orange + u_early) / 2

    return ratio_big * u_big_gold + ratio_other * u_early


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
    t0 = time.perf_counter()
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
    perf_log_elapsed(f"compute_items_total (items={len(items)})", t0)
    return total


def build_snapshot_pricing_dict(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    t0_total = time.perf_counter()
    """组装 ``board_snapshot.json`` 的 ``pricing`` 字段。

    从 ``board_snapshot`` 合并后的有效物品表（``game_state.items`` + ``grid_overlay``）
    计算 ``total``（不做外部覆盖）。
    有效空置 ``pricing.vacant`` 与快照 ``grid_overlay.vacant`` 一致时优先直接读取后者，
    否则由 :func:`grid_overlay.vacant_dict_from_board_snapshot` 计算；
    占位格优先 ``grid_overlay.occupied_cell_bids``。

    ``board_snapshot_config``：可选，形状同应用配置里的 ``board_snapshot`` 段；省略时从
    本地 ``configs``（runtime + config 深合并）读取。用于判定己方 ``hero_cid``（Ahmad 主价等），
    支持 ``self_user_uid`` 与跨对局 ``inferred_self_user_uid``（与策略面板 / 推断模块一致）。
    可选 ``ahmad_abde_scale``（非负有限数，缺省 ``1.0``）：见 :func:`_ahmad_pricing_detail_from_raw_pricing`。
    """
    from ..pricing._self_uid_inference import apply_self_uid_inference_to_board_snapshot

    t0_init = time.perf_counter()
    branch_bs = (
        board_snapshot_config
        if board_snapshot_config is not None
        else _local_board_snapshot_branch()
    )
    self_uid_infer_detail = apply_self_uid_inference_to_board_snapshot(
        board_snapshot,
        config_self_user_uid=str(branch_bs.get("self_user_uid") or "").strip(),
    )
    perf_log_elapsed("build_snapshot_pricing_dict: init", t0_init)
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

    t0_csv = time.perf_counter()
    raw_csv_cells = raw.get("csv_quality_groups_avg_per_cell") if isinstance(raw, dict) else None
    if isinstance(raw_csv_cells, dict):
        try:
            csv_cells_for_est = {str(k): float(v) for k, v in raw_csv_cells.items()}
        except (TypeError, ValueError):
            csv_cells_for_est = {}
    else:
        csv_cells_for_est = {}
    perf_log_elapsed("build_snapshot_pricing_dict: csv_cells_parse", t0_csv)

    t0_items = time.perf_counter()
    total_f = float(compute_items_total(snap_full))
    perf_log_elapsed("build_snapshot_pricing_dict: compute_items_total", t0_items)

    t0_vacant = time.perf_counter()
    vb = _grid_overlay.vacant_block_from_board_snapshot(snap_full)
    vacant_num = int(vb.get("geometric") or 0)
    vacant_src = str(vb.get("source") or "")
    perf_log_elapsed("build_snapshot_pricing_dict: vacant_block", t0_vacant)

    t0_units = time.perf_counter()
    u_orange = int(round(float(csv_cells_for_est.get("q5", 0.0))))
    u_gr = int(round(float(csv_cells_for_est.get("q5+q6", 0.0))))
    u_red = int(round(float(csv_cells_for_est.get("q6", 0.0))))

    st_ev = raw.get("event_stats") if isinstance(raw, dict) else None
    u_early, qg_early, pq_early = _vacant_early_unit_excluding_q4_when_q4_total_known(
        board_snapshot=snap_full,
        csv_cells_for_est=csv_cells_for_est,
        event_stats=st_ev,
    )
    perf_log_elapsed("build_snapshot_pricing_dict: unit_prices", t0_units)

    t0_tiers = time.perf_counter()
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
    perf_log_elapsed("build_snapshot_pricing_dict: tier_footprint", t0_tiers)
    t0_unknown = time.perf_counter()
    mid_n = item_db.normalize_map_id(map_id if map_id else None)
    uc_excess_f, uc_excess_detail = _unknown_value.unknown_contour_vacant_weighted_excess(
        snap_full,
        csv_cells_for_est if csv_cells_for_est else None,
        {},
        mid_n,
    )
    perf_log_elapsed("build_snapshot_pricing_dict: unknown_contour", t0_unknown)
    uc_vacant_subtract = max(0, int(round(float(uc_excess_f))))
    vacant_adj = max(
        0,
        int(vacant_num) + int(kcw_geo) - int(tier_extra_cells) - uc_vacant_subtract,
    )
    t0_est = time.perf_counter()
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
            pts = rnd_min + pts/3
            pts_floor = pts
            pts_ceiling = pts
            early_pts_blended_with_random_avg = True
    else:
        # 低档总格已划定时：若仅公开金档总格，余下空置必为红格；若仅公开红档总格，余下必为金格。
        q5_gc = _event_stat_grid_count_optional(st_ev, "q5_grid_count")
        q6_gc = _event_stat_grid_count_optional(st_ev, "q6_grid_count")
        if q5_gc is not None and q6_gc is None:
            u_mid = float(u_red)
            u_lo = u_mid
            u_hi = u_mid
        elif q6_gc is not None and q5_gc is None:
            u_mid = float(u_orange)
            u_lo = u_mid
            u_hi = u_mid
        else:
            u_mid = float(u_orange)
            u_lo = float(u_orange)
            # 大金区域折算：配置开启时检测并调整 u_early，避免大金过大导致估价偏高
            from ..config.runtime import infer_big_gold_adjustment_enabled
            if infer_big_gold_adjustment_enabled():
                big_gold_cells, total_vacant = _detect_big_gold_regions(snap_full)
                u_early_adj = _adjust_u_early_for_big_gold(
                    float(u_early), float(u_orange), big_gold_cells, total_vacant
                )
                u_hi = u_early_adj
            else:
                u_hi = float(u_early)
        pts = vacant_pts_base + float(vacant_adj) * u_mid
        pts_floor = vacant_pts_base + float(vacant_adj) * u_lo
        pts_ceiling = vacant_pts_base + float(vacant_adj) * u_hi
    perf_log_elapsed("build_snapshot_pricing_dict: estimate_points", t0_est)

    t0_ahmad = time.perf_counter()
    ahmad_abde_scale = _strategy.ahmad.resolve_ahmad_abde_scale(snap_full, board_snapshot_config=board_snapshot_config)
    ahmad_detail = _strategy.ahmad.ahmad_pricing_detail_from_raw_pricing(
        raw,
        items_total=float(vacant_pts_base),
        vacant_adj=int(vacant_adj),
        board_items_total=float(total_f),
        ahmad_abde_scale=float(ahmad_abde_scale),
    )
    ahmad_points = int(ahmad_detail.get("ahmad_points") or 0)
    perf_log_elapsed("build_snapshot_pricing_dict: ahmad_pricing", t0_ahmad)

    generic_pts = int(round(pts))
    generic_floor = int(round(pts_floor))
    generic_ceil = int(round(pts_ceiling))
    self_hc = _self_player_hero_cid(snap_full, board_snapshot_config=board_snapshot_config)
    on_express = _strategy.ahmad.map_bundle_is_express_station_series(map_id)
    ahmad_pricing_active = (self_hc == _strategy.ahmad._AHMAD_HERO_CID) and on_express

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
        "unknown_contour_vacant_cell_excess_subtract": int(uc_vacant_subtract),
        "early_points_blended_with_random_avg": bool(early_pts_blended_with_random_avg),
        "ahmad_points": ahmad_points,
        "ahmad_points_detail": ahmad_detail,
        "ahmad_abde_scale": float(ahmad_abde_scale),
        "ahmad_pricing_active": bool(ahmad_pricing_active),
        "self_uid_inference": dict(self_uid_infer_detail),
    }
    if uc_excess_detail:
        pricing["unknown_contour_vacant_weighted_excess"] = dict(uc_excess_detail)
    if ahmad_pricing_active:
        pricing["generic_points"] = generic_pts
        pricing["generic_points_floor"] = generic_floor
        pricing["generic_points_ceiling"] = generic_ceil
    perf_log_elapsed(f"build_snapshot_pricing_dict: TOTAL (map={map_id}, round={current_round})", t0_total)
    return pricing
