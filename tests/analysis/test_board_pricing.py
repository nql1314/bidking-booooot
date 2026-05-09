# -*- coding: utf-8 -*-
"""getlog.board_pricing 单测（不依赖 tkinter）。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidking.analysis import _board_pricing as bp
from bidking.parsing.constants import (
    MAP_SKILL_TOTAL_GOLD_CELLS,
    MAP_SKILL_TOTAL_HIDDEN_CELLS,
    MAP_SKILL_TOTAL_RED_CELLS,
)


class BoardPricingTests(unittest.TestCase):
    def tearDown(self) -> None:
        bp.set_map_quality_csv_override(None)

    def test_csv_quality_group_from_possible_set(self) -> None:
        self.assertIsNone(bp._csv_quality_group_from_possible_set(frozenset()))
        self.assertEqual(
            bp._csv_quality_group_from_possible_set(frozenset(range(1, 7))),
            "all",
        )
        self.assertEqual(bp._csv_quality_group_from_possible_set(frozenset({3})), "q3")
        self.assertEqual(
            bp._csv_quality_group_from_possible_set(frozenset({5, 6})),
            "q5+q6",
        )

    def test_possible_qualities_empty_when_no_unknown_items(self) -> None:
        """无 quality 扫描时：空格品质推断不读 items，仍视为全集。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 3,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": 5,
                },
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        self.assertEqual(
            bp._possible_qualities_from_negative_constraints(snap),
            frozenset(range(1, 7)),
        )

    def test_possible_qualities_from_scan_history_miss_implies_not_that_tier(self) -> None:
        """品质扫描的 hit_uids 为已揭示该档的物品；未知 uid 未命中则排除该档。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "unk": {
                    "uid": "unk",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["814463533815838"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["814463533815815"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["814463533815811"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["814463533815812"]},
                {"scan_type": "category", "value": 101, "hit_uids": ["x"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        poss = bp._possible_qualities_from_negative_constraints(snap)
        self.assertEqual(poss, frozenset({5, 6}))

    def test_possible_qualities_quality_scan_same_value_last_overwrites(self) -> None:
        """同一 value 多条 quality 扫描时以后出现的 hit_uids 为准。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "unk": {
                    "uid": "unk",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 3, "hit_uids": ["unk"]},
                {"scan_type": "quality", "value": 3, "hit_uids": []},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        poss = bp._possible_qualities_from_negative_constraints(snap)
        self.assertEqual(poss, frozenset({1, 2, 4, 5, 6}))

    def test_possible_qualities_no_quality_scans_is_all(self) -> None:
        """无 quality 扫描时未知物品仍可能品质为全集 → 全局 all。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [1, 2, 3, 4],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        all_q = frozenset(range(1, 7))
        poss = bp._possible_qualities_from_negative_constraints(snap)
        self.assertEqual(poss, all_q)
        self.assertEqual(bp._csv_quality_group_from_possible_set(poss), "all")

    def test_possible_qualities_scan_only_q56(self) -> None:
        """仅 scan_history：未知 uid 未出现在 1–4 档 hit → 仍可能 5、6。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["814463533815838"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["814463533815815"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["814463533815811"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["814463533815812"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        poss = bp._possible_qualities_from_negative_constraints(snap)
        self.assertEqual(poss, frozenset({5, 6}))
        self.assertEqual(bp._csv_quality_group_from_possible_set(poss), "q5+q6")

    def test_vacant_early_unit_csv_miss_is_zero(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["x"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        unit, qg, _ = bp._vacant_early_unit_from_exclusions(
            board_snapshot=snap,
            csv_cells_raw={"q3": 99.0},
            csv_cells={"q3": 99.0},
            blends=None,
            pricing={},
        )
        self.assertEqual(qg, "q5+q6")
        self.assertEqual(unit, 0)

    def test_vacant_early_unit_csv_hit(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["x"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        raw = {"q5+q6": 1234.56}
        unit, qg, _ = bp._vacant_early_unit_from_exclusions(
            board_snapshot=snap,
            csv_cells_raw=raw,
            csv_cells=dict(raw),
            blends=None,
            pricing={},
        )
        self.assertEqual(qg, "q5+q6")
        self.assertEqual(unit, 1235)

    def test_possible_qualities_intersection_unknown_items(self) -> None:
        """仅 scan_history：各档扫描若仅此且空 hit → 该档不可能；未扫描的档仍可能（与 items 数量无关）。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
                "b": {
                    "uid": "b",
                    "box_id": 1,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": []},
                {"scan_type": "quality", "value": 2, "hit_uids": []},
                {"scan_type": "quality", "value": 4, "hit_uids": []},
                {"scan_type": "quality", "value": 5, "hit_uids": []},
                {"scan_type": "quality", "value": 6, "hit_uids": []},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1000.0}, "skill_logs": []}
        poss = bp._possible_qualities_from_negative_constraints(snap)
        self.assertEqual(poss, frozenset({3}))

    def test_map_skill_total_hidden_cells_from_logs(self) -> None:
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": 200009, "TotalHitBoxIndex": 42},
                    ]
                }
            }
        ]
        self.assertEqual(bp.map_skill_total_hidden_cells_from_logs(logs), 42)
        self.assertIsNone(bp.map_skill_total_hidden_cells_from_logs([]))

    def test_vacant_units_default_map(self) -> None:
        u5, u56, u6, hit = bp.vacant_unit_prices_for_map_id(0, None)
        self.assertFalse(hit)
        self.assertEqual(u5, bp.VACANT_UNIT_ALL_ORANGE)

    def test_map_quality_csv_uses_normalize_map_id_41xx(self) -> None:
        """CSV 仅含 21xx 时，日志 41xx（等价 MapCid）应命中同一行。"""
        keys = [
            "map_id",
            "tier",
            "nest_drop_id",
            "quality_group",
            "prob_in_group",
            "avg_price_per_item",
            "avg_price_per_cell",
        ]
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            suffix=".csv",
            delete=False,
            newline="",
        ) as tf:
            path = tf.name
            w = csv.DictWriter(tf, fieldnames=keys)
            w.writeheader()
            base = {
                "map_id": "2101",
                "tier": "101",
                "nest_drop_id": "2001",
                "prob_in_group": "1",
                "avg_price_per_item": "1",
            }
            w.writerow({**base, "quality_group": "q5", "avg_price_per_cell": "111"})
            w.writerow({**base, "quality_group": "q5+q6", "avg_price_per_cell": "222"})
            w.writerow({**base, "quality_group": "q6", "avg_price_per_cell": "333"})
        try:
            bp.set_map_quality_csv_override(path)
            u5, u56, u6, hit = bp.vacant_unit_prices_for_map_id(4101, None)
            self.assertTrue(hit)
            self.assertEqual(u5, 111)
            self.assertEqual(u56, 222)
            self.assertEqual(u6, 333)
        finally:
            bp.set_map_quality_csv_override(None)
            Path(path).unlink(missing_ok=True)

    def test_early_round_extra_g_subtracts_from_vacant_linear_unit(self) -> None:
        """extra_g 金格加成与空格 unit 线性价重叠时，参与 unit 的空置格数扣 min(extra_g, vac_n)。"""
        keys = [
            "map_id",
            "tier",
            "nest_drop_id",
            "quality_group",
            "prob_in_group",
            "avg_price_per_item",
            "avg_price_per_cell",
        ]
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            suffix=".csv",
            delete=False,
            newline="",
        ) as tf:
            path = tf.name
            w = csv.DictWriter(tf, fieldnames=keys)
            w.writeheader()
            base = {
                "map_id": "2101",
                "tier": "101",
                "nest_drop_id": "2001",
                "prob_in_group": "1",
                "avg_price_per_item": "1",
            }
            w.writerow({**base, "quality_group": "q5", "avg_price_per_cell": "500"})
            w.writerow({**base, "quality_group": "q5+q6", "avg_price_per_cell": "100"})
            w.writerow({**base, "quality_group": "q6", "avg_price_per_cell": "600"})
        try:
            bp.set_map_quality_csv_override(path)
            gs = {
                "uid": "u1",
                "map_id": 2101,
                "current_round": 2,
                "players": {},
                "items": {
                    "a": {
                        "uid": "a",
                        "box_id": 19,
                        "box_id_confirmed": True,
                        "quality": 5,
                        "shape": "11",
                    },
                },
                "displayed_event_uids": [],
                "scan_history": [
                    {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                    {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                    {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
                    {"scan_type": "quality", "value": 4, "hit_uids": ["x"]},
                ],
            }
            snap = {
                "game_state": gs,
                "current_round": 2,
                "map_id": 2101,
                "pricing": {"total": 1000.0, "vacant_unit_q5": 300},
                "skill_logs": [
                    {
                        "game_data": {
                            "MapSkillLog": [
                                {"SkillCid": MAP_SKILL_TOTAL_GOLD_CELLS, "TotalHitBoxIndex": 10},
                            ]
                        }
                    }
                ],
            }
            pts, meta = bp.compute_aisha_bid_from_board_snapshot(snap, snapshot_path_hint=None)
            self.assertIsNotNone(pts)
            vac_n = int(meta["vacant_used"])
            self.assertEqual(vac_n, 19)
            self.assertEqual(meta.get("early_vacant_cells_for_linear_pricing"), 10)
            extra_g = 10 - 1
            unit = 100
            uq5 = 500
            expect = int(round(1000.0 + (vac_n - min(extra_g, vac_n)) * unit + extra_g * uq5))
            self.assertEqual(pts, expect)
            self.assertEqual(expect, 6500)
        finally:
            bp.set_map_quality_csv_override(None)
            Path(path).unlink(missing_ok=True)

    def test_early_round_extra_r_subtracts_from_vacant_linear_after_gold(self) -> None:
        """extra_r 红格加成与 unit 重叠时，在扣完金重叠后的空置上再扣 min(extra_r, vac_after_gold)。"""
        keys = [
            "map_id",
            "tier",
            "nest_drop_id",
            "quality_group",
            "prob_in_group",
            "avg_price_per_item",
            "avg_price_per_cell",
        ]
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            suffix=".csv",
            delete=False,
            newline="",
        ) as tf:
            path = tf.name
            w = csv.DictWriter(tf, fieldnames=keys)
            w.writeheader()
            base = {
                "map_id": "2101",
                "tier": "101",
                "nest_drop_id": "2001",
                "prob_in_group": "1",
                "avg_price_per_item": "1",
            }
            w.writerow({**base, "quality_group": "q5", "avg_price_per_cell": "500"})
            w.writerow({**base, "quality_group": "q5+q6", "avg_price_per_cell": "100"})
            w.writerow({**base, "quality_group": "q6", "avg_price_per_cell": "600"})
        try:
            bp.set_map_quality_csv_override(path)
            gs = {
                "uid": "u1",
                "map_id": 2101,
                "current_round": 2,
                "players": {},
                "items": {
                    "a": {
                        "uid": "a",
                        "box_id": 19,
                        "box_id_confirmed": True,
                        "quality": 6,
                        "shape": "11",
                    },
                },
                "displayed_event_uids": [],
                "scan_history": [
                    {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                    {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                    {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
                    {"scan_type": "quality", "value": 4, "hit_uids": ["x"]},
                ],
            }
            snap = {
                "game_state": gs,
                "current_round": 2,
                "map_id": 2101,
                "pricing": {"total": 1000.0, "vacant_unit_q5": 300, "vacant_unit_all_red": 999},
                "skill_logs": [
                    {
                        "game_data": {
                            "MapSkillLog": [
                                {"SkillCid": MAP_SKILL_TOTAL_RED_CELLS, "TotalHitBoxIndex": 5},
                            ]
                        }
                    }
                ],
            }
            pts, meta = bp.compute_aisha_bid_from_board_snapshot(snap, snapshot_path_hint=None)
            self.assertIsNotNone(pts)
            vac_n = int(meta["vacant_used"])
            self.assertEqual(vac_n, 19)
            extra_r = 5 - 1
            g_sub = 0
            vac_after = vac_n - g_sub
            r_sub = min(extra_r, vac_after)
            self.assertEqual(meta.get("early_vacant_cells_for_linear_pricing"), vac_after - r_sub)
            unit = 100
            uq6 = 600
            expect = int(round(1000.0 + (vac_after - r_sub) * unit + extra_r * uq6))
            self.assertEqual(pts, expect)
            self.assertEqual(expect, 1000 + 15 * 100 + 4 * 600)
        finally:
            bp.set_map_quality_csv_override(None)
            Path(path).unlink(missing_ok=True)

    def test_vacant_200009_total_minus_board_occupied(self) -> None:
        """有 200009 总藏品格数时，定价空置 = 总数 − 画板占位格数。"""
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": MAP_SKILL_TOTAL_HIDDEN_CELLS, "TotalHitBoxIndex": 61},
                    ]
                }
            }
        ]
        self.assertEqual(
            bp.vacant_cells_from_map_skill_total_hidden(logs, occupied_cell_count=10),
            51,
        )
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        p = bp.build_snapshot_pricing_dict(
            total=1000.0,
            raw_vacant=3,
            sum_gold_red_min_minus_weighted=0.0,
            map_id=0,
            current_round=5,
            skill_logs=logs,
            game_state_json=gs,
            snapshot_path_hint=None,
            vacant_occupied_cell_count=0,
        )
        self.assertEqual(p.get("vacant_geometric"), 61)
        self.assertEqual(p.get("vacant_effective_count"), 61)

    def test_build_snapshot_three_position_totals(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        p = bp.build_snapshot_pricing_dict(
            total=1000.0,
            raw_vacant=3,
            sum_gold_red_min_minus_weighted=0.0,
            map_id=0,
            current_round=5,
            skill_logs=[],
            game_state_json=gs,
            snapshot_path_hint=None,
        )
        self.assertIn("known_items_total", p)
        self.assertEqual(p["known_items_total"], 1000.0)
        self.assertIn("position_total_all_gold", p)
        self.assertIn("position_total_gold_red", p)
        self.assertIn("position_total_all_red", p)
        self.assertAlmostEqual(p["position_total_all_gold"], p["est_orange"])
        self.assertIsNotNone(p.get("aisha_bid"))
        ab = p["aisha_bid"]
        self.assertIsInstance(ab, dict)
        self.assertIn("points", ab)
        self.assertIn("points_floor", ab)
        self.assertIn("points_ceiling", ab)


if __name__ == "__main__":
    unittest.main()
