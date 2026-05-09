"""艾莎策略：基于画板快照的估价。

历史路径（``_aisha_legacy``）：从 ``board_snapshot.path`` 文件读 JSON 快照
计算出价；新代码 **优先使用 in-process 快照** —— 直接消费 :mod:`bidking.bridge.snapshot_store`
里的 dict，避免依赖外部 JSON 文件。

文件读取链路保留作为 *可选* 调试通道，由 ``runtime.board_snapshot.write_mode``
控制。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..analysis import (
    build_snapshot_pricing_dict,
    compute_aisha_bid_from_board_snapshot,
)
from . import _aisha_legacy as _legacy

# 复用文件版历史 API（保留以兼容外部进程）
read_board_snapshot_if_enabled = _legacy._read_board_snapshot_if_enabled
is_aisha_premium_mode = _legacy.is_aisha_premium_mode
clear_board_snapshot_file = getattr(_legacy, "clear_board_snapshot_file", None)
compute_aisha_snapshot_bid_points = getattr(_legacy, "compute_aisha_snapshot_bid_points", None)
current_round_from_snapshot = getattr(_legacy, "current_round_from_snapshot", None)
max_other_player_bid_from_snapshot_players = getattr(
    _legacy, "max_other_player_bid_from_snapshot_players", None
)


def compute_bid_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    pricing_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """进程内入口：直接吃 :mod:`bidking.bridge.snapshot_store` 的 dict。

    返回结构与历史 ``compute_aisha_bid_from_board_snapshot`` 一致：

    - ``points`` / ``points_floor`` / ``points_ceiling``
    - ``aisha_bid`` (即 ``points`` × 万)
    - ``meta`` 子 dict（quality_group / unit_price 等）
    """
    return compute_aisha_bid_from_board_snapshot(snapshot)


def build_pricing_dict(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """围绕 snapshot 算 ``est_orange/gold_red/red`` 等聚合估价 dict。"""
    return build_snapshot_pricing_dict(snapshot)


__all__ = [
    "read_board_snapshot_if_enabled",
    "is_aisha_premium_mode",
    "clear_board_snapshot_file",
    "compute_aisha_snapshot_bid_points",
    "current_round_from_snapshot",
    "max_other_player_bid_from_snapshot_players",
    "compute_bid_from_snapshot",
    "build_pricing_dict",
]
