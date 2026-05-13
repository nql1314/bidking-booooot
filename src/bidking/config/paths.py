"""配置文件 / 数据资源的标准路径解析。

- 优先取环境变量 ``BIDKING_HOME``。
- 否则向上找包含 ``configs/`` 与 ``data/`` 的目录。
- 兜底取当前工作目录。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _looks_like_root(p: Path) -> bool:
    return (p / "configs").is_dir() and (p / "data").is_dir()


def project_root() -> Path:
    env = os.environ.get("BIDKING_HOME")
    if env:
        return Path(env).resolve()

    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if _looks_like_root(parent):
            return parent

    return Path.cwd().resolve()


def configs_dir() -> Path:
    return project_root() / "configs"


def data_dir() -> Path:
    return project_root() / "data"


def board_snapshot_default_path() -> Path:
    """默认画板快照 JSON：``<project_root>/data/board_snapshot.json``。"""
    return (data_dir() / "board_snapshot.json").resolve()


def resolve_board_snapshot_path(raw: Optional[str]) -> Path:
    """
    解析 ``board_snapshot.path``（``configs`` 合并结果）。

    - 空或未设置：:func:`board_snapshot_default_path`。
    - 绝对路径：``expanduser`` 后 ``resolve``。
    - 相对路径：相对 :func:`project_root`（例如 ``data/board_snapshot.json`` 与 exe+data 分发一致）。
    """
    s = (raw or "").strip()
    if not s:
        return board_snapshot_default_path()
    p = Path(s).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (project_root() / s).resolve()


def runtime_path() -> Path:
    return configs_dir() / "runtime.json"


def config_overlay_path() -> Path:
    """与本机/玩法相关的覆盖配置（窗口、点击、快照路径等），与 :func:`runtime_path` 深合并。"""
    return configs_dir() / "config.json"


def pricing_path() -> Path:
    return configs_dir() / "pricing.json"


def pricing_map_overlay_path(map_id: int | str) -> Path:
    """``configs/pricing.maps/<map_id>.json`` 路径（文件不一定已存在，供 GUI 读写）。"""
    return configs_dir() / "pricing.maps" / f"{map_id}.json"


def pricing_map_override_path(map_id: int | str) -> Optional[Path]:
    candidate = pricing_map_overlay_path(map_id)
    return candidate if candidate.is_file() else None
