# -*- coding: utf-8 -*-
"""英雄 SkillCid 与道具 ItemCid 同号时合并分表（避免误读 TotalHitBoxIndex 等）。"""

from __future__ import annotations

import unittest

from bidking.analysis.skill_event_stats_from_logs import (
    merge_latest_skill_entries,
    parse_skill_entries_to_event_stats_direct,
)


class TestSkillItemMergeSplit(unittest.TestCase):
    def test_hero_skill_100105_does_not_satisfy_item_100105_bindings(self) -> None:
        """仅有英雄 SkillCid=100105 时，不得从该条读道具 TotalHitBoxIndex 写出 q3_grid_count=0。"""
        logs = [
            {
                "event_type": "S2C_37_game_next_round_notify",
                "game_data": {
                    "HeroSkillLog": [
                        {
                            "SkillCid": 100105,
                            "HeroCid": 105,
                            "CastTime": "1",
                            "HitBoxList": [
                                {
                                    "BoxId": 1,
                                    "ItemUid": "961935681275791",
                                    "ItemSlotType": 11,
                                    "ItemQuility": 3,
                                }
                            ],
                            "Uid": "961935681276049",
                        }
                    ]
                },
            }
        ]
        merged = merge_latest_skill_entries(logs)
        self.assertIn(100105, merged.by_skill_cid)
        self.assertNotIn(100105, merged.by_item_cid)
        es = parse_skill_entries_to_event_stats_direct(merged)
        self.assertIsNone(
            es.get("q3_grid_count"),
            "q3_grid_count 不应因英雄日志缺 TotalHitBoxIndex 被写成 0",
        )

    def test_item_100105_scan_still_writes_q3_grid_count(self) -> None:
        logs = [
            {
                "event_type": "x",
                "game_data": {
                    "ItemSkillLog": [
                        {
                            "ItemCid": 100105,
                            "SkillCid": 100105,
                            "TotalHitBoxIndex": 5,
                            "Uid": "item_uid_1",
                        }
                    ]
                },
            }
        ]
        merged = merge_latest_skill_entries(logs)
        self.assertEqual(merged.by_item_cid[100105].get("TotalHitBoxIndex"), 5)
        es = parse_skill_entries_to_event_stats_direct(merged)
        self.assertEqual(es.get("q3_grid_count"), 5)


if __name__ == "__main__":
    unittest.main()
