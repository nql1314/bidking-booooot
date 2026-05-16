# -*- coding: utf-8 -*-
"""技能表导出的绑定：日志 SkillCid / ItemCid → ``event_stats`` 与 UI 用映射。

本模块为**显式快照表**：元组/字典由既有解析行为固化而来，按
:mod:`bidking.parsing.skill_export_generated` 的分组用注释分段，便于审阅。
**不再**根据 ``param_*`` 推导绑定；更新 ``Skill_export.csv`` 并重新生成
``skill_export_generated`` 后，若技能行增减或语义变化，须同步更新本文件中的字面量
（可用旧版推导逻辑或测试对比重新导出快照）。

:data:`HERO_SKILL_CATEGORY_TAGS_OR` 为英雄 ``SkillCid`` → 揭示物品类别 OR 集合的**显式快照**
（原由 ``param_07=0`` + ``param_09`` 纯类别列表推导）；供日志 ``HeroSkillLog`` 写入
``ItemKnowledge.categories_any``；与鉴影 ``SKILL_TO_CATEGORY`` 并存。
"""

from __future__ import annotations

import ast
import csv
from typing import Dict, List, Tuple

from .skill_export_generated import SKILL_EXPORT_BY_ID

# ItemCid → 日志合并用规范 SkillCid（鉴影等）；与 ``ITEM_TOOLS`` 首元一致，见文件末尾由表生成
_ITEM_SKILL_CANONICAL_SKILL_CID: Dict[int, int] = {
    100151: 2001,
    100152: 2002,
    100153: 2003,
    100154: 2004,
    100155: 2005,
    100156: 2006,
    100157: 2007,
    100158: 2008,
    100159: 2009,
    100160: 2010,
    100174: 801,
}

Tuple3I = Tuple[str, int, str]
Tuple3F = Tuple[str, int, str]

# ---------------------------------------------------------------------------
# 地图竞拍信息（param_07=1）：_skill_export_part_map_auction_board
# ---------------------------------------------------------------------------

# _registry_map_hidden_cell_scan_lines + _registry_map_hit_item_count_lines
_RAW_MAP_AUCTION_SKILL_INT: Tuple[Tuple3I, ...] = (
    ("total_grid_count", 200009, "TotalHitBoxIndex"),
    ("q4_grid_count", 200010, "TotalHitBoxIndex"),
    ("q5_grid_count", 200011, "TotalHitBoxIndex"),
    ("q6_grid_count", 200012, "TotalHitBoxIndex"),
    ("total_count", 200017, "HitItemIndex"),
    ("q4_count", 200018, "HitItemIndex"),
    ("q5_count", 200019, "HitItemIndex"),
    ("q6_count", 200020, "HitItemIndex"),
    ("q4_price_total", 503, "HitItemTotalPrice"),
    ("q5_price_total", 504, "HitItemTotalPrice"),
    ("q6_price_total", 505, "HitItemTotalPrice"),
)

# _registry_map_avg_cell_scan_lines
_RAW_MAP_AUCTION_SKILL_FLOAT: Tuple[Tuple3F, ...] = (
    ("q4_grid_avg", 200013, "AllHitItemAvgBoxIndex"),
    ("total_grid_avg", 200014, "AllHitItemAvgBoxIndex"),
    ("q5_grid_avg", 200015, "AllHitItemAvgBoxIndex"),
    ("q6_grid_avg", 200016, "AllHitItemAvgBoxIndex"),
    ("q4_price_avg", 200036, "AllHitItemAvgPrice"),
    ("q5_price_avg", 200037, "AllHitItemAvgPrice"),
    ("q6_price_avg", 200038, "AllHitItemAvgPrice"),
)

# ---------------------------------------------------------------------------
# 英雄携带技能（param_07=0）：_skill_export_part_hero_skills — 艾哈迈德等
# ---------------------------------------------------------------------------

#: 维克托 ``SkillCid=100209``：紫+金+红（品质 4/5/6）**合并件数**在 ``event_stats`` 中的专用键。
#: 与 ``q4_count`` / ``q5_count`` / ``q6_count``（分档件数）不同源，勿混用或相加对比。
VIKTOR_COMBINED_HIGH_TIER_ITEM_COUNT_KEY: str = "viktor_q456_item_count"

_RAW_HERO_SKILL_INT: Tuple[Tuple3I, ...] = (
    ("total_count", 100204, "HitItemIndex"),
    (VIKTOR_COMBINED_HIGH_TIER_ITEM_COUNT_KEY, 100209, "HitItemIndex"),
    ("q12_count", 1002044, "HitItemIndex"),
)

