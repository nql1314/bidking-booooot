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

# ─── 英雄技能映射 ──────────────────────────────────────────────────────────

# 艾莎英雄技能 SkillCid → 扫描到的品质上限
HERO_SKILL_QUALITY: Dict[int, int] = {
    1001034: 1,
    1001033: 2,
    1001032: 3,
    1001031: 4,
}
HERO_ID: Dict[int, str] = {
    102: "chenmei",
    103: "aisha",
    104: "jiabuli",
    106: "naaomi",
    107: "suofei",
    108: "nainai",
    110: "yishabeila",
    203: "laiangnade",
    204: "ahmad",
    207: "wuqiling",
    208: "yisen",
    209: "vector",
    301: "lawen"
}
# ─── 英雄技能 ──────────────────────────────────────────────────────────────

# 英雄技能 SkillCid → 描述（未收录的 SkillCid 在输出时显示"未知英雄技能"）
HERO_SKILL_DESC: Dict[int, str] = {
    # aisha
    1001034: "品质1物品轮廓+位置",
    1001033: "品质2物品轮廓+位置",
    1001032: "品质3物品轮廓+位置",
    1001031: "品质4物品轮廓+位置",
    # ahmad
    100204: "总藏品数量",
    1002041: "品质5平均格数",
    1002042: "品质4平均格数",
    1002043: "品质3平均格数",
    1002044: "品质12总数",
    #naaomi
    100106: "时尚潮流+数码电子 金红数",
    1001061: "时尚潮流+数码电子 轮廓",
    #laiangnade
    100203: "饮食扫描 品质",
    1002031: "文玩古董 品质",

    #yiwan
    100205: "武器 能源 轮廓",

    #vector
    100209: "紫金红",

    #wuqiling
    100207: "文物 总数",
    10002071: "文物 轮廓",
    10002072: "文物 品质",

}

# ─── 道具映射 ──────────────────────────────────────────────────────────────

# 道具 ItemCid → (触发技能 SkillCid, 道具中文名, 揭示的类别 tag)
ITEM_TOOLS: Dict[int, Tuple[int, str, int]] = {
    100151: (2001, "家具物品鉴影", 101),
    100152: (2002, "医疗药品鉴影", 102),
    100153: (2003, "时尚潮流鉴影", 103),
    100154: (2004, "兵装军火鉴影", 104),
    100155: (2005, "珠宝矿藏鉴影", 105),
    100156: (2006, "文物古董鉴影", 106),
    100157: (2007, "数码娱乐鉴影", 107),
    100158: (2008, "能源交通鉴影", 108),
    100159: (2009, "食饮珍馐鉴影", 109),
    100160: (2010, "书画古籍鉴影", 110),
}

ITEM_SKILL_DESC: Dict[int, str] = {


    100104: "普品扫描",
    100105: "良品扫描",
    100106: "优品扫描",
    # 100107: "至宝体量",
    # 100108: "极品扫描",
    # 100109: "总仓储空间",
    # 100110: "珍品扫描",

    100110: "普品均格",
    100111: "良品均价",
    100112: "优品均价",
    100113: "极品均价",
    # 100114: "珍品均价",
    
    100116: "普品存量",
    100117: "良品存量",
    100118: "优品存量",
    100119: "库存清点",
    100120: "极品存量",
    100121: "珍品存量",
    100122: "普品估价",
    100123: "良品估价",
    100124: "优品估价",
    # 100125: "巨物估价",
    # 100126: "极品估价",
    # 100127: "至宝估价",
    # 100128: "终极审计",
    # 100129: "珍品估价",
}

# 技能 SkillCid → 揭示的类别 tag（由 ITEM_TOOLS 反向推导）
SKILL_TO_CATEGORY: Dict[int, int] = {v[0]: v[2] for v in ITEM_TOOLS.values()}

# ─── 类别映射 ──────────────────────────────────────────────────────────────

# 类别 tag → 中文名
CATEGORY_NAMES: Dict[int, str] = {
    101: "家具物品", 102: "医疗药品", 103: "时尚潮流", 104: "兵装军火",
    105: "珠宝矿藏", 106: "文物古董", 107: "数码娱乐", 108: "能源交通",
    109: "食饮珍馐", 110: "书画古籍",
}

# ─── 地图技能 ──────────────────────────────────────────────────────────────

# 地图技能 SkillCid → 描述（未收录的 SkillCid 在输出时显示"未知地图技能"）
MAP_SKILL_DESC: Dict[int, str] = {
    0: "初始技能",
    200001: "品质4物品轮廓+位置",
    200002: "地图初始化技能",
    200005: "全场各类别每格均价",
    200009: "所有藏品格数",
    200010: "紫色总格",
    200011: "金色总占用格",
    200012: "红品质占用格数",
    200013: "紫色平均占用格",
    200014: "所有藏品均格",
    200015: "金色平均占用格",
    200016: "红色平均占用格",
    200017: "总藏品数量",
    200018: "紫色(Q=4)物品数量",
    200019: "金色(Q=5)物品数量",
    200020: "红色(Q=6)物品数量",
    200021: "随机揭示2件藏品",
    200022: "随机显示4件藏品",
    200023: "随机显示6件藏品",
    200024: "随机显示8件藏品",
    200026: "随机3品质",
    200027: "随机6品质",
    200028: "随机9品质",
    200029: "随机12品质",
    200031: "随机3均价",
    200032: "随机6均价",
    200033: "随机9均价",
    200034: "随机12均价",
    200036: "紫色均价",
    200037: "金色均价",
    200038: "红色均价",
    200039: "所有道具轮廓",
    200046: "显示一种类型品质",
    200048: "显示最高品质",
    200049: "显示最高价值",
    200050: "显示占位最高的道具",
    990001: "显示金色品质",
    990002: "显示红色品质",
    990003: "金色总价",
    990004: "红色总价",

}

