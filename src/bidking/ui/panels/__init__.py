"""按你列出的 6 大面板拆分；当前为 facade，全部由 :mod:`..grid._grid_view`
内部组装实现。后续会逐步把对应区段（``_build_*``）抽到独立类。

- :mod:`.map_panel`        —— 10×30 网格 + 品质着色 + 未知底色 + 空置橘红
- :mod:`.inventory_panel`  —— 已有藏品格子（点击候选 / 估价）
- :mod:`.totals_panel`     —— 地图总格 / 紫金红 数量&总格 / 未知 / 空置
- :mod:`.price_panel`      —— 估算总价 / 艾莎 bid / 四档 CSV 估价
"""

from . import inventory_panel, map_panel, price_panel, totals_panel  # noqa: F401

__all__ = ["map_panel", "inventory_panel", "totals_panel", "price_panel"]
