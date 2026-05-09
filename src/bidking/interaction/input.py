"""键鼠输入：点击 / 输入价格 / 取消 / 道具序列 / 出价提交。

facade，把 ``_legacy_bot`` 中相关函数以稳定 API 暴露。
"""

from __future__ import annotations

from . import _legacy_bot as _b

click_point = getattr(_b, "click_point", None)
type_price = getattr(_b, "type_price", None)
press_escape = getattr(_b, "press_escape", None)
run_tool_sequence = getattr(_b, "run_tool_sequence", None)
input_bid = getattr(_b, "input_bid", None)
park_mouse = getattr(_b, "park_mouse", None)

__all__ = [
    "click_point",
    "type_price",
    "press_escape",
    "run_tool_sequence",
    "input_bid",
    "park_mouse",
]
