"""第 4 层 · 出价策略。

只消费 :mod:`bidking.analysis` 暴露的快照 / 派生指标，不直接读 ``GameState``。

子模块：

- :mod:`._constraint_solver` —— 通用色块约束求解（``solve_color`` / ``validate_input``…）
- :mod:`.ahmad`              —— 艾哈迈德溢价 / 价值锚 ceiling / flat-solve
- :mod:`.aisha`              —— 艾莎快照 bid（in-process 与文件双通道）
- :mod:`.post_process`       —— burst_limit / cap / safe_guard / 对手价 floor
- :mod:`.strategy`           —— 模式路由（AHMAD / AISHA），RAVEN 仅留枚举
"""

from .strategy import BidDecision, Mode, compute_bid, normalize_mode
from .post_process import PostProcessConfig, post_process

__all__ = [
    "BidDecision",
    "Mode",
    "compute_bid",
    "normalize_mode",
    "PostProcessConfig",
    "post_process",
]
