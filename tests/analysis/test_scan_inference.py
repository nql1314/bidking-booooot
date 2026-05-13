"""扫描推断 facade 用例 —— 与 board_pricing 主测互补。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidking.analysis.scan_inference import (
    apply_census_absent_qualities_from_raw_pricing,
    census_absent_qualities_from_board_snapshot,
    csv_quality_group_from_possible_set,
    possible_qualities_from_scan_history,
)
from bidking.parsing.state import ItemKnowledge


class ScanInferenceFacadeTests(unittest.TestCase):
    def test_csv_quality_group_basic(self) -> None:
        self.assertIsNone(csv_quality_group_from_possible_set(frozenset()))
        self.assertEqual(csv_quality_group_from_possible_set(frozenset({3})), "q3")
        self.assertEqual(csv_quality_group_from_possible_set(frozenset({5, 6})), "q5+q6")
        self.assertEqual(csv_quality_group_from_possible_set(frozenset(range(1, 7))), "all")

    def test_possible_qualities_empty_snapshot(self) -> None:
        snap = {"items": {}, "scan_history": []}
        self.assertEqual(possible_qualities_from_scan_history(snap), frozenset(range(1, 7)))

    def test_census_absent_from_board_snapshot(self) -> None:
        snap = {"raw_pricing": {"census_absent_qualities": [5, 6]}}
        self.assertEqual(census_absent_qualities_from_board_snapshot(snap), frozenset({5, 6}))

    def test_possible_qualities_merges_census_absent_without_scan(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 1,
            "current_round": 1,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {
            "game_state": gs,
            "raw_pricing": {"census_absent_qualities": [5, 6]},
        }
        self.assertEqual(
            possible_qualities_from_scan_history(snap),
            frozenset({1, 2, 3, 4}),
        )

    def test_possible_qualities_census_only_adds_absent_not_in_scan_last(self) -> None:
        """census 与 scan 同一档时不覆盖 last hit；另一档仅 census 时仍补入负向。"""
        gs = {
            "uid": "u1",
            "map_id": 1,
            "current_round": 1,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 5, "hit_uids": ["a"]},
            ],
        }
        snap = {
            "game_state": gs,
            "raw_pricing": {"census_absent_qualities": [5, 6]},
        }
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({1, 2, 3, 4}))


class CensusAbsentPhantomTests(unittest.TestCase):
    def test_apply_census_absent_to_phantoms_and_unknown_quality_items(self) -> None:
        state_items = {
            "u1": ItemKnowledge(uid="u1"),
            "u2": ItemKnowledge(uid="u2"),
        }
        state_items["u1"].quality = None
        state_items["u2"].quality = 4
        phantom_items = {"p1": ItemKnowledge(uid="p1")}
        apply_census_absent_qualities_from_raw_pricing(
            state_items,
            phantom_items,
            {"census_absent_qualities": [5, 6]},
        )
        self.assertEqual(phantom_items["p1"].excluded_qualities, {5, 6})
        self.assertEqual(state_items["u1"].excluded_qualities, {5, 6})
        self.assertEqual(state_items["u2"].excluded_qualities, set())


if __name__ == "__main__":
    unittest.main()