# param_16 [3000] → AllHitItemAvgBoxIndex；param_09 品质档与 event_stats 前缀一致
_RAW_HERO_SKILL_FLOAT: Tuple[Tuple3F, ...] = (
    ("q5_grid_avg", 1002041, "AllHitItemAvgBoxIndex"),
    ("q4_grid_avg", 1002042, "AllHitItemAvgBoxIndex"),
    ("q3_grid_avg", 1002043, "AllHitItemAvgBoxIndex"),
)

# ---------------------------------------------------------------------------
# 道具工具：技能行上以 SkillCid 直读（与 ItemCid 直读并存，见 skill_event_stats 写入顺序）
# _skill_export_part_item_hidden_cell_scan / hit_count_scan 默认不需要设置 除非遇到特殊的手动填
# ---------------------------------------------------------------------------

_RAW_ITEM_TOOL_SKILL_ROW_INT: Tuple[Tuple3I, ...] = (
)

_RAW_ITEM_TOOL_SKILL_ROW_FLOAT: Tuple[Tuple3F, ...] = (
)

# ---------------------------------------------------------------------------
# 道具工具：ItemSkillLog 以 ItemCid 直读 — _skill_export_part_item_* 并集
# ---------------------------------------------------------------------------

# _skill_export_part_item_hidden_cell_scan + item_hit_count_scan + item_price_total_scan
_RAW_ITEM_TOOL_ITEM_INT: Tuple[Tuple3I, ...] = (
    ("total_grid_count", 100103, "TotalHitBoxIndex"),
    ("q12_grid_count", 100104, "TotalHitBoxIndex"),
    ("q3_grid_count", 100105, "TotalHitBoxIndex"),
    ("q4_grid_count", 100106, "TotalHitBoxIndex"),
    ("q5_grid_count", 100107, "TotalHitBoxIndex"),
    ("q6_grid_count", 100108, "TotalHitBoxIndex"),
    ("total_count", 100115, "HitItemIndex"),
    ("q2_count", 100116, "HitItemIndex"),
    ("q3_count", 100117, "HitItemIndex"),
    ("q4_count", 100118, "HitItemIndex"),
    ("q5_count", 100119, "HitItemIndex"),
    ("q6_count", 100120, "HitItemIndex"),
    ("q12_price_total", 100122, "HitItemTotalPrice"),
    ("q3_price_total", 100123, "HitItemTotalPrice"),
    ("q4_price_total", 100124, "HitItemTotalPrice"),
    ("q5_price_total", 100125, "HitItemTotalPrice"),
    ("q6_price_total", 100126, "HitItemTotalPrice"),
)

_RAW_ITEM_TOOL_ITEM_FLOAT: Tuple[Tuple3F, ...] = (
    ("total_grid_avg", 100109, "AllHitItemAvgBoxIndex"),
    ("q12_grid_avg", 100110, "AllHitItemAvgBoxIndex"),
    ("q3_grid_avg", 100111, "AllHitItemAvgBoxIndex"),
    ("q4_grid_avg", 100112, "AllHitItemAvgBoxIndex"),
    ("q5_grid_avg", 100113, "AllHitItemAvgBoxIndex"),
    ("q6_grid_avg", 100114, "AllHitItemAvgBoxIndex"),
)

# ---------------------------------------------------------------------------
# 汇总：对外常量（顺序为 地图 int → 英雄 int → 道具技能行 int，与旧合并顺序一致）
# ---------------------------------------------------------------------------

RAW_PRICING_DIRECT_SKILL_INT_BINDINGS: Tuple[Tuple3I, ...] = (
    _RAW_MAP_AUCTION_SKILL_INT + _RAW_HERO_SKILL_INT + _RAW_ITEM_TOOL_SKILL_ROW_INT
)

# 须在 ``ItemSkillLog`` 整型直读之后应用的**通用**英雄整型覆盖（当前为空）。
# 玛丽亚 ``SkillCid=100108`` → ``event_stats["q123_price_total"]``；``10010801`` → ``q123_count``（``HitBoxList``）。
# 与道具 ``ItemCid=100108`` 同号键冲突，在 :mod:`bidking.analysis.skill_event_stats_from_logs` 中按 ``HeroCid`` 判别单独写入。
RAW_PRICING_INT_AFTER_ITEM_LOG: Tuple[Tuple3I, ...] = ()
RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS: Tuple[Tuple3F, ...] = (
    _RAW_MAP_AUCTION_SKILL_FLOAT + _RAW_HERO_SKILL_FLOAT + _RAW_ITEM_TOOL_SKILL_ROW_FLOAT
)
RAW_PRICING_DIRECT_ITEM_INT_BINDINGS: Tuple[Tuple3I, ...] = _RAW_ITEM_TOOL_ITEM_INT
RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS: Tuple[Tuple3F, ...] = _RAW_ITEM_TOOL_ITEM_FLOAT

