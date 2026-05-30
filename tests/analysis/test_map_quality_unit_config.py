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
    map_quality_unit_per_cell_ceiling_from_refs,
    merge_config_overrides_into_runtime,
    validate_map_quality_unit_per_cell_override,
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
        cell = {"q5": 1000.0, "q5+q6": 2000.0, "q4+q5+q6": 4000.0}
        item = {"q5": 500.0, "q5+q6": 4000.0, "q4+q5+q6": 8000.0}
        cell2, item2, applied = apply_map_quality_unit_per_cell_overrides(
            cell, item, {"q5": 2000.0, "q56": 3000.0, "q456": 5000.0}
        )
        self.assertEqual(cell2["q5"], 2000.0)
        self.assertEqual(cell2["q5+q6"], 3000.0)
        self.assertEqual(cell2["q4+q5+q6"], 5000.0)
        self.assertAlmostEqual(item2["q5"], 1000.0)
        self.assertAlmostEqual(item2["q5+q6"], 6000.0)
        self.assertAlmostEqual(item2["q4+q5+q6"], 10000.0)
        self.assertIn("q5", applied)
        self.assertIn("q5+q6", applied)
        self.assertIn("q4+q5+q6", applied)

    def test_config_overrides_q456_parsed(self) -> None:
        ov = config_overrides_from_pricing(
            {"map_quality_unit_per_cell": {"q456": 15000.0}}
        )
        self.assertEqual(ov.get("q456"), 15000.0)

    def test_config_overrides_q3456_parsed(self) -> None:
        ov = config_overrides_from_pricing(
            {"map_quality_unit_per_cell": {"q3456": 12000.0}}
        )
        self.assertEqual(ov.get("q3456"), 12000.0)

    def test_ceiling_from_refs_avg_times_1_2(self) -> None:
        cap = map_quality_unit_per_cell_ceiling_from_refs({"avg_per_cell": 1000.0})
        self.assertAlmostEqual(cap, 1200.0)

    def test_validate_rejects_above_ceiling(self) -> None:
        refs = {"q5": {"avg_per_cell": 1000.0}}
        validate_map_quality_unit_per_cell_override("q5", 1200.0, refs)
        with self.assertRaises(ValueError):
            validate_map_quality_unit_per_cell_override("q5", 1200.01, refs)

    def test_validate_skips_when_no_csv_avg(self) -> None:
        validate_map_quality_unit_per_cell_override("q5", 999999.0, {})

    def test_apply_overrides_q3456_cell_and_scaled_item(self) -> None:
        cell = {"q3+q4+q5+q6": 4000.0}
        item = {"q3+q4+q5+q6": 8000.0}
        cell2, item2, applied = apply_map_quality_unit_per_cell_overrides(
            cell, item, {"q3456": 6000.0}
        )
        self.assertEqual(cell2["q3+q4+q5+q6"], 6000.0)
        self.assertAlmostEqual(item2["q3+q4+q5+q6"], 12000.0)
        self.assertIn("q3+q4+q5+q6", applied)

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
