"""tkinter 顶层壳：BidKingApp。

复用历史 ``bidking_gui.BidKingApp`` 的实现（位于 :mod:`._legacy_gui`）；
新代码请从这里 import :class:`BidKingApp`，方便后续替换底层实现。
"""

from __future__ import annotations

import os
import sys

from ._legacy_gui import BidKingApp


def _backfill_history_reports() -> None:
    """启动时把历史日志里所有"已结束"对局补录到独立的历史 CSV。

    环境变量 ``BIDKING_DISABLE_HISTORY_REPORT_BACKFILL`` 为真则跳过。
    """
    if os.environ.get(
        "BIDKING_DISABLE_HISTORY_REPORT_BACKFILL", ""
    ).strip().lower() in ("1", "true", "yes"):
        return
    try:
        from bidking.parsing.constants import (
            DEFAULT_GAME_LOG,
            LOCAL_COPY_LOG,
            LOCAL_LOG,
            resource_path,
        )
        from bidking.parsing.game_report_csv import (
            backfill_history_game_reports_csv,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[history-report] 跳过：{exc}", file=sys.stderr)
        return

    log_path = next(
        (p for p in (DEFAULT_GAME_LOG, LOCAL_LOG, LOCAL_COPY_LOG) if os.path.exists(p)),
        None,
    )
    if not log_path:
        return
    csv_path = resource_path("item_prices.csv")
    if not os.path.exists(csv_path):
        return
    try:
        result = backfill_history_game_reports_csv(log_path, csv_path)
        if result is None:
            return
        out, wrote = result
        if wrote > 0:
            print(f"[history-report] 已写出 {wrote} 局到 {out}", file=sys.stderr)
        else:
            print(f"[history-report] 已存在，跳过：{out}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[history-report] 跳过：{exc}", file=sys.stderr)


def main() -> None:
    """启动 GUI 应用。"""
    from bidking.parsing.game_report_csv import init_game_report_csv_session

    init_game_report_csv_session()
    _backfill_history_reports()

    import tkinter as tk

    root = tk.Tk()
    BidKingApp(root)
    root.mainloop()


__all__ = ["BidKingApp", "main"]
