# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from bidking.pricing.postprocess import apply_bid_cap, known_items_total_from_pricing


class TestApplyBidCap(unittest.TestCase):
    def test_caps_at_insurance_when_known_items_total_above_threshold(self) -> None:
        cfg = {
            "automation": {
                "bid_cap_price": 5000,
                "bid_cap_skip_when_total_above": 4000,
            }
        }
        fin, payload = apply_bid_cap(
            cfg, 9000, {}, known_items_total=5000.0
        )
        self.assertEqual(fin, 4000)
        bc = payload["bid_cap"]
        self.assertTrue(bc.get("skipped"))
        self.assertTrue(bc.get("applied"))
        self.assertEqual(bc.get("insurance_cap_price"), 4000)
        self.assertEqual(bc.get("reason"), "known_items_total_above_skip_threshold")
        self.assertEqual(bc.get("known_items_total"), 5000.0)

    def test_insurance_cap_not_applied_when_final_price_below_insurance(self) -> None:
        cfg = {
            "automation": {
                "bid_cap_price": 3_500_000,
                "bid_cap_skip_when_total_above": 4_000_000,
            }
        }
        fin, payload = apply_bid_cap(
            cfg, 3_800_000, {}, known_items_total=4_100_000.0
        )
        self.assertEqual(fin, 3_800_000)
        bc = payload["bid_cap"]
        self.assertTrue(bc.get("skipped"))
        self.assertFalse(bc.get("applied"))

    def test_applies_cap_when_known_total_below_threshold_even_if_total_high(self) -> None:
        cfg = {
            "automation": {
                "bid_cap_price": 5000,
                "bid_cap_skip_when_total_above": 4000,
            }
        }
        fin, payload = apply_bid_cap(
            cfg, 9000, {}, known_items_total=3000.0
        )
        self.assertEqual(fin, 5000)
        self.assertTrue(payload["bid_cap"].get("applied"))

    def test_known_items_total_from_pricing_field(self) -> None:
        self.assertEqual(
            known_items_total_from_pricing({"known_items_total": 12345.5}),
            12345.5,
        )
        self.assertIsNone(known_items_total_from_pricing({"total": 99999}))


if __name__ == "__main__":
    unittest.main()
