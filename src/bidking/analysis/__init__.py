"""第 3 层 · 数据分析。

分析 :mod:`..parsing` 产出的 ``GameState``，得到判断/估价用派生指标，
再经 :mod:`.snapshot` 汇成统一画板快照 dict 推到 :mod:`..bridge`。

子模块：

- :mod:`.snapshot`        —— 统一画板快照（含 items / scan_history / map_skill_logs / pricing）
- :mod:`.vacant`          —— 空置/几何空置/有效空置/诈骗格
- :mod:`.quality_stats`   —— 各品质件数/总格/未确认轮廓
- :mod:`.scan_inference`  —— 扫描历史 → 空格可能品质
- :mod:`.unknown_value`   —— 未知物品权重估价 / 等效格价
- :mod:`.map_avg_csv`     —— 地图×品质 CSV 单价

并经由 :mod:`._board_pricing` 暴露 ``compute_aisha_bid_from_board_snapshot`` /
``build_snapshot_pricing_dict``，第 4 层 ``pricing.aisha`` 可直接消费。
"""

from . import map_avg_csv, quality_stats, raw_pricing, scan_inference, snapshot, unknown_value, vacant
from .snapshot import (
    build_board_snapshot,
    game_state_from_json,
    game_state_to_json,
    item_knowledge_from_json,
    item_knowledge_to_json,
)
from ._board_pricing import (
    build_snapshot_pricing_dict,
    compute_aisha_bid_from_board_snapshot,
    current_round_from_board_snapshot,
    map_id_from_board_snapshot,
)
from .raw_pricing import build_raw_pricing_dict

__all__ = [
    "snapshot",
    "vacant",
    "quality_stats",
    "scan_inference",
    "unknown_value",
    "map_avg_csv",
    "raw_pricing",
    "build_raw_pricing_dict",
    "build_board_snapshot",
    "build_snapshot_pricing_dict",
    "compute_aisha_bid_from_board_snapshot",
    "current_round_from_board_snapshot",
    "map_id_from_board_snapshot",
    "game_state_from_json",
    "game_state_to_json",
    "item_knowledge_from_json",
    "item_knowledge_to_json",
]
