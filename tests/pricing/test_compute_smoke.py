"""pricing.compute 烟测（不依赖 GUI）。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from bidking.config.map_runtime_overlay import merged_runtime_with_map_pricing
from bidking.pricing import compute as compute_mod
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

    def test_pricing_maps_bundle_key_normalizes_41xx_map_id(self) -> None:
        """41xx 等价 MapCid 应与 21xx 一样命中同一 pricing.maps 档键（如 210）。"""
        seen: list[str | None] = []

        def _wrap(
            cfg: dict,
            *,
            map_bundle_key: str | None = None,
        ) -> dict:
            seen.append(map_bundle_key)
            return merged_runtime_with_map_pricing(cfg, map_bundle_key=map_bundle_key)

        cfg: dict = {
            "board_snapshot": {"enabled": False},
            "pricing": {"fallback_bid_price": 11111},
            "automation": {"selected_mode": "aisha_premium"},
        }
        snap = {
            "schema_version": 2,
            "game_state": {"map_id": 4104, "players": {}},
            "pricing": {
                "total": 1000.0,
                "points": 50000,
                "points_floor": 40000,
                "points_ceiling": 90000,
                "vacant": 8,
                "ahmad_points": 100,
            },
        }
        with patch.object(compute_mod, "merged_runtime_with_map_pricing", side_effect=_wrap):
            compute_price(
                cfg,
                config_path=Path(__file__).resolve(),
                round_no=4,
                board_snapshot=snap,
                price_config={},
            )
        self.assertEqual(seen, ["210"])

    def test_universal_advisor_role_overrides_mode(self) -> None:
        cfg: dict = {
            "board_snapshot": {"enabled": False},
            "pricing": {"fallback_bid_price": 11111},
            "automation": {"selected_mode": "ahmad_premium"},
            "advisor": {"role": "universal"},
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
        self.assertEqual(det.get("role"), "universal")
        self.assertGreater(p, 1000)


if __name__ == "__main__":
    unittest.main()
