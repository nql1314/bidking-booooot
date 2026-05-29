"""pricing.compute 烟测（不依赖 GUI）。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from bidking.config.map_runtime_overlay import merged_runtime_with_map_pricing
from bidking.pricing import compute as compute_mod
from bidking.pricing.compute import compute_price
from bidking.pricing.snapshot_io import resolve_effective_round


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

    def test_strategy_role_override_uses_aisha_despite_ahmad_premium(self) -> None:
        """显式 strategy_role=aisha 时基底走 points，不受 automation 里 ahmad_premium 影响。"""
        cfg: dict = {
            "board_snapshot": {"enabled": False},
            "pricing": {"fallback_bid_price": 11111},
            "automation": {"selected_mode": "ahmad_premium"},
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
                "ahmad_pricing_active": False,
                "ahmad_points": 100,
            },
        }
        p, det = compute_price(
            cfg,
            config_path=Path(__file__).resolve(),
            round_no=4,
            board_snapshot=snap,
            price_config={},
            strategy_role="aisha",
        )
        self.assertFalse(det.get("fallback"))
        self.assertEqual(det.get("role"), "aisha")
        self.assertEqual(
            (det.get("board_snapshot_bid") or {}).get("bid_points_source"),
            "snapshot_pricing.points",
        )
        self.assertGreater(p, 1000)

    def test_resolve_effective_round_prefers_ocr_when_snapshot_lags(self) -> None:
        snap = {"current_round": 3, "game_state": {"current_round": 3}}
        self.assertEqual(resolve_effective_round(4, snap), 4)

    def test_resolve_effective_round_prefers_snapshot_when_ocr_lags(self) -> None:
        snap = {"current_round": 4, "game_state": {"current_round": 4}}
        self.assertEqual(resolve_effective_round(3, snap), 4)

    def test_compute_effective_round_when_snapshot_lags_ocr(self) -> None:
        cfg: dict = {
            "board_snapshot": {"enabled": False},
            "pricing": {"fallback_bid_price": 11111},
            "automation": {"selected_mode": "aisha_premium"},
        }
        snap = {
            "schema_version": 2,
            "current_round": 3,
            "game_state": {"current_round": 3, "players": {}},
            "pricing": {
                "total": 1000.0,
                "points": 50000,
                "points_floor": 40000,
                "points_ceiling": 90000,
                "vacant": 8,
                "ahmad_points": 100,
            },
        }
        _, det = compute_price(
            cfg,
            config_path=Path(__file__).resolve(),
            round_no=4,
            board_snapshot=snap,
            price_config={"enable_opponent_bid_adjustment": False},
        )
        self.assertEqual(det.get("effective_round"), 4)

    def test_refresh_pricing_ignores_stale_cached_points(self) -> None:
        """完整画板快照应重算 pricing，不用文件中过期的 points/total。"""
        import copy
        import json
        from pathlib import Path

        snap_path = Path(__file__).resolve().parents[2] / "data" / "board_snapshot.json"
        if not snap_path.is_file():
            self.skipTest("data/board_snapshot.json 不可用")
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        stale_pts = int((snap.get("pricing") or {}).get("points") or 0)
        self.assertGreater(stale_pts, 0)

        cfg: dict = {
            "board_snapshot": {"enabled": False, "path": str(snap_path)},
            "pricing": {
                "fallback_bid_price": 11111,
                "enable_opponent_bid_adjustment": False,
            },
            "automation": {"selected_mode": "aisha_premium", "bid_ratio_by_round": {"4": 1.0}},
        }
        work = copy.deepcopy(snap)
        p, det = compute_price(
            cfg,
            config_path=Path(__file__).resolve(),
            round_no=4,
            board_snapshot=work,
            price_config={"enable_opponent_bid_adjustment": False},
            strategy_role="aisha",
        )
        self.assertTrue(det.get("pricing_refreshed"))
        refreshed_pts = int((work.get("pricing") or {}).get("points") or 0)
        self.assertNotEqual(refreshed_pts, stale_pts)
        self.assertEqual(
            int((det.get("board_snapshot_bid") or {}).get("points") or 0),
            refreshed_pts,
        )
        self.assertEqual(int(det.get("source_value") or 0), refreshed_pts)


if __name__ == "__main__":
    unittest.main()
