#!/usr/bin/env python3
"""Bot 自动化总控 GUI（``BidKingApp``）。

只保留启动 bot 必须的「选图 / 局数（次数×循环）与循环间休息 / 自动化脚本 / 道具回合 / 启动停止」
表单 + 运行日志。

出价参数、棋盘快照（self_user_uid 等）与主配置 / 地图 JSON 编辑器已迁移到
``bidking.runner.viewer_main`` 启动页的「策略配置」标签页（``BotConfigPanel``）。
bot 总控窗口本身**不再**编辑或写出这些字段，仅在点「开启」前从磁盘
``configs/`` 读取已保存的值；若 ``board_snapshot.self_user_uid`` 为空，可依赖
进程内跨对局 UID 推断（见 ``bidking.pricing._self_uid_inference``）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta
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
    "艾哈迈德跑刀": "fresh_bidking_bot",
    "艾莎通用": "fresh_aisha_bot",
    "通用角色（全角色）": "fresh_aisha_bot",
}
BOT_RUNNER_COMBO_VALUES = tuple(BOT_RUNNER_LABEL_TO_KEY.keys())


def _parse_positive_int(text: object, *, default: int = 1) -> int:
    s = str(text).strip()
    if s.isdigit() and int(s) > 0:
        return int(s)
    return default


def _parse_nonnegative_int(text: object, *, default: int = 0) -> int:
    s = str(text).strip()
    if s.isdigit():
        return int(s)
    return default


def _parse_nonnegative_minutes(text: object, *, default: float = 1.0) -> float:
    s = str(text).strip().replace(",", ".")
    if not s:
        return default
    try:
        v = float(s)
    except ValueError:
        return default
    return max(0.0, v)


def _format_minutes_for_entry(value: object) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        x = 1.0
    if x < 0:
        x = 0.0
    if x == int(x):
        return str(int(x))
    return format(x, "g")


def _parse_clock_hour(text: object, *, default: int = 8) -> int:
    s = str(text).strip()
    if s.isdigit():
        return max(0, min(23, int(s)))
    return default


def _parse_clock_minute(text: object, *, default: int = 0) -> int:
    s = str(text).strip()
    if s.isdigit():
        return max(0, min(59, int(s)))
    return default


def _seconds_until_local_time(hour: int, minute: int, *, now: datetime | None = None) -> int:
    """距本地 ``hour:minute`` 的秒数；若今日该时刻已过则等到次日。"""
    current = now or datetime.now()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return max(0, int((target - current).total_seconds()))


def _format_countdown(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}小时{m:02d}分{s:02d}秒"
    if m:
        return f"{m}分{s:02d}秒"
    return f"{s}秒"


def _bot_runner_label_from_config(cfg: dict) -> str:
    """与 :func:`resolve_bot_runner` 一致地还原下拉显示文案（aisha 与通用共用同一脚本键）。"""
    key = resolve_bot_runner(cfg)
    role = str((cfg.get("advisor") or {}).get("role", "")).strip().lower()
    if key == "fresh_aisha_bot" and role == "universal":
        return "通用角色（全角色）"
    if key == "fresh_aisha_bot":
        return "艾莎通用"
    return "艾哈迈德跑刀"


def resolve_bot_runner(cfg: dict) -> str:
    auto = cfg.get("automation") or {}
    br = auto.get("bot_runner")
    if br == "aisha_idle_bot":
        return "fresh_aisha_bot"
    if br in ("fresh_bidking_bot", "fresh_aisha_bot"):
        return br
    role = str((cfg.get("advisor") or {}).get("role", "")).strip().lower()
    if role == "universal":
        return "fresh_aisha_bot"
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
            self.root.geometry("640x720")
        else:
            self.root.title(f"竞拍之王助手 v{__version__}")
            self.root.geometry("640x660")
        self.root.minsize(300, 520)

        self.worker: threading.Thread | None = None
        self.stop_requested = False
        self._schedule_after_id: str | None = None
        self._scheduled_remaining_sec: int = 0
        self._scheduled_target_label: str = ""
        self.original_log = bot.log
        bot.log = GuiLogger(self.append_log)

        self.runtime_base: dict = {}
        self.overlay: dict = {}
        self.config: dict = {}
        self.reload_config_sources(initial=True)

        self.map_var = tk.StringVar()
        self.runs_var = tk.StringVar()
        self.cycles_var = tk.StringVar()
        self.rest_minutes_var = tk.StringVar()
        self.tool_round_vars: dict[int, tk.BooleanVar] = {}
        self.aisha_round4_vacant_gate_var = tk.BooleanVar(value=False)
        self.aisha_round4_min_vacant_var = tk.StringVar(value="5")
        self.bot_runner_var = tk.StringVar(value=BOT_RUNNER_COMBO_VALUES[0])
        self.scheduled_start_enabled_var = tk.BooleanVar(value=False)
        self.scheduled_start_hour_var = tk.StringVar(value="8")
        self.scheduled_start_minute_var = tk.StringVar(value="0")
        self.shutdown_after_run_enabled_var = tk.BooleanVar(value=False)
        self.shutdown_after_run_delay_var = tk.StringVar(value="60")

        self.build_ui()
        self.load_into_form()
        try:
            from ..interaction.public_blacklist_sync import (
                schedule_public_blacklist_sync_on_startup,
            )

            schedule_public_blacklist_sync_on_startup(self.config)
        except Exception as exc:
            print(
                f"[bidking] 公共黑名单启动同步未安排: {exc}",
                file=sys.stderr,
            )
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
            text="游戏分辨率 1920×1080（请与游戏窗口一致后再启动自动化）\n\
             合理使用 切勿长时间挂机 风险自负",
            foreground="#c02020",
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

        settings_box = ttk.LabelFrame(main, text="1. 选图与局数（次数×循环）", padding=10)
        settings_box.pack(fill="x", pady=(0, 8))

        ttk.Label(settings_box, text="地图").grid(row=0, column=0, sticky="w", pady=4)
        self.map_combo = ttk.Combobox(
            settings_box, textvariable=self.map_var, state="readonly", width=20,
        )
        self.refresh_map_combo_from_config()
        self.map_combo.grid(row=0, column=1, sticky="w", pady=4)
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_combo_selected)

        run_row = ttk.Frame(settings_box)
        run_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(run_row, text="次数").pack(side="left")
        ttk.Entry(run_row, textvariable=self.runs_var, width=6).pack(side="left", padx=(4, 0))
        ttk.Label(run_row, text="×").pack(side="left", padx=(6, 6))
        ttk.Label(run_row, text="循环").pack(side="left")
        ttk.Entry(run_row, textvariable=self.cycles_var, width=5).pack(side="left", padx=(4, 0))
        ttk.Label(run_row, text="休息").pack(side="left", padx=(10, 0))
        ttk.Entry(run_row, textvariable=self.rest_minutes_var, width=6).pack(side="left", padx=(4, 0))
        ttk.Label(run_row, text="分钟").pack(side="left", padx=(4, 0))
        self.executed_runs_label = ttk.Label(
            run_row,
            text="（已执行 0 次）",
            foreground="#555555",
        )
        self.executed_runs_label.pack(side="left", padx=(14, 0))

        ttk.Label(settings_box, text="自动化脚本").grid(row=2, column=0, sticky="w", pady=4)
        self.bot_runner_combo = ttk.Combobox(
            settings_box,
            textvariable=self.bot_runner_var,
            state="readonly",
            width=34,
            values=BOT_RUNNER_COMBO_VALUES,
        )
        self.bot_runner_combo.grid(row=2, column=1, sticky="w", pady=4)

        schedule_row = ttk.Frame(settings_box)
        schedule_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(
            schedule_row,
            text="定时启动",
            variable=self.scheduled_start_enabled_var,
        ).pack(side="left")
        ttk.Label(schedule_row, text="  时").pack(side="left", padx=(8, 0))
        ttk.Entry(
            schedule_row, textvariable=self.scheduled_start_hour_var, width=3,
        ).pack(side="left", padx=(2, 0))
        ttk.Label(schedule_row, text="分").pack(side="left", padx=(6, 0))
        ttk.Entry(
            schedule_row, textvariable=self.scheduled_start_minute_var, width=3,
        ).pack(side="left", padx=(2, 0))
        ttk.Label(
            schedule_row,
            text="（点「开启」后等到该时刻再跑；已过则次日；可点「停止」取消）",
            foreground="#555555",
        ).pack(side="left", padx=(8, 0))

        shutdown_row = ttk.Frame(settings_box)
        shutdown_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(
            shutdown_row,
            text="跑完自动关机",
            variable=self.shutdown_after_run_enabled_var,
        ).pack(side="left")
        ttk.Label(shutdown_row, text="  延迟").pack(side="left", padx=(8, 0))
        ttk.Entry(
            shutdown_row, textvariable=self.shutdown_after_run_delay_var, width=4,
        ).pack(side="left", padx=(2, 0))
        ttk.Label(shutdown_row, text="秒").pack(side="left")
        ttk.Label(
            shutdown_row,
            text="（仅达目标局数正常结束；F9/停止不关机；CMD 执行 shutdown /a 可取消）",
            foreground="#555555",
        ).pack(side="left", padx=(8, 0))

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

        aisha_tool_row = ttk.Frame(tool_rounds_box)
        aisha_tool_row.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(
            aisha_tool_row,
            text="艾莎第4回合：按空置格决定是否用道具",
            variable=self.aisha_round4_vacant_gate_var,
        ).pack(side="left")
        ttk.Label(aisha_tool_row, text="（空置格 >=").pack(side="left", padx=(8, 0))
        ttk.Entry(
            aisha_tool_row, textvariable=self.aisha_round4_min_vacant_var, width=4,
        ).pack(side="left", padx=(2, 0))
        ttk.Label(
            aisha_tool_row, text=" 才用；需勾选第4回合；开启后第5回合禁用道具）",
        ).pack(side="left")

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
        self.cycles_var.set(str(_parse_positive_int(auto.get("run_cycles", 1), default=1)))
        self.rest_minutes_var.set(_format_minutes_for_entry(auto.get("cycle_rest_minutes", 1.0)))
        tool_rounds = {int(r) for r in auto.get("tool_rounds", [1, 2])}
        for round_no, var in self.tool_round_vars.items():
            var.set(round_no in tool_rounds)
        self.aisha_round4_vacant_gate_var.set(
            bool(auto.get("enable_aisha_round4_tool_vacant_gate", False))
        )
        min_vacant = auto.get("aisha_round4_tool_min_vacant")
        if min_vacant is None:
            min_vacant = auto.get("tool_skip_vacant_threshold", 5)
        self.aisha_round4_min_vacant_var.set(str(min_vacant))
        self.bot_runner_var.set(_bot_runner_label_from_config(self.config))
        self.scheduled_start_enabled_var.set(bool(auto.get("scheduled_start_enabled", False)))
        self.scheduled_start_hour_var.set(
            str(_parse_clock_hour(auto.get("scheduled_start_hour", 8))),
        )
        self.scheduled_start_minute_var.set(
            str(_parse_clock_minute(auto.get("scheduled_start_minute", 0))),
        )
        self.shutdown_after_run_enabled_var.set(
            bool(auto.get("shutdown_after_run_enabled", False)),
        )
        self.shutdown_after_run_delay_var.set(
            str(_parse_nonnegative_int(auto.get("shutdown_after_run_delay_seconds", 60), default=60)),
        )

    def _validate_disk_board_snapshot(self) -> None:
        """检查磁盘上的 ``board_snapshot`` 路径等；己方 UID 可留空以使用跨对局推断。"""
        self.reload_config_sources()

    def apply_form_to_config(self) -> None:
        """把「自动化」页的表单写入 overlay 并落盘。

        本方法**不再**修改 pricing / board_snapshot / 地图 overlay JSON；
        那些字段必须事先由 grid_view 启动页的「策略配置」标签页编辑保存。
        """
        self._validate_disk_board_snapshot()

        runs_value = _parse_positive_int(self.runs_var.get(), default=1)
        cycles_value = _parse_positive_int(self.cycles_var.get(), default=1)
        rest_minutes_value = _parse_nonnegative_minutes(self.rest_minutes_var.get(), default=1.0)
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
        if runner_label == "通用角色（全角色）":
            advisor_role = "universal"
        elif runner_key == "fresh_aisha_bot":
            advisor_role = "aisha"
        else:
            advisor_role = "ahmad"

        self.config.setdefault("automation", {})
        self.config["automation"]["bot_runner"] = runner_key
        self.config["automation"]["selected_mode"] = selected_mode
        self.config["automation"]["selected_map"] = selected_map
        self.config["automation"]["selected_runs"] = runs_value
        self.config["automation"]["run_cycles"] = cycles_value
        self.config["automation"]["cycle_rest_minutes"] = rest_minutes_value
        self.config["automation"]["tool_rounds"] = selected_tool_rounds
        min_vacant_value = _parse_positive_int(
            self.aisha_round4_min_vacant_var.get(), default=5,
        )
        self.config["automation"]["enable_aisha_round4_tool_vacant_gate"] = bool(
            self.aisha_round4_vacant_gate_var.get()
        )
        self.config["automation"]["aisha_round4_tool_min_vacant"] = min_vacant_value
        scheduled_enabled = bool(self.scheduled_start_enabled_var.get())
        scheduled_hour = _parse_clock_hour(self.scheduled_start_hour_var.get(), default=8)
        scheduled_minute = _parse_clock_minute(
            self.scheduled_start_minute_var.get(), default=0,
        )
        self.config["automation"]["scheduled_start_enabled"] = scheduled_enabled
        self.config["automation"]["scheduled_start_hour"] = scheduled_hour
        self.config["automation"]["scheduled_start_minute"] = scheduled_minute
        shutdown_enabled = bool(self.shutdown_after_run_enabled_var.get())
        shutdown_delay = _parse_nonnegative_int(
            self.shutdown_after_run_delay_var.get(), default=60,
        )
        self.config["automation"]["shutdown_after_run_enabled"] = shutdown_enabled
        self.config["automation"]["shutdown_after_run_delay_seconds"] = shutdown_delay
        self.config.setdefault("advisor", {})["role"] = advisor_role

        self.overlay.setdefault("automation", {})
        self.overlay["automation"]["bot_runner"] = runner_key
        self.overlay["automation"]["selected_mode"] = selected_mode
        self.overlay["automation"]["selected_map"] = selected_map
        self.overlay["automation"]["selected_runs"] = runs_value
        self.overlay["automation"]["run_cycles"] = cycles_value
        self.overlay["automation"]["cycle_rest_minutes"] = rest_minutes_value
        self.overlay["automation"]["tool_rounds"] = selected_tool_rounds
        self.overlay["automation"]["enable_aisha_round4_tool_vacant_gate"] = bool(
            self.aisha_round4_vacant_gate_var.get()
        )
        self.overlay["automation"]["aisha_round4_tool_min_vacant"] = min_vacant_value
        self.overlay["automation"]["scheduled_start_enabled"] = scheduled_enabled
        self.overlay["automation"]["scheduled_start_hour"] = scheduled_hour
        self.overlay["automation"]["scheduled_start_minute"] = scheduled_minute
        self.overlay["automation"]["shutdown_after_run_enabled"] = shutdown_enabled
        self.overlay["automation"]["shutdown_after_run_delay_seconds"] = shutdown_delay
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

    def _run_progress_sink(self, completed: int, _max_runs: int) -> None:
        """由 bot 线程调用，在主线程刷新「已执行」标签。"""

        def _apply() -> None:
            try:
                self.executed_runs_label.configure(text=f"（已执行 {completed} 次）")
            except tk.TclError:
                pass

        try:
            self.root.after(0, _apply)
        except tk.TclError:
            pass

    def _cancel_scheduled_start(self) -> None:
        if self._schedule_after_id is not None:
            try:
                self.root.after_cancel(self._schedule_after_id)
            except tk.TclError:
                pass
            self._schedule_after_id = None
        self._scheduled_remaining_sec = 0
        self._scheduled_target_label = ""

    def _begin_start_ui(self) -> None:
        self.stop_requested = False
        bot.reset_stop()
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        try:
            self.executed_runs_label.configure(text="（已执行 0 次）")
        except tk.TclError:
            pass

    def _launch_bot_worker(self) -> None:
        self._cancel_scheduled_start()
        self.append_log("GUI start: bot thread launching")

        sink = self._run_progress_sink

        def runner():
            try:
                rk = self.config.get("automation", {}).get(
                    "bot_runner", "fresh_bidking_bot",
                )
                if rk == "aisha_idle_bot":
                    rk = "fresh_aisha_bot"
                if rk == "fresh_aisha_bot":
                    from ..interaction._legacy_bot import run_aisha_loop

                    run_aisha_loop(CONFIG_OVERLAY_PATH, progress_sink=sink)
                else:
                    bot.run_loop(CONFIG_OVERLAY_PATH, progress_sink=sink)
            except bot.StopRequested:
                self.append_log("GUI stop: stopped")
            except Exception as exc:  # noqa: BLE001
                from ..interaction.bot_startup_gate import BotStartupBlocked

                if isinstance(exc, BotStartupBlocked):
                    self.append_log(str(exc))
                    return
                self.append_log(traceback.format_exc())
            finally:
                self.root.after(0, self.on_worker_done)

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def _schedule_start_tick(self) -> None:
        self._schedule_after_id = None
        if self.stop_requested:
            return
        if self._scheduled_remaining_sec <= 0:
            self.append_log(f"定时到达（{self._scheduled_target_label}），正在启动 bot…")
            try:
                self.executed_runs_label.configure(text="（已执行 0 次）")
            except tk.TclError:
                pass
            self._launch_bot_worker()
            return

        try:
            self.executed_runs_label.configure(
                text=(
                    f"（定时 {self._scheduled_target_label}，"
                    f"还剩 {_format_countdown(self._scheduled_remaining_sec)}）"
                ),
            )
        except tk.TclError:
            pass

        if self._scheduled_remaining_sec % 60 == 0 or self._scheduled_remaining_sec <= 10:
            self.append_log(
                f"定时启动：目标 {self._scheduled_target_label}，"
                f"还剩 {_format_countdown(self._scheduled_remaining_sec)}",
            )

        self._scheduled_remaining_sec -= 1
        if self._scheduled_remaining_sec <= 0:
            self.append_log(f"定时到达（{self._scheduled_target_label}），正在启动 bot…")
            try:
                self.executed_runs_label.configure(text="（已执行 0 次）")
            except tk.TclError:
                pass
            self._launch_bot_worker()
            return

        self._schedule_after_id = self.root.after(1000, self._schedule_start_tick)

    def _arm_scheduled_start(self, hour: int, minute: int) -> None:
        delay_sec = _seconds_until_local_time(hour, minute)
        self._scheduled_target_label = f"{hour:02d}:{minute:02d}"
        self._scheduled_remaining_sec = delay_sec
        self._begin_start_ui()
        self.append_log(
            f"定时启动已设置：将于 {self._scheduled_target_label} 开跑"
            f"（约 {_format_countdown(delay_sec)} 后；可点「停止」取消）",
        )
        try:
            self.executed_runs_label.configure(
                text=(
                    f"（定时 {self._scheduled_target_label}，"
                    f"还剩 {_format_countdown(delay_sec)}）"
                ),
            )
        except tk.TclError:
            pass
        self._schedule_after_id = self.root.after(1000, self._schedule_start_tick)

    def start_bot(self) -> None:
        if self._schedule_after_id is not None:
            messagebox.showinfo("提示", "定时启动倒计时中，请先点「停止」取消")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "脚本已经在运行中")
            return
        try:
            self.apply_form_to_config()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("配置错误", str(exc))
            return

        from ..interaction.bot_startup_gate import BotStartupBlocked, ensure_bot_startup_allowed

        try:
            ensure_bot_startup_allowed(self.config)
        except BotStartupBlocked as exc:
            messagebox.showerror("Bot 不可用", str(exc))
            return

        auto = self.config.get("automation") or {}
        if auto.get("scheduled_start_enabled"):
            hour = _parse_clock_hour(auto.get("scheduled_start_hour", 8))
            minute = _parse_clock_minute(auto.get("scheduled_start_minute", 0))
            self._arm_scheduled_start(hour, minute)
            return

        self._begin_start_ui()
        self._launch_bot_worker()

    def stop_bot(self) -> None:
        if self._schedule_after_id is not None or self._scheduled_remaining_sec > 0:
            self.stop_requested = True
            self._cancel_scheduled_start()
            self.append_log("GUI stop: 已取消定时启动")
            self.on_worker_done()
            return
        bot.request_stop()
        self.stop_btn.state(["disabled"])
        self.append_log("GUI stop: requested")

    def on_worker_done(self) -> None:
        try:
            self.executed_runs_label.configure(text="（已执行 0 次）")
        except tk.TclError:
            pass
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])

    def on_close(self) -> None:
        self.stop_requested = True
        self._cancel_scheduled_start()
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
