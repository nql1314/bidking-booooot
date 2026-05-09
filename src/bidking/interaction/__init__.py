"""第 1 层 · 游戏交互。

只管「看屏幕、点鼠标、跑回合流程」。出价数额由 :func:`._legacy_bot.compute_price`
提供占位实现，后续可由策略层替换。

- :mod:`.window`      —— 窗口查找 / 客户区截图 / 坐标缩放
- :mod:`.ocr`         —— RapidOCR 单例
- :mod:`.input`       —— 点击 / 输入 / 道具序列 / 出价提交
- :mod:`.observe`     —— 截图 + OCR → ``Observation``
- :mod:`.round_flow`  —— 回合流程主循环

流程与兼容入口（含 ``run_aisha_loop``、仓库自动整理）均在 ``_legacy_bot``。
"""

from .window import capture_window_frame, find_window, scale_point  # noqa: F401
from .ocr import get_engine, infer_lines, rapidocr_once  # noqa: F401
from ._legacy_bot import compute_price  # noqa: F401

__all__ = [
    "capture_window_frame",
    "find_window",
    "scale_point",
    "get_engine",
    "infer_lines",
    "rapidocr_once",
    "compute_price",
]
