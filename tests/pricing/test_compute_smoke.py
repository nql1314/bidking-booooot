"""pricing.compute 烟测（不依赖 GUI）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from bidking.pricing.compute import compute_price


class TestPricingComputeSmoke(unittest.TestCase):
    def test_fallback_without_pricing_block(self) -> None:
        cfg: dict = {
            "board_snapshot": {"enabled": False},
            "pricing": {"fallback_bid_price": 22000},
            "automation": {"selected_mode": "ahmad_premium"},
        }
        p, det = compute_price(cfg, config_path=Path.cwd() / "_noop_price_cfg.json", round_no=3)
        self.assertIsInstance(p, int)
        self.assertTrue(det.get("fallback"))
        self.assertIn("reason", det)

    def test_aisha_role_uses_points(self) -> None:
        cfg: dict = {
            "board_snapshot": {"enabled": False},
            "pricing": {"fallback_bid_price": 11111},
            "automation": {"selected_mode": "aisha_premium"},
        }
        snap = {
            "schema_version": 2,
            "game_state": {"players": {}},
            "pricing": {
                "total": 1000.0,
                "points": 50000,
                "points_floor": 40000,
                "points_ceiling": 90000,
                "vacant": 8,
                "ahmad_points": 100,
            },
        }
        p, det = compute_price(
            cfg,
            config_path=Path(__file__).resolve(),
            round_no=4,
            board_snapshot=snap,
            price_config={},
        )
        self.assertFalse(det.get("fallback"))
        self.assertEqual(det.get("role"), "aisha")
        self.assertGreater(p, 1000)


if __name__ == "__main__":
    unittest.main()
