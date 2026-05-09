"""跨层胶水：进程内快照总线 + 可选文件写出。

数据流约定：

::

    parsing -> analysis -> bridge.snapshot_store.publish(snapshot)
                                                |
                          bridge.snapshot_file -+-> board_snapshot.json (可选)
                                                |
                                                +-> ui.app 订阅刷新
"""

from .snapshot_store import SnapshotStore, get_default_store
from .snapshot_file import (
    BoardSnapshotFileWriter,
    BoardSnapshotFileReader,
    write_mode_from_runtime,
)

__all__ = [
    "SnapshotStore",
    "get_default_store",
    "BoardSnapshotFileWriter",
    "BoardSnapshotFileReader",
    "write_mode_from_runtime",
]
