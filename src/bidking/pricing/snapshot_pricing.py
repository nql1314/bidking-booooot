"""画板快照 ``pricing`` 刷新：出价与 GUI 顶栏共用 ``build_snapshot_pricing_dict``。"""

from __future__ import annotations

from typing import Any

from ..analysis._board_pricing import build_snapshot_pricing_dict


def board_snapshot_can_refresh_pricing(board_snapshot: dict[str, Any]) -> bool:
    """是否具备重算 ``pricing`` 所需的画板基底（而非仅缓存 ``pricing`` 块）。"""
    if not isinstance(board_snapshot.get("game_state"), dict):
        return False
    if isinstance(board_snapshot.get("raw_pricing"), dict):
        return True
    go = board_snapshot.get("grid_overlay")
    if isinstance(go, dict) and go:
        return True
    if board_snapshot.get("skill_logs"):
        return True
    return False


def refresh_board_snapshot_pricing(
    board_snapshot: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    基于 ``game_state`` / ``raw_pricing`` / ``grid_overlay`` 重算并写回 ``pricing``。

    轻量烟测快照（仅 ``pricing`` 块）保留原缓存；完整画板快照始终走实时定价流水线。
    """
    cached = board_snapshot.get("pricing")
    if not board_snapshot_can_refresh_pricing(board_snapshot):
        return cached if isinstance(cached, dict) else {}

    hint: str | None = None
    if isinstance(config, dict):
        bs_cfg = config.get("board_snapshot") or {}
        raw_path = str(bs_cfg.get("path") or "").strip()
        if raw_path:
            hint = raw_path

    try:
        pricing = build_snapshot_pricing_dict(
            board_snapshot,
            snapshot_path_hint=hint,
        )
    except Exception:
        if isinstance(cached, dict) and cached.get("total") is not None:
            return cached
        raise

    board_snapshot["pricing"] = pricing
    return pricing
