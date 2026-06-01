# -*- coding: utf-8 -*-
"""手画网格覆盖层与日志状态同步（从 ``GridWindow`` 拆出，避免 UI 内嵌占位/幽灵算法）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple, Union

from ...analysis.grid_overlay_infer_vacant_rects import (
    VacantRectPhantomSpec,
    is_auto_vacant_rect_phantom_uid,
)
from ...analysis.scan_inference import apply_census_absent_qualities_from_raw_pricing
from ...parsing.state import GameState, ItemKnowledge

GRID_COLS = 10

# 与 ``_grid_view.PHANTOM_Q_INFER`` 一致：幽灵品质「原推断」占位
PHANTOM_Q_INFER = "_phantom_q_infer"
# 快照中表示 ``phantom_quality_pref`` 无键（金默认 Q5）
_VACANT_Q_PREF_ABSENT = object()


def _shape_wh(shape: object) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1


def effective_display_origin(
    uid: str,
    k: ItemKnowledge,
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
) -> Tuple[int, int]:
    if uid in manual_shapes:
        _, _, dc, dr = manual_shapes[uid]
        return dc, dr
    if k.box_id is None:
        return 0, 0
    return k.box_id % GRID_COLS, k.box_id // GRID_COLS


def effective_shape_wh(
    uid: str,
    k: ItemKnowledge,
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
) -> Tuple[int, int]:
    if k.shape is not None:
        return _shape_wh(k.shape)
    if uid in manual_shapes:
        w, h, _, _ = manual_shapes[uid]
        return w, h
    return 1, 1


def strip_manual_shapes_when_log_locked(
    items: Dict[str, ItemKnowledge],
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
) -> None:
    for uid, k in items.items():
        if k.shape is not None:
            manual_shapes.pop(uid, None)


def remove_phantoms_overlapping_confirmed_log(
    state_items: Dict[str, ItemKnowledge],
    phantom_items: Dict[str, ItemKnowledge],
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
    phantom_quality_pref: Dict[str, Union[int, str]],
) -> None:
    confirmed_occ: Set[Tuple[int, int]] = set()
    for uid, k in state_items.items():
        if k.box_id is None or not k.box_id_confirmed:
            continue
        dc, dr = effective_display_origin(uid, k, manual_shapes)
        w, h = effective_shape_wh(uid, k, manual_shapes)
        for ddr in range(h):
            for ddc in range(w):
                confirmed_occ.add((dr + ddr, dc + ddc))
    to_del: list = []
    for phid in phantom_items:
        if phid not in manual_shapes:
            continue
        w, h, dc, dr = manual_shapes[phid]
        if any(
            (dr + ddr, dc + ddc) in confirmed_occ
            for ddr in range(h)
            for ddc in range(w)
        ):
            to_del.append(phid)
    for phid in to_del:
        phantom_items.pop(phid, None)
        manual_shapes.pop(phid, None)
        phantom_quality_pref.pop(phid, None)


def apply_scan_history_to_phantom_items(
    phantom_items: Dict[str, ItemKnowledge],
    state: GameState,
) -> None:
    hist = getattr(state, "_scan_history", None) or []
    for phid, pk in phantom_items.items():
        for scan_type, value, hit_uids in hist:
            if phid in hit_uids:
                continue
            if scan_type == "category":
                pk.excluded_categories.add(value)
            else:
                pk.excluded_qualities.add(value)


@dataclass(frozen=True)
class AutoVacantPhantomSavedState:
    """purge 自动 ``phantom_vac_*`` 前保存的用户态与定价写回确认，供重算后恢复。"""

    quality_pref: object
    manual_confirm_item_id: Optional[int] = None
    user_locked: bool = False


def snapshot_auto_vacant_phantom_user_state(
    phantom_items: Dict[str, ItemKnowledge],
    phantom_quality_pref: Dict[str, Union[int, str]],
    phantom_quality_user_locked: Set[str],
) -> Dict[str, AutoVacantPhantomSavedState]:
    """在 purge 自动 ``phantom_vac_*`` 前保存品质偏好与手动物品确认，供重算后恢复。"""
    out: Dict[str, AutoVacantPhantomSavedState] = {}
    for uid in phantom_items:
        if not is_auto_vacant_rect_phantom_uid(uid):
            continue
        pk = phantom_items[uid]
        mc_raw = pk.manual_confirm_item_id
        mc_i: Optional[int] = None
        if mc_raw is not None:
            try:
                v = int(mc_raw)
                if v > 0:
                    mc_i = v
            except (TypeError, ValueError):
                pass
        out[uid] = AutoVacantPhantomSavedState(
            quality_pref=phantom_quality_pref.get(uid, _VACANT_Q_PREF_ABSENT),
            manual_confirm_item_id=mc_i,
            user_locked=uid in phantom_quality_user_locked,
        )
    return out


def snapshot_auto_vacant_phantom_quality_prefs(
    phantom_items: Dict[str, ItemKnowledge],
    phantom_quality_pref: Dict[str, Union[int, str]],
) -> Dict[str, object]:
    """兼容旧接口：仅保存品质偏好。"""
    saved = snapshot_auto_vacant_phantom_user_state(
        phantom_items, phantom_quality_pref, set()
    )
    return {uid: st.quality_pref for uid, st in saved.items()}


def apply_auto_vacant_phantom_manual_confirm(
    uid: str,
    pk: ItemKnowledge,
    spec: VacantRectPhantomSpec,
    saved: Dict[str, AutoVacantPhantomSavedState],
) -> None:
    """重算后写入 ``manual_confirm_item_id``：purge 前已有确认（含定价写回/用户锁定）优先于推断唯一补齐。"""
    prev = saved.get(uid)
    if prev is not None and prev.manual_confirm_item_id is not None:
        pk.manual_confirm_item_id = int(prev.manual_confirm_item_id)
        return
    if spec.manual_confirm_item_id is not None:
        pk.manual_confirm_item_id = int(spec.manual_confirm_item_id)


def vacant_rect_spec_auto_quality_pref(spec: VacantRectPhantomSpec) -> object:
    if spec.manual_confirm_item_id is not None:
        return _VACANT_Q_PREF_ABSENT
    if spec.quality is not None:
        return int(spec.quality)
    return PHANTOM_Q_INFER


def apply_vacant_rect_phantom_quality_pref(
    uid: str,
    spec: VacantRectPhantomSpec,
    phantom_quality_pref: Dict[str, Union[int, str]],
    saved: Dict[str, AutoVacantPhantomSavedState],
) -> None:
    """写入推断默认品质；若该 uid 此前存在且与用户手改不一致则保留手改。"""
    auto = vacant_rect_spec_auto_quality_pref(spec)
    if auto is _VACANT_Q_PREF_ABSENT:
        phantom_quality_pref.pop(uid, None)
    elif auto == PHANTOM_Q_INFER:
        phantom_quality_pref[uid] = PHANTOM_Q_INFER
    else:
        phantom_quality_pref[uid] = int(auto)

    if uid not in saved:
        return
    prev = saved[uid].quality_pref
    if prev == auto:
        return
    if prev is _VACANT_Q_PREF_ABSENT:
        phantom_quality_pref.pop(uid, None)
    else:
        phantom_quality_pref[uid] = prev  # type: ignore[assignment]


def restore_auto_vacant_phantom_user_locked(
    uid: str,
    saved: Dict[str, AutoVacantPhantomSavedState],
    phantom_quality_user_locked: Set[str],
) -> None:
    prev = saved.get(uid)
    if prev is not None and prev.user_locked:
        phantom_quality_user_locked.add(uid)


def reconcile_overlay_after_refresh(
    state: GameState,
    manual_shapes: Dict[str, Tuple[int, int, int, int]],
    phantom_items: Dict[str, ItemKnowledge],
    phantom_quality_pref: Dict[str, Union[int, str]],
    *,
    raw_pricing: Optional[Dict[str, Any]] = None,
) -> None:
    """日志刷新后：清掉已由协议锁外形的手动矩形、删掉与已确认物品重叠的幽灵、同步扫描负向约束。"""
    strip_manual_shapes_when_log_locked(state.items, manual_shapes)
    remove_phantoms_overlapping_confirmed_log(
        state.items, phantom_items, manual_shapes, phantom_quality_pref
    )
    apply_scan_history_to_phantom_items(phantom_items, state)
    apply_census_absent_qualities_from_raw_pricing(state.items, phantom_items, raw_pricing)
