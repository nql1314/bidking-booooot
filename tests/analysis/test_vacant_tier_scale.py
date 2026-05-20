"""空置金/金红幂律衰减与红档恒线性。"""

from __future__ import annotations

import math
import unittest

from bidking.analysis.vacant_tier_scale import (
    resolve_all_vacant_tier_exponents,
    resolve_vacant_tier_exponent,
    vacant_tier_premium,
    vacant_tier_scaled_cells,
)


class VacantTierScaleTests(unittest.TestCase):
    def test_q6_exponent_always_one_ignores_config(self) -> None:
        cfg = {"vacant_tier_cell_exponents": {"q5": 0.8, "q6": 0.7, "q5+q6": 0.82}}
        self.assertEqual(resolve_vacant_tier_exponent(cfg, "q6"), 1.0)
        all_exp = resolve_all_vacant_tier_exponents(cfg)
        self.assertEqual(all_exp["q6"], 1.0)
        self.assertEqual(all_exp["q5"], 0.8)

    def test_premium_linear_when_alpha_one(self) -> None:
        self.assertEqual(vacant_tier_premium(100.0, 10, 1.0), 1000.0)

    def test_premium_power_when_alpha_below_one(self) -> None:
        self.assertAlmostEqual(
            vacant_tier_premium(9587.0, 10, 0.85),
            9587.0 * (10**0.85),
            places=2,
        )

    def test_scaled_cells_alpha_one_equals_n(self) -> None:
        self.assertEqual(vacant_tier_scaled_cells(7, 1.0), 7.0)

    def test_red_premium_matches_linear_even_with_q6_in_config(self) -> None:
        cfg = {"vacant_tier_cell_exponents": {"q6": 0.75}}
        alpha = resolve_vacant_tier_exponent(cfg, "q6")
        self.assertEqual(alpha, 1.0)
        self.assertEqual(vacant_tier_premium(333.0, 5, alpha), 333.0 * 5.0)


if __name__ == "__main__":
    unittest.main()
