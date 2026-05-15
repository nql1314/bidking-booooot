# -*- coding: utf-8 -*-
"""``fraud_empty_cells_in_zone_prefix`` 铺板可解释性判定单元测试。"""

from __future__ import annotations

import unittest

from bidking.analysis.grid_overlay import (
    GRID_COLS,
    FraudPlacedItem,
    fraud_empty_cells_for_algorithm,
    fraud_empty_cells_in_zone_prefix,
    fraud_placed_items_from_merged_items,
)
from bidking.config.runtime import (
    infer_fraud_empty_cells_algorithm,
    infer_fraud_empty_cells_tiling_n,
)


def _fp(
    cells: set,
    w: int,
    h: int,
    *,
    anchor_bid: int | None = None,
) -> FraudPlacedItem:
    fs = frozenset(cells)
    min_bid = min(r * GRID_COLS + c for r, c in fs)
    ab = int(anchor_bid) if anchor_bid is not None else min_bid
    return FraudPlacedItem(cells=fs, w=w, h=h, min_bid=min_bid, anchor_bid=ab)


class FraudEmptyCellsTests(unittest.TestCase):
    def test_fraud_empty_cells_for_algorithm_none_always_empty(self) -> None:
        occ = {(0, 3)}
        placed = [_fp({(0, 3)}, 1, 1)]
        tiling = fraud_empty_cells_in_zone_prefix(occ, 10, placed)
        self.assertIn((0, 6), tiling)
        self.assertEqual(
            fraud_empty_cells_for_algorithm("none", occ, 10, placed),
            set(),
        )

    def test_infer_fraud_empty_cells_algorithm_tiling_n(self) -> None:
        self.assertEqual(
            infer_fraud_empty_cells_algorithm(
                {"grid_view": {"fraud_empty_cells_algorithm": "tiling_n"}}
            ),
            "tiling_n",
        )

    def test_infer_fraud_empty_cells_tiling_n(self) -> None:
        self.assertEqual(infer_fraud_empty_cells_tiling_n({"grid_view": {}}), 0)
        self.assertEqual(
            infer_fraud_empty_cells_tiling_n(
                {"grid_view": {"fraud_empty_cells_tiling_n": -3}}
            ),
            0,
        )

    def test_fraud_empty_cells_for_algorithm_tiling_n_strips_low_bids(self) -> None:
        # (0,6) bid=6 在纯 tiling 下为诈骗格；tiling_n 且 n=4、limit=10 时 thr=6，去掉 bid<=6
        occ = {(0, 3)}
        placed = [_fp({(0, 3)}, 1, 1)]
        full = fraud_empty_cells_in_zone_prefix(occ, 10, placed)
        self.assertIn((0, 6), full)
        tn = fraud_empty_cells_for_algorithm(
            "tiling_n", occ, 10, placed, fraud_empty_cells_tiling_n=4
        )
        self.assertNotIn((0, 6), tn)
        tn0 = fraud_empty_cells_for_algorithm(
            "tiling_n", occ, 10, placed, fraud_empty_cells_tiling_n=0
        )
        self.assertEqual(tn0, full)

    def test_infer_fraud_empty_cells_algorithm_from_raw(self) -> None:
        self.assertEqual(
            infer_fraud_empty_cells_algorithm({"grid_view": {}}),
            "tiling_strict",
        )
        self.assertEqual(
            infer_fraud_empty_cells_algorithm(
                {"grid_view": {"fraud_empty_cells_algorithm": "tiling"}}
            ),
            "tiling_strict",
        )
        self.assertEqual(
            infer_fraud_empty_cells_algorithm(
                {"grid_view": {"fraud_empty_cells_algorithm": "none"}}
            ),
            "none",
        )

    def test_fraud_empty_cells_tiling_alias_matches_tiling_strict(self) -> None:
        occ: set = set()
        placed = [_fp({(0, 0)}, 1, 1, anchor_bid=0)]
        strict = fraud_empty_cells_for_algorithm("tiling_strict", occ, 10, placed)
        legacy = fraud_empty_cells_for_algorithm("tiling", occ, 10, placed)
        self.assertEqual(strict, legacy)

    def test_no_placed_items_returns_empty_fraud(self) -> None:
        occ = {(0, 1), (1, 0)}
        self.assertEqual(fraud_empty_cells_in_zone_prefix(occ, 20, []), set())
        self.assertEqual(
            fraud_empty_cells_in_zone_prefix(occ, 20, None), set()
        )

    def test_far_a_anchored_beyond_limit_can_still_explain(self) -> None:
        # A 锚在 max_anchor 外：只要 min_bid > bid(C) 且棋盘内画得开，仍可解释 C。
        c = (0, 0)
        far = _fp({(0, 9)}, 1, 1)
        occ = {(0, 9)}
        placed = [far]
        fraud = fraud_empty_cells_in_zone_prefix(occ, 7, placed)
        self.assertNotIn(c, fraud)

    def test_prefix_exterior_empty_corridor_reaches_explainer(self) -> None:
        """顶左画形：更早占位并集按 ``B.min_bid < A.min_bid``。"""
        # (22,4)=224 早铺；(23,4)=234 晚铺；(22,5)=225 为空，需经 (23,5)=235 空走廊到 234。
        early = _fp({(22, 4)}, 1, 1)
        late = _fp({(23, 4)}, 1, 1)
        occ = {(22, 4), (23, 4)}
        placed = [early, late]
        fraud = fraud_empty_cells_in_zone_prefix(occ, 234, placed)
        self.assertNotIn((22, 5), fraud)

    def test_big_shape_explains_without_paint_bid_cap(self) -> None:
        # 顶左画形不对 P 内 bid 设上界：大矩形 + 低 max_anchor 仍应能解释左侧空格。
        early = _fp({(23, 2)}, 1, 1)
        big_cells = {
            (25, 2),
            (25, 3),
            (26, 2),
            (26, 3),
            (27, 2),
            (27, 3),
            (28, 2),
            (28, 3),
        }
        big = FraudPlacedItem(
            cells=frozenset(big_cells),
            w=2,
            h=4,
            min_bid=252,
            anchor_bid=252,
        )
        occ = {(23, 2)} | big_cells
        placed = [early, big]
        fraud = fraud_empty_cells_in_zone_prefix(occ, 252, placed)
        self.assertNotIn((23, 4), fraud)

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
        self.assertEqual(items[0].anchor_bid, 7)


if __name__ == "__main__":
    unittest.main()
