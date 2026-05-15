"""第 3 层 · 数据分析。

分析 :mod:`..parsing` 产出的 ``GameState``，得到判断/估价用派生指标，
再经 :mod:`.snapshot` 汇成统一画板快照 dict 推到 :mod:`..bridge`。

子模块：

- :mod:`.snapshot`        —— 统一画板快照（含 items / scan_history / map_skill_logs / pricing）
- :mod:`.grid_overlay`    —— 画板 overlay（空置/几何空置 + ``items`` 与 overlay 合并）
- :mod:`.fraud_empty_cells` —— 空置前缀区诈骗格判定（铺板可解释性等）
- :mod:`.quality_stats`   —— 各品质件数/总格/未确认轮廓
- :mod:`.scan_inference`  —— 扫描历史 → 空格可能品质
- :mod:`.unknown_value`   —— 未知物品权重估价 / 等效格价
- :mod:`.map_avg_csv`     —— 地图×品质 CSV 单价

并经由 :mod:`._board_pricing` 暴露 ``build_snapshot_pricing_dict`` /
``estimate_snapshot_item_price`` / ``estimate_snapshot_item_price_for_uid`` 等；策略层读 ``pricing.points``。
"""

from . import grid_overlay, fraud_empty_cells, map_avg_csv, quality_stats, raw_pricing, scan_inference, snapshot, unknown_value
from .snapshot import (
    build_board_snapshot,
    game_state_from_json,
    game_state_to_json,
    item_knowledge_from_json,
    item_knowledge_to_json,
)
from ._board_pricing import (
    build_snapshot_pricing_dict,
    current_round_from_board_snapshot,
    estimate_snapshot_item_price,
    estimate_snapshot_item_price_for_uid,
    map_id_from_board_snapshot,
)
from .raw_pricing import build_raw_pricing_dict, event_stats_q12_q3_q4_grids_all_known, read_skill_log_direct_prices

__all__ = [
    "snapshot",
    "grid_overlay",
    "fraud_empty_cells",
    "quality_stats",
    "scan_inference",
    "unknown_value",
    "map_avg_csv",
    "raw_pricing",
    "build_raw_pricing_dict",
    "event_stats_q12_q3_q4_grids_all_known",
    "read_skill_log_direct_prices",
    "build_board_snapshot",
    "build_snapshot_pricing_dict",
    "estimate_snapshot_item_price",
    "estimate_snapshot_item_price_for_uid",
    "current_round_from_board_snapshot",
    "map_id_from_board_snapshot",
    "game_state_from_json",
    "game_state_to_json",
    "item_knowledge_from_json",
    "item_knowledge_to_json",
]
