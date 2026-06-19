# -*- coding: utf-8 -*-
"""
物品数据库

负责加载 item_prices.csv 并提供基于约束条件的物品查询接口。
"""

import csv
import json
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from .state import CsvItem

DROP_WEIGHTS_CSV = "drop_table_weights.csv"
MERGED_DATA_CSV = "calculator_data_merged.csv"
MAP_PRIOR_HTML = "物品轮廓爆率推断器.html"
DEFAULT_MAP_CATEGORY_WEIGHTS: Dict[int, float] = {
    cat: 1.0 for cat in range(101, 111)
}
# 多候选权重期望价：单价超过该阈值的候选不参与期望计算（避免天价拉爆期望），
# 候选集合本身不变；已指定 ItemCid 或仅剩单候选时走精确价，不经过此逻辑。
WEIGHTED_EST_MAX_ITEM_BASE_VALUE: float = 5_000_000.0
# 1×1（shape=11）多候选权重期望价：排除 10 万以上高价品对均价的拉动（与 UI「10万+」标记一致）。
WEIGHTED_EST_MAX_1X1_ITEM_BASE_VALUE: float = 100_000.0
_DROP_WEIGHT_BY_ITEM: Dict[int, List[Tuple[int, int, int]]] = {}
_DROP_GRAPH: Dict[int, List[Tuple[int, float]]] = {}
_DROP_RESOLVED_CACHE: Dict[Tuple[int, Tuple[int, ...]], Dict[int, float]] = {}
_NEST_WEIGHTS: Dict[int, List[float]] = {}
_SUBMAP_PRIOR_MULT: Dict[int, Dict[int, Dict[int, float]]] = {}
_KNOWN_ITEM_IDS: Set[int] = set()
_ITEM_CATEGORY_TAGS: Dict[int, List[int]] = {}

MAP_TO_TIER_NEST: Dict[int, Tuple[int, int]] = {
    2101: (101, 2001), 2102: (101, 2002), 2103: (101, 2003), 2104: (101, 2004),
    2105: (101, 2005), 2106: (101, 2006), 2107: (101, 2007),
    2201: (102, 2011), 2202: (102, 2012), 2203: (102, 2013), 2204: (102, 2014),
    2205: (102, 2015),
    2301: (103, 2021), 2302: (103, 2022), 2303: (103, 2023), 2304: (103, 2024),
    2305: (103, 2025), 2306: (103, 2026), 2307: (103, 2027), 2308: (103, 2028),
    2309: (103, 2029), 2310: (103, 2030),
    2401: (104, 2031), 2402: (104, 2032), 2403: (104, 2033), 2404: (104, 2034),
    2405: (104, 2035), 2406: (104, 2036), 2407: (104, 2037), 2408: (104, 2038),
    2409: (104, 2039), 2410: (104, 2040),
    2501: (105, 2041), 2502: (105, 2042), 2503: (105, 2043), 2504: (105, 2044),
    2505: (105, 2045), 2506: (105, 2046), 2507: (105, 2047), 2508: (105, 2048),
    2509: (105, 2049), 2510: (105, 2050),
    # RankMap 沉船扩展子图：根池为 Drop 表 2141~2150（密封仓 UP），非 2041~2050
    2511: (105, 2141), 2512: (105, 2142), 2513: (105, 2143), 2514: (105, 2144),
    2515: (105, 2145), 2516: (105, 2146), 2517: (105, 2147), 2518: (105, 2148),
    2519: (105, 2149), 2520: (105, 2150),
    2601: (106, 2051),
    # 日志 MapId +2000 档（与 24xx/25xx 同巢池，见 normalize_map_id）
    4401: (104, 2031), 4402: (104, 2032), 4403: (104, 2033), 4404: (104, 2034),
    4405: (104, 2035), 4406: (104, 2036), 4407: (104, 2037), 4408: (104, 2038),
    4409: (104, 2039), 4410: (104, 2040),
    4501: (105, 2041), 4502: (105, 2042), 4503: (105, 2043), 4504: (105, 2044),
    4505: (105, 2045), 4506: (105, 2046), 4507: (105, 2047), 4508: (105, 2048),
    4509: (105, 2049), 4510: (105, 2050),
    4511: (105, 2141), 4512: (105, 2142), 4513: (105, 2143), 4514: (105, 2144),
    4515: (105, 2145), 4516: (105, 2146), 4517: (105, 2147), 4518: (105, 2148),
    4519: (105, 2149), 4520: (105, 2150),
    # RankMap「白色DOWN红色UP」活动子图 2521–2530：与 2501–2510 同巢池（Drop 无 224x 时见 map_id_for_drop_weights）
    2521: (105, 2041), 2522: (105, 2042), 2523: (105, 2043), 2524: (105, 2044),
    2525: (105, 2045), 2526: (105, 2046), 2527: (105, 2047), 2528: (105, 2048),
    2529: (105, 2049), 2530: (105, 2050),
}
# 25xx/45xx 非基础子图（末两位 11+）无可用 DROP 根或未登记时，回退到同位基础子图 2501–2510 / 4501–4510
_SHIP_BASE_SUBMAP_SLOT_MAX = 10
TIER_REF_NEST: Dict[int, int] = {
    101: 2001,
    102: 2011,
    103: 2021,
    104: 2031,
    105: 2041,
    106: 2051,
}


