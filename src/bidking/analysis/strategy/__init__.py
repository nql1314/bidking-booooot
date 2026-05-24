# -*- coding: utf-8 -*-
"""策略层子模块。

提供各英雄/场景专用的定价策略和决策辅助算法。

画板快照定价流程：

1. :mod:`.pipeline` —— 公共流水线（物品 total、空置调整、通用主价）
2. :mod:`.registry` —— 按角色选择策略并组装 ``pricing`` dict
3. :mod:`.generic` / :mod:`.ahmad` —— 各角色 finalize 逻辑

当前角色策略:

- :mod:`.generic` —— 通用空置主价（默认）
- :mod:`.ahmad` —— Ahmad 英雄专用估价（快递站系列地图）
"""

from .ahmad import (
    _AHMAD_HERO_CID,
    _CONTAINER_MAP_BUNDLE_KEY,
    _EXPRESS_STATION_MAP_BUNDLE_KEY,
    ahmad_points_from_raw_pricing,
    ahmad_pricing_detail_from_raw_pricing,
    is_ahmad_pricing_active,
    map_bundle_is_container_series,
    map_bundle_is_express_station_series,
    resolve_ahmad_abde_scale,
)
from .common import (
    event_stat_grid_count_optional,
    self_player_hero_cid,
)
from .generic import finalize_pricing_dict as generic_finalize_pricing_dict
from .registry import build_snapshot_pricing_dict

__all__ = [
    "_AHMAD_HERO_CID",
    "_EXPRESS_STATION_MAP_BUNDLE_KEY",
    "_CONTAINER_MAP_BUNDLE_KEY",
    "map_bundle_is_express_station_series",
    "map_bundle_is_container_series",
    "resolve_ahmad_abde_scale",
    "ahmad_pricing_detail_from_raw_pricing",
    "ahmad_points_from_raw_pricing",
    "is_ahmad_pricing_active",
    "generic_finalize_pricing_dict",
    "build_snapshot_pricing_dict",
    "event_stat_grid_count_optional",
    "self_player_hero_cid",
]
