#!/usr/bin/env python3
"""Bot 自动化总控 GUI（``BidKingApp``）。

只保留启动 bot 必须的「选图 / 重复轮数 / 自动化脚本 / 道具回合 / 启动停止」
表单 + 运行日志。

出价参数、棋盘快照（self_user_uid 等）与主配置 / 地图 JSON 编辑器已迁移到
``bidking.runner.viewer_main`` 启动页的「策略配置」标签页（``BotConfigPanel``）。
bot 总控窗口本身**不再**编辑或写出这些字段，仅在点「开启」前从磁盘
``configs/`` 读取已保存的值；若 ``board_snapshot.self_user_uid`` /
``self_name_substring`` 都为空（且未通过环境变量提供），会提示用户先去
grid_view 启动页的「策略配置」里填写。
"""
from __future__ import annotations

import json
import os
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .. import __version__
from ..interaction import _legacy_bot as bot
from ..config.map_runtime_overlay import (
    automation_maps_sorted_keys,
    resolve_automation_map_config_key,
)
from ..config.paths import config_overlay_path, runtime_path
from ..config.pricing import deep_merge
from ..config.runtime import apply_board_snapshot_env_overrides


ROOT = Path(__file__).resolve().parent
CONFIG_OVERLAY_PATH = config_overlay_path()

BOT_RUNNER_LABEL_TO_KEY = {
    "ahmad跑刀": "fresh_bidking_bot",
    "aisha通用": "fresh_aisha_bot",
}
BOT_RUNNER_KEY_TO_LABEL = {value: key for key, value in BOT_RUNNER_LABEL_TO_KEY.items()}
BOT_RUNNER_COMBO_VALUES = tuple(BOT_RUNNER_LABEL_TO_KEY.keys())


def resolve_bot_runner(cfg: dict) -> str:
    auto = cfg.get("automation") or {}
    br = auto.get("bot_runner")
    if br in ("fresh_bidking_bot", "fresh_aisha_bot"):
        return br
    role = str((cfg.get("advisor") or {}).get("role", "")).strip().lower()
    if role in ("aisha", "elsa"):
        return "fresh_aisha_bot"
    sm = str(auto.get("selected_mode", "")).strip().lower()
    if sm == "aisha_premium":
        return "fresh_aisha_bot"
    return "fresh_bidking_bot"


class GuiLogger:
    def __init__(self, write_line):
        self.write_line = write_line

    def __call__(self, message: str, *, gui_verbose_only: bool = False) -> None:
        if gui_verbose_only and not bot.gui_log_verbose():
            return
        self.write_line(message)


