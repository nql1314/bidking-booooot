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
from bidking.analysis import grid_overlay as grid_overlay_mod
from bidking.analysis.map_avg_csv import set_map_quality_csv_override
from bidking.analysis.raw_pricing import build_raw_pricing_dict
from bidking.analysis.scan_inference import (
    csv_quality_group_from_possible_set,
    possible_qualities_from_scan_history,
    vacant_early_unit_from_exclusions,
)
from bidking.parsing.constants import MAP_SKILL_TOTAL_HIDDEN_CELLS


class BoardPricingTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_map_quality_csv_override(None)

    def test_csv_quality_group_from_possible_set(self) -> None:
        self.assertIsNone(csv_quality_group_from_possible_set(frozenset()))
        self.assertEqual(
            csv_quality_group_from_possible_set(frozenset(range(1, 7))),
            "all",
        )
        self.assertEqual(csv_quality_group_from_possible_set(frozenset({3})), "q3")
        self.assertEqual(
            csv_quality_group_from_possible_set(frozenset({5, 6})),
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
            possible_qualities_from_scan_history(snap),
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
        poss = possible_qualities_from_scan_history(snap)
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
        poss = possible_qualities_from_scan_history(snap)
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
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, all_q)
        self.assertEqual(csv_quality_group_from_possible_set(poss), "all")

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
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({5, 6}))
        self.assertEqual(csv_quality_group_from_possible_set(poss), "q5+q6")

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
        unit, qg, _ = vacant_early_unit_from_exclusions(
            board_snapshot=snap,
            csv_cells_raw={"q3": 99.0},
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
        unit, qg, _ = vacant_early_unit_from_exclusions(
            board_snapshot=snap,
            csv_cells_raw=raw,
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
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({3}))

    def test_map_skill_total_hidden_for_overlay_from_raw_pricing(self) -> None:
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": MAP_SKILL_TOTAL_HIDDEN_CELLS, "TotalHitBoxIndex": 42},
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs, snapshot_path_hint=None)
        self.assertEqual(grid_overlay_mod.map_skill_total_hidden_for_overlay({"raw_pricing": raw}), 42)
        self.assertIsNone(grid_overlay_mod.map_skill_total_hidden_for_overlay(None))
        self.assertIsNone(grid_overlay_mod.map_skill_total_hidden_for_overlay({}))

    def test_merged_items_applies_overlay_manual_shape(self) -> None:
        """``grid_overlay.manual_shapes`` 在无 shape 时写入定价用外形（w*10+h）。"""
        snap = {
            "game_state": {
                "items": {
                    "x": {
                        "uid": "x",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": None,
                        "quality": 5,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {"manual_shapes": {"x": [2, 1, 0, 0]}},
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["x"]["shape"], 21)

    def test_early_round_vacant_dict_uses_geometry(self) -> None:
        """无 200009 时：``vacant_dict_from_board_snapshot`` 按几何前缀区计空置（与定价同源）。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 5,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 5,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {
            "game_state": gs,
            "skill_logs": [],
            "map_id": 2101,
            "current_round": 2,
        }
        vb = grid_overlay_mod.vacant_dict_from_board_snapshot(snap)
        self.assertEqual(vb.get("effective_count"), 5)
        self.assertEqual(vb.get("source"), "geometric_empty_zone")
        p = bp.build_snapshot_pricing_dict(snap, snapshot_path_hint=None)
        self.assertEqual(p["vacant"], 5)

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
            set_map_quality_csv_override(path)
            pricing = bp.build_snapshot_pricing_dict(
                {
                    "game_state": {"map_id": 4101, "current_round": 4, "items": {}},
                    "skill_logs": [],
                    "map_id": 4101,
                    "current_round": 4,
                    "grid_overlay": {
                        "vacant": {
                            "effective_count": 1,
                            "geometric": 1,
                            "source": "test",
                        }
                    },
                },
                snapshot_path_hint=None,
            )
            self.assertTrue(pricing.get("map_quality_avg_hit"))
            self.assertEqual(pricing.get("vacant_unit_all_orange"), 111)
            self.assertEqual(pricing.get("vacant_unit_gold_red"), 222)
            self.assertEqual(pricing.get("vacant_unit_all_red"), 333)
        finally:
            set_map_quality_csv_override(None)
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
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs, snapshot_path_hint=None)
        self.assertEqual(
            grid_overlay_mod.map_skill_hidden_vacant(
                grid_overlay_mod.map_skill_total_hidden_for_overlay({"raw_pricing": raw}),
                occupied_cell_count=10,
            ),
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
            {
                "game_state": gs,
                "skill_logs": logs,
                "map_id": 0,
                "current_round": 5,
            },
            snapshot_path_hint=None,
        )
        self.assertEqual(p.get("vacant_geometric"), 61)
        self.assertEqual(p.get("vacant_effective_count"), 61)

    def test_vacant_from_raw_pricing_when_skill_logs_empty(self) -> None:
        """``skill_logs`` 已剥离但 ``raw_pricing`` 含 200009 时，仍按总格数 − 占位算空置。"""
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": MAP_SKILL_TOTAL_HIDDEN_CELLS, "TotalHitBoxIndex": 61},
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs, snapshot_path_hint=None)
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
            {
                "game_state": gs,
                "skill_logs": [],
                "map_id": 0,
                "current_round": 5,
                "raw_pricing": raw,
            },
            snapshot_path_hint=None,
        )
        self.assertEqual(p.get("vacant_source"), "map_skill_total_hidden_minus_occupied")
        self.assertEqual(p.get("vacant_geometric"), 61)
        self.assertEqual(p.get("vacant_effective_count"), 61)

    def test_build_snapshot_three_position_totals(self) -> None:
        """定价重算空置：需有已确认锚点，前缀区内 3 格空则 ``vacant==3``。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        p = bp.build_snapshot_pricing_dict(
            {
                "game_state": gs,
                "skill_logs": [],
                "map_id": 0,
                "current_round": 5,
            },
            snapshot_path_hint=None,
        )
        self.assertIn("total", p)
        self.assertIn("points", p)
        self.assertIn("points_floor", p)
        self.assertIn("points_ceiling", p)
        self.assertIn("est_orange", p)
        self.assertIn("est_gold_red", p)
        self.assertIn("est_red", p)
        self.assertEqual(p["vacant"], 3)

    def test_ahmad_points_from_event_stats(self) -> None:
        """``pricing.ahmad_points`` 由 ``raw_pricing.event_stats`` 简单公式汇总。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {
                "total_count": 20,
                "q4_grid_min": 5,
                "q5_grid_min": None,
                "q6_grid_min": None,
            },
        }
        p = bp.build_snapshot_pricing_dict(
            {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5, "raw_pricing": raw},
            snapshot_path_hint=None,
        )
        # 20*1000 + 5*1000 + 0 + 0
        self.assertEqual(p.get("ahmad_points"), 25000)

    def test_raw_pricing_contains_requested_event_stats(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        logs = [
            {"game_data": {"MapSkillLog": [{"SkillCid": 200017, "HitItemIndex": 21, "AllHitItemAvgPrice": 123.5}]}},
            {"game_data": {"HeroSkillLog": [{"SkillCid": 1002044, "HitItemIndex": 6}]}},
            {"game_data": {"MapSkillLog": [{"SkillCid": 200019, "HitItemIndex": 3}]}},
            {
                "game_data": {
                    "MapSkillLog": [
                        {
                            "SkillCid": 200038,
                            "HitItemIndex": 1,
                            "AllHitItemAvgPrice": 456.7,
                        }
                    ]
                }
            },
            {
                "game_data": {
                    "MapSkillLog": [
                        {
                            "SkillCid": 200037,
                            "HitItemIndex": 3,
                            "AllHitItemAvgPrice": 99.5,
                        }
                    ]
                }
            },
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": 990003, "HitItemTotalPrice": 298},
                        {"SkillCid": 990004, "HitItemTotalPrice": 457},
                    ]
                }
            },
        ]
        raw = build_raw_pricing_dict(
            map_id=2101,
            skill_logs=logs,
            snapshot_path_hint=None,
        )
        st = raw.get("event_stats") or {}
        self.assertIn("csv_quality_groups_avg_per_cell", raw)
        self.assertIn("csv_quality_groups_avg_per_item", raw)
        self.assertIn("total_count", st)
        self.assertEqual(st.get("total_count"), 21)
        self.assertIn("total_grid_count", st)
        self.assertIn("q5_count", st)
        self.assertEqual(st.get("q5_count"), 3)
        self.assertIn("q5_grid_count", st)
        self.assertEqual(st.get("q5_price_avg"), 99.5)
        self.assertEqual(st.get("q5_price_total"), 298)
        self.assertIn("q6_price_avg", st)
        self.assertEqual(st.get("q6_price_total"), 457)
        self.assertIn("q6_count_min", st)

    def test_build_snapshot_pricing_from_snapshot_with_raw_pricing(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = build_raw_pricing_dict(
            map_id=0,
            skill_logs=[],
            snapshot_path_hint=None,
        )
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5, "raw_pricing": raw}
        p = bp.build_snapshot_pricing_dict(snap)
        self.assertEqual(p.get("total"), 0.0)

    def test_build_snapshot_uses_raw_pricing_csv_units(self) -> None:
        snap = {
            "game_state": {
                "uid": "u1",
                "map_id": 9999,
                "current_round": 5,
                "players": {},
                "items": {
                    "a": {
                        "uid": "a",
                        "box_id": 2,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": 1,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
                "displayed_event_uids": [],
                "scan_history": [],
            },
            "skill_logs": [],
            "current_round": 5,
            "map_id": 9999,
            "raw_pricing": {
                "csv_quality_groups_avg_per_cell": {
                    "q5": 111.0,
                    "q5+q6": 222.0,
                    "q6": 333.0,
                }
            },
        }
        p = bp.build_snapshot_pricing_dict(snap)
        self.assertEqual(p.get("vacant_unit_all_orange"), 111)
        self.assertEqual(p.get("vacant_unit_gold_red"), 222)
        self.assertEqual(p.get("vacant_unit_all_red"), 333)
        self.assertEqual(p.get("vacant"), 2)
        t = float(p.get("total") or 0.0)
        self.assertEqual(p.get("est_orange"), int(round(t + 2 * 111)))


if __name__ == "__main__":
    unittest.main()
