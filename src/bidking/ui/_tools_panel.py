"""启动页 Notebook「工具」标签：各类小工具入口。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .tools.round_param_analysis import launch_round_param_analysis


class ToolsPanel:
    """主界面工具集合；各工具在独立窗口中打开，不阻塞启动页。"""

    def __init__(self, parent: tk.Widget) -> None:
        self.parent = parent
        self._shell = parent.winfo_toplevel()

        wrap = ttk.Frame(parent, padding=20)
        wrap.pack(fill="both", expand=True)

        ttk.Label(
            wrap,
            text="工具",
            font=("微软雅黑", 14, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            wrap,
            text="常用分析与小助手入口。点击后在独立窗口打开，可同时保留启动页与其它标签。",
            foreground="#5a6a7a",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(4, 16))

        card = ttk.LabelFrame(wrap, text="已集成", padding=12)
        card.pack(fill="x", anchor="nw")

        row = ttk.Frame(card)
        row.pack(fill="x", pady=4)

        ttk.Label(
            row,
            text="回合参数分析助手",
            font=("微软雅黑", 10, "bold"),
            width=22,
        ).pack(side="left", anchor="nw")

        desc = ttk.Frame(row)
        desc.pack(side="left", fill="x", expand=True, padx=(8, 12))

        ttk.Label(
            desc,
            text="读取 game_match_reports CSV，按 R1~R5 原/新系数反推估价并模拟利润，含阻止分析。",
            wraplength=520,
            justify="left",
        ).pack(anchor="w")

        ttk.Button(
            row,
            text="打开",
            command=lambda: launch_round_param_analysis(self._shell),
            width=10,
        ).pack(side="right", anchor="ne")
