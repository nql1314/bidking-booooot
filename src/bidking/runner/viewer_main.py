"""画板看板入口（show_grid 等价）：解析 + 分析 + UI；可 tail / replay。"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..parsing.constants import (
    DEFAULT_GAME_LOG,
    LOCAL_COPY_LOG,
    LOCAL_LOG,
    resource_path,
)
from ..parsing._legacy_runner import parse_last_game, parse_last_game_rounds
from ..ui.grid import GridWindow


# 启动看板页顶栏说明（与历史 bot GUI 说明一致）；B 站地址单独做可点击超链接
_LAUNCH_TAB_BANNER_PREFIX = "免费分享 禁止倒卖 Q群 956946772 B站（你的关注是我最大的动力） "
_BILIBILI_SPACE_URL = "https://space.bilibili.com/1934731"


def _effective_snapshot_path_for_viewer(cli_or_none: str | None) -> str | None:
    """命令行等显式传入的非空路径优先；否则使用合并配置里的 ``board_snapshot.path``（与 bot 读同一文件）。"""
    explicit = (cli_or_none or "").strip()
    if explicit:
        return explicit
    try:
        from ..config.paths import resolve_board_snapshot_path
        from ..config.runtime import load_runtime

        bs = load_runtime().board_snapshot
        configured = str(bs.get("path") or "").strip()
        return str(resolve_board_snapshot_path(configured))
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
    home_shell: tk.Tk | None = None,
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
            home_shell=home_shell,
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
        home_shell=home_shell,
    ).run()


def _launch_bot_runner(start_root: tk.Tk) -> None:
    """在独立 ``Toplevel`` 中打开 Bot 总控，不关闭、不阻塞启动主页。"""
    attr = "_bidking_bot_shell"
    existing = getattr(start_root, attr, None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except tk.TclError:
            setattr(start_root, attr, None)

    try:
        from ..ui._legacy_gui import BidKingApp
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror("Bot 总控不可用", f"导入失败：{exc}")
        return

    top = tk.Toplevel(start_root)
    setattr(start_root, attr, top)

    def _on_bot_shell_destroy(event: tk.Event) -> None:
        if event.widget is top:
            try:
                delattr(start_root, attr)
            except AttributeError:
                pass

    top.bind("<Destroy>", _on_bot_shell_destroy)
    BidKingApp(top)


def _show_start_page(default_log: str, csv_path: str) -> None:
    root = tk.Tk()
    root.title(f"BidKing 鉴影可视化 v{__version__} - 启动")
    root.geometry("780x720")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    launch_tab = ttk.Frame(notebook)
    config_tab = ttk.Frame(notebook)
    notebook.add(launch_tab, text="启动看板")
    notebook.add(config_tab, text="策略配置")

    # ── 启动看板 tab ───────────────────────────────────────────────────────
    log_var = tk.StringVar(value=default_log)
    mode_var = tk.StringVar(value="replay")
    board_var = tk.StringVar(value="elsa")

    frame = tk.Frame(launch_tab, padx=14, pady=12)
    frame.pack(fill="both", expand=True)

    banner_row = tk.Frame(frame)
    banner_row.pack(anchor="w", fill="x", pady=(0, 10))
    tk.Label(
        banner_row,
        text=_LAUNCH_TAB_BANNER_PREFIX,
        fg="#3a4a5a",
        font=("微软雅黑", 9),
    ).pack(side="left", anchor="nw")
    bilibili_lbl = tk.Label(
        banner_row,
        text=_BILIBILI_SPACE_URL,
        fg="#0066cc",
        font=("微软雅黑", 9, "underline"),
        cursor="hand2",
        wraplength=520,
        justify="left",
    )
    bilibili_lbl.pack(side="left", anchor="nw", fill="x", expand=True)

    def _open_bilibili_space(_event: object) -> None:
        webbrowser.open(_BILIBILI_SPACE_URL)

    bilibili_lbl.bind("<Button-1>", _open_bilibili_space)

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
    tk.Radiobutton(
        frame,
        text="通用（完美适配：艾莎，老师，索菲，伊森，拉文， 其他角色技能未解析，基本可用）",
        variable=board_var,
        value="universal",
    ).pack(anchor="w")
    tk.Radiobutton(
        frame,
        text="艾哈迈德(快递站特化）",
        variable=board_var,
        value="ahmad",
    ).pack(anchor="w")
    # tk.Radiobutton(frame, text="拉文", variable=board_var, value="raven").pack(anchor="w")

    def export_history_report() -> None:
        log_path = log_var.get().strip()
        if not os.path.exists(log_path):
            messagebox.showerror("错误", f"找不到日志文件:\n{log_path}")
            return
        if not os.path.exists(csv_path):
            messagebox.showerror("错误", f"找不到物品数据:\n{csv_path}")
            return
        try:
            from ..parsing.game_report_csv import backfill_history_game_reports_csv

            # 手动导出：全量扫描当前日志；覆盖同次启动已生成的历史 CSV，避免误触后仍是旧内容
            result = backfill_history_game_reports_csv(
                log_path, csv_path, overwrite=True,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc))
            return
        if result is None:
            messagebox.showinfo(
                "历史报告",
                "未生成文件：可能没有已结束对局，或已设置环境变量 "
                "BIDKING_DISABLE_GAME_REPORT。",
            )
            return
        out, wrote = result
        if wrote > 0:
            messagebox.showinfo("历史报告", f"已写出 {wrote} 局到\n{out}")
        else:
            messagebox.showinfo("历史报告", f"未写入新行（可能日志中无已结束对局）。\n{out}")

    history_row = tk.Frame(frame)
    history_row.pack(anchor="w", pady=(10, 4))
    tk.Button(
        history_row,
        text="导出历史报告",
        command=export_history_report,
    ).pack(side="left")
    tk.Label(
        history_row,
        text="（扫描当前 Log 中全部已结束对局；启动看板不会自动导出）",
        fg="#5a6a7a",
        font=("微软雅黑", 8),
    ).pack(side="left", padx=(8, 0))

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
        root.withdraw()
        try:
            _open_grid(
                log_path,
                csv_path,
                tail,
                board_mode=board_mode,
                snapshot_path=None,
                home_shell=root,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("启动失败", str(exc))
        finally:
            try:
                root.deiconify()
                root.lift()
            except tk.TclError:
                pass

    bottom = tk.Frame(frame)
    bottom.pack(fill="x", pady=(10, 0))

    # ⚠ 谨慎使用：在独立窗口打开 Bot 总控；总控里点「开启」后会接管鼠标 / 键盘。
    # 请先在「策略配置」里核对出价参数、棋盘快照与主配置 JSON；仅在确实需要自动出价时再点。
    tk.Button(
        bottom,
        text="启动 Bot 总控（暂时不要使用 等我修复 现在会封号）",
        command=lambda: _launch_bot_runner(root),
        bg="#664422",
        fg="#ffe8c8",
        activebackground="#7a5530",
        activeforeground="#ffffff",
        relief="flat",
        padx=10,
        pady=4,
        cursor="hand2",
    ).pack(side="left")

    tk.Button(bottom, text="启动", command=start).pack(side="right")

    # ── 策略配置 tab ─────────────────────────────────────────────────────
    try:
        from ..ui._bot_config_panel import BotConfigPanel

        BotConfigPanel(config_tab)
    except Exception as exc:  # noqa: BLE001
        ttk.Label(
            config_tab,
            text=f"策略配置面板加载失败：{exc}",
            foreground="#aa3333",
            padding=20,
        ).pack(fill="both", expand=True)

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
        "--history-report",
        action="store_true",
        help="启动前把历史对局补录到 game_match_reports_history_<启动时间>.csv（默认不执行）",
    )
    parser.add_argument(
        "--history-report-overwrite",
        action="store_true",
        help="与 --history-report 同用时，若历史 CSV 已存在则强制覆盖重写",
    )
    args = parser.parse_args(argv)

    board_mode = "elsa"

    if argv is None and len(sys.argv) == 1:
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

    if args.history_report:
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
