"""端到端冒烟：parsing → analysis → bridge.snapshot_store → 文件写出。

不依赖游戏窗口；用纯 Python 构造 ``GameState``，验证：

1. ``analysis.build_board_snapshot`` 能输出统一 dict（含 pricing 子键）。
2. ``bridge.snapshot_store`` 订阅回调被触发，``get_latest()`` 反映最新快照。
3. ``bridge.snapshot_file.BoardSnapshotFileWriter`` 落盘文件可被 reader 读回。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidking.analysis import build_board_snapshot
from bidking.bridge import (
    BoardSnapshotFileReader,
    BoardSnapshotFileWriter,
    SnapshotStore,
)
from bidking.parsing.state import GameState, ItemKnowledge


class PipelineSmokeTests(unittest.TestCase):
    def _make_state(self) -> GameState:
        st = GameState()
        st.uid = "g-1"
        st.map_id = 2101
        st.current_round = 2
        # 一个已揭示物品
        item = ItemKnowledge(uid="u1")
        item.box_id = 0
        item.box_id_confirmed = True
        item.shape = 11
        item.quality = 4
        item.categories = {101}
        st.items["u1"] = item
        # 负向约束：扫描品质 5 时未命中 u1
        st.record_scan("quality", 5, set())
        return st

    def test_pipeline(self) -> None:
        st = self._make_state()
        snap = build_board_snapshot(st, map_skill_logs=[], include_pricing=True)
        self.assertEqual(snap["uid"], "g-1")
        self.assertEqual(snap["map_id"], 2101)
        self.assertEqual(snap["current_round"], 2)
        self.assertIn("u1", snap["items"])
        self.assertIn("scan_history", snap)
        self.assertIn("pricing", snap)

        store = SnapshotStore()
        seen = []
        store.subscribe(lambda s: seen.append(s["current_round"]))
        store.publish(snap)
        self.assertEqual(seen, [2])

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "board_snapshot.json"
            writer = BoardSnapshotFileWriter(path, mode="both")
            store.subscribe(writer.write)
            store.publish(snap)
            reader = BoardSnapshotFileReader(path)
            roundtrip = reader.read()
            self.assertIsNotNone(roundtrip)
            self.assertEqual(roundtrip["uid"], "g-1")
            self.assertIn("u1", roundtrip["items"])


if __name__ == "__main__":
    unittest.main()
