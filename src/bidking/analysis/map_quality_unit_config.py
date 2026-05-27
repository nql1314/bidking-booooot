"""地图品质组合格单价：CSV 参考价与 ``pricing.map_quality_unit_per_cell`` 覆盖。

覆盖项含 q5 / q6 / q5+q6（配置键 ``q56``）/ q4+q5+q6（配置键 ``q456``）。
"""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, Mapping, Optional

from .map_avg_csv import map_quality_csv_path_resolved, representative_map_id_for_ticket

# CSV ``quality_group`` 键
CSV_QUALITY_Q5 = "q5"
CSV_QUALITY_Q6 = "q6"
CSV_QUALITY_Q56 = "q5+q6"
CSV_QUALITY_Q456 = "q4+q5+q6"

# 配置键（``q56``→``q5+q6``，``q456``→``q4+q5+q6``）
CONFIG_KEYS = (CSV_QUALITY_Q5, CSV_QUALITY_Q6, "q56", "q456")
CONFIG_TO_CSV: dict[str, str] = {
    CSV_QUALITY_Q5: CSV_QUALITY_Q5,
    CSV_QUALITY_Q6: CSV_QUALITY_Q6,
    "q56": CSV_QUALITY_Q56,
    "q456": CSV_QUALITY_Q456,
}


def _percentile_csv_basename(percentile: str) -> str:
    p = percentile.strip().lower()
    if p == "p25":
        return "map_quality_p25_out.csv"
    if p == "p50":
        return "map_quality_p50_out.csv"
    return "map_quality_avg_out.csv"


def _percentile_column(percentile: str, *, per_item: bool) -> str:
    p = percentile.strip().lower()
    if p == "avg":
        return "avg_price_per_item" if per_item else "avg_price_per_cell"
    if p == "p25":
        return "p25_price_per_item" if per_item else "p25_price_per_cell"
    if p == "p50":
        return "p50_price_per_item" if per_item else "p50_price_per_cell"
    raise ValueError(f"unknown percentile: {percentile}")


def _resolve_data_csv_path(percentile: str, snapshot_path_hint: Optional[str]) -> str:
    if percentile.strip().lower() == "avg":
        return map_quality_csv_path_resolved(snapshot_path_hint)
    name = _percentile_csv_basename(percentile)
    if snapshot_path_hint:
        snap = snapshot_path_hint.strip()
        if snap:
            cand = os.path.normpath(os.path.join(os.path.dirname(snap), "data", name))
            if os.path.isfile(cand):
                return cand
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.normpath(os.path.join(here, "..", "..", "..", "data", name))
        if os.path.isfile(cand):
            return cand
    except Exception:
        pass
    try:
        from bidking.config.paths import data_dir

        cand = str(data_dir() / name)
        if os.path.isfile(cand):
            return cand
    except Exception:
        pass
    return ""


def _load_row_values(
    map_id: int,
    quality_group: str,
    *,
    percentile: str,
    per_item: bool,
    snapshot_path_hint: Optional[str] = None,
) -> Optional[float]:
    path = _resolve_data_csv_path(percentile, snapshot_path_hint)
    if not path or not os.path.isfile(path):
        return None
    col = _percentile_column(percentile, per_item=per_item)
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    mid = int(row["map_id"])
                    qg = str(row["quality_group"]).strip()
                except (KeyError, TypeError, ValueError):
                    continue
                if mid != int(map_id) or qg != quality_group:
                    continue
                raw = row.get(col)
                if raw is None or str(raw).strip() == "":
                    return None
                return float(raw)
    except OSError:
        return None
    return None


def load_map_quality_unit_price_refs(
    map_id: int,
    snapshot_path_hint: Optional[str] = None,
) -> Dict[str, Dict[str, Optional[float]]]:
    """
    返回 ``q5`` / ``q6`` / ``q56`` / ``q456`` 的 CSV 参考价（件价、格价 × 均价/P25/P50）。

    ``map_id`` 会先归一化为代表 ``map_id``（与同档最小图一致）。
    """
    rep_id, _pfx = representative_map_id_for_ticket(int(map_id), snapshot_path_hint)
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for cfg_key, csv_qg in CONFIG_TO_CSV.items():
        refs: Dict[str, Optional[float]] = {}
        for stat in ("avg", "p25", "p50"):
            refs[f"{stat}_per_cell"] = _load_row_values(
                rep_id, csv_qg, percentile=stat, per_item=False, snapshot_path_hint=snapshot_path_hint
            )
            refs[f"{stat}_per_item"] = _load_row_values(
                rep_id, csv_qg, percentile=stat, per_item=True, snapshot_path_hint=snapshot_path_hint
            )
        out[cfg_key] = refs
    return out


