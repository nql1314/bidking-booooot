"""估算总价 / 艾莎 bid / 四档 CSV 估价 / 早期约束单价。

历史 ``GridWindow._build_vacant_estimate_bar`` + ``_build_legend`` 实现。
本模块为占位 facade，并暴露纯计算入口 :func:`build_pricing_dict`。
"""

from ...analysis import build_snapshot_pricing_dict as build_pricing_dict
from ..grid._grid_view import GridWindow

__all__ = ["GridWindow", "build_pricing_dict"]
