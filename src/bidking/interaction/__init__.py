"""第 1 层 · 游戏交互。

只管"看屏幕、点鼠标、跑回合流程"，不持有价格相关状态。

- :mod:`.window`      —— 窗口查找 / 客户区截图 / 坐标缩放
- :mod:`.ocr`         —— RapidOCR 单例
- :mod:`.text_patch`  —— OCR 文本 → patch / 对手价
- :mod:`.input`       —— 点击 / 输入 / 道具序列 / 出价提交
- :mod:`.observe`     —— 截图 + OCR → ``Observation``
- :mod:`.round_flow`  —— 回合流程主循环（策略由调用方注入）

为减小一次性迁移风险，``_legacy_bot`` / ``_legacy_aisha`` 暂存 2k+ 行的
原始内核；上述 facade 只是稳定的层 API。
"""

from .window import capture_window_frame, find_window, scale_point  # noqa: F401
from .ocr import get_engine, infer_lines, rapidocr_once  # noqa: F401
from .text_patch import (  # noqa: F401
    merge_patch,
    parse_central_info,
    get_max_other_players_last_bid_from_image,
)

__all__ = [
    "capture_window_frame",
    "find_window",
    "scale_point",
    "get_engine",
    "infer_lines",
    "rapidocr_once",
    "merge_patch",
    "parse_central_info",
    "get_max_other_players_last_bid_from_image",
]
