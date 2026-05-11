"""第 4 层 · 出价策略：读画板快照 ``pricing``，按角色算 base，再走倍数 / 对手 / 封顶 / 尾数 / bid_cap。"""

from .compute import compute_price

__all__ = ["compute_price"]
