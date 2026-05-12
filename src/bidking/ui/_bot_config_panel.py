"""可嵌入任意 tk 容器的「策略配置」面板。

聚合了原 ``BidKingApp``（bot 总控）中的可编辑项：
- 出价参数（pricing / automation）  —— 写入 ``configs/pricing.maps/<map_id>.json``
- 棋盘快照（board_snapshot）         —— 写入 ``configs/config.json`` 的 overlay
- 「本地覆盖」里的两个 JSON 编辑器
  - 主配置 overlay（``configs/config.json``）
  - 当前地图自定义（``configs/pricing.maps/<map_id>.json``）

设计上**独立持久化**：所有「保存」最终都落在磁盘上的 ``configs/`` 下。
bot 总控 GUI 在启动 bot 前再从磁盘 reload；因此 panel 与 BidKingApp
可以分别打开、各自编辑，磁盘是它们之间唯一的同步媒介（小工具场景下
接受偶发并发写入的风险）。

panel 自带一个**地图下拉**——和 ``BidKingApp.自动化`` 页中的地图下拉
**互不耦合**，仅用来选择"当前要编辑哪个地图的 pricing"。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Optional

from ..config.map_runtime_overlay import (
    automation_maps_sorted_keys,
    resolve_automation_map_config_key,
)
from ..config.paths import config_overlay_path, pricing_map_overlay_path, runtime_path
from ..config.pricing import deep_merge
from ..config.runtime import apply_board_snapshot_env_overrides


CONFIG_OVERLAY_PATH = config_overlay_path()

DEFAULT_BID_RATIO_BY_ROUND: dict[str, float] = {
    "1": 0.6, "2": 0.65, "3": 0.75, "4": 0.95, "5": 1.0,
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class BotConfigPanel:
    """把「出价参数 / 棋盘快照 / 配置 JSON 编辑」嵌入到任意父级容器。"""

    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self._top = parent.winfo_toplevel()

        self.runtime_base: dict = {}
        self.overlay: dict = {}
        self.config: dict = {}

        self.map_var = tk.StringVar()
        self.fallback_bid_var = tk.StringVar(value="22223")
        self.bid_cap_var = tk.StringVar(value="0")
        self.bid_ratio_vars: dict[int, tk.StringVar] = {
            r: tk.StringVar(value=str(DEFAULT_BID_RATIO_BY_ROUND[str(r)]))
            for r in range(1, 6)
        }
        self.self_user_uid_var = tk.StringVar(value="")
        self.self_name_substring_var = tk.StringVar(value="")

        self.config_json_auto_apply_var = tk.BooleanVar(value=True)
        self.map_overlay_auto_apply_var = tk.BooleanVar(value=True)
        self.config_json_status_var = tk.StringVar(value="")
        self.map_overlay_status_var = tk.StringVar(value="")
        self.map_overlay_path_var = tk.StringVar(value="")

        self._config_json_apply_after_id: Optional[str] = None
        self._map_overlay_apply_after_id: Optional[str] = None
        self._config_editor_syncing = False
        self._map_overlay_syncing = False

        self._reload_config_sources(initial=True)
        self._build_ui(parent)
        self._load_into_form()

    # ── 磁盘 IO / 合并 ──────────────────────────────────────────────────────

    def _rebuild_merged_config(self) -> None:
        self.config = deep_merge(self.runtime_base, self.overlay)
        apply_board_snapshot_env_overrides(self.config)

    def _reload_config_sources(self, *, initial: bool = False) -> None:
        rp = runtime_path()
        self.runtime_base = _load_json(rp) if rp.is_file() else {}
        self.overlay = (
            _load_json(CONFIG_OVERLAY_PATH) if CONFIG_OVERLAY_PATH.is_file() else {}
        )
        self._rebuild_merged_config()
        if not initial and hasattr(self, "config_json_text"):
            self._refresh_config_json_editor_from_model()

    # ── UI 构建 ─────────────────────────────────────────────────────────────

    def _build_ui(self, parent: tk.Widget) -> None:
        outer = ttk.Frame(parent, padding=8)
        outer.pack(fill="both", expand=True)

        info = ttk.Label(
            outer,
            text=(
                "本面板写入磁盘后立即生效；bot_runner GUI 启动时会再次读盘。\n"
                "下方「编辑地图」下拉只决定当前要编辑哪张地图的 pricing/automation，"
                "与 bot_runner GUI 自动化页的选图相互独立。"
            ),
            foreground="#555577",
            justify="left",
        )
        info.pack(fill="x", pady=(0, 6))

        map_row = ttk.Frame(outer)
        map_row.pack(fill="x", pady=(0, 8))
        ttk.Label(map_row, text="编辑地图").pack(side="left")
        self.map_combo = ttk.Combobox(
            map_row, textvariable=self.map_var, state="readonly", width=28,
        )
        self.map_combo.pack(side="left", padx=(6, 0))
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_combo_selected)

        self._build_pricing_box(outer)
        self._build_snapshot_box(outer)
        self._build_config_json_editor(outer)
        self._build_map_overlay_editor(outer)

    def _build_pricing_box(self, parent: tk.Widget) -> None:
        price_box = ttk.LabelFrame(parent, text="出价参数（pricing / automation）", padding=10)
        price_box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            price_box,
            text=(
                "以下写入 configs/pricing.maps/<地图 id，与游戏选图一致为三位>.json"
                "（与上方下拉所选对应）。"
            ),
            wraplength=720,
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        ttk.Label(price_box, text="兜底价").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(price_box, textvariable=self.fallback_bid_var, width=12).grid(
            row=1, column=1, sticky="w", padx=(4, 16),
        )

        ttk.Label(price_box, text="封顶价").grid(row=1, column=2, sticky="w", pady=2)
        ttk.Entry(price_box, textvariable=self.bid_cap_var, width=12).grid(
            row=1, column=3, sticky="w", padx=(4, 0),
        )

        ttk.Label(price_box, text="automation.bid_ratio_by_round").grid(
            row=2, column=0, sticky="nw", pady=(8, 2),
        )
        ratio_wrap = ttk.Frame(price_box)
        ratio_wrap.grid(row=2, column=1, columnspan=5, sticky="w", pady=(8, 2))
        for round_no in range(1, 6):
            col = ttk.Frame(ratio_wrap)
            col.pack(side="left", padx=(0, 10))
            ttk.Label(col, text=f"第{round_no}回合").pack(anchor="w")
            ttk.Entry(col, textvariable=self.bid_ratio_vars[round_no], width=8).pack(
                anchor="w",
            )

        save_row = ttk.Frame(price_box)
        save_row.grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(save_row, text="保存出价参数", command=self._save_pricing_form).pack(
            side="left",
        )
        self.pricing_status_var = tk.StringVar(value="")
        ttk.Label(save_row, textvariable=self.pricing_status_var, foreground="gray").pack(
            side="left", padx=(10, 0),
        )

    def _build_snapshot_box(self, parent: tk.Widget) -> None:
        snap_box = ttk.LabelFrame(parent, text="棋盘快照（board_snapshot）", padding=10)
        snap_box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            snap_box,
            text=(
                "写入 configs/config.json 的 board_snapshot：快照 JSON 路径固定为用户文档"
                "目录下的 bidking/board_snapshot.json；「己方 UID」与「名称关键字」至少填其一。"
            ),
            wraplength=720,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        fixed_snapshot_path = str(self.default_board_snapshot_path()).replace("\\", "/")
        ttk.Label(snap_box, text="快照文件 path（固定）").grid(
            row=1, column=0, sticky="w", pady=2,
        )
        ttk.Label(snap_box, text=fixed_snapshot_path).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=2,
        )
        snap_box.columnconfigure(1, weight=1)

        ttk.Label(snap_box, text="己方 UID").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(snap_box, textvariable=self.self_user_uid_var, width=28).grid(
            row=2, column=1, sticky="w", pady=2,
        )
        ttk.Label(snap_box, text="名称关键字").grid(
            row=2, column=2, sticky="w", padx=(12, 4), pady=2,
        )
        ttk.Entry(snap_box, textvariable=self.self_name_substring_var, width=20).grid(
            row=2, column=3, sticky="w", pady=2,
        )

        save_row = ttk.Frame(snap_box)
        save_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(save_row, text="保存快照配置", command=self._save_snapshot_form).pack(
            side="left",
        )
        self.snapshot_status_var = tk.StringVar(value="")
        ttk.Label(save_row, textvariable=self.snapshot_status_var, foreground="gray").pack(
            side="left", padx=(10, 0),
        )

    def _build_config_json_editor(self, parent: tk.Widget) -> None:
        box = ttk.LabelFrame(parent, text="主配置 overlay（configs/config.json）", padding=8)
        box.pack(fill="both", expand=True, pady=(0, 8))
        bar = ttk.Frame(box)
        bar.pack(fill="x")
        ttk.Label(
            bar,
            text=f"覆盖文件: {CONFIG_OVERLAY_PATH.name}（合并自 runtime.json + 本文件）",
        ).pack(side="left")
        ttk.Checkbutton(
            bar, text="编辑合法后自动保存",
            variable=self.config_json_auto_apply_var,
        ).pack(side="left", padx=(14, 0))
        ttk.Button(
            bar, text="保存", command=self._save_config_json_from_editor,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            bar, text="从磁盘重载", command=self._reload_config_json_from_disk,
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            bar, textvariable=self.config_json_status_var, foreground="gray",
        ).pack(side="left", padx=(10, 0))

        self.config_json_text = ScrolledText(
            box, wrap="word", font=("Consolas", 10), height=14, width=92,
        )
        self.config_json_text.pack(fill="both", expand=True, pady=(8, 0))
        self._refresh_config_json_editor_from_model()
        self.config_json_text.bind(
            "<KeyRelease>", self._on_config_json_editor_keyrelease,
        )

    def _build_map_overlay_editor(self, parent: tk.Widget) -> None:
        box = ttk.LabelFrame(
            parent,
            text="当前地图自定义（configs/pricing.maps/<上面下拉选定的地图>.json）",
            padding=8,
        )
        box.pack(fill="both", expand=True, pady=(0, 8))
        bar = ttk.Frame(box)
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.map_overlay_path_var).pack(side="left")
        ttk.Checkbutton(
            bar, text="编辑合法后自动保存",
            variable=self.map_overlay_auto_apply_var,
        ).pack(side="left", padx=(14, 0))
        ttk.Button(
            bar, text="保存", command=self._save_map_overlay_from_editor,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            bar, text="从磁盘重载", command=self._reload_map_overlay_from_disk,
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            bar, textvariable=self.map_overlay_status_var, foreground="gray",
        ).pack(side="left", padx=(10, 0))

        self.map_overlay_text = ScrolledText(
            box, wrap="word", font=("Consolas", 10), height=12, width=92,
        )
        self.map_overlay_text.pack(fill="both", expand=True, pady=(8, 0))
        self.map_overlay_text.bind(
            "<KeyRelease>", self._on_map_overlay_editor_keyrelease,
        )

    # ── 表单 ↔ 模型 ────────────────────────────────────────────────────────

    def default_board_snapshot_path(self) -> Path:
        docs = Path.home() / "Documents"
        if not docs.exists():
            docs = Path.home()
        return (docs / "bidking" / "board_snapshot.json").resolve()

    def _refresh_map_combo_from_config(self) -> None:
        auto = self.config.get("automation") or {}
        maps = auto.get("maps") or {}
        try:
            keys = automation_maps_sorted_keys(maps)
            self.map_combo["values"] = [
                f"{k}. {maps[k].get('name', k)}" for k in keys
            ]
        except (KeyError, TypeError):
            self.map_combo["values"] = []

    def _selected_map_key(self) -> str:
        text = self.map_var.get().strip()
        return text.split(".", 1)[0].strip() if "." in text else text

    def _effective_map_key(self) -> str:
        mk = self._selected_map_key()
        maps = (self.config.get("automation") or {}).get("maps") or {}
        if mk and isinstance(maps, dict) and mk in maps:
            return mk
        return resolve_automation_map_config_key(self.config.get("automation") or {})

    def _load_map_pricing_fields(self, map_key: str) -> None:
        mp = pricing_map_overlay_path(map_key)
        if mp.is_file():
            data = _load_json(mp)
            pr = data.get("pricing") if isinstance(data.get("pricing"), dict) else {}
            au = data.get("automation") if isinstance(data.get("automation"), dict) else {}
        else:
            pr = self.config.get("pricing") or {}
            au = self.config.get("automation") or {}
        self.fallback_bid_var.set(str(pr.get("fallback_bid_price", 22223)))
        self.bid_cap_var.set(str(au.get("bid_cap_price", 0)))
        br_src = au.get("bid_ratio_by_round") if isinstance(au.get("bid_ratio_by_round"), dict) else {}
        for round_no in range(1, 6):
            key = str(round_no)
            if key in br_src:
                self.bid_ratio_vars[round_no].set(str(br_src[key]))
            else:
                self.bid_ratio_vars[round_no].set(str(DEFAULT_BID_RATIO_BY_ROUND[key]))

    def _on_map_combo_selected(self, _event: object = None) -> None:
        mk = self._selected_map_key() or self._effective_map_key()
        self._load_map_pricing_fields(mk)
        self._refresh_map_overlay_editor_from_disk()

    def _load_into_form(self) -> None:
        self._refresh_map_combo_from_config()
        auto = self.config.get("automation") or {}
        map_key = resolve_automation_map_config_key(auto)
        maps = auto.get("maps") or {}
        item = maps.get(map_key, {}) if isinstance(maps, dict) else {}
        name = item.get("name", map_key)
        self.map_var.set(f"{map_key}. {name}" if map_key else "")
        self._load_map_pricing_fields(map_key)
        bs = self.config.get("board_snapshot") if isinstance(self.config.get("board_snapshot"), dict) else {}
        self.self_user_uid_var.set(str(bs.get("self_user_uid", "")))
        self.self_name_substring_var.set(str(bs.get("self_name_substring", "")))
        self._refresh_map_overlay_editor_from_disk()

    # ── 出价参数：保存 ─────────────────────────────────────────────────────

    def _map_overlay_doc_from_form(self) -> dict:
        try:
            fb = int(str(self.fallback_bid_var.get()).strip() or "22223")
        except ValueError:
            fb = 22223
        try:
            cap = int(str(self.bid_cap_var.get()).strip() or "0")
        except ValueError:
            cap = 0
        bid_ratio: dict[str, float] = {}
        for round_no in range(1, 6):
            raw = self.bid_ratio_vars[round_no].get().strip()
            key = str(round_no)
            try:
                bid_ratio[key] = float(raw) if raw else DEFAULT_BID_RATIO_BY_ROUND[key]
            except ValueError:
                bid_ratio[key] = DEFAULT_BID_RATIO_BY_ROUND[key]
        return {
            "pricing": {"fallback_bid_price": fb},
            "automation": {
                "bid_cap_price": cap,
                "bid_ratio_by_round": bid_ratio,
            },
        }

    def _save_pricing_form(self) -> None:
        try:
            selected_map = self._effective_map_key()
            if not selected_map:
                raise ValueError("当前未选中任何地图，请先在上方下拉里选一张地图。")
            doc_inc = self._map_overlay_doc_from_form()
            path = pricing_map_overlay_path(selected_map)
            prior = _load_json(path) if path.is_file() else {}
            merged = deep_merge(prior, doc_inc)
            au_doc = merged.get("automation")
            if isinstance(au_doc, dict):
                au_doc.pop("safe_guard_enabled", None)
                au_doc.pop("safe_guard_max_increase_ratio", None)
            _save_json(path, merged)
            self.pricing_status_var.set(f"已保存到 {path.name}")
            self._refresh_map_overlay_editor_from_disk()
        except (OSError, ValueError, TypeError) as exc:
            self.pricing_status_var.set(f"保存失败: {exc}")
            messagebox.showerror("出价参数", f"无法保存：\n{exc}")

    # ── 棋盘快照：保存 ─────────────────────────────────────────────────────

    def _save_snapshot_form(self) -> None:
        try:
            path_snap = str(self.default_board_snapshot_path()).replace("\\", "/")
            uid = str(self.self_user_uid_var.get()).strip()
            name_sub = str(self.self_name_substring_var.get()).strip()
            if "BIDKING_SELF_USER_UID" in os.environ:
                uid = os.environ["BIDKING_SELF_USER_UID"].strip()
            if "BIDKING_SELF_NAME_SUBSTRING" in os.environ:
                name_sub = os.environ["BIDKING_SELF_NAME_SUBSTRING"].strip()
            if not uid and not name_sub:
                raise ValueError("「己方 UID」与「名称关键字」须至少填写一项")

            bs_overlay = self.overlay.setdefault("board_snapshot", {})
            bs_overlay.setdefault("enabled", True)
            bs_overlay.setdefault("write_mode", "both")
            bs_overlay.setdefault("schema_version_min", 1)
            bs_overlay["path"] = path_snap.replace("\\", "/")
            if "BIDKING_SELF_USER_UID" not in os.environ:
                bs_overlay["self_user_uid"] = str(self.self_user_uid_var.get()).strip()
            else:
                bs_overlay.pop("self_user_uid", None)
            if "BIDKING_SELF_NAME_SUBSTRING" not in os.environ:
                bs_overlay["self_name_substring"] = str(
                    self.self_name_substring_var.get(),
                ).strip()
            else:
                bs_overlay.pop("self_name_substring", None)

            _save_json(CONFIG_OVERLAY_PATH, self.overlay)
            self._rebuild_merged_config()
            self._refresh_config_json_editor_from_model()
            self.snapshot_status_var.set("已保存到 config.json")
        except (OSError, ValueError, TypeError) as exc:
            self.snapshot_status_var.set(f"保存失败: {exc}")
            messagebox.showerror("棋盘快照", f"无法保存：\n{exc}")

    # ── 主配置 JSON 编辑器 ─────────────────────────────────────────────────

    def _refresh_config_json_editor_from_model(self) -> None:
        if not hasattr(self, "config_json_text"):
            return
        self._config_editor_syncing = True
        try:
            self.config_json_text.delete("1.0", "end")
            self.config_json_text.insert(
                "1.0", json.dumps(self.overlay, ensure_ascii=False, indent=2),
            )
        finally:
            self._config_editor_syncing = False

    def _on_config_json_editor_keyrelease(self, _event: tk.Event) -> None:
        if self._config_editor_syncing:
            return
        if not self.config_json_auto_apply_var.get():
            return
        if self._config_json_apply_after_id is not None:
            self._top.after_cancel(self._config_json_apply_after_id)
        self._config_json_apply_after_id = self._top.after(
            600, self._debounced_apply_config_json,
        )

    def _debounced_apply_config_json(self) -> None:
        self._config_json_apply_after_id = None
        try:
            self._parse_and_apply_config_json_editor(write_file=True)
            self.config_json_status_var.set("已自动保存")
            self._refresh_map_combo_from_config()
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
        self._rebuild_merged_config()
        if write_file:
            _save_json(CONFIG_OVERLAY_PATH, self.overlay)

    def _save_config_json_from_editor(self) -> None:
        try:
            self._parse_and_apply_config_json_editor(write_file=True)
            self.config_json_status_var.set("已保存")
            self._refresh_map_combo_from_config()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror("主配置", f"无法保存：\n{exc}")
            self.config_json_status_var.set("保存失败")

    def _reload_config_json_from_disk(self) -> None:
        try:
            self._reload_config_sources()
            self._load_into_form()
            self.config_json_status_var.set("已从磁盘加载")
        except OSError as exc:
            messagebox.showerror("主配置", str(exc))
        except json.JSONDecodeError as exc:
            messagebox.showerror("主配置", f"JSON 无效：{exc}")

    # ── 地图 overlay JSON 编辑器 ───────────────────────────────────────────

    def _refresh_map_overlay_editor_from_disk(self) -> None:
        if not hasattr(self, "map_overlay_text"):
            return
        mk = self._effective_map_key()
        if not mk:
            self.map_overlay_path_var.set("（未选地图）")
            self._map_overlay_syncing = True
            try:
                self.map_overlay_text.delete("1.0", "end")
            finally:
                self._map_overlay_syncing = False
            return
        path = pricing_map_overlay_path(mk)
        self.map_overlay_path_var.set(str(path))
        self._map_overlay_syncing = True
        try:
            self.map_overlay_text.delete("1.0", "end")
            if path.is_file():
                doc = _load_json(path)
            else:
                doc = self._map_overlay_doc_from_form()
            self.map_overlay_text.insert(
                "1.0", json.dumps(doc, ensure_ascii=False, indent=2),
            )
        finally:
            self._map_overlay_syncing = False

    def _on_map_overlay_editor_keyrelease(self, _event: tk.Event | None = None) -> None:
        if self._map_overlay_syncing:
            return
        if not self.map_overlay_auto_apply_var.get():
            return
        if self._map_overlay_apply_after_id is not None:
            self._top.after_cancel(self._map_overlay_apply_after_id)
        self._map_overlay_apply_after_id = self._top.after(
            600, self._debounced_apply_map_overlay,
        )

    def _debounced_apply_map_overlay(self) -> None:
        self._map_overlay_apply_after_id = None
        try:
            self._parse_and_apply_map_overlay_editor(write_file=True)
            self.map_overlay_status_var.set("已自动保存")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            self.map_overlay_status_var.set(f"JSON 未就绪: {exc}")

    def _parse_and_apply_map_overlay_editor(self, *, write_file: bool) -> None:
        if not hasattr(self, "map_overlay_text"):
            return
        raw = self.map_overlay_text.get("1.0", "end-1c").strip()
        if not raw:
            raise ValueError("地图自定义内容为空")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("地图自定义根节点必须是 JSON 对象")
        mk = self._effective_map_key()
        if not mk:
            raise ValueError("未选定地图")
        path = pricing_map_overlay_path(mk)
        if write_file:
            _save_json(path, parsed)
        self._load_map_pricing_fields(mk)

    def _save_map_overlay_from_editor(self) -> None:
        try:
            self._parse_and_apply_map_overlay_editor(write_file=True)
            self.map_overlay_status_var.set("已保存")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror("地图自定义", f"无法保存：\n{exc}")
            self.map_overlay_status_var.set("保存失败")

    def _reload_map_overlay_from_disk(self) -> None:
        try:
            self._reload_config_sources()
            self._load_into_form()
            self.map_overlay_status_var.set("已从磁盘加载")
        except OSError as exc:
            messagebox.showerror("地图自定义", str(exc))
        except json.JSONDecodeError as exc:
            messagebox.showerror("地图自定义", f"JSON 无效：{exc}")


__all__ = ["BotConfigPanel"]
