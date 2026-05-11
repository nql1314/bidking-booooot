#!/usr/bin/env python3
"""Win32 窗口捕获与后台输入：命令行入口。

实现位于 ``bidking.interaction.window``；本文件便于在仓库根目录执行：

    python tools/window_backend.py list-windows
    python tools/window_backend.py capture --full-client
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
_src_str = str(_SRC)
if _src_str not in sys.path:
    sys.path.insert(0, _src_str)

from bidking.interaction.window import main


if __name__ == "__main__":
    raise SystemExit(main())
