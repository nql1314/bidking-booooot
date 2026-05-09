"""统一的画板快照 dict —— analysis 层对外的"主输出"。

来源：``parsing.state.GameState`` + 累积的地图技能日志条目；
消费方：``pricing`` 策略层、``ui`` 看板层、``bridge`` 文件写出器。

关键字段（与历史 `state_json.game_state_to_json` 兼容）：

- ``uid``                  对局 UID
- ``map_id``               地图 ID
- ``current_round``        当前回合（1-based）
- ``players``              ``{user_uid: {name, hero_cid, prices, items_used}}``
- ``items``                ``{item_uid: ItemKnowledge JSON}``
- ``displayed_event_uids`` 已展示的 ItemSkillLog Uid
- ``scan_history``         ``[{scan_type, value, hit_uids}, ...]``

并附加（由 analysis 计算）：

- ``map_skill_logs``       聚合后的最新 ``MapSkillLog`` 条目（按 SkillCid 取最新）
- ``pricing``              ``build_snapshot_pricing_dict`` 的派生指标（可选）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..parsing.state import GameState, ItemKnowledge


def item_knowledge_to_json(k: ItemKnowledge) -> Dict[str, Any]:
    return {
        "uid": k.uid,
        "box_id": k.box_id,
        "box_id_confirmed": k.box_id_confirmed,
        "shape": k.shape,
        "quality": k.quality,
        "categories": sorted(k.categories),
        "item_cid": k.item_cid,
        "price": k.price,
        "manual_confirm_item_id": k.manual_confirm_item_id,
        "excluded_categories": sorted(k.excluded_categories),
        "excluded_qualities": sorted(k.excluded_qualities),
    }


def item_knowledge_from_json(d: Dict[str, Any]) -> ItemKnowledge:
    k = ItemKnowledge(uid=str(d.get("uid", "")))
    k.box_id = d.get("box_id")
    k.box_id_confirmed = bool(d.get("box_id_confirmed", False))
    k.shape = d.get("shape")
    k.quality = d.get("quality")
    k.categories = set(int(x) for x in (d.get("categories") or []))
    k.item_cid = d.get("item_cid")
    k.price = d.get("price")
    k.manual_confirm_item_id = d.get("manual_confirm_item_id")
    k.excluded_categories = set(int(x) for x in (d.get("excluded_categories") or []))
    k.excluded_qualities = set(int(x) for x in (d.get("excluded_qualities") or []))
    return k


def _player_to_json(p: dict) -> Dict[str, Any]:
    prices = p.get("prices") or {}
    items_used = p.get("items_used") or {}
    return {
        "name": p.get("name", ""),
        "hero_cid": int(p.get("hero_cid", 0) or 0),
        "prices": {str(int(k)): int(v) for k, v in prices.items()},
        "items_used": {str(int(k)): int(v) for k, v in items_used.items()},
    }


def game_state_to_json(state: GameState) -> Dict[str, Any]:
    players_out: Dict[str, Any] = {}
    for uid, p in (state.players or {}).items():
        players_out[str(uid)] = _player_to_json(p if isinstance(p, dict) else {})

    items_out: Dict[str, Any] = {}
    for item_uid, k in (state.items or {}).items():
        items_out[str(item_uid)] = item_knowledge_to_json(k)

    scan_history: List[Dict[str, Any]] = []
    for scan_type, value, hit_uids in getattr(state, "_scan_history", []) or []:
        scan_history.append(
            {
                "scan_type": scan_type,
                "value": int(value),
                "hit_uids": sorted(hit_uids),
            }
        )

    return {
        "uid": state.uid or "",
        "map_id": int(state.map_id or 0),
        "current_round": int(state.current_round or 1),
        "players": players_out,
        "items": items_out,
        "displayed_event_uids": sorted(state.displayed_event_uids),
        "scan_history": scan_history,
    }


def game_state_from_json(d: Dict[str, Any]) -> GameState:
    """仅供测试 / 工具回放；不还原内部处理器缓存。"""
    st = GameState()
    st.uid = str(d.get("uid", "") or "")
    st.map_id = int(d.get("map_id", 0) or 0)
    st.current_round = int(d.get("current_round", 1) or 1)
    for p_uid, pj in (d.get("players") or {}).items():
        if not isinstance(pj, dict):
            continue
        prices_raw = pj.get("prices") or {}
        items_raw = pj.get("items_used") or {}
        st.players[str(p_uid)] = {
            "name": pj.get("name", ""),
            "hero_cid": int(pj.get("hero_cid", 0) or 0),
            "prices": {int(k): int(v) for k, v in prices_raw.items()},
            "items_used": {int(k): int(v) for k, v in items_raw.items()},
        }
    for i_uid, ij in (d.get("items") or {}).items():
        if isinstance(ij, dict):
            st.items[str(i_uid)] = item_knowledge_from_json(ij)
    for u in d.get("displayed_event_uids") or []:
        st.displayed_event_uids.add(str(u))
    for row in d.get("scan_history") or []:
        if not isinstance(row, dict):
            continue
        hit = frozenset(str(x) for x in (row.get("hit_uids") or []))
        st._scan_history.append((str(row.get("scan_type")), int(row.get("value", 0)), hit))
    return st


def build_board_snapshot(
    state: GameState,
    *,
    map_skill_logs: Optional[List[dict]] = None,
    include_pricing: bool = False,
) -> Dict[str, Any]:
    """统一画板快照构造入口。

    若 ``include_pricing=True``，会调用 :mod:`._board_pricing` 计算
    ``pricing`` 子 dict，挂在结果根上。
    """
    snap = game_state_to_json(state)
    if map_skill_logs is not None:
        snap["map_skill_logs"] = list(map_skill_logs)
    if include_pricing:
        from ._board_pricing import build_snapshot_pricing_dict

        try:
            snap["pricing"] = build_snapshot_pricing_dict(snap)
        except Exception:
            snap["pricing"] = {}
    return snap
