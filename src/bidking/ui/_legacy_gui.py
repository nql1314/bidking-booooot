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
from ..config.paths import pricing_path, runtime_path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = runtime_path()
PRICE_CONFIG_PATH = pricing_path()

MAP_KEYS = ("1", "2", "3", "4", "5", "6", "7")

# GUI 下拉框文案 → 启动的脚本（与目录下 py 文件名对应）
BOT_RUNNER_LABEL_TO_KEY = {
    "艾哈迈德（OCR · fresh_bidking_bot.py）": "fresh_bidking_bot",
    "艾莎（快照 · fresh_aisha_bot.py）": "fresh_aisha_bot",
}
BOT_RUNNER_KEY_TO_LABEL = {value: key for key, value in BOT_RUNNER_LABEL_TO_KEY.items()}
BOT_RUNNER_COMBO_VALUES = tuple(BOT_RUNNER_LABEL_TO_KEY.keys())


def resolve_bot_runner(cfg: dict) -> str:
    """config.automation.bot_runner；若无则根据 advisor.role / selected_mode 推断艾莎→快照脚本。"""
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
        return "艾莎：需同时运行画板实时 tail，board_snapshot 路径与 bot 一致；回合与对手价来自快照。"
    return "艾哈迈德：优先带蓝色数量、绿白均格、绿白总格。"


