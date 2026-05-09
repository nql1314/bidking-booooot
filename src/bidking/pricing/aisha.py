"""艾莎策略：基于画板快照的估价。

消费 :mod:`bidking.analysis` 的 ``pricing.points`` / ``points_floor`` / ``points_ceiling``，
不再单独维护 ``aisha_bid`` 元数据字典。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..analysis import build_snapshot_pricing_dict
from . import _aisha_legacy as _legacy

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
    """进程内入口：直接吃快照 dict。

    返回 dict 含 ``points``、``aisha_bid``（与 ``points`` 同值，兼容旧 ``strategy`` 读键）、
    ``points_floor`` / ``points_ceiling`` 及完整 ``pricing``。
    """
    _ = pricing_config
    pricing = snapshot.get("pricing")
    if not isinstance(pricing, dict) or pricing.get("points") is None:
        pricing = build_snapshot_pricing_dict(snapshot)
    pts = pricing.get("points")
    try:
        pts_int = int(round(float(pts)))
    except (TypeError, ValueError):
        pts_int = 0
    pf = pricing.get("points_floor")
    pc = pricing.get("points_ceiling")
    return {
        "points": pts_int,
        "points_floor": pf,
        "points_ceiling": pc,
        "aisha_bid": pts_int,
        "pricing": pricing,
    }


def build_pricing_dict(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """围绕 snapshot 算 ``pricing`` 聚合估价 dict。"""
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
