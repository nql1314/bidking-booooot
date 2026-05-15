"""runtime.json + config.json 加载与轻量类型化访问。

默认读取 ``configs/runtime.json`` 为基底，再与 ``configs/config.json`` **深合并**
（后者覆盖前者）。显式传入 ``path`` 时仅加载该文件（供测试或单文件模式）。

合并后会对 ``board_snapshot`` 应用环境变量（若设置则覆盖 JSON，便于不把 UID/名称提交进仓库或打进包内）：

- ``BIDKING_SELF_USER_UID`` → ``board_snapshot.self_user_uid``
- ``BIDKING_SELF_NAME_SUBSTRING`` → ``board_snapshot.self_name_substring``

仅当对应变量**出现在** ``os.environ`` 中时才覆盖（含空字符串）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from .paths import config_overlay_path, runtime_path


@dataclass
class RuntimeConfig:
    raw: Dict[str, Any]
    source_path: Optional[Path] = None

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def safety(self) -> Dict[str, Any]:
        return self.raw.get("safety", {})

    @property
    def window(self) -> Dict[str, Any]:
        return self.raw.get("window", {})

    @property
    def capture(self) -> Dict[str, Any]:
        return self.raw.get("capture", {})

    @property
    def ocr(self) -> Dict[str, Any]:
        return self.raw.get("ocr", {})

    @property
    def advisor(self) -> Dict[str, Any]:
        return self.raw.get("advisor", {})

    @property
    def pricing(self) -> Dict[str, Any]:
        return self.raw.get("pricing", {})

    @property
    def board_snapshot(self) -> Dict[str, Any]:
        return self.raw.get("board_snapshot", {})

    @property
    def automation(self) -> Dict[str, Any]:
        return self.raw.get("automation", {})

    @property
    def timing(self) -> Dict[str, Any]:
        return self.raw.get("timing", {})

    @property
    def clicks(self) -> Dict[str, Any]:
        return self.raw.get("clicks", {})

    @property
    def debug(self) -> Dict[str, Any]:
        return self.raw.get("debug", {})

    @property
    def grid_view(self) -> Dict[str, Any]:
        return self.raw.get("grid_view", {})


def apply_board_snapshot_env_overrides(cfg: Dict[str, Any]) -> None:
    """将 ``BIDKING_SELF_*`` 环境变量写入 ``cfg['board_snapshot']``（就地修改）。"""
    raw_bs = cfg.get("board_snapshot")
    bs: Dict[str, Any] = raw_bs if isinstance(raw_bs, dict) else {}
    if not isinstance(raw_bs, dict):
        cfg["board_snapshot"] = bs
    if "BIDKING_SELF_USER_UID" in os.environ:
        bs["self_user_uid"] = os.environ["BIDKING_SELF_USER_UID"].strip()
    if "BIDKING_SELF_NAME_SUBSTRING" in os.environ:
        bs["self_name_substring"] = os.environ["BIDKING_SELF_NAME_SUBSTRING"].strip()


def load_runtime(path: Optional[Path | str] = None) -> RuntimeConfig:
    if path is not None:
        p = Path(path).resolve()
        with p.open("r", encoding="utf-8-sig") as fp:
            data = json.load(fp)
        apply_board_snapshot_env_overrides(data)
        return RuntimeConfig(raw=data, source_path=p)

    from .pricing import deep_merge

    rp = runtime_path()
    cp = config_overlay_path()
    base: Dict[str, Any] = {}
    if rp.is_file():
        with rp.open("r", encoding="utf-8-sig") as fp:
            base = json.load(fp)
    overlay: Dict[str, Any] = {}
    if cp.is_file():
        with cp.open("r", encoding="utf-8-sig") as fp:
            overlay = json.load(fp)
    merged = deep_merge(base, overlay)
    apply_board_snapshot_env_overrides(merged)
    src = cp if cp.is_file() else rp
    return RuntimeConfig(raw=merged, source_path=src.resolve() if src.is_file() else cp.resolve())


def infer_unknown_contour_shapes_enabled(
    cfg: Optional[Union[RuntimeConfig, Mapping[str, Any]]] = None,
) -> bool:
    """
    是否对品质已知、轮廓未知的物品做 CSV 价带/概率轮廓推断（画板 ``infer_shapes``）。

    读取合并后配置 ``pricing.infer_unknown_contour_shapes``；键缺失时为 ``True``（与既有行为一致）。
    接受 ``RuntimeConfig`` 或已合并的 ``dict``（如 ``load_runtime().raw``）。
    """
    raw: Mapping[str, Any]
    if cfg is None:
        raw = load_runtime().raw
    elif isinstance(cfg, RuntimeConfig):
        raw = cfg.raw
    else:
        raw = cfg
    p = raw.get("pricing")
    if not isinstance(p, dict):
        return True
    v = p.get("infer_unknown_contour_shapes", True)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(int(v))
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return True


def infer_fraud_empty_cells_algorithm(
    cfg: Optional[Union[RuntimeConfig, Mapping[str, Any]]] = None,
) -> str:
    """
    空置前缀区「疑似诈骗格」剔除所用算法名，供 UI 与 :func:`bidking.analysis.grid_overlay.vacant_dict_from_board_snapshot` 使用。

    读取合并后配置 ``grid_view.fraud_empty_cells_algorithm``：

    - ``tiling_strict``（默认）：铺板可解释性，即 :func:`bidking.analysis.fraud_empty_cells.fraud_empty_cells_in_zone_prefix`；
      兼容旧配置值 ``tiling`` / ``tile`` / ``explainability``。
    - ``tiling_n``：铺板后再去掉 BoxId ``<= limit - n`` 的诈骗候选；``n`` 见 :func:`infer_fraud_empty_cells_tiling_n`；
    - ``none``（及 ``off`` / ``disabled`` / ``false`` / ``0``）：不做诈骗判断，诈骗格集合恒为空。

    未知非空字符串时回退为 ``tiling_strict``。
    """
    raw: Mapping[str, Any]
    if cfg is None:
        raw = load_runtime().raw
    elif isinstance(cfg, RuntimeConfig):
        raw = cfg.raw
    else:
        raw = cfg
    gv = raw.get("grid_view")
    if not isinstance(gv, dict):
        return "tiling_strict"
    v = gv.get("fraud_empty_cells_algorithm", "tiling_strict")
    s = str(v).strip().lower()
    if s in ("none", "off", "disabled", "false", "0"):
        return "none"
    if s in ("tiling_n", "tilingn"):
        return "tiling_n"
    if s in (
        "tiling_strict",
        "tilingstrict",
        "tiling",
        "tile",
        "explainability",
        "",
    ):
        return "tiling_strict"
    return "tiling_strict"


def infer_fraud_empty_cells_tiling_n(
    cfg: Optional[Union[RuntimeConfig, Mapping[str, Any]]] = None,
) -> int:
    """
    ``tiling_n`` 诈骗格算法所用的整数 ``n``（来自 ``grid_view.fraud_empty_cells_tiling_n``）。

    仅在 ``fraud_empty_cells_algorithm`` 为 ``tiling_n`` 时参与计算；解析失败或缺失时返回 ``0``
    （与纯 ``tiling_strict`` 等价）。返回值恒为非负整数。
    """
    raw: Mapping[str, Any]
    if cfg is None:
        raw = load_runtime().raw
    elif isinstance(cfg, RuntimeConfig):
        raw = cfg.raw
    else:
        raw = cfg
    gv = raw.get("grid_view")
    if not isinstance(gv, dict):
        return 0
    v = gv.get("fraud_empty_cells_tiling_n", 0)
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return max(0, n)
