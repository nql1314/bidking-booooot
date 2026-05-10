# -*- coding: utf-8 -*-
"""从快照/日志中的 ``shape`` 字段解析画板矩形宽高（含 ``w*10+h`` 与两位数字符串）。"""

from __future__ import annotations

from typing import Any, Tuple


def shape_wh_from_snapshot(shape: Any) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1
