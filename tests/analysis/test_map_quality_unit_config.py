"""金/红格单价配置覆盖与 CSV 参考价加载。"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bidking.analysis.map_avg_csv import set_map_quality_csv_override
from bidking.analysis._board_pricing import build_snapshot_pricing_dict
from bidking.analysis.map_quality_unit_config import (
    apply_map_quality_unit_per_cell_overrides,
    config_overrides_from_pricing,
    merge_config_overrides_into_runtime,
)
from bidking.analysis.raw_pricing import build_raw_pricing_dict


class MapQualityUnitConfigTests(unittest.TestCase):
    def test_config_overrides_parsed(self) -> None:
        ov = config_overrides_from_pricing(
            {"map_quality_unit_per_cell": {"q5": 12000, "q6": 0, "q56": 30000}}
        )
        self.assertEqual(ov.get("q5"), 12000.0)
        self.assertEqual(ov.get("q56"), 30000.0)
        self.assertNotIn("q6", ov)

    def test_apply_overrides_cell_and_scaled_item(self) -> None:
        cell = {"q5": 1000.0, "q5+q6": 2000.0}
        item = {"q5": 500.0, "q5+q6": 4000.0}
        cell2, item2, applied = apply_map_quality_unit_per_cell_overrides(
            cell, item, {"q5": 2000.0, "q56": 3000.0}
        )
        self.assertEqual(cell2["q5"], 2000.0)
        self.assertEqual(cell2["q5+q6"], 3000.0)
        self.assertAlmostEqual(item2["q5"], 1000.0)
        self.assertAlmostEqual(item2["q5+q6"], 6000.0)
        self.assertIn("q5", applied)
        self.assertIn("q5+q6", applied)

    def test_build_raw_pricing_config_overrides_csv(self) -> None:
        tmp = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", suffix=".csv", delete=False
        )
        w = csv.writer(tmp)
        w.writerow(
            [
                "map_id",
                "tier",
                "nest_drop_id",
                "quality_group",
                "prob_in_group",
                "avg_price_per_item",
                "avg_price_per_cell",
            ]
        )
        w.writerow([2101, 101, 2001, "q5", 1, 100, 1000])
        w.writerow([2101, 101, 2001, "q6", 1, 200, 2000])
        w.writerow([2101, 101, 2001, "q5+q6", 1, 150, 1500])
        tmp.close()
        csv_path = Path(tmp.name)
        set_map_quality_csv_override(str(csv_path))
        map_json = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json")
        json.dump(
            {"pricing": {"map_quality_unit_per_cell": {"q5": 7777}}},
            map_json,
            ensure_ascii=False,
        )
        map_json.close()
        map_path = Path(map_json.name)
        try:
            from bidking.config import map_runtime_overlay as mro

            orig = mro.pricing_map_overlay_path
            mro.pricing_map_overlay_path = lambda mid: map_path  # type: ignore[assignment]
            try:
                raw = build_raw_pricing_dict(map_id=2101, skill_logs=[])
            finally:
                mro.pricing_map_overlay_path = orig  # type: ignore[assignment]
            cells = raw["csv_quality_groups_avg_per_cell"]
            self.assertEqual(cells["q5"], 7777.0)
            self.assertEqual(cells["q6"], 2000.0)
            self.assertIn("q5", raw.get("map_quality_unit_override_keys") or [])
        finally:
            set_map_quality_csv_override(None)
            csv_path.unlink(missing_ok=True)
            map_path.unlink(missing_ok=True)

    def test_cached_raw_pricing_reapplies_map_unit_overrides(self) -> None:
        """快照内嵌旧 raw_pricing 时，定价仍应读取当前 pricing.maps 格单价覆盖。"""
        from bidking.config import map_runtime_overlay as mro

        map_json = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json")
        json.dump(
            {"pricing": {"map_quality_unit_per_cell": {"q56": 22000}}},
            map_json,
            ensure_ascii=False,
        )
        map_json.close()
        map_path = Path(map_json.name)
        orig = mro.pricing_map_overlay_path
        mro.pricing_map_overlay_path = lambda mid: map_path  # type: ignore[assignment]
        try:
            snap = {
                "game_state": {"map_id": 2401, "current_round": 4, "items": {}},
                "skill_logs": [],
                "map_id": 2401,
                "current_round": 4,
                "raw_pricing": {
                    "csv_quality_groups_avg_per_cell": {
                        "q5": 100.0,
                        "q5+q6": 200.0,
                        "q6": 300.0,
                    }
                },
            }
            p = build_snapshot_pricing_dict(snap)
            self.assertEqual(p.get("vacant_unit_gold_red"), 22000)
        finally:
            mro.pricing_map_overlay_path = orig  # type: ignore[assignment]
            map_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
