"""链式地图配置解析。"""

import unittest

from bidking.config.map_chain import (
    automation_run_schedule,
    default_tool_rounds,
    parse_automation_map_chain,
    tool_rounds_set_for_chain_step,
)


class MapChainTests(unittest.TestCase):
    def test_legacy_fallback_single_map(self) -> None:
        auto = {"selected_map": "230", "selected_runs": 7, "maps": {"230": {}}}
        chain = parse_automation_map_chain(auto)
        self.assertEqual(chain, [{"map_id": "230", "runs": 7, "tool_rounds": [1, 2]}])

    def test_empty_tool_rounds_disables_tool(self) -> None:
        auto = {
            "tool_rounds": [],
            "map_chain": [{"map_id": "230", "runs": 1, "tool_rounds": []}],
        }
        chain = parse_automation_map_chain(auto)
        self.assertEqual(chain[0]["tool_rounds"], [])
        self.assertEqual(tool_rounds_set_for_chain_step(chain[0], auto), set())
        self.assertEqual(default_tool_rounds(auto), [])

    def test_per_map_tool_rounds(self) -> None:
        auto = {
            "tool_rounds": [1, 2],
            "map_chain": [
                {"map_id": "240", "runs": 1, "tool_rounds": [3, 4]},
                {"map_id": "210", "runs": 1},
            ],
        }
        chain = parse_automation_map_chain(auto)
        self.assertEqual(chain[0]["tool_rounds"], [3, 4])
        self.assertEqual(chain[1]["tool_rounds"], [1, 2])
        self.assertEqual(tool_rounds_set_for_chain_step(chain[0], auto), {3, 4})
        self.assertEqual(tool_rounds_set_for_chain_step(chain[1], auto), {1, 2})

    def test_chain_total_runs(self) -> None:
        auto = {
            "map_chain": [
                {"map_id": "240", "runs": 2},
                {"map_id": "210", "runs": 3},
            ],
            "run_cycles": 4,
        }
        _, per_big, cycles, total, _ = automation_run_schedule(auto)
        self.assertEqual(per_big, 5)
        self.assertEqual(cycles, 4)
        self.assertEqual(total, 20)


if __name__ == "__main__":
    unittest.main()