def config_overrides_from_pricing(pricing: Mapping[str, Any] | None) -> Dict[str, float]:
    """从 ``pricing.map_quality_unit_per_cell`` 解析有效覆盖（>0 的浮点）。"""
    if not isinstance(pricing, Mapping):
        return {}
    raw = pricing.get("map_quality_unit_per_cell")
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, float] = {}
    for cfg_key in CONFIG_KEYS:
        v = raw.get(cfg_key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0 and f == f:  # finite and positive
            out[cfg_key] = f
    return out


def apply_map_quality_unit_per_cell_overrides(
    per_cell: Dict[str, float],
    per_item: Dict[str, float],
    overrides: Mapping[str, float],
) -> tuple[Dict[str, float], Dict[str, float], list[str]]:
    """
    将配置覆盖写入 ``per_cell`` / ``per_item``（格价为主；件价按 CSV 均价比例缩放）。

    返回新 dict 与已应用的 CSV 品质键列表（如 ``q5``、``q6``、``q5+q6``、``q4+q5+q6``）。
    """
    cell_out = dict(per_cell)
    item_out = dict(per_item)
    applied_csv: list[str] = []
    for cfg_key, price_cell in overrides.items():
        csv_qg = CONFIG_TO_CSV.get(cfg_key)
        if not csv_qg:
            continue
        cell_out[csv_qg] = float(price_cell)
        applied_csv.append(csv_qg)
        old_cell = per_cell.get(csv_qg)
        old_item = per_item.get(csv_qg)
        if (
            old_cell is not None
            and old_item is not None
            and float(old_cell) > 0
        ):
            item_out[csv_qg] = float(old_item) * float(price_cell) / float(old_cell)
        else:
            item_out[csv_qg] = float(price_cell)
    return cell_out, item_out, applied_csv


def apply_map_overrides_to_csv_quality_groups(
    per_cell: Mapping[str, float],
    per_item: Mapping[str, float] | None,
    map_id: int,
    *,
    config: Mapping[str, Any] | None = None,
) -> tuple[Dict[str, float], Dict[str, float], list[str]]:
    """
    在已有 ``csv_quality_groups_avg_*`` 上重放 ``pricing.map_quality_unit_per_cell`` 覆盖。

    快照若内嵌旧 ``raw_pricing``，仍须按当前 ``pricing.maps`` 刷新格单价（画板实时刷新会重建 raw，
    但回放/写盘快照常复用缓存）。
    """
    cell_in = {str(k): float(v) for k, v in per_cell.items()}
    item_in: Dict[str, float] = {}
    if isinstance(per_item, Mapping):
        for k, v in per_item.items():
            try:
                item_in[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    if config is None:
        from ..config.runtime import load_runtime

        cfg = load_runtime().raw
    else:
        cfg = config
    ov = merge_config_overrides_into_runtime(cfg, int(map_id))
    if not ov:
        return cell_in, item_in, []
    return apply_map_quality_unit_per_cell_overrides(cell_in, item_in, ov)


def merge_config_overrides_into_runtime(
    config: Mapping[str, Any],
    map_id: int,
) -> Dict[str, float]:
    """按对局 ``map_id`` 档键合并 ``pricing.maps`` 后读取覆盖项。"""
    try:
        from ..config.map_runtime_overlay import merged_runtime_with_map_pricing
        from ..parsing.item_db import map_bundle_key_for_automation

        bk = map_bundle_key_for_automation(int(map_id))
        merged = merged_runtime_with_map_pricing(dict(config), map_bundle_key=bk)
        pricing = merged.get("pricing") if isinstance(merged.get("pricing"), dict) else {}
    except Exception:
        pricing = config.get("pricing") if isinstance(config.get("pricing"), Mapping) else {}
    return config_overrides_from_pricing(pricing)


__all__ = [
    "CONFIG_KEYS",
    "CONFIG_TO_CSV",
    "CSV_QUALITY_Q456",
    "CSV_QUALITY_Q56",
    "CSV_QUALITY_Q5",
    "CSV_QUALITY_Q6",
    "apply_map_overrides_to_csv_quality_groups",
    "apply_map_quality_unit_per_cell_overrides",
    "config_overrides_from_pricing",
    "load_map_quality_unit_price_refs",
    "merge_config_overrides_into_runtime",
]
