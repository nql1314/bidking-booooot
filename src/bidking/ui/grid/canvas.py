"""画布 / 网格绘制工具（facade）。

历史实现位于 :mod:`._grid_view`：``_build_canvas`` / ``_draw`` / ``_draw_item``
等是 :class:`.GridWindow` 的实例方法，外部一般通过 ``GridWindow`` 使用，不直
接调用。
"""

from ._grid_view import GridWindow

__all__ = ["GridWindow"]
