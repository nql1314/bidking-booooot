from __future__ import annotations

from typing import Any

_ROUND5_SKIP_RATIO_OPPONENT_HERO_CIDS = frozenset({103, 107})

ROUND_RULES = {
    1: {"multiplier": 2.0, "pace": 0.42, "label": "两倍出价第二直接获得"},
    2: {"multiplier": 1.6, "pace": 0.56, "label": "1.6 倍出价第二直接获得"},
    3: {"multiplier": 1.3, "pace": 0.77, "label": "1.3 倍出价第二直接获得"},
    4: {"multiplier": 1.1, "pace": 0.91, "label": "1.1 倍出价第二直接获得"},
    5: {"multiplier": 1.0, "pace": 1.00, "label": "价高者得"},
}


def resolve_round_multiplier(round_no: int, price_config: dict[str, Any]) -> float:
    r = max(1, min(5, int(round_no)))
    rr = price_config.get("round_rules") or {}
    item = rr.get(str(r))
    if isinstance(item, dict) and item.get("multiplier") is not None:
        return float(item["multiplier"])
    return float(ROUND_RULES.get(r, ROUND_RULES[5])["multiplier"])


def _opponents_have_hero_cids(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    hero_cids: frozenset[int],
) -> bool:
    bs_cfg = config.get("board_snapshot") or {}
    self_uid = str(bs_cfg.get("self_user_uid") or "").strip()
    name_hint = str(bs_cfg.get("self_name_substring") or "").strip()
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return False
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
            continue
        pname = str(pdata.get("name") or "")
        if name_hint and name_hint in pname:
            continue
        try:
            hc = int(pdata.get("hero_cid") or 0)
        except (TypeError, ValueError):
            continue
        if hc in hero_cids:
            return True
    return False


def resolve_automation_bid_ratio(
    config: dict[str, Any],
    round_no: int,
    board_snapshot: dict[str, Any] | None,
) -> tuple[float, bool]:
    """automation.bid_ratio_by_round；第 5 回合遇对手 hero 103/107 时倍数强制为 1。"""
    if int(round_no) >= 4 and board_snapshot is not None:
        if _opponents_have_hero_cids(
            board_snapshot, config, _ROUND5_SKIP_RATIO_OPPONENT_HERO_CIDS
        ):
            return 1.0, True
    auto = config.get("automation") or {}
    raw = auto.get("bid_ratio_by_round")
    if raw is None:
        raw = config.get("bid_ratio_by_round")
    if not isinstance(raw, dict):
        return 1.0, False
    key = str(int(round_no))
    v = raw.get(key)
    if v is None:
        v = raw.get("default")
    if v is None:
        return 1.0, False
    try:
        r = float(v)
    except (TypeError, ValueError):
        return 1.0, False
    return (r if r > 0 else 1.0), False
