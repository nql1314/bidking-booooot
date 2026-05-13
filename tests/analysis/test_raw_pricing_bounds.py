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
    _infer_q56_grid_from_total_and_q14,
    _merge_with_min_from_avg,
    _min_merge_bound_from_price_avg,
    _min_positive_int_avg_product_near_integer,
    _min_total_from_avg,
    _min_total_price_from_avg_times_hit_count,
    build_raw_pricing_dict,
    event_stats_q12_q3_q4_grids_all_known,
)
from bidking.parsing.constants import (
    ITEM_SKILL_DESC,
    ITEM_SKILL_EVENT_STATS,
    MAP_SKILL_RANDOM3_AVG_PRICE,
    MAP_SKILL_TOTAL_GOLD_COUNT,
)


class RawPricingBoundsTests(unittest.TestCase):
    def test_item_skill_logged_missing_price_is_zero(self) -> None:
        logs = [
            {
                "game_data": {
                    "ItemSkillLog": [
                        {"SkillCid": 1, "ItemCid": 100122},
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs)
        self.assertEqual(raw["event_stats"].get("q12_price_total"), 0)

    def test_item_skill_direct_log_fills_event_stats(self) -> None:
        logs = [
            {
                "game_data": {
                    "ItemSkillLog": [
                        {
                            "SkillCid": 999001,
                            "ItemCid": 100104,
                            "TotalHitBoxIndex": 11,
                        },
                        {
                            "SkillCid": 999002,
                            "ItemCid": 100117,
                            "HitItemIndex": 7,
                        },
                        {
                            "SkillCid": 999003,
                            "ItemCid": 100122,
                            "HitItemTotalPrice": 333,
                        },
                        {
                            "SkillCid": 999004,
                            "ItemCid": 100125,
                            "HitItemTotalPrice": 555,
                        },
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs)
        st = raw["event_stats"]
        self.assertEqual(st.get("q12_grid_count"), 11)
        self.assertEqual(st.get("q3_count"), 7)
        self.assertEqual(st.get("q12_price_total"), 333)
        self.assertEqual(st.get("item_100125_price_total"), 555)

    def test_item_skill_desc_keys_have_event_stats_row(self) -> None:
        for k in ITEM_SKILL_DESC:
            self.assertIn(
                k,
                ITEM_SKILL_EVENT_STATS,
                msg=f"ITEM_SKILL_EVENT_STATS 缺少 ItemCid {k}，与 ITEM_SKILL_DESC 不同步",
            )

    def test_min_positive_int_avg_product_near_integer(self) -> None:
        self.assertEqual(_min_positive_int_avg_product_near_integer(2.4), 5)
        self.assertEqual(_min_positive_int_avg_product_near_integer(10.0 / 3.0), 3)
        self.assertEqual(_min_positive_int_avg_product_near_integer(3.0), 1)

    def test_min_merge_bound_integer_price_is_one(self) -> None:
        self.assertEqual(_min_merge_bound_from_price_avg(16800), 1)
        self.assertEqual(_min_merge_bound_from_price_avg(16800.0), 1)

    def test_min_total_from_avg_integer_round_trip(self) -> None:
        """总价整数化路径不因「整数均价」收缩为 1（合并路径与此无关）。"""
        self.assertEqual(_min_total_from_avg(16800), 16800)

    def test_min_total_price_random3_default_hit_count(self) -> None:
        self.assertEqual(
            _min_total_price_from_avg_times_hit_count(
                16800, None, skill_cid=MAP_SKILL_RANDOM3_AVG_PRICE
            ),
            50400,
        )

    def test_min_merge_bound_fractional_uses_smallest_multiplier(self) -> None:
        self.assertEqual(_min_merge_bound_from_price_avg(10.0 / 3.0), 3)

    def test_min_merge_bound_loose_avg_price_like_skill(self) -> None:
        """严格阈值下无整数倍乘积时，放宽阈值后应得到最小件数（如 5949.6665×3≈17850）。"""
        self.assertEqual(_min_merge_bound_from_price_avg(5949.6665), 3)

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

    def test_build_raw_pricing_census_absent_on_explicit_map_zero_gold(self) -> None:
        skill_logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": MAP_SKILL_TOTAL_GOLD_COUNT, "HitItemIndex": 0},
                    ]
                }
            }
        ]
        rp = build_raw_pricing_dict(map_id=2101, skill_logs=skill_logs)
        self.assertEqual(rp.get("census_absent_qualities"), [5])

    def test_build_raw_pricing_census_absent_empty_when_gold_tier_nonzero_after_coherence(self) -> None:
        skill_logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": MAP_SKILL_TOTAL_GOLD_COUNT, "HitItemIndex": 2},
                    ]
                }
            }
        ]
        rp = build_raw_pricing_dict(map_id=2101, skill_logs=skill_logs)
        self.assertEqual(rp.get("census_absent_qualities"), [])

    def test_event_stats_q12_q3_q4_with_explicit_q12(self) -> None:
        raw = {"event_stats": {"q12_grid_count": 1, "q3_grid_count": 2, "q4_grid_count": 3}}
        self.assertTrue(event_stats_q12_q3_q4_grids_all_known(raw))

    def test_event_stats_q12_q3_q4_fallback_q1_q2(self) -> None:
        raw = {"event_stats": {"q1_grid_count": 1, "q2_grid_count": 2, "q3_grid_count": 3, "q4_grid_count": 4}}
        self.assertTrue(event_stats_q12_q3_q4_grids_all_known(raw))

    def test_infer_q56_uses_q12_sum(self) -> None:
        """守恒用 q12+q3+q4，与分写 q1–q4 等价。"""
        d = {
            "total_grid_count": 100,
            "q12_grid_count": 10,
            "q3_grid_count": 20,
            "q4_grid_count": 30,
            "q5_grid_count": 40,
        }
        _infer_q56_grid_from_total_and_q14(d)
        self.assertEqual(d.get("q6_grid_count"), 0)

    def test_infer_q56_derives_q12_from_q1_q2(self) -> None:
        d = {
            "total_grid_count": 50,
            "q1_grid_count": 5,
            "q2_grid_count": 5,
            "q3_grid_count": 10,
            "q4_grid_count": 10,
            "q5_grid_count": 15,
        }
        _infer_q56_grid_from_total_and_q14(d)
        self.assertEqual(d.get("q6_grid_count"), 5)


if __name__ == "__main__":
    unittest.main()
