"""地图面板（10×30 网格）—— 由 :class:`bidking.ui.grid.GridWindow` 内
``_build_canvas`` 与 ``_draw`` 提供。本模块为占位 facade，便于后续拆出。
"""

from ..grid._grid_view import GridWindow

__all__ = ["GridWindow"]
