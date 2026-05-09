"""快照总线 + 文件写出。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidking.bridge import (
    BoardSnapshotFileReader,
    BoardSnapshotFileWriter,
    SnapshotStore,
    write_mode_from_runtime,
)


class BridgeTests(unittest.TestCase):
    def test_store_publish_subscribe(self) -> None:
        store = SnapshotStore()
        seen = []
        unsub = store.subscribe(lambda s: seen.append(dict(s)))
        store.publish({"current_round": 1})
        store.publish({"current_round": 2})
        self.assertEqual(len(seen), 2)
        self.assertEqual(store.get_latest(), {"current_round": 2})
        unsub()
        store.publish({"current_round": 3})
        self.assertEqual(len(seen), 2)
        self.assertEqual(store.get_latest(), {"current_round": 3})

    def test_file_writer_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snap.json"
            writer = BoardSnapshotFileWriter(path, mode="both")
            self.assertTrue(writer.enabled)
            writer.write({"hello": "world", "n": 1})
            reader = BoardSnapshotFileReader(path)
            self.assertEqual(reader.read(), {"hello": "world", "n": 1})

    def test_file_writer_off(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snap.json"
            writer = BoardSnapshotFileWriter(path, mode="off")
            self.assertFalse(writer.enabled)
            writer.write({"x": 1})
            self.assertFalse(path.exists())

    def test_write_mode_resolution(self) -> None:
        self.assertEqual(write_mode_from_runtime({}), "both")
        self.assertEqual(write_mode_from_runtime({"write_mode": "FILE"}), "file")
        self.assertEqual(write_mode_from_runtime({"write_mode": "off"}), "off")
        self.assertEqual(write_mode_from_runtime({"write_mode": "weird"}), "both")


if __name__ == "__main__":
    unittest.main()
