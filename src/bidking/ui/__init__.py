"""第 5 层 · tkinter UI 与画板。

- :mod:`.app`               —— BidKingApp（精简版 bot 自动化总控；启停 + 选图 + 道具回合 + 日志）
- :mod:`._bot_config_panel` —— BotConfigPanel（策略配置：出价参数 / 棋盘快照 / 地图与主配置 JSON 两列；嵌入 grid_view 启动页）
- :mod:`._visual_config_panel` —— VisualConfigPanel（基于 visual_config_schema.json 的可视化配置）
- :mod:`._tools_panel` —— ToolsPanel（启动页「工具」标签：回合参数分析等入口）
- :mod:`.grid`              —— 画板 GridWindow（地图 + 估价信息条 + 图例 + 回放导航）
- :mod:`.panels`            —— 面板 facade（map / inventory / totals / price）
- :mod:`.log_view`          —— UI 内关键决策行流
"""

from .app import BidKingApp
from ._bot_config_panel import BotConfigPanel
from ._visual_config_panel import VisualConfigPanel
from ._tools_panel import ToolsPanel
from .grid import GridWindow
from .log_view import UiLogView, default_view

__all__ = [
    "BidKingApp",
    "BotConfigPanel",
    "VisualConfigPanel",
    "ToolsPanel",
    "GridWindow",
    "UiLogView",
    "default_view",
]
