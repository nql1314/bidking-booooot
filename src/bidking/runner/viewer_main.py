"""画板看板入口（show_grid 等价）：解析 + 分析 + UI；可 tail / replay。"""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from .. import __version__
from ..parsing.constants import (
    DEFAULT_GAME_LOG,
    LOCAL_COPY_LOG,
    LOCAL_LOG,
    resource_path,
)
from ..parsing._legacy_runner import parse_last_game, parse_last_game_rounds
from ..ui.grid import GridWindow


def _effective_snapshot_path_for_viewer(cli_or_none: str | None) -> str | None:
    """命令行等显式传入的非空路径优先；否则使用合并配置里的 ``board_snapshot.path``（与 bot 读同一文件）。"""
    explicit = (cli_or_none or "").strip()
    if explicit:
        return explicit
    try:
        from ..config.runtime import load_runtime

        bs = load_runtime().board_snapshot
        configured = str(bs.get("path") or "").strip()
        return configured or None
    except Exception:
        return None


def _default_log_path() -> str:
    candidates = [
        DEFAULT_GAME_LOG,
        os.path.join(os.getcwd(), LOCAL_LOG),
        os.path.join(os.getcwd(), LOCAL_COPY_LOG),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return DEFAULT_GAME_LOG


def _open_grid(
    log_path: str,
    csv_path: str,
    tail: bool,
    *,
    board_mode: str = "elsa",
    snapshot_path: str | None = None,
    snapshot_export_overlay: bool = True,
) -> None:
    sp = _effective_snapshot_path_for_viewer(snapshot_path)
    if tail:
        state, csv_index, csv_items = parse_last_game(log_path, csv_path)
        if state is None:
            from ..parsing.state import GameState

            state = GameState()
        GridWindow(
            state,
            csv_index,
            csv_items,
            log_path=log_path,
            board_mode=board_mode,
            snapshot_path=sp,
            snapshot_export_overlay=snapshot_export_overlay,
        ).run()
        return

    snapshots, csv_index, csv_items = parse_last_game_rounds(log_path, csv_path)
    if not snapshots:
        raise RuntimeError("未找到任何对局数据，请确认日志文件包含游戏记录。")
    first_state = snapshots[0][1]
    GridWindow(
        first_state,
        csv_index,
        csv_items,
        snapshots=snapshots,
        board_mode=board_mode,
        snapshot_path=sp,
        snapshot_export_overlay=snapshot_export_overlay,
    ).run()


def _show_start_page(default_log: str, csv_path: str) -> None:
    root = tk.Tk()
    root.title(f"BidKing 鉴影可视化 v{__version__} - 启动")

    log_var = tk.StringVar(value=default_log)
    mode_var = tk.StringVar(value="replay")
    board_var = tk.StringVar(value="elsa")

    frame = tk.Frame(root, padx=14, pady=12)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="Log 文件路径").pack(anchor="w")
    path_row = tk.Frame(frame)
    path_row.pack(fill="x", pady=(2, 8))
    tk.Entry(path_row, textvariable=log_var, width=60).pack(side="left", fill="x", expand=True)

    def browse_log() -> None:
        chosen = filedialog.askopenfilename(
            title="选择 Player.log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )
        if chosen:
            log_var.set(chosen)

    tk.Button(path_row, text="浏览…", command=browse_log).pack(side="left", padx=(6, 0))

    tk.Radiobutton(frame, text="回放", variable=mode_var, value="replay").pack(anchor="w")
    tk.Radiobutton(frame, text="实时 tail", variable=mode_var, value="tail").pack(anchor="w")
    tk.Label(frame, text="看板角色").pack(anchor="w", pady=(8, 0))
    tk.Radiobutton(frame, text="艾莎", variable=board_var, value="elsa").pack(anchor="w")
    # tk.Radiobutton(frame, text="拉文", variable=board_var, value="raven").pack(anchor="w")

    def start() -> None:
        log_path = log_var.get().strip()
        if not os.path.exists(log_path):
            messagebox.showerror("错误", f"找不到日志文件:\n{log_path}")
            return
        if not os.path.exists(csv_path):
            messagebox.showerror("错误", f"找不到物品数据:\n{csv_path}")
            return
        tail = mode_var.get() == "tail"
        board_mode = board_var.get()
        root.destroy()
        try:
            _open_grid(log_path, csv_path, tail, board_mode=board_mode, snapshot_path=None)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("启动失败", str(exc))

    tk.Button(frame, text="启动", command=start).pack(anchor="e", pady=(10, 0))
    root.mainloop()


def _run_history_backfill(
    log_path: str | None,
    csv_path: str,
    *,
    overwrite: bool,
) -> None:
    """启动时把日志里所有"已结束"的对局补录到独立的历史 CSV；失败静默忽略。"""
    if not log_path or not os.path.exists(log_path) or not os.path.exists(csv_path):
        return
    try:
        from ..parsing.game_report_csv import backfill_history_game_reports_csv

        result = backfill_history_game_reports_csv(
            log_path, csv_path, overwrite=overwrite,
        )
        if result is None:
            return
        out, wrote = result
        if wrote > 0:
            print(f"[history-report] 已写出 {wrote} 局到 {out}", file=sys.stderr)
        else:
            print(f"[history-report] 已存在，跳过：{out}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[history-report] 跳过：{exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    from ..parsing.game_report_csv import init_game_report_csv_session

    init_game_report_csv_session()

    parser = argparse.ArgumentParser(description=f"BidKing 物品格局可视化 v{__version__}")
    parser.add_argument("--log", default=None, help="日志文件路径")
    parser.add_argument(
        "--csv",
        default=resource_path("item_prices.csv"),
        help="物品 CSV 路径",
    )
    parser.add_argument("--tail", action="store_true", help="实时监听模式")
    # parser.add_argument("--raven", action="store_true", help="拉文看板")
    parser.add_argument(
        "--snapshot-path",
        default=None,
        help="覆盖快照写出路径；省略时优先用 configs 合并结果中的 board_snapshot.path",
    )
    parser.add_argument("--snapshot-no-overlay", action="store_true", help="快照不含 grid_overlay")
    parser.add_argument(
        "--no-history-report",
        action="store_true",
        help="禁用启动时把历史对局补录到 game_match_reports_history_<启动时间>.csv",
    )
    parser.add_argument(
        "--history-report-overwrite",
        action="store_true",
        help="若本次启动的历史 CSV 已存在，强制覆盖重写",
    )
    args = parser.parse_args(argv)

    board_mode = "elsa"

    if argv is None and len(sys.argv) == 1:
        if not args.no_history_report:
            _run_history_backfill(
                _default_log_path(), args.csv,
                overwrite=args.history_report_overwrite,
            )
        _show_start_page(_default_log_path(), args.csv)
        return

    log_path = args.log
    if log_path is None:
        for cand in (DEFAULT_GAME_LOG, LOCAL_LOG, LOCAL_COPY_LOG):
            if os.path.exists(cand):
                log_path = cand
                break
        else:
            print("错误: 找不到日志文件。请用 --log 指定。", file=sys.stderr)
            sys.exit(1)

    csv_path = args.csv
    if not os.path.exists(csv_path):
        print(f"错误: 找不到 CSV 文件: {csv_path}", file=sys.stderr)
        sys.exit(1)

    if not args.no_history_report:
        _run_history_backfill(
            log_path, csv_path,
            overwrite=args.history_report_overwrite,
        )

    snap = (args.snapshot_path or "").strip() or None
    _open_grid(
        log_path,
        csv_path,
        args.tail,
        board_mode=board_mode,
        snapshot_path=snap,
        snapshot_export_overlay=not args.snapshot_no_overlay,
    )


if __name__ == "__main__":
    main()