class BidKingApp:
    def __init__(self, root: tk.Tk | tk.Toplevel):
        self.root = root
        if isinstance(self.root, tk.Toplevel):
            self.root.title(f"竞拍之王助手 — Bot 总控 v{__version__}")
            self.root.geometry("520x700")
        else:
            self.root.title(f"竞拍之王助手 v{__version__}")
            self.root.geometry("520x640")
        self.root.minsize(300, 520)

        self.worker: threading.Thread | None = None
        self.stop_requested = False
        self.original_log = bot.log
        bot.log = GuiLogger(self.append_log)

        self.runtime_base: dict = {}
        self.overlay: dict = {}
        self.config: dict = {}
        self.reload_config_sources(initial=True)

        self.map_var = tk.StringVar()
        self.runs_var = tk.StringVar()
        self.tool_round_vars: dict[int, tk.BooleanVar] = {}
        self.bot_runner_var = tk.StringVar(value=BOT_RUNNER_COMBO_VALUES[0])

        self.build_ui()
        self.load_into_form()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ── 配置加载/合并 ──────────────────────────────────────────────────────

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def save_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _rebuild_merged_config(self) -> None:
        self.config = deep_merge(self.runtime_base, self.overlay)
        apply_board_snapshot_env_overrides(self.config)

    def reload_config_sources(self, *, initial: bool = False) -> None:
        rp = runtime_path()
        self.runtime_base = self.load_json(rp) if rp.is_file() else {}
        self.overlay = (
            self.load_json(CONFIG_OVERLAY_PATH) if CONFIG_OVERLAY_PATH.is_file() else {}
        )
        self._rebuild_merged_config()
        if not initial and hasattr(self, "map_combo"):
            self.refresh_map_combo_from_config()

    # ── UI 构建 ─────────────────────────────────────────────────────────────

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        tip_box = ttk.Frame(main)
        tip_box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            tip_box,
            text="游戏分辨率 1920×1080（请与游戏窗口一致后再启动自动化）。",
            foreground="#2a5a8a",
            font=("", 10, "bold"),
            wraplength=480,
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            tip_box,
            text=(
                "出价参数 / 棋盘快照 / 主配置 JSON 请到 grid_view 启动页的"
                "「策略配置」标签里维护；本窗口仅负责启动 bot。"
            ),
            foreground="#557755",
            wraplength=480,
        ).pack(anchor="w")

        settings_box = ttk.LabelFrame(main, text="1. 选图与重复轮数", padding=10)
        settings_box.pack(fill="x", pady=(0, 8))

        ttk.Label(settings_box, text="地图").grid(row=0, column=0, sticky="w", pady=4)
        self.map_combo = ttk.Combobox(
            settings_box, textvariable=self.map_var, state="readonly", width=20,
        )
        self.refresh_map_combo_from_config()
        self.map_combo.grid(row=0, column=1, sticky="w", pady=4)
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_combo_selected)

        ttk.Label(settings_box, text="重复次数").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings_box, textvariable=self.runs_var, width=10).grid(
            row=1, column=1, sticky="w", pady=4,
        )

        ttk.Label(settings_box, text="自动化脚本").grid(row=2, column=0, sticky="w", pady=4)
        self.bot_runner_combo = ttk.Combobox(
            settings_box,
            textvariable=self.bot_runner_var,
            state="readonly",
            width=34,
            values=BOT_RUNNER_COMBO_VALUES,
        )
        self.bot_runner_combo.grid(row=2, column=1, sticky="w", pady=4)

        button_box = ttk.LabelFrame(main, text="2. 控制 F9强制停止", padding=10)
        button_box.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(button_box, text="开启", command=self.start_bot)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(button_box, text="停止", command=self.stop_bot)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.stop_btn.state(["disabled"])

        tool_rounds_box = ttk.LabelFrame(main, text="3. 道具使用回合", padding=10)
        tool_rounds_box.pack(fill="x", pady=(10, 0))
        ttk.Label(
            tool_rounds_box, text="勾选后，该回合会自动使用最左边道具。",
        ).pack(side="left", padx=(0, 12))
        for round_no in range(1, 6):
            var = tk.BooleanVar(value=round_no in (1, 2))
            self.tool_round_vars[round_no] = var
            ttk.Checkbutton(
                tool_rounds_box, text=f"第{round_no}回合", variable=var,
            ).pack(side="left", padx=(0, 8))

        log_box = ttk.LabelFrame(main, text="运行日志 / Debug", padding=10)
        log_box.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_box, height=20, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    # ── 模型 ↔ 表单 ────────────────────────────────────────────────────────

    def refresh_map_combo_from_config(self) -> None:
        if not hasattr(self, "map_combo"):
            return
        auto = self.config.get("automation") or {}
        maps = auto.get("maps") or {}
        try:
            keys = automation_maps_sorted_keys(maps)
            self.map_combo["values"] = [
                f"{k}. {maps[k].get('name', k)}" for k in keys
            ]
        except (KeyError, TypeError):
            self.map_combo["values"] = []

    def _on_map_combo_selected(self, _event: tk.Event | None = None) -> None:
        pass

    def selected_map_key(self) -> str:
        text = self.map_var.get().strip()
        return text.split(".", 1)[0].strip() if "." in text else text

    def effective_map_key(self) -> str:
        mk = self.selected_map_key()
        maps = (self.config.get("automation") or {}).get("maps") or {}
        if mk and isinstance(maps, dict) and mk in maps:
            return mk
        return resolve_automation_map_config_key(self.config.get("automation") or {})

    def load_into_form(self) -> None:
        auto = self.config.get("automation") or {}
        map_key = resolve_automation_map_config_key(auto)
        maps = auto.get("maps") or {}
        item = maps.get(map_key, {}) if isinstance(maps, dict) else {}
        name = item.get("name", map_key)
        self.map_var.set(f"{map_key}. {name}" if map_key else "")
        self.runs_var.set(str(auto.get("selected_runs") or auto.get("default_runs", 1)))
        tool_rounds = {int(r) for r in auto.get("tool_rounds", [1, 2])}
        for round_no, var in self.tool_round_vars.items():
            var.set(round_no in tool_rounds)
        runner_key = resolve_bot_runner(self.config)
        self.bot_runner_var.set(
            BOT_RUNNER_KEY_TO_LABEL.get(runner_key, BOT_RUNNER_COMBO_VALUES[0]),
        )

    def _validate_disk_board_snapshot(self) -> None:
        """检查磁盘上的 ``board_snapshot`` 至少能识别己方。

        ``self_user_uid`` 或 ``self_name_substring`` 必须有一个非空（或通过
        ``BIDKING_SELF_USER_UID`` / ``BIDKING_SELF_NAME_SUBSTRING`` 环境变量
        提供）；都没有则拒绝启动并指向 grid_view 的「策略配置」标签页。
        """
        self.reload_config_sources()
        bs = self.config.get("board_snapshot") if isinstance(
            self.config.get("board_snapshot"), dict,
        ) else {}
        uid = str(
            bs.get("self_user_uid")
            or os.environ.get("BIDKING_SELF_USER_UID")
            or "",
        ).strip()
        name_sub = str(
            bs.get("self_name_substring")
            or os.environ.get("BIDKING_SELF_NAME_SUBSTRING")
            or "",
        ).strip()
        if not uid and not name_sub:
            raise ValueError(
                "未配置 board_snapshot.self_user_uid 或 self_name_substring。\n"
                "请在 grid_view 启动页的「策略配置」标签页里填写「己方 UID」"
                "或「名称关键字」并保存后再启动。",
            )

    def apply_form_to_config(self) -> None:
        """把「自动化」页的表单写入 overlay 并落盘。

        本方法**不再**修改 pricing / board_snapshot / 地图 overlay JSON；
        那些字段必须事先由 grid_view 启动页的「策略配置」标签页编辑保存。
        """
        self._validate_disk_board_snapshot()

        runs_value = (
            int(self.runs_var.get())
            if self.runs_var.get().isdigit() and int(self.runs_var.get()) > 0
            else 1
        )
        selected_map = self.selected_map_key() or self.effective_map_key()
        if not selected_map:
            selected_map = resolve_automation_map_config_key(
                self.config.get("automation") or {},
            )
        selected_tool_rounds = [
            round_no for round_no, var in self.tool_round_vars.items() if var.get()
        ]

        runner_label = self.bot_runner_var.get().strip()
        runner_key = BOT_RUNNER_LABEL_TO_KEY.get(runner_label, "fresh_bidking_bot")
        selected_mode = (
            "aisha_premium" if runner_key == "fresh_aisha_bot" else "ahmad_premium"
        )
        advisor_role = "aisha" if runner_key == "fresh_aisha_bot" else "ahmad"

        self.config.setdefault("automation", {})
        self.config["automation"]["bot_runner"] = runner_key
        self.config["automation"]["selected_mode"] = selected_mode
        self.config["automation"]["selected_map"] = selected_map
        self.config["automation"]["selected_runs"] = runs_value
        self.config["automation"]["tool_rounds"] = selected_tool_rounds
        self.config.setdefault("advisor", {})["role"] = advisor_role

        self.overlay.setdefault("automation", {})
        self.overlay["automation"]["bot_runner"] = runner_key
        self.overlay["automation"]["selected_mode"] = selected_mode
        self.overlay["automation"]["selected_map"] = selected_map
        self.overlay["automation"]["selected_runs"] = runs_value
        self.overlay["automation"]["tool_rounds"] = selected_tool_rounds
        self.overlay.setdefault("advisor", {})["role"] = advisor_role

        self.save_json(CONFIG_OVERLAY_PATH, self.overlay)
        self.config = deep_merge(self.runtime_base, self.overlay)
        apply_board_snapshot_env_overrides(self.config)

    # ── 日志 / 启停 ────────────────────────────────────────────────────────

    def append_log(self, message: str) -> None:
        line = f"[{bot.log_timestamp()}] {message}"

        def _write():
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")

        self.root.after(0, _write)

    def start_bot(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "脚本已经在运行中")
            return
        try:
            self.apply_form_to_config()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("配置错误", str(exc))
            return

        self.stop_requested = False
        bot.reset_stop()
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.append_log("GUI start: bot thread launching")

        def runner():
            try:
                rk = self.config.get("automation", {}).get(
                    "bot_runner", "fresh_bidking_bot",
                )
                if rk == "fresh_aisha_bot":
                    from ..interaction._legacy_bot import run_aisha_loop

                    run_aisha_loop(CONFIG_OVERLAY_PATH)
                else:
                    bot.run_loop(CONFIG_OVERLAY_PATH)
            except bot.StopRequested:
                self.append_log("GUI stop: stopped")
            except Exception:  # noqa: BLE001
                self.append_log(traceback.format_exc())
            finally:
                self.root.after(0, self.on_worker_done)

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def stop_bot(self) -> None:
        bot.request_stop()
        self.stop_btn.state(["disabled"])
        self.append_log("GUI stop: requested")

    def on_worker_done(self) -> None:
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])

    def on_close(self) -> None:
        bot.request_stop()
        bot.log = self.original_log
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    BidKingApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