RISK_OPTIONS = {
    "保守": "floor_price",
    "均衡": "avg_price",
    "激进": "avg_price_plus_25",
    "自定义": "custom_factor",
}
RISK_LABEL_BY_VALUE = {value: label for label, value in RISK_OPTIONS.items()}


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
        self.root.geometry("780x940")
        self.root.minsize(300, 860)

        self.worker: threading.Thread | None = None
        self.stop_requested = False
        self.original_log = bot.log
        bot.log = GuiLogger(self.append_log)

        self.config = self.load_json(CONFIG_PATH)
        self.price_config = self.load_json(PRICE_CONFIG_PATH)

        self.map_var = tk.StringVar()
        self.runs_var = tk.StringVar()
        self.risk_var = tk.StringVar()
        self.tool_round_vars: dict[int, tk.BooleanVar] = {}
        self.custom_risk_var = tk.StringVar()
        self.fallback_price_var = tk.StringVar()
        self.safe_guard_enabled_var = tk.BooleanVar()
        self.safe_guard_ratio_var = tk.StringVar()
        self.bid_cap_price_var = tk.StringVar()
        self.opponent_bid_sticky_ratio_var = tk.StringVar()
        self.weight_summary_var = tk.StringVar()
        self.bot_runner_var = tk.StringVar(value=BOT_RUNNER_COMBO_VALUES[0])
        self.price_config_auto_apply_var = tk.BooleanVar(value=True)
        self._price_config_apply_after_id: str | None = None
        self._price_editor_syncing = False
        self.config_json_auto_apply_var = tk.BooleanVar(value=True)
        self._config_json_apply_after_id: str | None = None
        self._config_editor_syncing = False

        self.build_ui()
        self.load_into_form()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def save_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)
        main = ttk.Frame(notebook, padding=12)
        notebook.add(main, text="自动化")
        config_page = ttk.Frame(notebook, padding=8)
        notebook.add(config_page, text="主配置 (config.json)")
        self.build_config_json_tab(config_page)
        price_page = ttk.Frame(notebook, padding=8)
        notebook.add(price_page, text="价格配置")
        self.build_price_config_tab(price_page)

        top = ttk.Frame(main)
        top.pack(fill="x")

        weight_box = ttk.LabelFrame(top, text="1. 品类权重设置", padding=10)
        weight_box.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(weight_box, text="新版逻辑按品类权重计算场景价格").pack(anchor="w")
        ttk.Label(weight_box, textvariable=self.weight_summary_var, wraplength=420, justify="left").pack(anchor="w", pady=(6, 8))
        ttk.Button(weight_box, text="设置权重", command=self.open_weight_editor).pack(anchor="w")

        settings_box = ttk.LabelFrame(top, text="2. 选图与重复轮数", padding=10)
        settings_box.pack(side="left", fill="both", expand=True)

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

        button_box = ttk.LabelFrame(main, text="3. 控制", padding=10)
        button_box.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(button_box, text="开启", command=self.start_bot)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(button_box, text="停止", command=self.stop_bot)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.stop_btn.state(["disabled"])

        tool_rounds_box = ttk.LabelFrame(main, text="5. 道具使用回合", padding=10)
        tool_rounds_box.pack(fill="x", pady=(10, 0))
        ttk.Label(tool_rounds_box, text="勾选后，该回合会自动使用最左边道具。").pack(side="left", padx=(0, 12))
        for round_no in range(1, 6):
            var = tk.BooleanVar(value=round_no in (1, 2))
            self.tool_round_vars[round_no] = var
            ttk.Checkbutton(tool_rounds_box, text=f"第{round_no}回合", variable=var).pack(side="left", padx=(0, 8))

        risk_box = ttk.LabelFrame(main, text="6. 拍卖激进度", padding=10)
        risk_box.pack(fill="x", pady=(10, 0))
        ttk.Label(risk_box, text="模式").pack(side="left")
        risk_combo = ttk.Combobox(risk_box, textvariable=self.risk_var, state="readonly", width=12)
        risk_combo["values"] = list(RISK_OPTIONS.keys())
        risk_combo.pack(side="left", padx=(8, 12))
        ttk.Label(risk_box, text="自定义倍率").pack(side="left")
        ttk.Entry(risk_box, textvariable=self.custom_risk_var, width=10).pack(side="left", padx=(8, 12))
        ttk.Label(risk_box, text="例如 -0.2=平均价80%，0.8=平均价180%").pack(side="left")

        extra_box = ttk.LabelFrame(main, text="4. 安全与出价限制", padding=10)
        extra_box.pack(fill="x", pady=(10, 0))
        row2 = ttk.Frame(extra_box)
        row2.pack(fill="x")
        ttk.Checkbutton(row2, text="安全开关", variable=self.safe_guard_enabled_var).pack(side="left")
        ttk.Label(row2, text="单回合最大加价比例").pack(side="left", padx=(12, 0))
        ttk.Entry(row2, textvariable=self.safe_guard_ratio_var, width=10).pack(side="left", padx=(8, 12))
        ttk.Label(row2, text="例如 0.5 代表超过上回合 50% 就自动取消").pack(side="left")

        row3 = ttk.Frame(extra_box)
        row3.pack(fill="x", pady=(8, 0))
        ttk.Label(row3, text="出价硬顶").pack(side="left")
        ttk.Entry(row3, textvariable=self.bid_cap_price_var, width=10).pack(side="left", padx=(8, 12))
        ttk.Label(row3, text="达到硬顶后停止继续加价，0 代表无硬顶").pack(side="left")

        row4 = ttk.Frame(extra_box)
        row4.pack(fill="x", pady=(8, 0))
        ttk.Label(row4, text="对手博弈粘性比例").pack(side="left")
        ttk.Entry(row4, textvariable=self.opponent_bid_sticky_ratio_var, width=10).pack(side="left", padx=(8, 12))
        ttk.Label(row4, text="用于第2轮起且对手价在区间内时 bid*(1+比例) 分支（非线性防黏）").pack(side="left")

        row5 = ttk.Frame(extra_box)
        row5.pack(fill="x", pady=(8, 0))
        ttk.Label(row5, text="Fallback 出价").pack(side="left")
        ttk.Entry(row5, textvariable=self.fallback_price_var, width=10).pack(side="left", padx=(8, 12))
        ttk.Label(row5, text="识别失败或被安全开关拦截时使用").pack(side="left")

        tip_box = ttk.LabelFrame(main, text="7. 道具提示", padding=10)
        tip_box.pack(fill="x", pady=(10, 0))
        self.tip_label = ttk.Label(tip_box, text=tip_text_for_bot_runner_label(BOT_RUNNER_COMBO_VALUES[0]))
        self.tip_label.pack(anchor="w")
        self.bot_runner_combo.bind("<<ComboboxSelected>>", self._on_bot_runner_combo_change)

        log_box = ttk.LabelFrame(main, text="运行日志 / Debug", padding=10)
        log_box.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_box, height=20, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def build_price_config_tab(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x")
        ttk.Label(bar, text=f"文件: {PRICE_CONFIG_PATH.name}").pack(side="left")
        ttk.Checkbutton(bar, text="编辑合法后自动保存", variable=self.price_config_auto_apply_var).pack(side="left", padx=(14, 0))
        ttk.Button(bar, text="保存", command=self.save_price_config_from_editor).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="从磁盘重载", command=self.reload_price_config_from_disk).pack(side="left", padx=(4, 0))
        self.price_config_status_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.price_config_status_var, foreground="gray").pack(side="left", padx=(10, 0))

        self.price_config_text = ScrolledText(parent, wrap="word", font=("Consolas", 10), height=32, width=92)
        self.price_config_text.pack(fill="both", expand=True, pady=(8, 0))

        self.refresh_price_config_editor_from_model()
        self.price_config_text.bind("<KeyRelease>", self._on_price_editor_keyrelease)

    def build_config_json_tab(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x")
        ttk.Label(bar, text=f"文件: {CONFIG_PATH.name}").pack(side="left")
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
            self.config_json_text.insert("1.0", json.dumps(self.config, ensure_ascii=False, indent=2))
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
        self.config = parsed
        if write_file:
            self.save_json(CONFIG_PATH, self.config)

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
            self.config = self.load_json(CONFIG_PATH)
            self.refresh_config_json_editor_from_model()
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
        self.config = parsed

    def refresh_map_combo_from_config(self) -> None:
        if not hasattr(self, "map_combo"):
            return
        auto = self.config.get("automation") or {}
        maps = auto.get("maps") or {}
        try:
            self.map_combo["values"] = [f"{k}. {maps[k]['name']}" for k in MAP_KEYS if k in maps]
        except (KeyError, TypeError):
            self.map_combo["values"] = []

    def refresh_price_config_editor_from_model(self) -> None:
        if not hasattr(self, "price_config_text"):
            return
        self._price_editor_syncing = True
        try:
            self.price_config_text.delete("1.0", "end")
            self.price_config_text.insert("1.0", json.dumps(self.price_config, ensure_ascii=False, indent=2))
        finally:
            self._price_editor_syncing = False

    def _on_price_editor_keyrelease(self, event: tk.Event) -> None:  # noqa: ARG002
        if self._price_editor_syncing:
            return
        if not self.price_config_auto_apply_var.get():
            return
        if self._price_config_apply_after_id is not None:
            self.root.after_cancel(self._price_config_apply_after_id)
        self._price_config_apply_after_id = self.root.after(600, self._debounced_apply_price_config)

    def _debounced_apply_price_config(self) -> None:
        self._price_config_apply_after_id = None
        try:
            self._parse_and_apply_price_editor(write_file=True)
            self.price_config_status_var.set("已自动保存")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            self.price_config_status_var.set(f"JSON 未就绪: {exc}")

    def _parse_and_apply_price_editor(self, *, write_file: bool) -> None:
        raw = self.price_config_text.get("1.0", "end-1c").strip()
        if not raw:
            raise ValueError("内容为空")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("根节点必须是 JSON 对象")
        self.price_config = parsed
        if write_file:
            self.save_json(PRICE_CONFIG_PATH, self.price_config)
        self.refresh_weight_summary()

    def save_price_config_from_editor(self) -> None:
        try:
            self._parse_and_apply_price_editor(write_file=True)
            self.price_config_status_var.set("已保存")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror("价格配置", f"无法保存：\n{exc}")
            self.price_config_status_var.set("保存失败")

    def reload_price_config_from_disk(self) -> None:
        try:
            self.price_config = self.load_json(PRICE_CONFIG_PATH)
            self.refresh_price_config_editor_from_model()
            self.refresh_weight_summary()
            self.price_config_status_var.set("已从磁盘加载")
        except OSError as exc:
            messagebox.showerror("价格配置", str(exc))
        except json.JSONDecodeError as exc:
            messagebox.showerror("价格配置", f"JSON 无效：{exc}")

    def sync_price_config_editor_to_model_for_run(self) -> None:
        if not hasattr(self, "price_config_text"):
            return
        raw = self.price_config_text.get("1.0", "end-1c").strip()
        if not raw:
            raise ValueError("「价格配置」页内容为空，请填写 JSON 或点击「从磁盘重载」")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"「价格配置」JSON 无效: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("「价格配置」根节点必须是 JSON 对象")
        self.price_config = parsed
        self.refresh_weight_summary()

    def load_into_form(self) -> None:
        default_map = str(self.config.get("automation", {}).get("default_map", "4"))
        self.map_var.set(f"{default_map}. {self.config['automation']['maps'][default_map]['name']}")
        self.runs_var.set(str(self.config.get("automation", {}).get("default_runs", 1)))
        self.risk_var.set("均衡")
        selected_risk = self.config.get("automation", {}).get("selected_risk", "avg_price")
        self.risk_var.set(RISK_LABEL_BY_VALUE.get(selected_risk, "均衡"))
        self.custom_risk_var.set(str(self.config.get("automation", {}).get("custom_risk_factor", 0.0)))
        self.fallback_price_var.set(str(self.config.get("pricing", {}).get("fallback_bid_price", 30000)))
        self.safe_guard_enabled_var.set(bool(self.config.get("automation", {}).get("safe_guard_enabled", False)))
        self.safe_guard_ratio_var.set(str(self.config.get("automation", {}).get("safe_guard_max_increase_ratio", 0.5)))
        self.bid_cap_price_var.set(str(self.config.get("automation", {}).get("bid_cap_price", 0)))
        self.opponent_bid_sticky_ratio_var.set(
            str(
                self.config.get("automation", {}).get(
                    "opponent_bid_sticky_ratio",
                    self.config.get("automation", {}).get("sticky_increment_ratio", 0.2),
                )
            )
        )
        tool_rounds = {int(item) for item in self.config.get("automation", {}).get("tool_rounds", [1, 2])}
        for round_no, var in self.tool_round_vars.items():
            var.set(round_no in tool_rounds)
        runner_key = resolve_bot_runner(self.config)
        self.bot_runner_var.set(BOT_RUNNER_KEY_TO_LABEL.get(runner_key, BOT_RUNNER_COMBO_VALUES[0]))
        self.tip_label.config(text=tip_text_for_bot_runner_label(self.bot_runner_var.get()))
        self.refresh_weight_summary()

    def _on_bot_runner_combo_change(self, event: tk.Event | None = None) -> None:  # noqa: ARG002
        self.tip_label.config(text=tip_text_for_bot_runner_label(self.bot_runner_var.get()))

    def append_log(self, message: str) -> None:
        # GUI replaces bot.log with GuiLogger(append_log), which bypasses
        # fresh_bidking_bot.log()'s timestamp + append_app_log; keep the same line format here.
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
        self.sync_price_config_editor_to_model_for_run()
        runs_value = int(self.runs_var.get()) if self.runs_var.get().isdigit() and int(self.runs_var.get()) > 0 else 1
        selected_map = self.selected_map_key() or "4"
        selected_risk = RISK_OPTIONS.get(self.risk_var.get().strip(), "avg_price")
        selected_tool_rounds = [round_no for round_no, var in self.tool_round_vars.items() if var.get()]
        custom_risk_factor = float(self.custom_risk_var.get().strip() or "0")
        fallback_bid_price = int(float(self.fallback_price_var.get().strip() or "30000"))
        safe_guard_ratio = float(self.safe_guard_ratio_var.get().strip() or "0")
        bid_cap_price = int(float(self.bid_cap_price_var.get().strip() or "0"))
        opponent_bid_sticky_ratio = float(self.opponent_bid_sticky_ratio_var.get().strip() or "0")

        self.config.setdefault("automation", {})
        self.config.setdefault("pricing", {})
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
        self.config["automation"]["selected_risk"] = selected_risk
        self.config["automation"]["custom_risk_factor"] = custom_risk_factor
        self.config["automation"]["safe_guard_enabled"] = bool(self.safe_guard_enabled_var.get())
        self.config["automation"]["safe_guard_max_increase_ratio"] = safe_guard_ratio
        self.config["automation"]["bid_cap_price"] = bid_cap_price
        self.config["automation"]["opponent_bid_sticky_ratio"] = opponent_bid_sticky_ratio
        self.config["automation"]["tool_rounds"] = selected_tool_rounds
        self.config["pricing"]["fallback_bid_price"] = fallback_bid_price

        self.save_json(CONFIG_PATH, self.config)
        self.refresh_config_json_editor_from_model()
        self.save_json(PRICE_CONFIG_PATH, self.price_config)

    def refresh_weight_summary(self) -> None:
        weights = self.price_config.get("category_weights", {})
        non_default = [f"cat{i}={weights.get(f'cat{i}', 1)}" for i in range(1, 11) if int(weights.get(f"cat{i}", 1)) != 1]
        if non_default:
            self.weight_summary_var.set("当前已修改: " + "，".join(non_default))
        else:
            self.weight_summary_var.set("当前全部为默认权重 1")

    def open_weight_editor(self) -> None:
        top = tk.Toplevel(self.root)
        top.title("品类权重设置")
        top.geometry("520x420")
        top.transient(self.root)
        top.grab_set()

        labels = [
            ("cat1", "家具日用"),
            ("cat2", "医疗用品"),
            ("cat3", "时尚潮流"),
            ("cat4", "武器装备"),
            ("cat5", "矿物珠宝"),
            ("cat6", "文玩古董"),
            ("cat7", "数码电子"),
            ("cat8", "能源交通"),
            ("cat9", "饮食烹饪"),
            ("cat10", "书籍绘画"),
        ]
        vars_map: dict[str, tk.StringVar] = {}
        weights = self.price_config.setdefault("category_weights", {})
        wrapper = ttk.Frame(top, padding=12)
        wrapper.pack(fill="both", expand=True)
        header = ttk.Frame(wrapper)
        header.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        ttk.Label(header, text="只支持 0 / 1 / 2。0=排除，1=默认，2=强化").pack(anchor="w")
        for idx, (key, label) in enumerate(labels):
            row = idx // 2 + 1
            col = (idx % 2) * 2
            ttk.Label(wrapper, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=6)
            var = tk.StringVar(value=str(weights.get(key, 1)))
            vars_map[key] = var
            combo = ttk.Combobox(wrapper, textvariable=var, state="readonly", width=8)
            combo["values"] = ("0", "1", "2")
            combo.grid(row=row, column=col + 1, sticky="w", pady=6)

        button_row = ttk.Frame(wrapper)
        button_row.grid(row=6 + 1, column=0, columnspan=4, sticky="w", pady=(16, 0))

        def reset_weights() -> None:
            for key in vars_map:
                vars_map[key].set("1")

        def save_weights() -> None:
            for key, var in vars_map.items():
                self.price_config.setdefault("category_weights", {})[key] = int(var.get())
            self.save_json(PRICE_CONFIG_PATH, self.price_config)
            self.refresh_weight_summary()
            self.refresh_price_config_editor_from_model()
            top.destroy()

        ttk.Button(button_row, text="恢复默认", command=reset_weights).pack(side="left")
        ttk.Button(button_row, text="保存", command=save_weights).pack(side="left", padx=(8, 0))

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
                    from ..interaction import _legacy_aisha as aisha_bot

                    aisha_bot.run_aisha_loop(CONFIG_PATH)
                else:
                    bot.run_loop(CONFIG_PATH)
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
    app = BidKingApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
