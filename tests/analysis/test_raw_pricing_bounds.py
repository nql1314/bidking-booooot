# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidking.analysis.raw_pricing import (
    _finalize_tier_min_bounds,
    _merge_with_min_from_avg,
    _min_merge_bound_from_price_avg,
    _min_positive_int_avg_product_near_integer,
    _min_total_price_from_avg,
)


class RawPricingBoundsTests(unittest.TestCase):
    def test_min_positive_int_avg_product_near_integer(self) -> None:
        self.assertEqual(_min_positive_int_avg_product_near_integer(2.4), 5)
        self.assertEqual(_min_positive_int_avg_product_near_integer(10.0 / 3.0), 3)
        self.assertEqual(_min_positive_int_avg_product_near_integer(3.0), 1)

    def test_min_merge_bound_integer_price_is_one(self) -> None:
        self.assertEqual(_min_merge_bound_from_price_avg(16800), 1)
        self.assertEqual(_min_merge_bound_from_price_avg(16800.0), 1)

    def test_min_total_price_from_avg_integer_still_uses_numerator(self) -> None:
        """总价下界路径不因「整数均价」收缩为 1。"""
        self.assertEqual(_min_total_price_from_avg(16800), 16800)

    def test_min_merge_bound_fractional_uses_smallest_multiplier(self) -> None:
        self.assertEqual(_min_merge_bound_from_price_avg(10.0 / 3.0), 3)

    def test_merge_with_min_from_price_vs_grid(self) -> None:
        self.assertEqual(_merge_with_min_from_avg(3, 16800.0, from_price=True), 3)
        self.assertEqual(_merge_with_min_from_avg(3, 10.0 / 3.0, from_price=True), 3)

    def test_finalize_tier_with_integer_price_avg(self) -> None:
        d = {
            "count": 4,
            "grid_count": 12,
            "grid_avg": 3.0,
            "price_avg": 16800.0,
        }
        _finalize_tier_min_bounds(
            d,
            count_k="count",
            grid_k="grid_count",
            avg_grid_k="grid_avg",
            avg_price_k="price_avg",
            count_min_k="count_min",
            grid_min_k="grid_min",
        )
        self.assertEqual(d["count_min"], 4)
        self.assertEqual(d["grid_min"], 12)


if __name__ == "__main__":
    unittest.main()
