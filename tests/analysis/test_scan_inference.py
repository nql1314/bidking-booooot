"""扫描推断 facade 用例 —— 与 board_pricing 主测互补。"""

from __future__ import annotations

import unittest

from bidking.analysis.scan_inference import (
    csv_quality_group_from_possible_set,
    possible_qualities_from_negative_constraints,
    possible_qualities_from_scan_history,
)


class ScanInferenceFacadeTests(unittest.TestCase):
    def test_csv_quality_group_basic(self) -> None:
        self.assertIsNone(csv_quality_group_from_possible_set(frozenset()))
        self.assertEqual(csv_quality_group_from_possible_set(frozenset({3})), "q3")
        self.assertEqual(csv_quality_group_from_possible_set(frozenset({5, 6})), "q5+q6")
        self.assertEqual(csv_quality_group_from_possible_set(frozenset(range(1, 7))), "all")

    def test_possible_qualities_alias(self) -> None:
        self.assertIs(
            possible_qualities_from_negative_constraints,
            possible_qualities_from_scan_history,
        )

    def test_possible_qualities_empty_snapshot(self) -> None:
        snap = {"items": {}, "scan_history": []}
        self.assertEqual(possible_qualities_from_scan_history(snap), frozenset(range(1, 7)))


if __name__ == "__main__":
    unittest.main()
