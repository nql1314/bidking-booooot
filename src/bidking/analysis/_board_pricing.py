# -*- coding: utf-8 -*-
"""
画板快照定价：由 ``game_state.items`` 与 ``grid_overlay`` 合并后的有效物品表汇总总价、
权重占位与空置格，再结合扫描推断与地图 CSV 格均价给出 ``points`` / ``est_*``。

``items`` 合并优先使用快照 ``grid_overlay["merged_items_dict"]``（见 :func:`grid_overlay.merged_items_dict_from_snapshot`），否则由 :func:`grid_overlay.merged_items_dict` 计算（含 ``manual_shapes`` 几何补全等）。

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

低档总格已齐（``q14_grid_known``）时，若 ``random_avg_price_min`` 仍明显高于 ``points``（>50%），
对 ``points`` / ``points_floor`` / ``points_ceiling`` 分别做 ``random_avg_price_min + 原值/3``（与早期回合同式）。

合并物品上 **仍无 ``shape``、品质已知且已确认占位** 时，几何占位按锚格计；``pricing.total`` 已为该档
CSV 权重期望价。``max(0, 加权等效格数 − 1)`` 按品质从对应 ``q*_grid_min`` 的 ``tier_extra`` 格数/价值中
扣减（见 :func:`unknown_value.unknown_contour_vacant_weighted_excess` 的 ``excess_by_quality``），不再单独从
``vacant_adj`` 扣减，避免与 ``total`` 重复计价。

已知轮廓且品质未知、CSV 为多候选（权重价）的物品：标价已计入 ``pricing.total``，空置侧不再单独做 kcw 扣减/加回。

完整 ``pricing`` 组装流程见 :mod:`.strategy`（公共流水线 + 各角色 enrich）。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
from ..config.runtime import resolve_auto_vacant_phantom_price_quantile
from ..parsing.item_db import (
    _weighted_est_price,
    map_category_ratios,
    query_item,
    weighted_est_max_item_base_value,
)
from . import grid_overlay as _grid_overlay
from ._shape_wh import shape_wh_from_snapshot
from .grid_overlay import is_auto_vacant_rect_phantom_uid
from .grid_overlay_vacant_zone import infer_max_shape_wh_for_unknown_contour_merged_row
from . import strategy as _strategy
from ..logsys.perf_log import perf_log_elapsed

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    t0 = time.perf_counter()
    from . import unknown_value as _unknown_value

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
    """合并行上的 ``shape`` 用于 CSV 轮廓过滤（含手动画框写入的外形）。"""
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


def _resolve_auto_vacant_phantom_price_quantile_for_snapshot(
    board_snapshot: Dict[str, Any],
) -> Optional[float]:
    raw = board_snapshot.get("raw_pricing")
    if isinstance(raw, dict) and raw.get("auto_vacant_phantom_price") is not None:
        return resolve_auto_vacant_phantom_price_quantile(
            snapshot_override=raw.get("auto_vacant_phantom_price")
        )
    pricing_dict: Optional[Dict[str, Any]] = None
    try:
        from ..config.runtime import load_runtime

        pricing_raw = load_runtime().raw.get("pricing")
        if isinstance(pricing_raw, dict):
            pricing_dict = pricing_raw
    except Exception:
        pass
    return resolve_auto_vacant_phantom_price_quantile(pricing_dict=pricing_dict)


def _item_value(
    it: Dict[str, Any],
    *,
    csv_index: Dict[int, Any],
    csv_items: List[Any],
    map_id_normalized: Optional[int],
    map_category_weights: Dict[int, float],
    price_quantile: Optional[float] = None,
    max_shape_wh: Optional[Tuple[int, int]] = None,
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

    max_wh = max_shape_wh if sh is None else None
    best, count, unique, est, _label = query_item(
        sh,
        q,
        cats,
        item_cid_i,
        csv_index,
        csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
        max_shape_wh=max_wh,
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
    need_reprice = price_quantile is not None or w_est is None
    if need_reprice and csv_items:
        cand = list(csv_items)
        if sh is not None:
            cand = [i for i in cand if i.shape == sh]
        elif max_wh is not None:
            mw, mh = max_wh

            def _fits_shape(shape: Any) -> bool:
                w, h = shape_wh_from_snapshot(shape)
                return w <= mw and h <= mh

            cand = [i for i in cand if _fits_shape(i.shape)]
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
        if cand:
            w_est = _weighted_est_price(
                cand,
                map_category_weights or None,
                map_id_normalized,
                max_item_base_value=weighted_est_max_item_base_value(sh),
                quantile=price_quantile,
            )
    result = float(w_est) if w_est is not None else float(best.base_value)
    perf_log_elapsed("_item_value (weighted)", t0)
    return result


def estimate_snapshot_item_price(
    it: Dict[str, Any],
    *,
    board_snapshot: Dict[str, Any],
    uid: Optional[str] = None,
) -> Optional[float]:
    """单件展示用估价（与画板汇总逻辑同源）。"""
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return None
    weights = map_category_ratios(mid) or {}
    q_override: Optional[float] = None
    if uid is not None and is_auto_vacant_rect_phantom_uid(str(uid)):
        q_override = _resolve_auto_vacant_phantom_price_quantile_for_snapshot(board_snapshot)
    max_wh: Optional[Tuple[int, int]] = None
    if uid is not None:
        items_all = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
        max_wh = infer_max_shape_wh_for_unknown_contour_merged_row(
            str(uid), it, items_all
        )
    v = _item_value(
        it,
        csv_index=csv_index,
        csv_items=csv_items,
        map_id_normalized=mid_n,
        map_category_weights=weights,
        price_quantile=q_override,
        max_shape_wh=max_wh,
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
    return estimate_snapshot_item_price(it, board_snapshot=work, uid=str(uid))


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
    auto_vac_q = _resolve_auto_vacant_phantom_price_quantile_for_snapshot(board_snapshot)
    total = 0.0
    for uid, it in items.items():
        if not isinstance(it, dict):
            continue
        uid_s = str(uid)
        q = auto_vac_q if is_auto_vacant_rect_phantom_uid(uid_s) else None
        max_wh = infer_max_shape_wh_for_unknown_contour_merged_row(uid_s, it, items)
        total += _item_value(
            it,
            csv_index=csv_index,
            csv_items=csv_items,
            map_id_normalized=mid_n,
            map_category_weights=weights,
            price_quantile=q,
            max_shape_wh=max_wh,
        )
    perf_log_elapsed(f"compute_items_total (items={len(items)})", t0)
    return total


def compute_known_items_total(board_snapshot: Dict[str, Any]) -> float:
    """已知物品标价之和：与 :func:`compute_items_total` 同源，但排除自动 ``phantom_vac_*`` 填充。"""
    t0 = time.perf_counter()
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_n = item_db.normalize_map_id(mid)
    items = _grid_overlay.merged_items_dict_from_snapshot(board_snapshot)
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0
    weights = map_category_ratios(mid) or {}
    total = 0.0
    for uid, it in items.items():
        if is_auto_vacant_rect_phantom_uid(str(uid)):
            continue
        if not isinstance(it, dict):
            continue
        total += _item_value(
            it,
            csv_index=csv_index,
            csv_items=csv_items,
            map_id_normalized=mid_n,
            map_category_weights=weights,
        )
    perf_log_elapsed(f"compute_known_items_total (items={len(items)})", t0)
    return total


def build_snapshot_pricing_dict(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """组装 ``board_snapshot.json`` 的 ``pricing`` 字段（委托 :mod:`.strategy`）。"""
    return _strategy.build_snapshot_pricing_dict(
        board_snapshot,
        snapshot_path_hint=snapshot_path_hint,
        board_snapshot_config=board_snapshot_config,
    )


# 单测与旧代码兼容 re-export
from .strategy.ahmad import (  # noqa: E402
    map_bundle_is_express_station_series,
)
from .strategy.common import (  # noqa: E402
    blend_points_with_random_avg_min_if_dominant as _blend_points_with_random_avg_min_if_dominant,
    event_stat_grid_count_optional as _event_stat_grid_count_optional,
    self_player_hero_cid as _self_player_hero_cid,
)
