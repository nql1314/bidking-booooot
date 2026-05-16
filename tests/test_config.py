"""config 层：runtime 加载、pricing 空文件兜底、深合并。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bidking.config import (
    apply_board_snapshot_env_overrides,
    deep_merge,
    load_pricing,
    load_runtime,
    resolve_for,
)


class ConfigTests(unittest.TestCase):
    def test_runtime_load(self) -> None:
        rc = load_runtime()
        self.assertIn("automation", rc.raw)
        self.assertEqual(rc.window.get("title_keyword"), "BidKing")

    def test_pricing_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nope.json"
            self.assertEqual(load_pricing(p), {})

    def test_resolve_map_override_with_base(self) -> None:
        base = {
            "ahmad_premium": {"round1_base_factor": 1, "x": {"a": 1}},
            "grid_prices": {"green": 0.0},
        }
        with tempfile.TemporaryDirectory() as tmp:
            override_path = Path(tmp) / "2.json"
            override = {"ahmad_premium": {"round1_base_factor": 2}}
            override_path.write_text(json.dumps(override, ensure_ascii=False), encoding="utf-8")

            def fake_override(mid: int | str) -> Path | None:
                return override_path if str(mid) == "2" else None

            with patch("bidking.config.pricing.pricing_map_override_path", fake_override):
                merged = resolve_for("2", base=base)

        self.assertEqual(merged["ahmad_premium"]["round1_base_factor"], 2)
        self.assertEqual(merged["ahmad_premium"]["x"]["a"], 1)

    def test_resolve_unknown_map(self) -> None:
        base = {"k": 1}
        merged = resolve_for("999", base=base)
        self.assertEqual(merged, base)

    def test_deep_merge(self) -> None:
        a = {"x": 1, "y": {"a": 1, "b": 2}, "z": [1, 2]}
        b = {"y": {"b": 20, "c": 3}, "z": [9]}
        self.assertEqual(
            deep_merge(a, b),
            {"x": 1, "y": {"a": 1, "b": 20, "c": 3}, "z": [9]},
        )

    def test_board_snapshot_env_overrides(self) -> None:
        cfg: dict = {"board_snapshot": {"self_user_uid": "old"}}
        with patch.dict(
            os.environ,
            {"BIDKING_SELF_USER_UID": "from_env"},
            clear=False,
        ):
            apply_board_snapshot_env_overrides(cfg)
        bs = cfg["board_snapshot"]
        self.assertEqual(bs["self_user_uid"], "from_env")

    def test_refresh_poll_loop_locals_run_schedule(self) -> None:
        from bidking.interaction._legacy_bot import refresh_poll_loop_locals

        cfg = {
            "automation": {
                "selected_runs": 3,
                "run_cycles": 4,
                "cycle_rest_minutes": 0.5,
                "maps": {},
            },
            "timing": {},
            "safety": {},
        }
        lv = refresh_poll_loop_locals(cfg)
        self.assertEqual(lv["runs_per_cycle"], 3)
        self.assertEqual(lv["run_cycles"], 4)
        self.assertEqual(lv["max_runs"], 12)
        self.assertEqual(lv["cycle_rest_minutes"], 0.5)

    def test_refresh_poll_loop_locals_schedule_defaults(self) -> None:
        from bidking.interaction._legacy_bot import refresh_poll_loop_locals

        cfg = {
            "automation": {"selected_runs": 5, "maps": {}},
            "timing": {},
            "safety": {},
        }
        lv = refresh_poll_loop_locals(cfg)
        self.assertEqual(lv["runs_per_cycle"], 5)
        self.assertEqual(lv["run_cycles"], 1)
        self.assertEqual(lv["max_runs"], 5)
        self.assertEqual(lv["cycle_rest_minutes"], 1.0)


if __name__ == "__main__":
    unittest.main()
