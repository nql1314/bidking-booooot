"""late_round_low_bid_surrender 后处理单元测试。"""

from __future__ import annotations

import unittest
from typing import Any

from bidking.pricing.postprocess import apply_late_round_low_bid_surrender
from bidking.pricing.self_bid_cache import resolve_self_bid_cache_amount


class TestLateRoundLowBidSurrender(unittest.TestCase):
    def _run(
        self,
        *,
        enabled: bool,
        fin: int,
        round_no: int,
        after_round: int = 4,
        below: int = 5000,
        surrender_bid: int = 886,
    ) -> tuple[int, dict[str, Any]]:
        cfg = {
            "pricing": {
                "enable_late_round_low_bid_surrender": enabled,
                "late_round_low_bid_surrender_after_round": after_round,
                "late_round_low_bid_surrender_below": below,
                "late_round_low_bid_surrender_bid": surrender_bid,
            }
        }
        payload: dict[str, Any] = {}
        return apply_late_round_low_bid_surrender(cfg, fin, round_no, payload)

    def test_disabled_leaves_bid(self) -> None:
        out, payload = self._run(enabled=False, fin=1000, round_no=5)
        self.assertEqual(out, 1000)
        self.assertFalse(payload["late_round_low_bid_surrender"]["applied"])

    def test_round_at_threshold_skips(self) -> None:
        out, payload = self._run(enabled=True, fin=1000, round_no=4, after_round=4)
        self.assertEqual(out, 1000)
        self.assertFalse(payload["late_round_low_bid_surrender"]["applied"])

    def test_low_bid_after_threshold_forces_surrender(self) -> None:
        out, payload = self._run(enabled=True, fin=3000, round_no=5, below=5000)
        self.assertEqual(out, 886)
        meta = payload["late_round_low_bid_surrender"]
        self.assertTrue(meta["applied"])
        self.assertEqual(meta["before"], 3000)
        self.assertEqual(meta["after"], 886)
        self.assertEqual(payload["self_bid_cache_amount"], 3000)
        self.assertEqual(resolve_self_bid_cache_amount(886, payload), 3000)

    def test_bid_at_or_above_threshold_unchanged(self) -> None:
        out, payload = self._run(enabled=True, fin=5000, round_no=5, below=5000)
        self.assertEqual(out, 5000)
        self.assertFalse(payload["late_round_low_bid_surrender"]["applied"])


if __name__ == "__main__":
    unittest.main()
