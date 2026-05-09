"""回合流程骨架：``handle_round`` / ``handle_end_transition`` /
``run_map_selection_transition`` / ``run_loop``。

facade，转发 ``_legacy_bot`` 与 ``_legacy_aisha`` 的入口。
策略层（pricing）通过 callable 注入决策，本层不做估价。
"""

from __future__ import annotations

from . import _legacy_aisha as _a
from . import _legacy_bot as _b

handle_round = getattr(_b, "handle_round", None)
handle_end_transition = getattr(_b, "handle_end_transition", None)
run_map_selection_transition = getattr(_b, "run_map_selection_transition", None)
run_loop = getattr(_b, "run_loop", None)
run_aisha_loop = getattr(_a, "run_aisha_loop", None)

__all__ = [
    "handle_round",
    "handle_end_transition",
    "run_map_selection_transition",
    "run_loop",
    "run_aisha_loop",
]
