"""第 5 层 · tkinter UI 与画板。

- :mod:`.app`        —— BidKingApp（自动化/runtime/pricing 编辑 + 启动 runner）
- :mod:`.grid`       —— 画板 GridWindow（地图 + 估价信息条 + 图例 + 回放导航）
- :mod:`.panels`     —— 面板 facade（map / inventory / totals / price）
- :mod:`.log_view`   —— UI 内关键决策行流
"""

from .app import BidKingApp
from .grid import GridWindow
from .log_view import UiLogView, default_view

__all__ = ["BidKingApp", "GridWindow", "UiLogView", "default_view"]
