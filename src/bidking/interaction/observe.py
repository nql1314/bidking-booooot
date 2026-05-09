"""观察：截图 + OCR + 解析 → ``Observation``。

facade，转发 ``_legacy_bot`` 中的观察函数。
"""

from __future__ import annotations

from . import _legacy_bot as _b

observe_state_round = getattr(_b, "observe_state_round", None)
observe_state_poll = getattr(_b, "observe_state_poll", None)
parse_round_number = getattr(_b, "parse_round_number", None)
has_end_prompt = getattr(_b, "has_end_prompt", None)
CaptureResult = getattr(_b, "CaptureResult", None)
Observation = getattr(_b, "Observation", None)

__all__ = [
    "observe_state_round",
    "observe_state_poll",
    "parse_round_number",
    "has_end_prompt",
    "CaptureResult",
    "Observation",
]
