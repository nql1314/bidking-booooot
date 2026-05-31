"""空置金红 floor/ceiling 择优：normal、aggressive 与 force_gold_red 模式。"""

from __future__ import annotations

import unittest

from bidking.pricing.strategies.aisha_base import compute_base_bid_points
from bidking.pricing.vacant_red import (
    _aggressive_floor_ceiling_choice,
    apply_early_auto_fill_ceiling_anchor,
    apply_vacant_red_floor_ceiling_pick,
    resolve_vacant_red_floor_ceiling_pick_mode,
)


class TestVacantRedPickMode(unittest.TestCase):
    def test_resolve_mode_defaults_normal(self) -> None:
        self.assertEqual(resolve_vacant_red_floor_ceiling_pick_mode({}), "normal")

    def test_resolve_mode_aggressive_aliases(self) -> None:
        for raw in ("aggressive", "激进", "积极"):
            cfg = {"pricing": {"vacant_red_floor_ceiling_pick_mode": raw}}
            self.assertEqual(resolve_vacant_red_floor_ceiling_pick_mode(cfg), "aggressive")

    def test_resolve_mode_force_gold_red_aliases(self) -> None:
        for raw in ("force_gold_red", "强制金红", "强制"):
            cfg = {"pricing": {"vacant_red_floor_ceiling_pick_mode": raw}}
            self.assertEqual(
                resolve_vacant_red_floor_ceiling_pick_mode(cfg), "force_gold_red"
            )

    def test_aggressive_vac_le_4_uses_floor(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=40_000,
            points_ceiling=90_000,
            vacant_used=4,
            max_opponent_bid=80_000,
        )
        self.assertEqual(chosen, 40_000)
        self.assertEqual(rule, "aggressive_vac_le_4_floor")

    def test_aggressive_floor_gt_opp_x1_2(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=50_000,
            points_ceiling=90_000,
            vacant_used=8,
            max_opponent_bid=30_000,
        )
        self.assertEqual(chosen, 50_000)
        self.assertEqual(rule, "aggressive_floor_gt_opp_x1_2")

    def test_aggressive_floor_gt_max_opp_avg(self) -> None:
        # floor > max_opp 且 floor <= 1.2 * max_opp 时取均价
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=50_000,
            points_ceiling=90_000,
            vacant_used=8,
            max_opponent_bid=45_000,
        )
        self.assertEqual(chosen, 70_000)
        self.assertEqual(rule, "aggressive_floor_gt_max_opp_avg")

    def test_aggressive_opp_ge_floor_x1_2_red(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=50_000,
            points_ceiling=90_000,
            vacant_used=8,
            max_opponent_bid=65_000,
        )
        self.assertEqual(chosen, 90_000)
        self.assertEqual(rule, "aggressive_opp_ge_floor_x1_2_red")

    def test_aggressive_vac_5_12_avg_without_opp(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=40_000,
            points_ceiling=80_000,
            vacant_used=10,
            max_opponent_bid=None,
        )
        self.assertEqual(chosen, 60_000)
        self.assertEqual(rule, "aggressive_vac_5_12_avg")

    def test_aggressive_vac_ge_12_red_without_opp(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=40_000,
            points_ceiling=80_000,
            vacant_used=15,
            max_opponent_bid=None,
        )
        self.assertEqual(chosen, 80_000)
        self.assertEqual(rule, "aggressive_vac_ge_12_red")

    def test_aggressive_dark_map_vac_ge_12_uses_avg(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=40_000,
            points_ceiling=80_000,
            vacant_used=15,
            max_opponent_bid=1,
            dark_map=True,
        )
        self.assertEqual(chosen, 60_000)
        self.assertEqual(rule, "aggressive_dark_map_avg")

    def test_aggressive_dark_map_skips_opponent_rules(self) -> None:
        chosen, rule, _ = _aggressive_floor_ceiling_choice(
            points_floor=50_000,
            points_ceiling=90_000,
            vacant_used=8,
            max_opponent_bid=99_999,
            dark_map=True,
        )
        self.assertEqual(chosen, 70_000)
        self.assertEqual(rule, "aggressive_vac_5_12_avg")

    def test_apply_aggressive_round4_with_opponent_bids(self) -> None:
        cfg = {
            "pricing": {
                "enable_vacant_red_floor_ceiling_pick": True,
                "vacant_red_floor_ceiling_pick_mode": "aggressive",
            },
            "automation": {"selected_map": "3"},
            "board_snapshot": {"self_user_uid": "self"},
        }
        snap = {
            "game_state": {
                "map_id": 2104,
                "players": {
                    "self": {"prices": {"2": 45_000}},
                    "opp1": {"prices": {"2": 62_000}},
                    "opp2": {"prices": {"2": 48_000}},
                },
            }
        }
        pricing = {
            "points_floor": 50_000,
            "points_ceiling": 90_000,
            "vacant": 8,
        }
        chosen, detail = apply_vacant_red_floor_ceiling_pick(
            cfg, snap, pricing, round_no=4, fin=50_000
        )
        self.assertTrue(detail.get("applied"))
        self.assertEqual(detail.get("pick_mode"), "aggressive")
        self.assertEqual(detail.get("decision_rule"), "aggressive_opp_ge_floor_x1_2_red")
        self.assertEqual(chosen, 90_000)

    def test_apply_aggressive_dark_map_440_vac_ge_12_avg(self) -> None:
        cfg = {
            "pricing": {
                "enable_vacant_red_floor_ceiling_pick": True,
                "vacant_red_floor_ceiling_pick_mode": "aggressive",
            },
            "automation": {"selected_map": "440"},
            "board_snapshot": {"self_user_uid": "self"},
        }
        snap = {
            "game_state": {
                "map_id": 4402,
                "players": {
                    "self": {"prices": {"2": 1}},
                    "opp1": {"prices": {"2": 4}},
                },
            }
        }
        pricing = {
            "points_floor": 40_000,
            "points_ceiling": 80_000,
            "vacant": 14,
        }
        chosen, detail = apply_vacant_red_floor_ceiling_pick(
            cfg, snap, pricing, round_no=4, fin=40_000
        )
        self.assertTrue(detail.get("applied"))
        self.assertEqual(detail.get("pick_mode"), "aggressive")
        self.assertEqual(detail.get("decision_rule"), "aggressive_dark_map_avg")
        self.assertEqual(chosen, 60_000)

    def test_apply_force_gold_red_always_uses_ceiling(self) -> None:
        cfg = {
            "pricing": {
                "enable_vacant_red_floor_ceiling_pick": True,
                "vacant_red_floor_ceiling_pick_mode": "force_gold_red",
            },
            "automation": {"selected_map": "3"},
            "board_snapshot": {"self_user_uid": "self"},
        }
        snap = {
            "game_state": {
                "players": {
                    "self": {"prices": {"2": 45_000}},
                    "opp1": {"prices": {"2": 30_000}},
                }
            }
        }
        pricing = {
            "points_floor": 50_000,
            "points_ceiling": 90_000,
            "vacant": 3,
        }
        chosen, detail = apply_vacant_red_floor_ceiling_pick(
            cfg, snap, pricing, round_no=4, fin=50_000
        )
        self.assertTrue(detail.get("applied"))
        self.assertEqual(detail.get("pick_mode"), "force_gold_red")
        self.assertEqual(detail.get("decision_rule"), "force_gold_red_ceiling")
        self.assertEqual(chosen, 90_000)

    def test_apply_normal_still_uses_red_inference(self) -> None:
        cfg = {
            "pricing": {"enable_vacant_red_floor_ceiling_pick": True},
            "automation": {"selected_map": "440"},
            "board_snapshot": {"self_user_uid": "self"},
        }
        snap = {
            "game_state": {
                "players": {
                    "self": {"prices": {"2": 45_000}},
                    "opp1": {"prices": {"2": 30_000}},
                }
            }
        }
        pricing = {
            "points_floor": 50_000,
            "points_ceiling": 90_000,
            "vacant": 3,
        }
        chosen, detail = apply_vacant_red_floor_ceiling_pick(
            cfg, snap, pricing, round_no=4, fin=50_000
        )
        self.assertTrue(detail.get("applied"))
        self.assertEqual(detail.get("pick_mode"), "normal")
        self.assertFalse(detail.get("has_red_inferred"))
        self.assertEqual(chosen, 50_000)