def normalize_map_id(map_id: Optional[int]) -> Optional[int]:
    """将游戏日志里的等价 MapCid 归一到权重表使用的地图 ID。"""
    if map_id is None:
        return None
    # 先尝试 −2000（44xx→24xx、45xx→25xx、含 4511→2511），以便 MAP 中同时登记
    # 日志 MapId 与表内 ID 时，仍归一到 HTML/先验里使用的较小号。
    minus2k = map_id - 2000
    if minus2k in MAP_TO_TIER_NEST:
        return minus2k
    if map_id in MAP_TO_TIER_NEST:
        return map_id
    fallback = ship_series_weight_fallback_map_id(map_id)
    if fallback is not None:
        return fallback
    return map_id


def ship_series_weight_fallback_map_id(map_id: int) -> Optional[int]:
    """
    25xx/45xx 非基础子图（末两位 11+，含 2511–2520 / 2521–2530 / 253x / 453x 等）
    在 DROP 未配置或未登记时，回退到同位基础子图 2501–2510（45xx 经 normalize 亦为 25xx 同位）。

    映射：末两位 slot → ((slot - 1) % 10) + 1，例如 2515→2505、2525→2505、2535→2505。
    """
    band = map_id // 100
    slot = map_id % 100
    if band not in (25, 45) or slot <= _SHIP_BASE_SUBMAP_SLOT_MAX:
        return None
    base_slot = ((slot - 1) % 10) + 1
    base = band * 100 + base_slot
    if base not in MAP_TO_TIER_NEST:
        return None
    return normalize_map_id(base) or base


def _nest_drop_root_available(map_id: int) -> bool:
    entry = MAP_TO_TIER_NEST.get(map_id)
    if not entry:
        return False
    nest = entry[1]
    return bool(_DROP_GRAPH.get(nest))


def map_id_for_drop_weights(map_id: Optional[int]) -> Optional[int]:
    """
    解析用于掉落图递归的地图 ID：先 normalize，再校验巢根是否在 DROP 图中；
    25xx/45xx 非基础子图缺表或巢根不可用时回退 2501–2510 / 4501–4510 同位。
    """
    mid = normalize_map_id(map_id)
    if mid is None:
        return None
    if mid in MAP_TO_TIER_NEST and _nest_drop_root_available(mid):
        return mid
    fallback = ship_series_weight_fallback_map_id(mid)
    if fallback is not None and fallback in MAP_TO_TIER_NEST:
        return fallback
    return mid if mid in MAP_TO_TIER_NEST else None


