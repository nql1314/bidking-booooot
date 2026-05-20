# -*- coding: utf-8 -*-
"""策略层子模块。

提供各英雄/场景专用的定价策略和决策辅助算法。

当前模块:

- :mod:`.ahmad` —— Ahmad 英雄专用估价策略（快递站系列地图）
"""

from .ahmad import (
    # 常量
    _AHMAD_HERO_CID,
    _EXPRESS_STATION_MAP_BUNDLE_KEY,
    _CONTAINER_MAP_BUNDLE_KEY,
    # 地图判断
    map_bundle_is_express_station_series,
    map_bundle_is_container_series,
    # 核心算法
    resolve_ahmad_abde_scale,
    ahmad_pricing_detail_from_raw_pricing,
    ahmad_points_from_raw_pricing,
    is_ahmad_pricing_active,
)

__all__ = [
    # 常量
    "_AHMAD_HERO_CID",
    "_EXPRESS_STATION_MAP_BUNDLE_KEY",
    "_CONTAINER_MAP_BUNDLE_KEY",
    # 地图判断函数
    "map_bundle_is_express_station_series",
    "map_bundle_is_container_series",
    # 核心算法函数
    "resolve_ahmad_abde_scale",
    "ahmad_pricing_detail_from_raw_pricing",
    "ahmad_points_from_raw_pricing",
    "is_ahmad_pricing_active",
]
