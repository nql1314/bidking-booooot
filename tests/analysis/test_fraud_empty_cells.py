# -*- coding: utf-8 -*-
"""``fraud_empty_cells_in_zone_prefix`` 铺板可解释性判定单元测试。"""

from __future__ import annotations

import unittest

from bidking.analysis.grid_overlay import (
    GRID_COLS,
    FraudPlacedItem,
    fraud_empty_cells_in_zone_prefix,
    fraud_placed_items_from_merged_items,
)


def _fp(cells: set, w: int, h: int) -> FraudPlacedItem:
    fs = frozenset(cells)
    min_bid = min(r * GRID_COLS + c for r, c in fs)
    return FraudPlacedItem(cells=fs, w=w, h=h, min_bid=min_bid)


class FraudEmptyCellsTests(unittest.TestCase):
    def test_no_placed_items_returns_empty_fraud(self) -> None:
        occ = {(0, 1), (1, 0)}
        self.assertEqual(fraud_empty_cells_in_zone_prefix(occ, 20, []), set())
        self.assertEqual(
            fraud_empty_cells_in_zone_prefix(occ, 20, None), set()
        )

    def test_far_a_outside_prefix_cannot_reach_cells(self) -> None:
        # C 在 prefix 内；A 的 min_bid 虽大于 bid(C)，但 footprint 超出 limit，BFS 无法碰到 A → 不解释。
        c = (0, 0)
        far = _fp({(0, 9)}, 1, 1)
        occ = {(0, 9)}
        placed = [far]
        fraud = fraud_empty_cells_in_zone_prefix(occ, 7, placed)
        self.assertIn(c, fraud)

    def test_adjacent_later_item_explains_hole(self) -> None:
        occ = {(0, 1)}
        placed = [_fp({(0, 1)}, 1, 1)]
        fraud = fraud_empty_cells_in_zone_prefix(occ, 10, placed)
        self.assertNotIn((0, 0), fraud)

    def test_later_item_skipped_when_min_bid_not_after_c(self) -> None:
        # C 在 (0,6) bid=6；A 仅在 (0,3) min_bid=3，不满足「后面」故不参与解释
        occ = {(0, 3)}
        placed = [_fp({(0, 3)}, 1, 1)]
        fraud = fraud_empty_cells_in_zone_prefix(occ, 10, placed)
        self.assertIn((0, 6), fraud)

    def test_fraud_placed_items_from_merged_items_shape_none(self) -> None:
        merged = {
            "u1": {
                "box_id": 7,
                "box_id_confirmed": False,
                "shape": None,
            }
        }
        items = fraud_placed_items_from_merged_items(merged)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].w, 1)
        self.assertEqual(items[0].h, 1)
        self.assertEqual(items[0].cells, frozenset({(0, 7)}))


if __name__ == "__main__":
    unittest.main()
