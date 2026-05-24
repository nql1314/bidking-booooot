"""基于 ``configs/visual_config_schema.json`` 的可视化配置面板。"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Optional

from ..config.map_runtime_overlay import (
    resolve_automation_map_config_key,
    strategy_map_combo_entries,
)
from ..config.paths import (
    config_overlay_path,
    configs_dir,
    pricing_map_overlay_path,
    runtime_path,
)
from ..config.runtime import apply_board_snapshot_env_overrides
from ..analysis.map_avg_csv import load_prefix3_to_min_map_id
from ..analysis.map_quality_unit_config import CONFIG_KEYS, load_map_quality_unit_price_refs
from ..config.visual_schema import (
    coerce_field_value,
    format_field_value,
    get_by_path,
    load_visual_config_schema,
    schema_fields_for_scope,
    set_by_path,
    visual_config_schema_path,
)
from ._hover_tip import LabelHoverTip

_MAP_QUALITY_UNIT_LABELS: dict[str, str] = {
    "q5": "金 (Q5) 格单价",
    "q6": "红 (Q6) 格单价",
    "q56": "金+红 (Q56) 格单价",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _FieldBinding:
    __slots__ = ("field", "var", "widget")

    def __init__(self, field: dict[str, Any], var: tk.Variable, widget: tk.Widget):
        self.field = field
        self.var = var
        self.widget = widget


class VisualConfigPanel:
    """主配置 overlay + 当前地图 pricing.maps 的可视化编辑。"""

    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self._top = parent.winfo_toplevel()

        self.runtime_base: dict = {}
        self.overlay: dict = {}
        self.config: dict = {}
        self.map_doc: dict = {}

        self.map_var = tk.StringVar()
        self.status_var = tk.StringVar(value="")
        self.schema_path_var = tk.StringVar()

        self._config_bindings: list[_FieldBinding] = []
        self._map_bindings: list[_FieldBinding] = []
        self._map_quality_unit_vars: dict[str, tk.StringVar] = {}

        self._reload_config_sources()
        self._build_ui(parent)
        self._load_into_form()

    # ── 磁盘 ────────────────────────────────────────────────────────────────

    def _rebuild_merged_config(self) -> None:
        from ..config.pricing import deep_merge

        self.config = deep_merge(self.runtime_base, self.overlay)
        apply_board_snapshot_env_overrides(self.config)

    def _reload_config_sources(self) -> None:
        rp = runtime_path()
        self.runtime_base = _load_json(rp) if rp.is_file() else {}
        overlay_path = config_overlay_path()
        self.overlay = _load_json(overlay_path) if overlay_path.is_file() else {}
        self._rebuild_merged_config()
        self._reload_map_doc()

    def _reload_map_doc(self) -> None:
        mk = self._effective_map_key()
        if not mk:
            self.map_doc = {}
            return
        path = pricing_map_overlay_path(mk)
        self.map_doc = _load_json(path) if path.is_file() else {}

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self, parent: tk.Widget) -> None:
        outer = ttk.Frame(parent, padding=8)
        outer.pack(fill="both", expand=True)

        info = ttk.Label(
            outer,
            text=(
                "字段定义来自 configs/visual_config_schema.json；hide=true 的项不在本页显示。\n"
                "鼠标悬停字段名可查看说明。左侧写入 configs/config.json；"
                "右侧写入 configs/pricing.maps/<地图>.json。"
                "scope=both 的项在两区均可编辑，保存时各自写入对应文件。"
            ),
            foreground="#555577",
            justify="left",
        )
        info.pack(fill="x", pady=(0, 6))

        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="编辑地图").pack(side="left")
        self.map_combo = ttk.Combobox(
            top, textvariable=self.map_var, state="readonly", width=40,
        )
        self.map_combo.pack(side="left", padx=(6, 12))
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_combo_selected)

        ttk.Button(top, text="从磁盘重载", command=self._reload_from_disk).pack(side="left", padx=4)
        ttk.Button(top, text="重载 schema", command=self._reload_schema_and_form).pack(side="left", padx=4)
        ttk.Label(top, textvariable=self.status_var, foreground="gray").pack(side="left", padx=(12, 0))

        schema_row = ttk.Frame(outer)
        schema_row.pack(fill="x", pady=(0, 6))
        ttk.Label(schema_row, text="Schema:").pack(side="left")
        ttk.Label(
            schema_row, textvariable=self.schema_path_var, foreground="#666688",
        ).pack(side="left", padx=(4, 0))

        panes = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        panes.pack(fill="both", expand=True, pady=(0, 8))

        config_wrap = ttk.Frame(panes)
        map_wrap = ttk.Frame(panes)
        panes.add(config_wrap, weight=1)
        panes.add(map_wrap, weight=1)

        self._config_canvas_frame = self._build_scope_column(
            config_wrap,
            title="主配置（configs/config.json）",
            save_cmd=self._save_config_scope,
        )
        self._map_canvas_frame = self._build_scope_column(
            map_wrap,
            title="当前地图（configs/pricing.maps/<id>.json）",
            save_cmd=self._save_map_scope,
        )

        self.schema_path_var.set(str(visual_config_schema_path()))

    def _build_scope_column(
        self,
        parent: tk.Widget,
        *,
        title: str,
        save_cmd,
    ) -> ttk.Frame:
        box = ttk.LabelFrame(parent, text=title, padding=6)
        box.pack(fill="both", expand=True)

        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="保存", command=save_cmd).pack(side="left")

        canvas = tk.Canvas(box, highlightthickness=0)
        vsb = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")),
        )
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _on_canvas_configure(event: tk.Event, c=canvas, wid=win_id) -> None:
            c.itemconfigure(wid, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event: tk.Event, c=canvas) -> None:
            c.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _e, c=canvas: c.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e, c=canvas: c.unbind_all("<MouseWheel>"))

        setattr(inner, "_field_container", True)
        box._inner_frame = inner  # type: ignore[attr-defined]
        box._canvas = canvas  # type: ignore[attr-defined]
        return box

    def _populate_scope_fields(
        self,
        box: ttk.Frame,
        bindings: list[_FieldBinding],
        fields: list[dict[str, Any]],
        data: dict[str, Any],
        merged_fallback: dict[str, Any],
    ) -> None:
        inner: ttk.Frame = box._inner_frame  # type: ignore[attr-defined]
        for child in inner.winfo_children():
            child.destroy()
        bindings.clear()

        groups: dict[str, list[dict[str, Any]]] = {}
        for field in fields:
            g = str(field.get("group") or "其他")
            groups.setdefault(g, []).append(field)

        row = 0
        for group_name in sorted(groups.keys()):
            grp = ttk.LabelFrame(inner, text=group_name, padding=8)
            grp.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            inner.columnconfigure(0, weight=1)
            row += 1
            gi = 0
            for field in groups[group_name]:
                path = str(field.get("path") or "").strip()
                if not path:
                    continue
                label = str(field.get("label") or path)
                desc = str(field.get("description") or "").strip()

                label_widget = ttk.Label(grp, text=label, width=22)
                label_widget.grid(row=gi, column=0, sticky="nw", pady=2)
                if desc:
                    LabelHoverTip(label_widget, desc)

                var, widget = self._make_widget(grp, field)
                ftype_w = str(field.get("type") or "str").strip().lower()
                if ftype_w == "json":
                    widget.grid(row=gi, column=1, sticky="ew", padx=(4, 0), pady=2)
                else:
                    widget.grid(row=gi, column=1, sticky="w", padx=(4, 0), pady=2)
                grp.columnconfigure(1, weight=1)

                val = get_by_path(data, path)
                if val is None:
                    val = get_by_path(merged_fallback, path)
                ftype = str(field.get("type") or "str").strip().lower()
                if ftype == "bool":
                    var.set(bool(val))
                elif ftype == "json" and isinstance(widget, tk.Text):
                    widget.delete("1.0", "end")
                    widget.insert("1.0", format_field_value(val, field))
                else:
                    var.set(format_field_value(val, field))

                bindings.append(_FieldBinding(field, var, widget))
                gi += 1

    def _make_widget(
        self,
        parent: tk.Widget,
        field: dict[str, Any],
    ) -> tuple[tk.Variable, tk.Widget]:
        ftype = str(field.get("type") or "str").strip().lower()
        if ftype == "bool":
            var = tk.BooleanVar()
            w = ttk.Checkbutton(parent, variable=var)
            return var, w
        if ftype == "enum":
            choices = field.get("choices") if isinstance(field.get("choices"), list) else []
            var = tk.StringVar()
            w = ttk.Combobox(parent, textvariable=var, values=choices, width=18)
            if choices:
                w.configure(state="readonly")
            return var, w
        if ftype == "json":
            var = tk.StringVar()
            from tkinter.scrolledtext import ScrolledText

            w = ScrolledText(parent, height=4, width=36, font=("Consolas", 9))
            return var, w
        var = tk.StringVar()
        w = ttk.Entry(parent, textvariable=var, width=20)
        return var, w

    # ── 表单加载 ────────────────────────────────────────────────────────────

    def _refresh_map_combo_from_config(self) -> None:
        try:
            self.map_combo["values"] = strategy_map_combo_entries(
                self.config, configs_root=configs_dir()
            )
        except (KeyError, TypeError, OSError):
            self.map_combo["values"] = []

    def _selected_map_key(self) -> str:
        text = self.map_var.get().strip()
        return text.split(".", 1)[0].strip() if "." in text else text

    def _effective_map_key(self) -> str:
        mk = self._selected_map_key()
        if mk:
            return mk
        return resolve_automation_map_config_key(self.config.get("automation") or {})

    def _load_into_form(self) -> None:
        self._refresh_map_combo_from_config()
        auto = self.config.get("automation") or {}
        map_key = resolve_automation_map_config_key(auto)
        maps = auto.get("maps") or {}
        item = maps.get(map_key, {}) if isinstance(maps, dict) else {}
        name = item.get("name", map_key)
        self.map_var.set(f"{map_key}. {name}" if map_key else "")
        self._reload_map_doc()
        self._rebuild_field_forms()

    def _rebuild_field_forms(self) -> None:
        schema = load_visual_config_schema()
        config_fields = schema_fields_for_scope(schema, "config")
        map_fields = schema_fields_for_scope(schema, "map")

        self._populate_scope_fields(
            self._config_canvas_frame,
            self._config_bindings,
            config_fields,
            self.overlay,
            self.config,
        )
        map_merged = self.config
        if self.map_doc:
            from ..config.pricing import deep_merge

            map_merged = deep_merge(self.config, self.map_doc)
        self._populate_scope_fields(
            self._map_canvas_frame,
            self._map_bindings,
            map_fields,
            self.map_doc,
            map_merged,
        )
        self._populate_map_quality_unit_section(self._map_canvas_frame, self.map_doc)

    def _representative_map_id_for_editor(self) -> int:
        mk = self._effective_map_key()
        if not mk:
            return 0
        try:
            return int(load_prefix3_to_min_map_id().get(mk, int(mk) if mk.isdigit() else 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _fmt_ref_price(v: object) -> str:
        if v is None:
            return "—"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "—"
        if f <= 0 or f != f:
            return "—"
        if f >= 1000:
            return f"{f:,.0f}"
        return f"{f:.2f}".rstrip("0").rstrip(".")

    def _guidance_text_for_unit_key(self, refs: dict, cfg_key: str) -> str:
        row = refs.get(cfg_key) if isinstance(refs, dict) else None
        if not isinstance(row, dict):
            return "（无 CSV 参考，请先运行 tools/map_quality_*_prices.py）"
        avg = self._fmt_ref_price(row.get("avg_per_cell"))
        p25 = self._fmt_ref_price(row.get("p25_per_cell"))
        p50 = self._fmt_ref_price(row.get("p50_per_cell"))
        return f"CSV 指导价（格）：均价 {avg}　P25 {p25}　P50 {p50}"

    def _populate_map_quality_unit_section(
        self,
        box: ttk.Frame,
        map_doc: dict[str, Any],
    ) -> None:
        inner: ttk.Frame = box._inner_frame  # type: ignore[attr-defined]
        rep_mid = self._representative_map_id_for_editor()
        refs = load_map_quality_unit_price_refs(rep_mid) if rep_mid > 0 else {}

        grp = ttk.LabelFrame(
            inner,
            text="金/红格单价覆盖（优先于 CSV，用于估价）",
            padding=8,
        )
        grp.grid(row=999, column=0, sticky="ew", pady=(0, 8))
        inner.columnconfigure(0, weight=1)

        hint = (
            f"代表 map_id={rep_mid or '—'}（与同档 CSV 行一致）。"
            "留空或 0 表示使用 CSV 均价；填写后覆盖 q5/q6/q5+q6 格单价。"
        )
        ttk.Label(grp, text=hint, foreground="#555577", wraplength=520, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        pricing = map_doc.get("pricing") if isinstance(map_doc.get("pricing"), dict) else {}
        overrides = pricing.get("map_quality_unit_per_cell")
        if not isinstance(overrides, dict):
            overrides = {}

        self._map_quality_unit_vars.clear()
        gi = 1
        for cfg_key in CONFIG_KEYS:
            label = _MAP_QUALITY_UNIT_LABELS.get(cfg_key, cfg_key)
            ttk.Label(grp, text=label, width=22).grid(row=gi, column=0, sticky="nw", pady=3)
            var = tk.StringVar()
            cur = overrides.get(cfg_key)
            if cur is not None:
                try:
                    f = float(cur)
                    if f > 0:
                        var.set(str(int(f)) if f == int(f) else str(f))
                except (TypeError, ValueError):
                    pass
            entry = ttk.Entry(grp, textvariable=var, width=14)
            entry.grid(row=gi, column=1, sticky="w", padx=(4, 0), pady=3)
            self._map_quality_unit_vars[cfg_key] = var

            gtxt = self._guidance_text_for_unit_key(refs, cfg_key)
            gl = ttk.Label(grp, text=gtxt, foreground="#666688", wraplength=480, justify="left")
            gl.grid(row=gi + 1, column=0, columnspan=2, sticky="w", padx=(0, 0), pady=(0, 6))
            gi += 2

    def _apply_map_quality_unit_to_doc(self, doc: dict[str, Any]) -> None:
        if not self._map_quality_unit_vars:
            return
        pricing = doc.get("pricing")
        if not isinstance(pricing, dict):
            pricing = {}
            doc["pricing"] = pricing
        bucket = pricing.get("map_quality_unit_per_cell")
        if not isinstance(bucket, dict):
            bucket = {}
        for cfg_key, var in self._map_quality_unit_vars.items():
            raw = var.get().strip()
            if not raw:
                bucket.pop(cfg_key, None)
                continue
            try:
                val = float(raw.replace(",", ""))
            except ValueError as exc:
                raise ValueError(f"{_MAP_QUALITY_UNIT_LABELS.get(cfg_key, cfg_key)}: 无效数字") from exc
            if val <= 0:
                bucket.pop(cfg_key, None)
            else:
                bucket[cfg_key] = val
        if bucket:
            pricing["map_quality_unit_per_cell"] = bucket
        else:
            pricing.pop("map_quality_unit_per_cell", None)

    def _on_map_combo_selected(self, _event: object = None) -> None:
        self._reload_map_doc()
        self._rebuild_field_forms()

    def _reload_from_disk(self) -> None:
        try:
            self._reload_config_sources()
            self._load_into_form()
            self.status_var.set("已从磁盘加载")
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("可视化配置", str(exc))

    def _reload_schema_and_form(self) -> None:
        try:
            load_visual_config_schema()
            self._rebuild_field_forms()
            self.status_var.set("已重载 schema")
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Schema", str(exc))

    # ── 保存 ────────────────────────────────────────────────────────────────

    def _apply_bindings(
        self,
        doc: dict[str, Any],
        bindings: list[_FieldBinding],
    ) -> None:
        for binding in bindings:
            field = binding.field
            path = str(field.get("path") or "").strip()
            if not path:
                continue
            ftype = str(field.get("type") or "str").strip().lower()
            if ftype == "bool":
                raw_val = binding.var.get()
                value: Any = bool(raw_val)
            elif ftype == "json" and isinstance(binding.widget, tk.Text):
                raw_s = binding.widget.get("1.0", "end-1c").strip()
                try:
                    value = coerce_field_value(field, raw_s)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{field.get('label', path)}: {exc}") from exc
            else:
                raw = binding.var.get()
                if isinstance(raw, str):
                    raw_s = raw
                else:
                    raw_s = str(raw)
                try:
                    value = coerce_field_value(field, raw_s)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{field.get('label', path)}: {exc}") from exc
            lo = field.get("min")
            hi = field.get("max")
            if lo is not None and isinstance(value, (int, float)) and value < lo:
                raise ValueError(f"{field.get('label', path)} 不能小于 {lo}")
            if hi is not None and isinstance(value, (int, float)) and value > hi:
                raise ValueError(f"{field.get('label', path)} 不能大于 {hi}")
            set_by_path(doc, path, value)

    def _save_config_scope(self) -> None:
        try:
            self._apply_bindings(self.overlay, self._config_bindings)
            _save_json(config_overlay_path(), self.overlay)
            self._rebuild_merged_config()
            self.status_var.set("主配置已保存")
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("主配置", str(exc))
            self.status_var.set(f"保存失败: {exc}")

    def _save_map_scope(self) -> None:
        try:
            mk = self._effective_map_key()
            if not mk:
                raise ValueError("请先选择地图")
            path = pricing_map_overlay_path(mk)
            prior = _load_json(path) if path.is_file() else {}
            doc = dict(prior)
            self._apply_bindings(doc, self._map_bindings)
            self._apply_map_quality_unit_to_doc(doc)
            au_doc = doc.get("automation")
            if isinstance(au_doc, dict):
                au_doc.pop("safe_guard_enabled", None)
                au_doc.pop("safe_guard_max_increase_ratio", None)
                au_doc.pop("default_map", None)
            _save_json(path, doc)
            self.map_doc = doc
            self.status_var.set(f"地图 {mk} 已保存")
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("地图配置", str(exc))
            self.status_var.set(f"保存失败: {exc}")


__all__ = ["VisualConfigPanel"]
