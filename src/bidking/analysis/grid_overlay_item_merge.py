"""``game_state.items`` 与 ``grid_overlay`` 的手动/幽灵/推断字段合并为定价用物品表。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

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


def apply_unknown_cell_quality_pref_to_items(
    items: Dict[str, Any], overlay: Any
) -> None:
    """
    将 ``grid_overlay.unknown_cell_quality_pref`` 写入合并表 ``quality``。

    与画板弹窗「候选品质」下拉一致：仅日志侧品质仍为空、且未精确价锁定 CID 时生效；
    须与 ``excluded_qualities`` 一致。早于 :func:`apply_manual_confirm_projection` 调用，
    以便双击确认候选后仍以 CSV 行为准覆盖手选档位。
    """
    if not isinstance(overlay, dict):
        return
    raw = overlay.get("unknown_cell_quality_pref")
    if not isinstance(raw, dict) or not raw:
        return
    for uid_raw, qv in raw.items():
        uid_s = str(uid_raw)
        row = items.get(uid_s)
        if not isinstance(row, dict):
            continue
        if row.get("quality") is not None:
            continue
        cid = row.get("item_cid")
        if cid is not None and row.get("price") is not None:
            continue
        q: Optional[int] = None
        if isinstance(qv, int) and 1 <= qv <= 6:
            q = qv
        else:
            try:
                qi = int(qv)
            except (TypeError, ValueError):
                continue
            if 1 <= qi <= 6:
                q = qi
        if q is None:
            continue
        ex = row.get("excluded_qualities")
        if isinstance(ex, (list, tuple, set)) and q in ex:
            continue
        row["quality"] = q


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
    """
    ``manual_shapes`` 格式为 ``[w,h,dc,dr]``。

    凡在 ``manual_shapes`` 中有条目的 uid，一律写入 ``shape=w*10+h`` 并标记 ``_overlay_shape_origin="manual"``，
    **覆盖**日志已有外形与先前推断外形，与画板拖框后 ``_manual_shapes`` 优先于推算一致。
    """
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
        if isinstance(row, dict):
            row["shape"] = sh
            row["_overlay_shape_origin"] = "manual"


_PHANTOM_QUALITY_PREF_INFER = "_phantom_q_infer"


def _excluded_qualities_set(row: Dict[str, Any]) -> Set[int]:
    ex: Set[int] = set()
    raw = row.get("excluded_qualities")
    if not isinstance(raw, (list, tuple, set)):
        return ex
    for x in raw:
        try:
            ex.add(int(x))
        except (TypeError, ValueError):
            continue
    return ex


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
        if q is not None and q not in _excluded_qualities_set(row):
            row["quality"] = q


def apply_phantom_default_quality_for_phantom_rows(items: Dict[str, Any], overlay: Any) -> None:
    """
    与 ``GridWindow._phantom_effective_quality`` 对齐：显式偏好应用后仍为 ``quality is None`` 的幽灵，
    若不是推断笔（``phantom_quality_pref != _phantom_q_infer``），则默认 **Q5（金笔缺省）**；
    扫描已排除 Q5（``5 in excluded_qualities``）时不强套金，保持 None。

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
        if 5 in _excluded_qualities_set(row):
            continue
        row["quality"] = 5


def sync_phantom_row_quality_from_overlay(items: Dict[str, Any], overlay: Any) -> None:
    """``phantom_quality_pref`` + 缺省 Q5；须在 ``apply_unknown_cell_quality_pref_to_items`` 与 ``apply_manual_confirm_projection`` 之前调用。"""
    if not isinstance(overlay, dict):
        return
    apply_phantom_quality_pref_to_items(items, overlay.get("phantom_quality_pref"))
    apply_phantom_default_quality_for_phantom_rows(items, overlay)


