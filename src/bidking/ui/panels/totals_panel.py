"""总格 / 紫金红 数量&格 / 未知 / 空置 —— 由 :class:`bidking.ui.grid.GridWindow`
内 ``_build_info_bar`` 与 ``_build_legend`` 提供。

可直接消费 :func:`bidking.analysis.quality_stats.per_quality_summary` 的输出
做汇总展示。
"""

from ...analysis.quality_stats import per_quality_summary
from ..grid._grid_view import GridWindow

__all__ = ["GridWindow", "per_quality_summary"]
