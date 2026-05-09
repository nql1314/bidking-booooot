"""第 2 层 · 日志解析与原始数据。

包含：

- :mod:`.log_source`  —— 日志行到 ``(event_type, dict)``、tail 迭代
- :mod:`.constants`   —— 技能 ID / 类别 / 地图技能映射
- :mod:`.state`       —— ``ItemKnowledge`` / ``GameState``（含 ``record_scan`` 负向约束）
- :mod:`.events`      —— 事件 dataclass（解耦事件与状态）
- :mod:`.processors`  —— 从日志条目落到 state 的处理器
- :mod:`.handlers`    —— ``S2C_33/37/39/45`` 路由
- :mod:`.item_db`     —— CSV 载入 / ``query_item`` / 权重期望 / ``normalize_map_id``

仅做"日志 → 事件 + 数据"，不做后续加工。
"""

from .log_source import extract_event, iter_log_lines
from .state import CsvItem, GameState, ItemKnowledge
from .events import (
    GameOverEvent,
    GameStartEvent,
    GlobalSkillStats,
    HeroSkillEvent,
    HitBox,
    ItemSkillEvent,
    MapSkillEvent,
    RoundEndEvent,
)
from .item_db import (
    load_csv,
    normalize_map_id,
    query_item,
)
from .handlers import (
    handle_s2c33,
    handle_s2c37,
    handle_s2c39,
    handle_s2c45,
)
from .processors import (
    process_hero_skill_log,
    process_item_skill_log,
    process_map_skill_log,
)

__all__ = [
    "extract_event",
    "iter_log_lines",
    "CsvItem",
    "GameState",
    "ItemKnowledge",
    "GameOverEvent",
    "GameStartEvent",
    "GlobalSkillStats",
    "HeroSkillEvent",
    "HitBox",
    "ItemSkillEvent",
    "MapSkillEvent",
    "RoundEndEvent",
    "load_csv",
    "normalize_map_id",
    "query_item",
    "handle_s2c33",
    "handle_s2c37",
    "handle_s2c39",
    "handle_s2c45",
    "process_hero_skill_log",
    "process_item_skill_log",
    "process_map_skill_log",
]