def map_tier_nest_for_weights(map_id: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    """返回 (tier, nest_drop_id)，供地图权重与巢品质倍率使用。"""
    mid = map_id_for_drop_weights(map_id)
    if mid is None or mid not in MAP_TO_TIER_NEST:
        return None, None
    tier, nest = MAP_TO_TIER_NEST[mid]
    return tier, nest


def map_bundle_key_for_automation(map_id: int) -> str:
    """
    游戏 ``MapId`` 对应到 ``automation.maps`` / ``pricing.maps`` / 门票表的**档键**（三位：XY0）。

    同档多子图（如 2301~2310）共享一档：取十进制字符串**前两位**再补 ``0``，
    例如 ``2306`` / ``2310`` → ``\"230\"``；若截取前三位会把 ``2310`` 误成 ``231``。
    """
    s = str(int(map_id))
    if len(s) >= 3:
        return s[:2] + "0"
    return s


def load_csv(path: str) -> Tuple[Dict[int, CsvItem], List[CsvItem]]:
    """
    解析 item_prices.csv，返回两种索引结构：

    返回值:
        index : item_id -> CsvItem  字典，用于精确 ID 查找
        items : CsvItem 列表，用于按条件过滤查找

    CSV 必须包含列: item_id, name, category_tags, shape, quality, base_value
    """
    global _KNOWN_ITEM_IDS, _ITEM_CATEGORY_TAGS

    index: Dict[int, CsvItem] = {}
    items: List[CsvItem] = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                tags_raw = row['category_tags'].strip()
                if not tags_raw.startswith('['):
                    tags_raw = f'[{tags_raw}]'
                tags: List[int] = json.loads(tags_raw)
                item = CsvItem(
                    item_id=int(row['item_id']),
                    name=row['name'],
                    category_tags=tags,
                    shape=int(row['shape']),
                    quality=int(row['quality']),
                    base_value=int(row['base_value']),
                )
                index[item.item_id] = item
                items.append(item)
            except Exception:
                continue
    _KNOWN_ITEM_IDS = set(index)
    _ITEM_CATEGORY_TAGS = {
        item_id: item.category_tags
        for item_id, item in index.items()
    }
    base_dir = os.path.dirname(path) or "."
    load_weight_data(base_dir)
    load_map_prior_data(os.path.join(base_dir, MAP_PRIOR_HTML))
    return index, items


def load_weight_data(base_dir: str) -> Dict[int, List[Tuple[int, int, int]]]:
    """
    优先读取 HTML 工具使用的合并 CSV；不存在时回退到旧的简化权重表。

    calculator_data_merged.csv 里包含完整 DROP 图（含 MapCid/子图根），能让地图递归权重生效；
    drop_table_weights.csv 只有类别+品质直连物品池，作为兼容后备。
    """
    merged_path = os.path.join(base_dir, MERGED_DATA_CSV)
    if os.path.exists(merged_path):
        return load_drop_weights(merged_path)
    return load_drop_weights(os.path.join(base_dir, DROP_WEIGHTS_CSV))


def load_drop_weights(path: str) -> Dict[int, List[Tuple[int, int, int]]]:
    """
    解析掉落权重表，返回 item_id -> [(category, quality, weight), ...]。

    兼容两种格式：
      - calculator_data_merged.csv: record_type=DROP 的完整掉落图
      - drop_table_weights.csv: 只有 drop_id/ref_id/weight/ref_type 的简化表

    drop_id 前三位通常是类别，第四位是品质；ref_id 可能是物品 ID，也可能是下级 drop_id。
    HTML 工具里对 ref_type 不做硬过滤，而是按"ref_id 若存在物品则算物品，否则可递归展开"。
    """
    global _DROP_GRAPH, _DROP_RESOLVED_CACHE, _DROP_WEIGHT_BY_ITEM

    weights: Dict[int, List[Tuple[int, int, int]]] = {}
    graph: Dict[int, List[Tuple[int, float]]] = {}
    if not os.path.exists(path):
        _DROP_WEIGHT_BY_ITEM = weights
        _DROP_GRAPH = graph
        _DROP_RESOLVED_CACHE = {}
        return weights

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            record_type = (row.get('record_type') or 'DROP').upper()
            if record_type != 'DROP':
                continue
            try:
                drop_id = int(row['drop_id'])
                category = drop_id // 10
                quality = drop_id % 10
                ref_id = int(row['ref_id'])
                weight = int(row['weight'])
            except (KeyError, TypeError, ValueError):
                continue
            if weight <= 0:
                continue
            graph.setdefault(drop_id, []).append((ref_id, float(weight)))
            weights.setdefault(ref_id, []).append((category, quality, weight))

    _DROP_WEIGHT_BY_ITEM = weights
    _DROP_GRAPH = graph
    _DROP_RESOLVED_CACHE = {}
    return weights


def load_map_prior_data(path: str) -> None:
    """从 HTML 工具中读取子图品质巢权重和子图池化倍率；缺失时自动回退为 1。"""
    global _NEST_WEIGHTS, _SUBMAP_PRIOR_MULT

    if not os.path.exists(path):
        _NEST_WEIGHTS = {}
        _SUBMAP_PRIOR_MULT = {}
        return

    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
        nest_match = re.search(r"const\s+NEST_W\s*=\s*(\{.*?\});", text, re.S)
        mult_match = re.search(
            r"const\s+SUBMAP_PRIOR_MULT\s*=\s*(\{.*?\});\s*const\s+SUBMAPS_BY_TIER",
            text,
            re.S,
        )
        nest_raw = json.loads(nest_match.group(1)) if nest_match else {}
        mult_raw = json.loads(mult_match.group(1)) if mult_match else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        _NEST_WEIGHTS = {}
        _SUBMAP_PRIOR_MULT = {}
        return

    _NEST_WEIGHTS = {int(k): [float(x) for x in v] for k, v in nest_raw.items()}
    _SUBMAP_PRIOR_MULT = {
        int(tier): {
            int(map_id): {int(item_id): float(mult) for item_id, mult in item_map.items()}
            for map_id, item_map in maps.items()
        }
        for tier, maps in mult_raw.items()
    }


def _resolve_drop_to_items(
    drop_id: Optional[int],
    item_ids: Set[int],
) -> Dict[int, float]:
    """按 HTML 的 resolveDropToItems 逻辑递归展开 drop 图，并归一化到物品份额。"""
    if drop_id is None or not _DROP_GRAPH:
        return {}

    cache_key = (drop_id, tuple(sorted(item_ids)))
    if cache_key in _DROP_RESOLVED_CACHE:
        return _DROP_RESOLVED_CACHE[cache_key]

    out: Dict[int, float] = {}

    def dfs(cur_drop_id: int, scale: float, path_seen: Set[int]) -> None:
        edges = _DROP_GRAPH.get(cur_drop_id, [])
        total = sum(weight for _ref_id, weight in edges)
        if total <= 0:
            return
        for ref_id, weight in edges:
            child_scale = scale * (weight / total)
            if ref_id in _KNOWN_ITEM_IDS:
                if ref_id in item_ids:
                    out[ref_id] = out.get(ref_id, 0.0) + child_scale
            elif ref_id in _DROP_GRAPH and ref_id not in path_seen:
                path_seen.add(ref_id)
                dfs(ref_id, child_scale, path_seen)
                path_seen.remove(ref_id)

    dfs(drop_id, 1.0, {drop_id})
    total_out = sum(out.values())
    if total_out > 0:
        out = {item_id: weight / total_out for item_id, weight in out.items()}
    _DROP_RESOLVED_CACHE[cache_key] = out
    return out


def _nest_quality_multiplier(map_id: Optional[int], quality: int) -> float:
    """子图品质巢权重：当前子图 NEST 期望价 / 当前档参考 NEST 期望价。"""
    tier, nest = map_tier_nest_for_weights(map_id)
    if tier is None or nest is None:
        return 1.0
    ref_nest = TIER_REF_NEST.get(tier)
    cur_weights = _NEST_WEIGHTS.get(nest)
    ref_weights = _NEST_WEIGHTS.get(ref_nest) if ref_nest is not None else None
    idx = max(0, min(5, quality - 1))
    if not cur_weights or not ref_weights or idx >= len(cur_weights) or idx >= len(ref_weights):
        return 1.0
    ref_value = ref_weights[idx]
    if ref_value <= 0:
        return 1.0
    return cur_weights[idx] / ref_value


def _submap_pool_multiplier(map_id: Optional[int], item_id: int) -> float:
    """子图池化倍率：HTML 内 SUBMAP_PRIOR_MULT 中预计算的物品倍率。"""
    map_id = normalize_map_id(map_id)
    if map_id is None or map_id not in MAP_TO_TIER_NEST:
        return 1.0
    tier, _nest = MAP_TO_TIER_NEST[map_id]
    mult = _SUBMAP_PRIOR_MULT.get(tier, {}).get(map_id, {}).get(item_id)
    if mult is None or mult <= 0:
        return 1.0
    return mult


def _candidate_weight(
    item: CsvItem,
    map_category_weights: Optional[Dict[int, float]] = None,
    map_id: Optional[int] = None,
    map_drop_weights: Optional[Dict[int, float]] = None,
) -> float:
    """计算单个候选的有效出现权重；地图类别权重入口默认全为 1。"""
    category_weights = map_category_weights or DEFAULT_MAP_CATEGORY_WEIGHTS

    if map_drop_weights:
        # 完整地图 drop 图已经包含品质比例和物品池概率，不能再叠乘叶子池权重。
        base = map_drop_weights.get(item.item_id, 0.0)
        if base <= 0:
            return 0.0
        category_mult = max(
            (category_weights.get(category, 1.0) for category in item.category_tags),
            default=1.0,
        )
        return base * category_mult

    rows = _DROP_WEIGHT_BY_ITEM.get(item.item_id, [])
    total = 0.0
    for category, quality, weight in rows:
        if quality != item.quality or category not in item.category_tags:
            continue
        total += weight * category_weights.get(category, 1.0)

    base = total if total > 0 else 1.0
    return (
        base
        * _nest_quality_multiplier(map_id, item.quality)
        * _submap_pool_multiplier(map_id, item.item_id)
    )


def weighted_est_max_item_base_value(
    shape: Optional[int],
    *,
    quality: Optional[int] = None,
) -> float:
    """多候选权重期望价用的单价上限。

    - 已确认 1×1（``shape==11``）与轮廓未知红（``shape is None`` 且 ``quality==6``）
      使用 :data:`WEIGHTED_EST_MAX_1X1_ITEM_BASE_VALUE`（10 万），削弱天价品对期望价的影响。
    """
    if shape == 11:
        return WEIGHTED_EST_MAX_1X1_ITEM_BASE_VALUE
    if shape is None and quality == 6:
        return WEIGHTED_EST_MAX_1X1_ITEM_BASE_VALUE
    return WEIGHTED_EST_MAX_ITEM_BASE_VALUE


def weighted_percentile(
    pairs: List[Tuple[float, float]],
    quantile: float,
) -> Optional[float]:
    """按权重 ``pairs=(value, weight)`` 求分位；``quantile`` 为 0.25 / 0.5 等。"""
    if not pairs:
        return None
    try:
        q = float(quantile)
    except (TypeError, ValueError):
        return None
    if q <= 0.0 or q > 1.0:
        return None
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    target = q * total
    cum = 0.0
    for val, w in sorted(pairs, key=lambda x: x[0]):
        cum += w
        if cum >= target - 1e-15:
            return val
    return pairs[-1][0]


def _weighted_est_price(
    candidates: List[CsvItem],
    map_category_weights: Optional[Dict[int, float]] = None,
    map_id: Optional[int] = None,
    *,
    max_item_base_value: Optional[float] = None,
    quantile: Optional[float] = None,
) -> Optional[float]:
    """按掉落权重计算候选集合的期望价格。

    仅用于期望单价：``base_value`` 大于 ``max_item_base_value``（默认
    :data:`WEIGHTED_EST_MAX_ITEM_BASE_VALUE`）的候选不计入加权和（权重在剩余候选上自然重归一）；
    若全部高于阈值则退回全体候选，以免无可用子集。地图 drop 解析仍基于完整 ``candidates`` 的 item_id 集合。
    """
    map_id_norm = normalize_map_id(map_id)
    _tier, map_drop_id = map_tier_nest_for_weights(map_id)
    map_drop_weights = _resolve_drop_to_items(
        map_drop_id,
        {item.item_id for item in candidates},
    )
    cap = (
        float(max_item_base_value)
        if max_item_base_value is not None
        else WEIGHTED_EST_MAX_ITEM_BASE_VALUE
    )
    priced = [c for c in candidates if float(c.base_value) <= cap]
    est_pool = priced if priced else candidates
    pairs: List[Tuple[float, float]] = []
    for item in est_pool:
        weight = _candidate_weight(
            item, map_category_weights, map_id_norm, map_drop_weights
        )
        pairs.append((float(item.base_value), float(weight)))
    weight_sum = sum(w for _, w in pairs)
    if weight_sum <= 0 and map_drop_weights:
        # 地图根图没有覆盖当前候选集合时，退回全局/旧权重，避免全 0。
        return _weighted_est_price(
            candidates,
            map_category_weights,
            None,
            max_item_base_value=cap,
            quantile=quantile,
        )
    if weight_sum <= 0:
        return None
    if quantile is None:
        weighted_sum = sum(v * w for v, w in pairs)
        return weighted_sum / weight_sum
    return weighted_percentile(pairs, quantile)


def candidate_probabilities(
    candidates: List[CsvItem],
    map_category_weights: Optional[Dict[int, float]] = None,
    map_id: Optional[int] = None,
) -> Dict[int, float]:
    """返回候选物品在当前约束集合内的归一化出现概率。"""
    if not candidates:
        return {}
    if len(candidates) == 1:
        return {candidates[0].item_id: 1.0}

    map_id_norm = normalize_map_id(map_id)
    _tier, map_drop_id = map_tier_nest_for_weights(map_id)
    map_drop_weights = _resolve_drop_to_items(
        map_drop_id,
        {item.item_id for item in candidates},
    )
    weights = {
        item.item_id: _candidate_weight(
            item, map_category_weights, map_id_norm, map_drop_weights
        )
        for item in candidates
    }
    total = sum(weights.values())

    if total <= 0 and map_drop_weights:
        return candidate_probabilities(candidates, map_category_weights, None)
    if total <= 0:
        equal = 1.0 / len(candidates)
        return {item.item_id: equal for item in candidates}
    return {item_id: weight / total for item_id, weight in weights.items()}


def probability_source_label(candidates: List[CsvItem], map_id: Optional[int] = None) -> str:
    """说明候选概率当前使用的是地图递归权重还是全局回退权重。"""
    original_map_id = map_id
    map_id_norm = normalize_map_id(map_id)
    weight_map_id = map_id_for_drop_weights(map_id)
    if weight_map_id is None or weight_map_id not in MAP_TO_TIER_NEST:
        return "全局权重"
    map_drop_id = MAP_TO_TIER_NEST[weight_map_id][1]
    resolved = _resolve_drop_to_items(map_drop_id, {item.item_id for item in candidates})
    if resolved:
        parts = [str(p) for p in (original_map_id, map_id_norm, weight_map_id) if p is not None]
        deduped: List[str] = []
        for p in parts:
            if not deduped or deduped[-1] != p:
                deduped.append(p)
        chain = "->".join(deduped + [str(map_drop_id)])
        return f"地图权重 {chain}"
    return f"全局权重（地图 {original_map_id}->{map_id_norm}->{map_drop_id} 未覆盖候选）"


def map_category_ratios(map_id: Optional[int]) -> Dict[int, float]:
    """返回地图根 drop 的类别占比（category -> ratio），会自动归一化 map_id。"""
    _tier, map_drop_id = map_tier_nest_for_weights(map_id)
    if map_drop_id is None:
        return {}
    totals: Dict[int, float] = {}

    def dfs(cur_drop_id: int, scale: float, path_seen: Set[int]) -> None:
        edges = _DROP_GRAPH.get(cur_drop_id, [])
        total = sum(weight for _ref_id, weight in edges if weight > 0)
        if total <= 0:
            return
        for ref_id, weight in edges:
            if weight <= 0:
                continue
            child_scale = scale * (weight / total)
            category = ref_id // 10
            quality = ref_id % 10
            # 类别池节点通常是 1011~1106（category*10 + quality）。
            if 101 <= category <= 110 and 1 <= quality <= 6:
                totals[category] = totals.get(category, 0.0) + child_scale
                continue
            # 新地图 2601 会经由通用品质池 1201~1206 直接落到物品。
            # 这类链路没有类别池节点，需要按物品自身类别回填地图类别占比。
            if ref_id in _KNOWN_ITEM_IDS:
                tags = [
                    tag for tag in _ITEM_CATEGORY_TAGS.get(ref_id, [])
                    if 101 <= tag <= 110
                ]
                if tags:
                    tag_scale = child_scale / len(tags)
                    for tag in tags:
                        totals[tag] = totals.get(tag, 0.0) + tag_scale
                continue
            if ref_id in _DROP_GRAPH and ref_id not in path_seen:
                path_seen.add(ref_id)
                dfs(ref_id, child_scale, path_seen)
                path_seen.remove(ref_id)

    dfs(map_drop_id, 1.0, {map_drop_id})
    total_weight = sum(totals.values())
    if total_weight <= 0:
        return {}
    return {
        category: weight / total_weight
        for category, weight in totals.items()
    }


def filter_csv_candidates_for_query(
    shape: Optional[int],
    quality: Optional[int],
    categories: Set[int],
    item_cid: Optional[int],
    csv_index: Dict[int, CsvItem],
    csv_items: List[CsvItem],
    excluded_categories: Optional[Set[int]] = None,
    excluded_qualities: Optional[Set[int]] = None,
    max_shape_wh: Optional[Tuple[int, int]] = None,
    categories_any: Optional[Set[int]] = None,
) -> List[CsvItem]:
    """
    与 :func:`query_item` 相同的过滤顺序，返回候选列表（不计算期望价）。
    ``item_cid`` 命中 CSV 时仅返回该单行。
    """
    if item_cid and item_cid in csv_index:
        return [csv_index[item_cid]]

    candidates = list(csv_items)

    if shape is not None:
        candidates = [i for i in candidates if i.shape == shape]
    elif max_shape_wh is not None:
        max_w, max_h = max_shape_wh

        def _fits(s: int) -> bool:
            ss = str(s)
            if len(ss) == 2:
                return int(ss[0]) <= max_w and int(ss[1]) <= max_h
            return False

        candidates = [i for i in candidates if _fits(i.shape)]

    if quality is not None:
        candidates = [i for i in candidates if i.quality == quality]

    if excluded_qualities:
        candidates = [i for i in candidates if i.quality not in excluded_qualities]

    if categories:
        with_cat = [i for i in candidates if all(c in i.category_tags for c in categories)]
        if with_cat:
            candidates = with_cat

    if categories_any:
        ca = set(categories_any)
        with_any = [i for i in candidates if ca.intersection(i.category_tags)]
        if with_any:
            candidates = with_any

    if excluded_categories:
        candidates = [
            i for i in candidates
            if not any(c in excluded_categories for c in i.category_tags)
        ]

    return candidates


def query_item(
    shape: Optional[int],
    quality: Optional[int],
    categories: Set[int],
    item_cid: Optional[int],
    csv_index: Dict[int, CsvItem],
    csv_items: List[CsvItem],
    excluded_categories: Optional[Set[int]] = None,
    excluded_qualities: Optional[Set[int]] = None,
    max_shape_wh: Optional[Tuple[int, int]] = None,
    map_category_weights: Optional[Dict[int, float]] = None,
    map_id: Optional[int] = None,
    categories_any: Optional[Set[int]] = None,
) -> Tuple[Optional[CsvItem], int, bool, Optional[float], str]:
    """
    根据已知约束查询物品候选，返回最佳匹配及统计信息。

    Args:
        shape               : ItemSlotType，如 11=1×1（None=未知）
        quality             : 品质 1~6（None=未知）
        categories          : 已知类别 tag 集合（空=未知）；CSV 上须**同时**含于 ``category_tags``（AND）
        categories_any      : 英雄技能 OR 类别约束（空=忽略）；候选须与集合**至少有一个** tag 相交
        item_cid            : 精确 ItemCid（None=未知）
        csv_index           : load_csv() 返回的 ID 索引
        csv_items           : load_csv() 返回的全量列表
        excluded_categories : 负向约束——确定不属于这些类别的 tag 集合
        excluded_qualities  : 负向约束——确定不是这些品质的品质值集合
        max_shape_wh        : (max_w, max_h) 推断的最大允许尺寸（shape=None 时生效）
        map_category_weights: 地图类别权重倍率入口，默认所有类别为 1.0
        map_id              : MapCid，用于叠加子图品质巢权重与子图池化倍率

    返回值:
        (best, count, unique, est_price, price_label)
        best        : 价格最高的候选 CsvItem，无候选时为 None
        count       : 候选总数
        unique      : 是否唯一确定（count == 1 或精确命中）
        est_price   : 估算价格（唯一确定时为 None）
        price_label : 估算方式说明，如 "权重价"

    过滤顺序（优先级依次降低）：
        1. ItemCid 已知 → 精确查找，直接返回
        2. 按 shape 过滤（正向）；shape=None 且 max_shape_wh 非空时按最大允许尺寸过滤
        3. 按 quality 过滤（正向）
        4. 按 excluded_qualities 过滤（负向，排除确认不是的品质）
        5. 按 categories 过滤（正向，必须含全部已知类别 tag）
        6. 按 categories_any 过滤（正向 OR：``category_tags`` 与集合有交集）
        7. 按 excluded_categories 过滤（负向，排除含有已确认不属于类别的候选）
        8. 若类别正向过滤后为空，保留 shape+quality 结果（容错）

    估算规则（多候选时）：按 drop_table_weights.csv 中的掉落权重计算期望价；
    单价高于形状相关上限的候选不参与该期望（1×1 与轮廓未知红为
    :data:`WEIGHTED_EST_MAX_1X1_ITEM_BASE_VALUE` 即 10 万，其余为
    :data:`WEIGHTED_EST_MAX_ITEM_BASE_VALUE` 即 500 万），不改变候选列表；
    ItemCid 已指定或仅剩单候选时为精确价，不适用此截断。
    """
    if item_cid and item_cid in csv_index:
        return csv_index[item_cid], 1, True, None, ""

    candidates = filter_csv_candidates_for_query(
        shape,
        quality,
        categories,
        None,
        csv_index,
        csv_items,
        excluded_categories=excluded_categories,
        excluded_qualities=excluded_qualities,
        max_shape_wh=max_shape_wh,
        categories_any=categories_any,
    )

    if not candidates:
        return None, 0, False, None, ""

    best = max(candidates, key=lambda i: i.base_value)
    count = len(candidates)
    if count == 1:
        return best, 1, True, None, ""

    est = _weighted_est_price(
        candidates,
        map_category_weights,
        map_id,
        max_item_base_value=weighted_est_max_item_base_value(shape, quality=quality),
    )
    label = "权重价" if est is not None else ""

    return best, count, False, est, label
