# -*- coding: utf-8 -*-
"""画板快照定价策略注册与编排。"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from ...logsys.perf_log import perf_log_elapsed
from . import ahmad as _ahmad_strategy
from . import generic as _generic_strategy
from .context import SnapshotPricingContext
from .context_dump import maybe_write_pricing_context_json
from .pipeline import build_pricing_context

EnrichFn = Callable[[SnapshotPricingContext, Dict[str, Any]], Dict[str, Any]]

# 按顺序执行的角色 enrich；新增角色策略在此注册即可。
_ROLE_ENRICHERS: List[EnrichFn] = [
    _ahmad_strategy.enrich_ahmad_pricing,
]


def build_snapshot_pricing_dict(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
    board_snapshot_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """组装 ``board_snapshot.json`` 的 ``pricing`` 字段。

    流程：公共流水线 → 通用 ``pricing`` 字段 → 各角色 enrich（可覆盖主价）。
    """
    t0_total = time.perf_counter()
    ctx = build_pricing_context(
        board_snapshot,
        snapshot_path_hint=snapshot_path_hint,
        board_snapshot_config=board_snapshot_config,
    )
    maybe_write_pricing_context_json(ctx)
    pricing = _generic_strategy.finalize_pricing_dict(ctx)
    for enrich in _ROLE_ENRICHERS:
        pricing = enrich(ctx, pricing)
    perf_log_elapsed(
        f"build_snapshot_pricing_dict: TOTAL (map={ctx.map_id}, round={ctx.current_round})",
        t0_total,
    )
    return pricing