def merged_items_dict(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    ``game_state.items`` 与 ``grid_overlay`` 合并后的定价用物品表（浅拷贝各行 dict，可原地改投影字段）。

    ``phantom_quality_pref`` 会把显式 Q1–Q6 写入幽灵行的 ``quality``（与画板一致）；
    ``unknown_cell_quality_pref`` 将弹窗「候选品质」写入日志行 ``quality``（与画板一致）；
    缺省金笔且无推断偏好键时补 **Q5**（与 ``GridWindow._phantom_effective_quality`` 一致）。
    定价侧将该 ``shape`` 与手动画框、日志外形一样参与 CSV 轮廓匹配（见 :func:`_board_pricing._pricing_shape_int_for_csv`）。
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
        sync_phantom_row_quality_from_overlay(items, overlay)
        apply_unknown_cell_quality_pref_to_items(items, overlay)
    csv_index, _csv_items = _load_item_prices_db()
    apply_manual_confirm_projection(items, csv_index)
    return items


def _snapshot_item_row_keys_from_game() -> Tuple[str, ...]:
    """与 :func:`bidking.analysis.snapshot.item_knowledge_to_json` 字段一致（合并表日志行基底）。"""
    return (
        "uid",
        "box_id",
        "box_id_confirmed",
        "shape",
        "quality",
        "categories",
        "categories_any",
        "item_cid",
        "price",
        "manual_confirm_item_id",
        "excluded_categories",
        "excluded_qualities",
    )


def _copy_json_field(val: Any) -> Any:
    """浅拷贝列表等，避免与 ``game_state`` 共享可变引用。"""
    if isinstance(val, list):
        return list(val)
    if isinstance(val, dict):
        return dict(val)
    return val


def _patch_cached_merged_log_rows_from_game_items(
    out: Dict[str, Any], gs_items: Any
) -> bool:
    """
    将当前 ``game_state.items`` 写回缓存合并表中的日志行，再跑 overlay 管线。

    否则插件/桥接只刷新了 ``items``、未重写 ``merged_items_dict`` 时，会出现推断外形/品质/确认 id
    与日志脱节。
    """
    if not isinstance(gs_items, dict) or not isinstance(out, dict):
        return True
    keys = _snapshot_item_row_keys_from_game()
    for uid_raw, grow in gs_items.items():
        if not isinstance(grow, dict):
            continue
        uid_s = str(uid_raw)
        row = out.get(uid_s)
        if not isinstance(row, dict):
            return False
        for k in keys:
            row[k] = _copy_json_field(grow.get(k))
        if row.get("shape") is not None:
            row["_overlay_shape_origin"] = "game"
        else:
            row.pop("_overlay_shape_origin", None)
    return True


def _patch_cached_merged_phantom_rows_from_overlay(
    out: Dict[str, Any], overlay: Any
) -> bool:
    """
    用手画幽灵在 ``grid_overlay.phantom_items`` 中的当前 JSON 覆盖缓存里对应行，
    避免只改了幽灵锚格/外形而 ``merged_items_dict`` 未重导时仍用旧幽灵基底。
    """
    if not isinstance(overlay, dict) or not isinstance(out, dict):
        return True
    ph = overlay.get("phantom_items")
    if not isinstance(ph, dict):
        return True
    keys = _snapshot_item_row_keys_from_game()
    for pid, it in ph.items():
        ps = str(pid)
        if not isinstance(it, dict):
            continue
        row = out.get(ps)
        if not isinstance(row, dict):
            return False
        for k in keys:
            row[k] = _copy_json_field(it.get(k))
        if row.get("shape") is not None:
            row["_overlay_shape_origin"] = "game"
        else:
            row.pop("_overlay_shape_origin", None)
    return True


def _merged_items_dict_cache_phantom_set_stale(overlay: Any, out: Dict[str, Any]) -> bool:
    """``phantom_items`` 显式给出且 uid 集与缓存合并表不一致时须全量合并。"""
    if not isinstance(overlay, dict) or not isinstance(out, dict):
        return False
    if "phantom_items" not in overlay:
        return False
    ph = overlay.get("phantom_items")
    if not isinstance(ph, dict):
        return False
    ph_ids = {str(k) for k in ph}
    out_ph = {str(k) for k in out if str(k).startswith("phantom_")}
    if ph_ids != out_ph:
        return True
    for pid in ph_ids:
        if pid not in out:
            return True
    return False


def _merged_items_dict_cache_orphan_manual_shape(
    out: Dict[str, Any], manual_shapes: Any
) -> bool:
    """缓存行曾标为手动画框，但当前 ``manual_shapes`` 已无该 uid（用户撤销拖框）：须全量重合并。"""
    if not isinstance(out, dict):
        return False
    manual_map = manual_shapes if isinstance(manual_shapes, dict) else {}
    uids_m = {str(x) for x in manual_map}
    for uid_s, row in out.items():
        if (
            isinstance(row, dict)
            and row.get("_overlay_shape_origin") == "manual"
            and str(uid_s) not in uids_m
        ):
            return True
    return False


def merged_items_dict_from_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    优先使用 ``grid_overlay["merged_items_dict"]``（与 UI 写出一致），否则调用 :func:`merged_items_dict`。

    命中缓存时：

    1. 用当前 ``game_state.items`` **覆盖**缓存里对应日志行的基底字段（外形/品质/锚格/确认物品 id 等），
       避免桥接只更新 ``items``、未重写 ``merged_items_dict`` 时定价仍用旧推断/旧确认。
    2. 若幽灵 uid 集与 ``phantom_items`` 不一致（新增/删除手画幽灵），放弃缓存、全量合并。
    3. 若缓存行标 ``manual`` 但 ``manual_shapes`` 已无该 uid（撤销拖框），全量合并。
    4. 再按 ``manual_shapes``、``phantom_quality_pref``、``unknown_cell_quality_pref``、
       ``manual_confirm_projection`` 与全量路径一致地刷新。

    任一步发现日志 uid 在 ``items`` 中有而缓存合并表无，则全量 :func:`merged_items_dict`。
    """
    overlay = board_snapshot.get("grid_overlay")
    if isinstance(overlay, dict) and "merged_items_dict" in overlay:
        cached = overlay.get("merged_items_dict")
        if isinstance(cached, dict):
            gs = board_snapshot.get("game_state") or {}
            gs_items = gs.get("items") if isinstance(gs, dict) else None
            out: Dict[str, Any] = {}
            for k, v in cached.items():
                out[str(k)] = dict(v) if isinstance(v, dict) else v
            if not _patch_cached_merged_log_rows_from_game_items(out, gs_items):
                return merged_items_dict(board_snapshot)
            if not _patch_cached_merged_phantom_rows_from_overlay(out, overlay):
                return merged_items_dict(board_snapshot)
            if _merged_items_dict_cache_phantom_set_stale(overlay, out):
                return merged_items_dict(board_snapshot)
            manual_raw = overlay.get("manual_shapes")
            if _merged_items_dict_cache_orphan_manual_shape(out, manual_raw):
                return merged_items_dict(board_snapshot)
            apply_manual_shapes_to_items(out, manual_raw)
            sync_phantom_row_quality_from_overlay(out, overlay)
            apply_unknown_cell_quality_pref_to_items(out, overlay)
            csv_index, _ = _load_item_prices_db()
            apply_manual_confirm_projection(out, csv_index)
            return out
    return merged_items_dict(board_snapshot)
