"""出价后处理纯函数用例。"""

from __future__ import annotations

import unittest

from bidking.pricing.post_process import (
    PostProcessConfig,
    apply_bid_cap,
    apply_opponent_floor,
    apply_safe_guard,
    apply_value_anchor_ceiling,
    cap_with_burst_limit,
    post_process,
)


class PostProcessTests(unittest.TestCase):
    def test_burst_limit(self) -> None:
        self.assertAlmostEqual(cap_with_burst_limit(150.0, 100.0, 1.3), 130.0)
        self.assertAlmostEqual(cap_with_burst_limit(120.0, 100.0, 1.3), 120.0)

    def test_bid_cap(self) -> None:
        self.assertEqual(apply_bid_cap(500.0, 300), 300.0)
        self.assertEqual(apply_bid_cap(200.0, 300), 200.0)
        self.assertEqual(apply_bid_cap(200.0, None), 200.0)

    def test_safe_guard(self) -> None:
        cfg = PostProcessConfig(
            safe_guard_enabled=True,
            safe_guard_max_increase_ratio=0.5,
            last_submitted_price=100,
        )
        self.assertEqual(apply_safe_guard(200.0, cfg), 150.0)

    def test_opponent_floor(self) -> None:
        cfg = PostProcessConfig(
            opponent_bid_k_increment=1.0,
            opponent_bid_defensive_bump=10,
            opponent_bid_min=50,
        )
        self.assertEqual(apply_opponent_floor(100.0, 200, cfg), 210.0)
        self.assertEqual(apply_opponent_floor(40.0, None, cfg), 40.0)

    def test_value_anchor_ceiling(self) -> None:
        self.assertEqual(apply_value_anchor_ceiling(500.0, 300.0), 300.0)
        self.assertEqual(apply_value_anchor_ceiling(100.0, 300.0), 100.0)
        self.assertEqual(apply_value_anchor_ceiling(100.0, None), 100.0)

    def test_post_process_pipeline(self) -> None:
        cfg = PostProcessConfig(
            burst_limit=1.3,
            bid_cap_price=200,
            safe_guard_enabled=True,
            safe_guard_max_increase_ratio=0.5,
            last_submitted_price=100,
        )
        result = post_process(500.0, base=100.0, cfg=cfg, opponent_bid=None)
        # burst: min(500, 130)=130; bid_cap: 130 (200); safe_guard: min(130, 150) = 130
        self.assertEqual(result, 130)


if __name__ == "__main__":
    unittest.main()
