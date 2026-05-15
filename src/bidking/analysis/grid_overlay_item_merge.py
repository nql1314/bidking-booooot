"""``game_state.items`` 与 ``grid_overlay`` 的手动/幽灵/推断字段合并为定价用物品表。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..parsing import item_db
from . import unknown_value as _unknown_value

_item_prices_cache: Optional[Tuple[Dict[int, Any], list]] = None


def _load_item_prices_db() -> Tuple[Dict[int, Any], list]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    path = _unknown_value._item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache


def _parse_manual_shape_entry(entry: Any) -> Optional[Tuple[int, int, int, int]]:
    if isinstance(entry, (list, tuple)) and len(entry) >= 4:
        try:
            return int(entry[0]), int(entry[1]), int(entry[2]), int(entry[3])
        except (TypeError, ValueError):
            return None
    if isinstance(entry, dict):
        try:
            return (
                int(entry["w"]),
                int(entry["h"]),
                int(entry["dc"]),
                int(entry["dr"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _shape_int_from_wh(w: int, h: int) -> Optional[int]:
    if 1 <= w <= 9 and 1 <= h <= 9:
        return w * 10 + h
    return None


def apply_manual_confirm_projection(
    items: Dict[str, Any],
    csv_index: Dict[int, Any],
) -> None:
    """将 ``manual_confirm_item_id`` 投影为定价用 ``item_cid`` / ``quality`` / ``shape`` / ``price``。"""
    for row in items.values():
        if not isinstance(row, dict):
            continue
        cid = row.get("manual_confirm_item_id")
        if not cid:
            continue
        try:
            item = csv_index.get(int(cid))
        except (TypeError, ValueError):
            item = None
        if item is None:
            continue
        row["item_cid"] = int(item.item_id)
        row["quality"] = int(item.quality)
        row["shape"] = int(item.shape)
        row["price"] = int(item.base_value)
        row["_overlay_shape_origin"] = "game"


def apply_manual_shapes_to_items(items: Dict[str, Any], manual_shapes: Any) -> None:
    if not isinstance(manual_shapes, dict):
        return
    for uid, entry in manual_shapes.items():
        uid_s = str(uid)
        tup = _parse_manual_shape_entry(entry)
        if tup is None:
            continue
        w, h = tup[0], tup[1]
        sh = _shape_int_from_wh(w, h)
        if sh is None:
            continue
        row = items.get(uid_s)
        if isinstance(row, dict) and row.get("shape") is None:
            row["shape"] = sh
            row["_overlay_shape_origin"] = "manual"


def apply_infer_shapes_to_items(items: Dict[str, Any], infer_shapes: Any) -> None:
    """``infer_shapes`` 与 ``manual_shapes`` 同格式；仅填补仍为 ``shape is None`` 的行（不覆盖手动画框）。"""
    if not isinstance(infer_shapes, dict):
        return
    for uid, entry in infer_shapes.items():
        uid_s = str(uid)
        tup = _parse_manual_shape_entry(entry)
        if tup is None:
            continue
        w, h = tup[0], tup[1]
        sh = _shape_int_from_wh(w, h)
        if sh is None:
            continue
        row = items.get(uid_s)
        if isinstance(row, dict) and row.get("shape") is None:
            row["shape"] = sh
            row["_overlay_shape_origin"] = "infer"


_PHANTOM_QUALITY_PREF_INFER = "_phantom_q_infer"


def apply_phantom_quality_pref_to_items(items: Dict[str, Any], phantom_quality_pref: Any) -> None:
    """
    将 ``grid_overlay.phantom_quality_pref`` 写入合并表中的 ``quality``。

    手画幽灵在 ``phantom_items`` JSON 里常为 ``quality: null``，真实档位仅保存在偏好里；
    若不合并，定价会把幽灵当成「品质未知」走入 known-contour 加权 / kcw 分支。
    """
    if not isinstance(phantom_quality_pref, dict):
        return
    for uid_raw, val in phantom_quality_pref.items():
        uid_s = str(uid_raw)
        row = items.get(uid_s)
        if not isinstance(row, dict):
            continue
        q: Optional[int] = None
        if isinstance(val, int) and 1 <= val <= 6:
            q = val
        elif isinstance(val, str):
            if val.strip() == _PHANTOM_QUALITY_PREF_INFER:
                continue
            try:
                vi = int(val.strip())
            except (TypeError, ValueError):
                continue
            if 1 <= vi <= 6:
                q = vi
        if q is not None:
            row["quality"] = q


def apply_phantom_default_quality_for_phantom_rows(items: Dict[str, Any], overlay: Any) -> None:
    """
    与 ``GridWindow._phantom_effective_quality`` 对齐：显式偏好应用后仍为 ``quality is None`` 的幽灵，
    若不是推断笔（``phantom_quality_pref != _phantom_q_infer``），则默认 **Q5（金笔缺省）**。

    推断笔在偏好里为 ``_phantom_q_infer`` 时不写入，保持 None。
    """
    if not isinstance(overlay, dict):
        return
    ph = overlay.get("phantom_items")
    if not isinstance(ph, dict):
        return
    pref = overlay.get("phantom_quality_pref")
    pref_d: Dict[str, Any] = pref if isinstance(pref, dict) else {}
    for uid_raw in ph:
        uid_s = str(uid_raw)
        row = items.get(uid_s)
        if not isinstance(row, dict) or row.get("quality") is not None:
            continue
        raw_p = pref_d.get(uid_s)
        if raw_p is None:
            raw_p = pref_d.get(uid_raw)
        if isinstance(raw_p, str) and raw_p.strip() == _PHANTOM_QUALITY_PREF_INFER:
            continue
        if raw_p == _PHANTOM_QUALITY_PREF_INFER:
            continue
        row["quality"] = 5


def sync_phantom_row_quality_from_overlay(items: Dict[str, Any], overlay: Any) -> None:
    """``phantom_quality_pref`` + 缺省 Q5；须在 ``manual_confirm_projection`` 之前调用。"""
    if not isinstance(overlay, dict):
        return
    apply_phantom_quality_pref_to_items(items, overlay.get("phantom_quality_pref"))
    apply_phantom_default_quality_for_phantom_rows(items, overlay)


def merged_items_dict(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    ``game_state.items`` 与 ``grid_overlay`` 合并后的定价用物品表（浅拷贝各行 dict，可原地改投影字段）。

    ``grid_overlay.infer_shapes`` 会写入几何用 ``shape``，并标记 ``_overlay_shape_origin == "infer"``；
    ``phantom_quality_pref`` 会把显式 Q1–Q6 写入幽灵行的 ``quality``（与画板一致）；
    缺省金笔且无推断偏好键时补 **Q5**（与 ``GridWindow._phantom_effective_quality`` 一致）。
    定价侧对推断外形按未知轮廓做多候选加权（见 :mod:`_board_pricing`）。
    """
    gs = board_snapshot.get("game_state") or {}
    raw = gs.get("items") if isinstance(gs, dict) else None
    items: Dict[str, Any] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                row = dict(v)
                if row.get("shape") is not None:
                    row["_overlay_shape_origin"] = "game"
                items[str(k)] = row
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict):
        ph = overlay.get("phantom_items")
        if isinstance(ph, dict):
            for uid, it in ph.items():
                suid = str(uid)
                if suid not in items and isinstance(it, dict):
                    prow = dict(it)
                    if prow.get("shape") is not None:
                        prow["_overlay_shape_origin"] = "game"
                    items[suid] = prow
        apply_manual_shapes_to_items(items, overlay.get("manual_shapes"))
        apply_infer_shapes_to_items(items, overlay.get("infer_shapes"))
        sync_phantom_row_quality_from_overlay(items, overlay)
    csv_index, _csv_items = _load_item_prices_db()
    apply_manual_confirm_projection(items, csv_index)
    return items


def merged_items_dict_from_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    优先使用 ``grid_overlay["merged_items_dict"]``（与 UI 写出一致），否则调用 :func:`merged_items_dict`。

    命中缓存时仍会按当前 ``phantom_items`` / ``phantom_quality_pref`` **重写幽灵 ``quality``**，
    避免磁盘里旧的 ``merged_items_dict`` 与偏好脱节。
    """
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict) and "merged_items_dict" in overlay:
        cached = overlay.get("merged_items_dict")
        if isinstance(cached, dict):
            out: Dict[str, Any] = {}
            for k, v in cached.items():
                out[str(k)] = dict(v) if isinstance(v, dict) else v
            sync_phantom_row_quality_from_overlay(out, overlay)
            return out
    return merged_items_dict(board_snapshot)
