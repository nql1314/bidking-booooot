# -*- coding: utf-8 -*-
"""兼容入口：独立运行 ``python tools/gui8.py`` 仍可用。

实现已迁入 ``bidking.ui.tools.round_param_analysis``。
"""

from __future__ import annotations

from bidking.ui.tools.round_param_analysis import App, RoundParamAnalysisApp, main

__all__ = ["App", "RoundParamAnalysisApp", "main"]

if __name__ == "__main__":
    main()
