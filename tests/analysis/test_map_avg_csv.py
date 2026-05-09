"""``map_quality_avg_out.csv`` facade 用例。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from bidking.analysis.map_avg_csv import (
    load_map_quality_cells_by_map_id,
    set_map_quality_csv_override,
    vacant_unit_prices_for_map_id,
)


class MapAvgCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", suffix=".csv", delete=False
        )
        writer = csv.writer(tmp)
        writer.writerow(["map_id", "quality_group", "avg_price_per_cell"])
        writer.writerow([2101, "q5", "1234.5"])
        writer.writerow([2101, "q5+q6", "5678.9"])
        writer.writerow([2101, "q6", "9999.0"])
        tmp.close()
        self.csv_path = Path(tmp.name)
        set_map_quality_csv_override(str(self.csv_path))

    def tearDown(self) -> None:
        set_map_quality_csv_override(None)
        try:
            self.csv_path.unlink()
        except OSError:
            pass

    def test_load_and_lookup(self) -> None:
        cells = load_map_quality_cells_by_map_id()
        self.assertIn(2101, cells)
        self.assertAlmostEqual(cells[2101]["q5"], 1234.5)

    def test_vacant_unit_prices_three_tier(self) -> None:
        q5, q5_q6, q6, csv_hit = vacant_unit_prices_for_map_id(2101)
        self.assertTrue(csv_hit)
        self.assertEqual(q5, 1234)  # round(1234.5) = 1234 (banker's)
        self.assertEqual(q5_q6, 5679)
        self.assertEqual(q6, 9999)


if __name__ == "__main__":
    unittest.main()
