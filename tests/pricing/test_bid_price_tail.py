# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from bidking.pricing.postprocess import apply_human_like_price_tail


class TestBidPriceTail(unittest.TestCase):
    def test_default_custom_tails_pick_min_valid(self) -> None:
        cfg = {"automation": {}}
        fin, payload = apply_human_like_price_tail(13_321, {}, cfg)
        self.assertEqual(fin, 13_333)
        ht = payload["human_price_tail"]
        self.assertEqual(ht.get("pattern"), "333")
        self.assertEqual(ht.get("mode"), "custom_tails")
        self.assertEqual(ht.get("tails"), [333, 666, 888])

    def test_custom_tails_picks_next_tail_in_same_thousand(self) -> None:
        cfg = {"automation": {"bid_price_tails": [333, 666, 888]}}
        fin, payload = apply_human_like_price_tail(13_500, {}, cfg)
        self.assertEqual(fin, 13_666)
        self.assertEqual(payload["human_price_tail"]["pattern"], "666")

    def test_custom_tails_carries_to_next_thousand(self) -> None:
        cfg = {"automation": {"bid_price_tails": [333, 666, 888]}}
        fin, payload = apply_human_like_price_tail(13_999, {}, cfg)
        self.assertEqual(fin, 14_333)
        self.assertEqual(payload["human_price_tail"]["pattern"], "333_carry")

    def test_disabled_skips_tail(self) -> None:
        cfg = {"automation": {"enable_bid_price_tail": False}}
        fin, payload = apply_human_like_price_tail(13_321, {}, cfg)
        self.assertEqual(fin, 13_321)
        self.assertEqual(payload["human_price_tail"]["pattern"], "disabled")

    def test_empty_tails_list_uses_legacy(self) -> None:
        cfg = {"automation": {"bid_price_tails": []}}
        fin, payload = apply_human_like_price_tail(13_321, {}, cfg)
        self.assertEqual(fin, 13_333)
        self.assertEqual(payload["human_price_tail"]["mode"], "legacy_thousands_digit")

    def test_legacy_four_thousands_digit(self) -> None:
        cfg = {"automation": {"bid_price_tails": []}}
        fin, payload = apply_human_like_price_tail(14_321, {}, cfg)
        self.assertEqual(fin, 14_444)
        self.assertEqual(payload["human_price_tail"]["pattern"], "444")

    def test_skip_when_price_below_divisor(self) -> None:
        cfg = {"automation": {"bid_price_tails": [333, 666]}}
        fin, payload = apply_human_like_price_tail(500, {}, cfg)
        self.assertEqual(fin, 500)
        self.assertTrue(str(payload["human_price_tail"]["pattern"]).startswith("skip_lt_"))

    def test_two_digit_tail_width(self) -> None:
        cfg = {
            "automation": {
                "bid_price_tail_digits": 2,
                "bid_price_tails": [33, 66, 88],
            }
        }
        fin, payload = apply_human_like_price_tail(1_050, {}, cfg)
        self.assertEqual(fin, 1_066)
        self.assertEqual(payload["human_price_tail"]["pattern"], "66")


if __name__ == "__main__":
    unittest.main()