# 地图技能中哪些 SkillCid 可以强制设定 HitBoxList 中物品的品质
MAP_SKILL_FORCE_QUALITY: Dict[int, int] = {
    200001: 4,   # 该技能只命中品质=4的物品
    990001: 5,   # 该技能只命中品质=5的物品
    990002: 6,   # 该技能只命中品质=6的物品
}

# 轮廓类技能（英雄品质扫描 ∪ 地图强制品质）：可从 HitBoxList 推理件数/占格/价
OUTLINE_SKILL_QUALITY: Dict[int, int] = {**HERO_SKILL_QUALITY, **MAP_SKILL_FORCE_QUALITY}

# ─── 地图与英雄成对技能（语义相同，日志里可能只出现其中一种）────────────────
# 总藏品件数
SKILL_CID_TOTAL_ITEM_COUNT: Tuple[int, ...] = (200017, 100204)
# 紫色 Q4：件数、均格、均价（200010/200018 均为紫色件数类；1002042 为英雄「品质4平均格数」）
SKILL_CID_Q4_AVG_GRID: Tuple[int, ...] = (200013, 1002042)

SKILL_CID_Q5_AVG_GRID: Tuple[int, ...] = (200015, 1002041)
# 全场藏品平均占格（均格）
SKILL_CID_ALL_ITEMS_AVG_GRID: Tuple[int, ...] = (200014,)

# 艾莎 board_snapshot 出价（逻辑在 ``getlog.board_pricing``；旧注释曾指向 bidking-bot aisha_premium）引用的地图技能 ID
MAP_SKILL_TOTAL_HIDDEN_CELLS = 200009     # 所有藏品格数（TotalHitBoxIndex）；未满前空置计数可据此、且可跳过诈骗格过滤
MAP_SKILL_TOTAL_PURPLE_CELLS = 200010       # 地图紫格总数
MAP_SKILL_TOTAL_GOLD_CELLS = 200011       # 地图金格总数
MAP_SKILL_TOTAL_RED_CELLS = 200012        # 地图红格总数
MAP_SKILL_AVG_RED_CELLS = 200016         # 红色平均占用格
MAP_SKILL_TOTAL_PURPLE_COUNT = 200018       # 地图紫格件数
MAP_SKILL_TOTAL_GOLD_COUNT = 200019       # 地图金格件数
MAP_SKILL_TOTAL_RED_COUNT = 200020       # 地图红格件数
MAP_SKILL_AVG_PURPLE_PRICE = 200036       # 紫色物品均价
MAP_SKILL_AVG_GOLD_PRICE = 200037         # 金色物品均价
MAP_SKILL_AVG_RED_PRICE = 200038          # 红色物品均价

MAP_SKILL_RANDOM3_AVG_PRICE = 200031       # 随机3均价
MAP_SKILL_RANDOM6_AVG_PRICE = 200032      # 随机6均价
MAP_SKILL_RANDOM9_AVG_PRICE = 200033      # 随机9均价
MAP_SKILL_RANDOM12_AVG_PRICE = 200034      # 随机12均价
MAP_SKILL_GOLD_TOTAL_PRICE = 990003       # 金色总价
MAP_SKILL_RED_TOTAL_PRICE = 990004       # 红色总价

# 200009 揭示地图藏宝总占用格；在已知区内占位格数未达该总数前，画板自动空置区忽略诈骗格过滤；吃满后恢复几何空置 + 诈骗格规则。
# 200011/200012 揭示金/红总占用格；200015/200016 为平均占用类信息（bot 中不作总格数用于空余金红分拆）；
# 200019/200020 仅揭示件数（件数=0 时可推断该品质总格为 0）。
# 计算「剩余空格 × 单价」时需扣掉已由上述技能隐含、尚未落在「轮廓已确认」物品上的占用格，避免与 total/技能加价重复计价。
# 第 1–3 回合：若有 extra_g / extra_r（地图金/红格 − 已揭示 footprint），线性部分先扣 min(extra_g, vac_n)，再在剩余空置上扣 min(extra_r, …)，与 extra×q5/q6 格价不叠算同一批空置格。
# 仅有件数、未知每件形状时，每件按 MAP_SKILL_ITEM_COUNT_ESTIMATED_CELLS 格从空置计数中扣除（与 grid_view、aisha_premium 一致）。
# 若场上仍存在轮廓未知的 Q5/Q6（品质已知但 box 未确认或无形），则不对该色使用上述地图推断与扣减，以免与 pricing.total 重叠。
MAP_SKILL_ITEM_COUNT_ESTIMATED_CELLS = 2

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
