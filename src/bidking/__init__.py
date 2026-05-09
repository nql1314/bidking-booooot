"""bidking — 分层架构的自动化竞拍机器人 + 画板看板。

各层入口：

- :mod:`bidking.interaction` —— 第 1 层：游戏交互
- :mod:`bidking.parsing`     —— 第 2 层：日志解析与原始数据
- :mod:`bidking.analysis`    —— 第 3 层：数据分析
- :mod:`bidking.ui`          —— 第 4 层：tkinter UI 与画板
- :mod:`bidking.logsys`      —— 第 5 层：日志
- :mod:`bidking.config`      —— 第 6 层：配置
- :mod:`bidking.bridge`      —— 跨层胶水（snapshot store / file）
- :mod:`bidking.runner`      —— 入口
"""

__version__ = "0.1.0"