class TestEarlyAutoFillCeilingAnchor(unittest.TestCase):
    def test_round5_uses_ceiling_when_auto_fill_on_vacant_red_off(self) -> None:
        cfg = {
            "pricing": {
                "infer_vacant_rect_phantoms": True,
                "enable_vacant_red_floor_ceiling_pick": False,
            }
        }
        pricing = {
            "total": 1000.0,
            "points": 50_000,
            "points_floor": 40_000,
            "points_ceiling": 90_000,
            "vacant": 8,
        }
        chosen, detail = apply_early_auto_fill_ceiling_anchor(
            cfg, pricing, round_no=5, fin=50_000
        )
        self.assertTrue(detail.get("applied"))
        self.assertEqual(chosen, 90_000)
        self.assertEqual(detail.get("decision_rule"), "early_auto_fill_points_ceiling")
        self.assertEqual(detail.get("round"), 5)

    def test_round3_uses_ceiling_when_auto_fill_on_vacant_red_off(self) -> None:
        cfg = {
            "pricing": {
                "infer_vacant_rect_phantoms": True,
                "enable_vacant_red_floor_ceiling_pick": False,
            }
        }
        pricing = {
            "total": 1000.0,
            "points": 50_000,
            "points_floor": 40_000,
            "points_ceiling": 90_000,
            "vacant": 8,
        }
        chosen, detail = apply_early_auto_fill_ceiling_anchor(
            cfg, pricing, round_no=3, fin=50_000
        )
        self.assertTrue(detail.get("applied"))
        self.assertEqual(chosen, 90_000)
        self.assertEqual(detail.get("decision_rule"), "early_auto_fill_points_ceiling")

    def test_skipped_when_vacant_red_pick_enabled(self) -> None:
        cfg = {
            "pricing": {
                "infer_vacant_rect_phantoms": True,
                "enable_vacant_red_floor_ceiling_pick": True,
            }
        }
        pricing = {
            "points_floor": 40_000,
            "points_ceiling": 90_000,
        }
        chosen, detail = apply_early_auto_fill_ceiling_anchor(
            cfg, pricing, round_no=2, fin=50_000
        )
        self.assertFalse(detail.get("applied"))
        self.assertEqual(chosen, 50_000)

    def test_skipped_when_auto_fill_disabled(self) -> None:
        cfg = {
            "pricing": {
                "infer_vacant_rect_phantoms": False,
                "enable_vacant_red_floor_ceiling_pick": False,
            }
        }
        pricing = {
            "points_floor": 40_000,
            "points_ceiling": 90_000,
        }
        chosen, detail = apply_early_auto_fill_ceiling_anchor(
            cfg, pricing, round_no=1, fin=50_000
        )
        self.assertFalse(detail.get("applied"))
        self.assertEqual(chosen, 50_000)

    def test_aisha_base_integrates_early_ceiling(self) -> None:
        cfg = {
            "pricing": {
                "infer_vacant_rect_phantoms": True,
                "enable_vacant_red_floor_ceiling_pick": False,
            }
        }
        pricing = {
            "total": 1000.0,
            "points": 50_000,
            "points_floor": 40_000,
            "points_ceiling": 90_000,
            "vacant": 8,
        }
        anchor, meta = compute_base_bid_points(
            pricing,
            config=cfg,
            board_snapshot={"game_state": {"players": {}}},
            round_no=2,
        )
        self.assertEqual(anchor, 90_000)
        self.assertTrue((meta.get("early_auto_fill_ceiling_anchor") or {}).get("applied"))


if __name__ == "__main__":
    unittest.main()
