"""画板（grid）UI：tkinter 主窗体与子组件。

历史 ``getlog/grid_view.py`` 的全部组件暂存于 :mod:`._grid_view`，本子包以
稳定 facade 暴露主入口与可复用的 helper。子模块拆分仍在迁移期间逐步推进。
"""

from ._grid_view import GridWindow  # noqa: F401

__all__ = ["GridWindow"]
