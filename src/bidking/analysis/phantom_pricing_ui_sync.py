# -*- coding: utf-8 -*-
"""定价四轮幽灵分摊结果 → 画板 ``ItemKnowledge`` / ``phantom_quality_pref`` 同步。"""

from __future__ import annotations

from typing import Any, Dict, List, MutableMapping, Union

from ..parsing.state import ItemKnowledge

PHANTOM_Q_INFER = "_phantom_q_infer"


def phantom_quality_pref_explicit_quality(raw: Any) -> Union[int, None]:
    """显式 Q1–Q6；``_phantom_q_infer`` 与无效值返回 ``None``。"""
    if isinstance(raw, int) and 1 <= raw <= 6:
        return int(raw)
    if isinstance(raw, str):
        if raw.strip() == PHANTOM_Q_INFER:
            return None
        try:
            q = int(raw.strip())
        except (TypeError, ValueError):
            return None
        if 1 <= q <= 6:
            return q
    return None


def clear_phantom_auto_resolution_on_item(pk: ItemKnowledge) -> None:
    """用户手改幽灵品质/偏好时，清掉定价分摊写回的锁定字段。"""
    pk.quality = None
    pk.manual_confirm_item_id = None
    pk.item_cid = None
    pk.price = None


def _int_or_none(raw: Any) -> Union[int, None]:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def sync_phantom_items_from_overlay_after_pricing(
    overlay: Any,
    phantom_items: MutableMapping[str, ItemKnowledge],
    phantom_quality_pref: MutableMapping[str, Union[int, str]],
) -> List[str]:
    """
    将 ``phantom_unknown_tier_credit_q456`` 写回 ``grid_overlay`` 的字段同步到画板内存态。

    与手选品质 / 双击确认候选等价：更新 ``quality``、``manual_confirm_item_id``、
    ``item_cid`` / ``price`` / ``shape`` 及 ``phantom_quality_pref``。
    金红分拆（``phantom_tier_credit_by_quality`` 且 ``quality is None``）保持推断笔。

    返回发生变化的幽灵 ``uid`` 列表。
    """
    if not isinstance(overlay, dict):
        return []
    ph = overlay.get("phantom_items")
    if not isinstance(ph, dict):
        return []
    pref_raw = overlay.get("phantom_quality_pref")
    pref_overlay: Dict[str, Any] = pref_raw if isinstance(pref_raw, dict) else {}

    changed: List[str] = []

    for uid_s, pk in list(phantom_items.items()):
        row = ph.get(uid_s)
        if not isinstance(row, dict):
            continue
        uid_changed = False

        mc = _int_or_none(row.get("manual_confirm_item_id"))
        if pk.manual_confirm_item_id != mc:
            pk.manual_confirm_item_id = mc
            uid_changed = True

        cid = _int_or_none(row.get("item_cid"))
        if pk.item_cid != cid:
            pk.item_cid = cid
            uid_changed = True

        price = row.get("price")
        if price is not None:
            try:
                price_i = int(price)
            except (TypeError, ValueError):
                price_i = None
            if pk.price != price_i:
                pk.price = price_i
                uid_changed = True

        sh = _int_or_none(row.get("shape"))
        if sh is not None and pk.shape != sh:
            pk.shape = sh
            uid_changed = True

        tier_split = row.get("phantom_tier_credit_by_quality")
        pref_v = pref_overlay.get(uid_s)
        explicit_pref = phantom_quality_pref_explicit_quality(pref_v)
        infer_pref = pref_v == PHANTOM_Q_INFER or (
            isinstance(pref_v, str) and pref_v.strip() == PHANTOM_Q_INFER
        )
        q_new: Union[int, None] = _int_or_none(row.get("quality"))
        if explicit_pref is not None:
            if pk.quality != explicit_pref:
                pk.quality = explicit_pref
                uid_changed = True
            if phantom_quality_pref.get(uid_s) != explicit_pref:
                phantom_quality_pref[uid_s] = explicit_pref
                uid_changed = True
        elif isinstance(tier_split, dict) and tier_split:
            if pk.quality is not None:
                pk.quality = None
                uid_changed = True
            if phantom_quality_pref.get(uid_s) != PHANTOM_Q_INFER:
                phantom_quality_pref[uid_s] = PHANTOM_Q_INFER
                uid_changed = True
        elif infer_pref:
            if pk.quality is not None:
                pk.quality = None
                uid_changed = True
            if phantom_quality_pref.get(uid_s) != PHANTOM_Q_INFER:
                phantom_quality_pref[uid_s] = PHANTOM_Q_INFER
                uid_changed = True
        elif q_new is not None and 1 <= q_new <= 6:
            if pk.quality != q_new:
                pk.quality = q_new
                uid_changed = True
            if phantom_quality_pref.get(uid_s) != q_new:
                phantom_quality_pref[uid_s] = q_new
                uid_changed = True
        else:
            if pref_v is not None and phantom_quality_pref.get(uid_s) != pref_v:
                phantom_quality_pref[uid_s] = (
                    int(pref_v)
                    if isinstance(pref_v, int)
                    else str(pref_v)
                )
                uid_changed = True

        if uid_changed:
            changed.append(uid_s)

    return changed
