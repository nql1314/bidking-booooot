"""策略路由 facade 测试。"""

from __future__ import annotations

import unittest

from bidking.pricing.strategy import Mode, normalize_mode


class StrategyTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_mode("ahmad_premium"), Mode.AHMAD)
        self.assertEqual(normalize_mode("ahmad"), Mode.AHMAD)
        self.assertEqual(normalize_mode("aisha_premium"), Mode.AISHA)
        self.assertEqual(normalize_mode("aisha"), Mode.AISHA)
        self.assertEqual(normalize_mode("raven"), Mode.RAVEN)
        self.assertEqual(normalize_mode(None), Mode.AHMAD)
        self.assertEqual(normalize_mode("xxx"), Mode.AHMAD)


if __name__ == "__main__":
    unittest.main()
