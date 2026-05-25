"""tkinter 顶层壳：BidKingApp。

复用历史 ``bidking_gui.BidKingApp`` 的实现（位于 :mod:`._legacy_gui`）；
新代码请从这里 import :class:`BidKingApp`，方便后续替换底层实现。
"""

from __future__ import annotations

from ._legacy_gui import BidKingApp


def main() -> None:
    """启动 GUI 应用。"""
    from bidking.parsing.game_report_csv import init_game_report_csv_session

    init_game_report_csv_session()

    import tkinter as tk

    root = tk.Tk()
    BidKingApp(root)
    root.mainloop()


__all__ = ["BidKingApp", "main"]