OUTLINE_SKILL_QUALITY: Dict[int, int] = {
    200001: 4,
    200002: 5,
    200003: 6,
    1001031: 4,
    1001032: 3,
    1001033: 2,
    1001034: 1,
}

MAP_SKILL_FORCE_QUALITY: Dict[int, int] = {
    200001: 4,
    200002: 5,
    200003: 6,
}

HERO_SKILL_QUALITY: Dict[int, int] = {
    1001031: 4,
    1001032: 3,
    1001033: 2,
    1001034: 1,
}

HERO_SKILL_CID_MERGE_INTO_MAP: Dict[int, int] = {}

#: 英雄 ``SkillCid`` → 日志 ``HitBoxList`` 命中物品的类别 OR 集合（与 ``ItemKnowledge.categories_any`` 对齐）。
HERO_SKILL_CATEGORY_TAGS_OR: Dict[int, frozenset[int]] = {
    100101: frozenset({106}),
    100102: frozenset({105}),
    100105: frozenset({103}),
    100106: frozenset({103, 107}),
    100109: frozenset({102}),
    100201: frozenset({104}),
    100202: frozenset({101, 107}),
    100203: frozenset({109}),
    100205: frozenset({104, 108}),
    100206: frozenset({110}),
    100207: frozenset({106}),
    1001011: frozenset({106}),
    1001012: frozenset({106}),
    1001013: frozenset({106}),
    1001014: frozenset({106}),
    1001061: frozenset({103, 107}),
    1001091: frozenset({102}),
    1001092: frozenset({102}),
    1001093: frozenset({102}),
    1001094: frozenset({102}),
    1001101: frozenset({105}),
    1002021: frozenset({101, 107}),
    1002022: frozenset({101, 107}),
    1002023: frozenset({101, 107}),
    1002024: frozenset({101, 107}),
    1002061: frozenset({110}),
    1002062: frozenset({110}),
    1002063: frozenset({110}),
    1002064: frozenset({110}),
    1002065: frozenset({110}),
    10002031: frozenset({106}),
    10002071: frozenset({106}),
    10002072: frozenset({106}),
    10002073: frozenset({106}),
}

ITEM_SKILL_CANONICAL_SKILL_CID: Dict[int, int] = dict(_ITEM_SKILL_CANONICAL_SKILL_CID)

# 地图竞拍 skill_id 200001–200052（与 skill_export_generated._skill_export_part_map_auction_board 一致）
_MAP_AUCTION_BOARD_SKILL_IDS: Tuple[int, ...] = tuple(range(200001, 200053))

MAP_SKILL_DESC: Dict[int, str] = {
    sid: SKILL_EXPORT_BY_ID[sid].name_zh for sid in _MAP_AUCTION_BOARD_SKILL_IDS
}

# 道具工具 itemName_* 行：ItemCid → 对应 skill_id（显式表，无 param 分支）
_ITEM_TOOL_ITEM_CID_TO_SKILL_ID: Tuple[Tuple[int, int], ...] = (
    (100100, 100),
    (100101, 103),
    (100102, 106),
    (100103, 200),
    (100104, 201),
    (100105, 202),
    (100106, 203),
    (100107, 204),
    (100108, 205),
    (100109, 300),
    (100110, 301),
    (100111, 302),
    (100112, 303),
    (100113, 304),
    (100114, 305),
    (100115, 400),
    (100116, 401),
    (100117, 402),
    (100118, 403),
    (100119, 404),
    (100120, 405),
    (100121, 500),
    (100122, 501),
    (100123, 502),
    (100124, 503),
    (100125, 504),
    (100126, 505),
    (100127, 600),
    (100128, 601),
    (100129, 602),
    (100130, 603),
    (100131, 604),
    (100132, 605),
    (100133, 606),
    (100134, 700),
    (100135, 701),
    (100136, 702),
    (100137, 703),
    (100138, 704),
    (100139, 705),
    (100140, 706),
    (100151, 2001),
    (100152, 2002),
    (100153, 2003),
    (100154, 2004),
    (100155, 2005),
    (100156, 2006),
    (100157, 2007),
    (100158, 2008),
    (100159, 2009),
    (100160, 2010),
    (100161, 10000),
    (100162, 10001),
    (100163, 10002),
    (100164, 10003),
    (100165, 10010),
    (100166, 10011),
    (100167, 10012),
    (100168, 10013),
    (100169, 10014),
    (100170, 10015),
    (100171, 10016),
    (100172, 10017),
    (100173, 10018),
    (100174, 801),
)

ITEM_SKILL_DESC: Dict[int, str] = {
    iid: SKILL_EXPORT_BY_ID[sid].name_zh for iid, sid in _ITEM_TOOL_ITEM_CID_TO_SKILL_ID
}

