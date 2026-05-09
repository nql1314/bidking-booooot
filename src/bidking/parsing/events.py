"""第 2 层 · 事件 dataclass。

将日志原始数据落到统一的事件类型，方便 analysis/ui 层订阅。
区分两类事件：

- **作用于物品**（``ItemAffectingEvent``）：含 ``box_id`` / 轮廓 / 品质 等
  对具体物品的揭示，由 :class:`HeroSkillEvent` / :class:`MapSkillEvent`
  / :class:`ItemSkillEvent` 携带。
- **全局统计性**（``GlobalSkillStats``）：``HitItemIndex`` / ``TotalHitBoxIndex`` /
  ``AllHitItemAvgPrice`` / ``AllHitBoxAvgPrice`` / ``HitItemTotalPrice`` /
  ``AllHitItemAvgBoxIndex`` / ``HitItemTypeList`` 等，常见于地图技能。

注意：本模块**只描述事件结构**，不做估价；与既有 ``processors``/``handlers``
共存——上层迁移期间可继续使用 dict 形式的事件，新代码倾向于这里的 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


@dataclass
class GlobalSkillStats:
    """技能日志条目内的全局统计字段（非物品维度）。"""
    hit_item_index: Optional[int] = None
    total_hit_box_index: Optional[int] = None
    all_hit_item_avg_price: Optional[int] = None
    all_hit_box_avg_price: Optional[int] = None
    hit_item_total_price: Optional[int] = None
    all_hit_item_avg_box_index: Optional[float] = None
    hit_item_type_list: List[int] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_log_entry(cls, entry: Mapping[str, Any]) -> "GlobalSkillStats":
        return cls(
            hit_item_index=entry.get("HitItemIndex"),
            total_hit_box_index=entry.get("TotalHitBoxIndex"),
            all_hit_item_avg_price=entry.get("AllHitItemAvgPrice"),
            all_hit_box_avg_price=entry.get("AllHitBoxAvgPrice"),
            hit_item_total_price=entry.get("HitItemTotalPrice"),
            all_hit_item_avg_box_index=entry.get("AllHitItemAvgBoxIndex"),
            hit_item_type_list=list(entry.get("HitItemTypeList") or []),
            extra={
                k: v
                for k, v in entry.items()
                if k
                not in {
                    "HitItemIndex",
                    "TotalHitBoxIndex",
                    "AllHitItemAvgPrice",
                    "AllHitBoxAvgPrice",
                    "HitItemTotalPrice",
                    "AllHitItemAvgBoxIndex",
                    "HitItemTypeList",
                    "HitBoxList",
                }
            },
        )


@dataclass
class HitBox:
    """物品维度的揭示原子（来自 ``HitBoxList[i]``）。"""
    item_uid: str
    box_id: Optional[int] = None
    item_slot_type: Optional[int] = None
    item_quility: Optional[int] = None
    item_cid: Optional[int] = None
    item_price: Optional[int] = None
    item_type: List[int] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_box(cls, box: Mapping[str, Any]) -> "HitBox":
        return cls(
            item_uid=str(box.get("ItemUid", "")),
            box_id=box.get("BoxId"),
            item_slot_type=box.get("ItemSlotType"),
            item_quility=box.get("ItemQuility"),
            item_cid=box.get("ItemCid"),
            item_price=box.get("ItemPrice"),
            item_type=list(box.get("ItemType") or []),
            raw=dict(box),
        )


@dataclass
class _SkillEventBase:
    skill_cid: int
    cast_round: Optional[int]
    completed_round: Optional[int]
    user_uid: Optional[str] = None
    hit_boxes: List[HitBox] = field(default_factory=list)
    stats: GlobalSkillStats = field(default_factory=GlobalSkillStats)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HeroSkillEvent(_SkillEventBase):
    """英雄技能；可能含全量品质扫描（→ ``record_scan('quality', ...)``）。"""
    quality_scan_value: Optional[int] = None


@dataclass
class MapSkillEvent(_SkillEventBase):
    """地图技能；多含全局统计字段；少量直接落到具体物品。"""
    forced_quality: Optional[int] = None


@dataclass
class ItemSkillEvent(_SkillEventBase):
    """道具（鉴影/揭示）；通常含全量类别扫描（→ ``record_scan('category', tag)``）。"""
    item_cid_used: Optional[int] = None
    category_tag: Optional[int] = None


@dataclass
class GameStartEvent:
    """对应 ``S2C_33_game_start_notify``。"""
    game_uid: str
    map_id: int
    players: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoundEndEvent:
    """对应 ``S2C_37_game_next_round_notify``：``round_no`` 是刚结束的回合。"""
    round_no: int
    hero_skill_events: List[HeroSkillEvent] = field(default_factory=list)
    map_skill_events: List[MapSkillEvent] = field(default_factory=list)
    item_skill_events: List[ItemSkillEvent] = field(default_factory=list)
    user_logs: Sequence[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GameOverEvent:
    """对应 ``S2C_45_game_over_notify``。"""
    final_round: int
    raw: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "GlobalSkillStats",
    "HitBox",
    "HeroSkillEvent",
    "MapSkillEvent",
    "ItemSkillEvent",
    "GameStartEvent",
    "RoundEndEvent",
    "GameOverEvent",
]
