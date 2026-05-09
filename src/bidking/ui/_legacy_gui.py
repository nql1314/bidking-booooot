#!/usr/bin/env python3
from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from ..interaction import _legacy_bot as bot
from ..config.paths import config_overlay_path, runtime_path
from ..config.pricing import deep_merge


ROOT = Path(__file__).resolve().parent
CONFIG_OVERLAY_PATH = config_overlay_path()

MAP_KEYS = ("1", "2", "3", "4", "5", "6", "7")

BOT_RUNNER_LABEL_TO_KEY = {
    "通用 bot（fresh_bidking_bot.py）": "fresh_bidking_bot",
    "艾莎入口（fresh_aisha_bot.py）": "fresh_aisha_bot",
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


def tip_text_for_bot_runner_label(label: str) -> str:
    key = BOT_RUNNER_LABEL_TO_KEY.get(label, "fresh_bidking_bot")
    if key == "fresh_aisha_bot":
        return "艾莎入口：启动时清空 board_snapshot 文件；主循环与通用 bot 相同，出价由 pricing.compute_price 计算。"
    return "通用 bot：整窗 OCR + 固定流程；出价由 pricing.compute_price（快照 pricing）驱动。"


class GuiLogger:
    def __init__(self, write_line):
        self.write_line = write_line

    def __call__(self, message: str, *, gui_verbose_only: bool = False) -> None:
        if gui_verbose_only and not bot.gui_log_verbose():
            return
        self.write_line(message)


class BidKingApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("竞拍之王助手")
        self.root.geometry("780x820")
        self.root.minsize(300, 720)

        self.worker: threading.Thread | None = None
        self.stop_requested = False
        self.original_log = bot.log
        bot.log = GuiLogger(self.append_log)

        self.runtime_base: dict = {}
        self.overlay: dict = {}
        self.reload_config_sources(initial=True)

        self.map_var = tk.StringVar()
        self.runs_var = tk.StringVar()
        self.tool_round_vars: dict[int, tk.BooleanVar] = {}
        self.bot_runner_var = tk.StringVar(value=BOT_RUNNER_COMBO_VALUES[0])
        self.config_json_auto_apply_var = tk.BooleanVar(value=True)
        self._config_json_apply_after_id: str | None = None
        self._config_editor_syncing = False

        self.build_ui()
        self.load_into_form()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def save_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def reload_config_sources(self, *, initial: bool = False) -> None:
        rp = runtime_path()
        self.runtime_base = self.load_json(rp) if rp.is_file() else {}
        self.overlay = self.load_json(CONFIG_OVERLAY_PATH) if CONFIG_OVERLAY_PATH.is_file() else {}
        self.config = deep_merge(self.runtime_base, self.overlay)
        if not initial and hasattr(self, "config_json_text"):
            self.refresh_config_json_editor_from_model()

    def build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)
        main = ttk.Frame(notebook, padding=12)
        notebook.add(main, text="自动化")
        config_page = ttk.Frame(notebook, padding=8)
        notebook.add(config_page, text="本地覆盖 (config.json)")
        self.build_config_json_tab(config_page)

        settings_box = ttk.LabelFrame(main, text="1. 选图与重复轮数", padding=10)
        settings_box.pack(fill="x", pady=(0, 8))

        ttk.Label(settings_box, text="地图").grid(row=0, column=0, sticky="w", pady=4)
        self.map_combo = ttk.Combobox(settings_box, textvariable=self.map_var, state="readonly", width=20)
        self.refresh_map_combo_from_config()
        self.map_combo.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(settings_box, text="重复次数").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings_box, textvariable=self.runs_var, width=10).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(settings_box, text="自动化脚本").grid(row=2, column=0, sticky="w", pady=4)
        self.bot_runner_combo = ttk.Combobox(
            settings_box,
            textvariable=self.bot_runner_var,
            state="readonly",
            width=34,
            values=BOT_RUNNER_COMBO_VALUES,
        )
        self.bot_runner_combo.grid(row=2, column=1, sticky="w", pady=4)

        button_box = ttk.LabelFrame(main, text="2. 控制", padding=10)
        button_box.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(button_box, text="开启", command=self.start_bot)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(button_box, text="停止", command=self.stop_bot)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.stop_btn.state(["disabled"])

        tool_rounds_box = ttk.LabelFrame(main, text="3. 道具使用回合", padding=10)
        tool_rounds_box.pack(fill="x", pady=(10, 0))
        ttk.Label(tool_rounds_box, text="勾选后，该回合会自动使用最左边道具。").pack(side="left", padx=(0, 12))
        for round_no in range(1, 6):
            var = tk.BooleanVar(value=round_no in (1, 2))
            self.tool_round_vars[round_no] = var
            ttk.Checkbutton(tool_rounds_box, text=f"第{round_no}回合", variable=var).pack(side="left", padx=(0, 8))

        tip_box = ttk.LabelFrame(main, text="4. 说明", padding=10)
        tip_box.pack(fill="x", pady=(10, 0))
        self.tip_label = ttk.Label(tip_box, text=tip_text_for_bot_runner_label(BOT_RUNNER_COMBO_VALUES[0]))
        self.tip_label.pack(anchor="w")
        self.bot_runner_combo.bind("<<ComboboxSelected>>", self._on_bot_runner_combo_change)

        log_box = ttk.LabelFrame(main, text="运行日志 / Debug", padding=10)
        log_box.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_box, height=20, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def build_config_json_tab(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x")
        ttk.Label(bar, text=f"覆盖文件: {CONFIG_OVERLAY_PATH.name}（合并自 runtime.json + 本文件）").pack(side="left")
        ttk.Checkbutton(bar, text="编辑合法后自动保存", variable=self.config_json_auto_apply_var).pack(
            side="left", padx=(14, 0)
        )
        ttk.Button(bar, text="保存", command=self.save_config_json_from_editor).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="从磁盘重载", command=self.reload_config_json_from_disk).pack(side="left", padx=(4, 0))
        self.config_json_status_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.config_json_status_var, foreground="gray").pack(side="left", padx=(10, 0))

        self.config_json_text = ScrolledText(parent, wrap="word", font=("Consolas", 10), height=32, width=92)
        self.config_json_text.pack(fill="both", expand=True, pady=(8, 0))

        self.refresh_config_json_editor_from_model()
        self.config_json_text.bind("<KeyRelease>", self._on_config_json_editor_keyrelease)

    def refresh_config_json_editor_from_model(self) -> None:
        if not hasattr(self, "config_json_text"):
            return
        self._config_editor_syncing = True
        try:
            self.config_json_text.delete("1.0", "end")
            self.config_json_text.insert("1.0", json.dumps(self.overlay, ensure_ascii=False, indent=2))
        finally:
            self._config_editor_syncing = False

    def _on_config_json_editor_keyrelease(self, event: tk.Event) -> None:  # noqa: ARG002
        if self._config_editor_syncing:
            return
        if not self.config_json_auto_apply_var.get():
            return
        if self._config_json_apply_after_id is not None:
            self.root.after_cancel(self._config_json_apply_after_id)
        self._config_json_apply_after_id = self.root.after(600, self._debounced_apply_config_json)

    def _debounced_apply_config_json(self) -> None:
        self._config_json_apply_after_id = None
        try:
            self._parse_and_apply_config_json_editor(write_file=True)
            self.config_json_status_var.set("已自动保存")
            self.refresh_map_combo_from_config()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            self.config_json_status_var.set(f"JSON 未就绪: {exc}")

    def _parse_and_apply_config_json_editor(self, *, write_file: bool) -> None:
        raw = self.config_json_text.get("1.0", "end-1c").strip()
        if not raw:
            raise ValueError("内容为空")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("根节点必须是 JSON 对象")
        self.overlay = parsed
        self.config = deep_merge(self.runtime_base, self.overlay)
        if write_file:
            self.save_json(CONFIG_OVERLAY_PATH, self.overlay)

    def save_config_json_from_editor(self) -> None:
        try:
            self._parse_and_apply_config_json_editor(write_file=True)
            self.config_json_status_var.set("已保存")
            self.refresh_map_combo_from_config()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror("主配置", f"无法保存：\n{exc}")
            self.config_json_status_var.set("保存失败")

    def reload_config_json_from_disk(self) -> None:
        try:
            self.reload_config_sources()
            self.load_into_form()
            self.config_json_status_var.set("已从磁盘加载")
        except OSError as exc:
            messagebox.showerror("主配置", str(exc))
        except json.JSONDecodeError as exc:
            messagebox.showerror("主配置", f"JSON 无效：{exc}")

    def sync_config_json_editor_to_model_for_run(self) -> None:
        if not hasattr(self, "config_json_text"):
            return
        raw = self.config_json_text.get("1.0", "end-1c").strip()
        if not raw:
            raise ValueError("「主配置」页内容为空，请填写 JSON 或点击「从磁盘重载」")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"「主配置」JSON 无效: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("「主配置」根节点必须是 JSON 对象")
        self.overlay = parsed
        self.config = deep_merge(self.runtime_base, self.overlay)

    def refresh_map_combo_from_config(self) -> None:
        if not hasattr(self, "map_combo"):
            return
        auto = self.config.get("automation") or {}
        maps = auto.get("maps") or {}
        try:
            self.map_combo["values"] = [f"{k}. {maps[k]['name']}" for k in MAP_KEYS if k in maps]
        except (KeyError, TypeError):
            self.map_combo["values"] = []

    def load_into_form(self) -> None:
        default_map = str(self.config.get("automation", {}).get("default_map", "4"))
        self.map_var.set(f"{default_map}. {self.config['automation']['maps'][default_map]['name']}")
        self.runs_var.set(str(self.config.get("automation", {}).get("default_runs", 1)))
        tool_rounds = {int(item) for item in self.config.get("automation", {}).get("tool_rounds", [1, 2])}
        for round_no, var in self.tool_round_vars.items():
            var.set(round_no in tool_rounds)
        runner_key = resolve_bot_runner(self.config)
        self.bot_runner_var.set(BOT_RUNNER_KEY_TO_LABEL.get(runner_key, BOT_RUNNER_COMBO_VALUES[0]))
        self.tip_label.config(text=tip_text_for_bot_runner_label(self.bot_runner_var.get()))

    def _on_bot_runner_combo_change(self, event: tk.Event | None = None) -> None:  # noqa: ARG002
        self.tip_label.config(text=tip_text_for_bot_runner_label(self.bot_runner_var.get()))

    def append_log(self, message: str) -> None:
        line = f"[{bot.log_timestamp()}] {message}"

        def _write():
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")

        self.root.after(0, _write)

    def selected_map_key(self) -> str:
        text = self.map_var.get().strip()
        return text.split(".", 1)[0].strip() if "." in text else text

    def apply_form_to_config(self) -> None:
        self.sync_config_json_editor_to_model_for_run()
        runs_value = int(self.runs_var.get()) if self.runs_var.get().isdigit() and int(self.runs_var.get()) > 0 else 1
        selected_map = self.selected_map_key() or "4"
        selected_tool_rounds = [round_no for round_no, var in self.tool_round_vars.items() if var.get()]

        self.config.setdefault("automation", {})
        runner_label = self.bot_runner_var.get().strip()
        runner_key = BOT_RUNNER_LABEL_TO_KEY.get(runner_label, "fresh_bidking_bot")
        self.config["automation"]["bot_runner"] = runner_key
        if runner_key == "fresh_aisha_bot":
            self.config["automation"]["selected_mode"] = "aisha_premium"
            self.config.setdefault("advisor", {})["role"] = "aisha"
        else:
            self.config["automation"]["selected_mode"] = "ahmad_premium"
            self.config.setdefault("advisor", {})["role"] = "ahmad"
        self.config["automation"]["selected_map"] = selected_map
        self.config["automation"]["selected_runs"] = runs_value
        self.config["automation"]["tool_rounds"] = selected_tool_rounds

        self.overlay.setdefault("automation", {})
        self.overlay["automation"]["bot_runner"] = self.config["automation"]["bot_runner"]
        self.overlay["automation"]["selected_mode"] = self.config["automation"]["selected_mode"]
        self.overlay["automation"]["selected_map"] = self.config["automation"]["selected_map"]
        self.overlay["automation"]["selected_runs"] = self.config["automation"]["selected_runs"]
        self.overlay["automation"]["tool_rounds"] = self.config["automation"]["tool_rounds"]
        self.overlay.setdefault("advisor", {})["role"] = self.config["advisor"]["role"]
        self.config = deep_merge(self.runtime_base, self.overlay)
        self.save_json(CONFIG_OVERLAY_PATH, self.overlay)
        self.refresh_config_json_editor_from_model()

    def start_bot(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "脚本已经在运行中")
            return
        try:
            self.apply_form_to_config()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        self.stop_requested = False
        bot.reset_stop()
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.append_log("GUI start: bot thread launching")

        def runner():
            try:
                rk = self.config.get("automation", {}).get("bot_runner", "fresh_bidking_bot")
                if rk == "fresh_aisha_bot":
                    from ..interaction._legacy_bot import run_aisha_loop

                    run_aisha_loop(CONFIG_OVERLAY_PATH)
                else:
                    bot.run_loop(CONFIG_OVERLAY_PATH)
            except bot.StopRequested:
                self.append_log("GUI stop: stopped")
            except Exception:
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