ITEM_SKILL_EVENT_STATS: Dict[int, Tuple[str, ...]] = {
    100100: (),
    100101: (),
    100102: (),
    100103: ("total_grid_count",),
    100104: ("q12_grid_count",),
    100105: ("q3_grid_count",),
    100106: ("q4_grid_count",),
    100107: ("q5_grid_count",),
    100108: ("q6_grid_count",),
    100109: ("total_grid_avg",),
    100110: ("q12_grid_avg",),
    100111: ("q3_grid_avg",),
    100112: ("q4_grid_avg",),
    100113: ("q5_grid_avg",),
    100114: ("q6_grid_avg",),
    100115: ("total_count",),
    100116: ("q2_count",),
    100117: ("q3_count",),
    100118: ("q4_count",),
    100119: ("q5_count",),
    100120: ("q6_count",),
    100121: (),
    100122: ("q12_price_total",),
    100123: ("q3_price_total",),
    100124: ("q4_price_total",),
    100125: ("q5_price_total",),
    100126: ("q6_price_total",),
    100127: (),
    100128: (),
    100129: (),
    100130: (),
    100131: (),
    100132: (),
    100133: (),
    100134: (),
    100135: (),
    100136: (),
    100137: (),
    100138: (),
    100139: (),
    100140: (),
    100151: (),
    100152: (),
    100153: (),
    100154: (),
    100155: (),
    100156: (),
    100157: (),
    100158: (),
    100159: (),
    100160: (),
    100161: (),
    100162: (),
    100163: (),
    100164: (),
    100165: (),
    100166: (),
    100167: (),
    100168: (),
    100169: (),
    100170: (),
    100171: (),
    100172: (),
    100173: (),
    100174: (),
}


def _first_category_tag_from_skill_export(skill_id: int) -> int | None:
    """从技能表 ``param_09``（如 ``'[101]'``）取首个类别 tag，供鉴影负向 scan。"""
    row = SKILL_EXPORT_BY_ID.get(int(skill_id))
    if row is None:
        return None
    raw = (row.param_09 or "").strip()
    if not raw:
        return None
    try:
        val = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None
    if isinstance(val, (list, tuple)) and val:
        try:
            return int(val[0])
        except (TypeError, ValueError):
            return None
    return None


def _build_item_tools_for_category_scan() -> Dict[int, Tuple[int, str, int]]:
    """ItemCid → (SkillCid, 中文名, 类别 tag)；与 :mod:`.processors` 负向 ``record_scan('category', ...)`` 对齐。"""
    out: Dict[int, Tuple[int, str, int]] = {}
    for item_cid, skill_cid in _ITEM_SKILL_CANONICAL_SKILL_CID.items():
        tag = _first_category_tag_from_skill_export(skill_cid)
        if tag is None:
            continue
        name_zh = ITEM_SKILL_DESC.get(int(item_cid), "")
        out[int(item_cid)] = (int(skill_cid), name_zh, int(tag))
    return out


#: 鉴影类道具（仅含在 ``_ITEM_SKILL_CANONICAL_SKILL_CID`` 且技能表 ``param_09`` 可解析出 tag 的项）
ITEM_TOOLS: Dict[int, Tuple[int, str, int]] = _build_item_tools_for_category_scan()
#: ``SkillCid`` → 揭示的类别 tag（由 ``ITEM_TOOLS`` 反向索引）
SKILL_TO_CATEGORY: Dict[int, int] = {t[0]: t[2] for t in ITEM_TOOLS.values()}

MAP_SKILL_RANDOM3_AVG_PRICE: int = 200031
MAP_SKILL_RANDOM6_AVG_PRICE: int = 200032
MAP_SKILL_RANDOM9_AVG_PRICE: int = 200033
MAP_SKILL_RANDOM12_AVG_PRICE: int = 200034


def validate_skill_registry_vs_csv(csv_path: str) -> List[str]:
    """校验 CSV 与 :mod:`skill_export_generated` 中 ``param_16`` 等列一致。"""
    errs: List[str] = []
    path = csv_path
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sid = (row.get("skill_id") or "").strip()
            if not sid or not sid.isdigit():
                continue
            exp16 = (row.get("param_16") or "").strip()
            got = SKILL_EXPORT_BY_ID.get(int(sid))
            if got is None:
                errs.append(f"skill_id={sid}: CSV 有行但 skill_export_generated 缺失")
                continue
            if (got.param_16 or "").strip() != exp16:
                errs.append(
                    f"skill_id={sid}: param_16 不一致 CSV={exp16!r} generated={(got.param_16 or '').strip()!r}"
                )
    return errs
