"""OCR 文本 → 结构化 patch / 对手价。

仅做"文本 → 结构化数据"，不持有价格状态。

- :func:`parse_central_info` / :func:`merge_patch` —— 中央信息文本解析
- :func:`get_max_other_players_last_bid_from_image` 等 —— 对手价 OCR
"""

from __future__ import annotations

from ._central_info_parser import (  # noqa: F401
    merge_patch,
    parse_central_info,
)
from ._bid_history_parser import (  # noqa: F401
    coerce_valid_lobby_player_count,
    get_max_other_players_last_bid_from_image,
    read_multiplayer_layout_for_count,
    resolve_lobby_player_count_for_opponent_bid,
)

__all__ = [
    "merge_patch",
    "parse_central_info",
    "coerce_valid_lobby_player_count",
    "get_max_other_players_last_bid_from_image",
    "read_multiplayer_layout_for_count",
    "resolve_lobby_player_count_for_opponent_bid",
]
