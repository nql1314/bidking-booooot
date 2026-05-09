"""进程内最新分析快照的发布/订阅。

第 3 层（analysis）算完一份 snapshot dict 后调用 ``publish``；第 4 层（pricing）
通过 ``get_latest()`` 拿当前快照，第 5 层（ui）通过 ``subscribe(cb)`` 收到推送。
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

Snapshot = Dict[str, Any]
Listener = Callable[[Snapshot], None]


class SnapshotStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._latest: Optional[Snapshot] = None
        self._listeners: List[Listener] = []

    def publish(self, snapshot: Snapshot) -> None:
        with self._lock:
            self._latest = snapshot
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(snapshot)
            except Exception:
                pass

    def get_latest(self) -> Optional[Snapshot]:
        with self._lock:
            return self._latest

    def subscribe(self, cb: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(cb)

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(cb)
                except ValueError:
                    pass

        return _unsubscribe


_DEFAULT = SnapshotStore()


def get_default_store() -> SnapshotStore:
    return _DEFAULT
