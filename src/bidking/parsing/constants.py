# -*- coding: utf-8 -*-
"""
常量与映射表

包含所有游戏内固定数据（技能ID、类别ID、地图技能描述等），
以及若干格式化工具函数。
"""

import os
import sys
from typing import Dict, Set, Tuple

# ─── 路径默认值 ────────────────────────────────────────────────────────────

def resource_path(relative_path: str) -> str:
    """返回 ``data/<relative_path>`` 的绝对路径。

    优先级：
      1. PyInstaller ``sys._MEIPASS`` 下 ``data/`` 子目录（打进 onefile 包内的资源）
      2. 冻结程序：与 ``sys.executable`` 同目录的 ``data/``（常见「exe 与 data 同级」分发）
      3. 项目根 ``data/``（由 :func:`bidking.config.paths.data_dir` 解析）
      4. 兜底当前工作目录下的 ``data/``
    """
    base = getattr(sys, '_MEIPASS', None)
    if base:
        candidate = os.path.join(base, "data", relative_path)
        if os.path.exists(candidate):
            return candidate
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate = os.path.join(exe_dir, "data", relative_path)
        if os.path.isfile(candidate):
            return candidate
    try:
        from bidking.config.paths import data_dir
        return str(data_dir() / relative_path)
    except Exception:
        return os.path.join(os.getcwd(), "data", relative_path)


def default_game_log_path() -> str:
    """根据当前 Windows 用户动态定位 BidKing 的 Player.log。"""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        appdata_dir = os.path.dirname(local_appdata)
        return os.path.join(appdata_dir, "LocalLow", "laolin", "BidKing", "Player.log")
    else:
        user_dir = os.path.expanduser("~")
        return os.path.join(user_dir, "AppData", "LocalLow", "laolin", "BidKing", "Player.log")


DEFAULT_GAME_LOG = default_game_log_path()
LOCAL_LOG = "Player.log"
LOCAL_COPY_LOG = "Player - 副本.log"
CSV_PATH = resource_path("item_prices.csv")

# ─── 英雄 CID → 中文名（与 ``Skill_export.csv`` 主技能 ``name_zh`` 一致；键升序）────────────────

HERO_ID: Dict[int, str] = {
    101: "法蒂玛",
    102: "陈美",
    103: "艾莎",
    104: "加布里埃拉",
    105: "塔蒂安娜",
    106: "娜奥米",
    107: "索菲",
    108: "玛丽亚",
    109: "海琳娜",
    110: "伊莎贝拉",
    201: "乔治",
    202: "卡洛斯",
    203: "莱昂纳德",
    204: "艾哈迈德",
    205: "伊万",
    206: "武田宏志",
    207: "吴起灵",
    208: "伊森",
    209: "维克托",
    301: "拉文",
}

# ─── 类别映射 ──────────────────────────────────────────────────────────────

# 类别 tag → 中文名
CATEGORY_NAMES: Dict[int, str] = {
    101: "家具物品", 102: "医疗药品", 103: "时尚潮流", 104: "兵装军火",
    105: "珠宝矿藏", 106: "文物古董", 107: "数码娱乐", 108: "能源交通",
    109: "食饮珍馐", 110: "书画古籍",
}

# 技能日志「价」侧绑定、地图 SkillCid、轮廓表、英雄/道具合并边：见 :mod:`bidking.parsing.skill_bindings`。

# ─── 自 skill_bindings 再导出（供 ``raw_pricing`` 等 ``from .constants import *``）────────
from .skill_bindings import (  # noqa: E402
    HERO_SKILL_CID_MERGE_INTO_MAP,
    HERO_SKILL_QUALITY,
    ITEM_SKILL_CANONICAL_SKILL_CID,
    ITEM_SKILL_DESC,
    ITEM_SKILL_EVENT_STATS,
    ITEM_TOOLS,
    MAP_SKILL_DESC,
    MAP_SKILL_FORCE_QUALITY,
    OUTLINE_SKILL_QUALITY,
    RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS,
    RAW_PRICING_DIRECT_ITEM_INT_BINDINGS,
    RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS,
    RAW_PRICING_DIRECT_SKILL_INT_BINDINGS,
    SKILL_LOG_PRICE_AVG_BINDINGS,
    SKILL_LOG_PRICE_TOTAL_BINDINGS,
    SKILL_TO_CATEGORY,
)

# ─── 输出分隔符 ────────────────────────────────────────────────────────────

SEP  = "=" * 64
THIN = "-" * 64

# ─── 格式化工具函数 ────────────────────────────────────────────────────────

def fmt_shape(slot_type: int) -> str:
    """将 ItemSlotType 整数转为可读形状字符串，如 11→1x1, 22→2x2, 12→1x2。"""
    s = str(slot_type)
    if len(s) == 2:
        return f"{s[0]}x{s[1]}"
    return str(slot_type)


def fmt_categories(cats: Set[int]) -> str:
    """将类别 tag 集合转为中文名字符串，如 {101, 103} → '家具物品/时尚潮流'。"""
    return "/".join(CATEGORY_NAMES.get(c, str(c)) for c in sorted(cats))


def fmt_price(v: int) -> str:
    """整数价格格式化为千分位字符串，如 12345 → '12,345'。"""
    return f"{v:,}"
