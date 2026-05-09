"""config 层：runtime/pricing 加载与按地图深合并覆盖。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bidking.config import deep_merge, load_pricing, load_runtime, resolve_for
from bidking.config.paths import configs_dir


class ConfigTests(unittest.TestCase):
    def test_runtime_load(self) -> None:
        rc = load_runtime()
        self.assertIn("automation", rc.raw)
        self.assertEqual(rc.window.get("title_keyword"), "BidKing")

    def test_pricing_global(self) -> None:
        p = load_pricing()
        self.assertIn("ahmad_premium", p)
        self.assertIn("grid_prices", p)
        self.assertNotIn("by_map", p["ahmad_premium"], "by_map 应已迁出至 pricing.maps/")

    def test_resolve_map_override(self) -> None:
        p = load_pricing()
        merged_2 = resolve_for("2", base=p)
        self.assertAlmostEqual(merged_2["ahmad_premium"]["round1_base_factor"], 1.3)
        self.assertAlmostEqual(merged_2["ahmad_premium"]["base_item_per_piece_w"], 0.11)
        # 颜色字典深合并：原 grid_rate_w_by_round.5.gold=1, 覆盖到 1.0
        self.assertAlmostEqual(
            merged_2["ahmad_premium"]["grid_rate_w_by_round"]["5"]["red"], 4.5
        )

    def test_resolve_unknown_map(self) -> None:
        p = load_pricing()
        merged = resolve_for("999", base=p)
        self.assertEqual(merged, p)

    def test_deep_merge(self) -> None:
        a = {"x": 1, "y": {"a": 1, "b": 2}, "z": [1, 2]}
        b = {"y": {"b": 20, "c": 3}, "z": [9]}
        self.assertEqual(
            deep_merge(a, b),
            {"x": 1, "y": {"a": 1, "b": 20, "c": 3}, "z": [9]},
        )

    def test_pricing_files_present(self) -> None:
        self.assertTrue((configs_dir() / "pricing.maps" / "1.json").is_file())
        self.assertTrue((configs_dir() / "pricing.maps" / "2.json").is_file())


if __name__ == "__main__":
    unittest.main()
