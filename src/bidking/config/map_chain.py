"""链式地图运行计划：多地图顺序执行，每段独立局数，外层大循环与休息。"""

from __future__ import annotations

from typing import Any

from .map_runtime_overlay import resolve_automation_map_config_key

_DEFAULT_TOOL_ROUNDS = [1, 2]


def default_tool_rounds(auto: dict[str, Any]) -> list[int]:
    """全局道具回合（``automation.tool_rounds``）。

    键不存在时回退 ``[1, 2]``；显式 ``[]`` 表示本局不使用道具。
    """
    if "tool_rounds" not in auto:
        return list(_DEFAULT_TOOL_ROUNDS)
    return parse_tool_rounds_list(auto.get("tool_rounds"))


def parse_tool_rounds_list(raw: Any) -> list[int]:
    """解析 1–5 回合号列表。

    - ``[]`` 保持为空（用户未勾选任何回合）；
    - 非 list 类型视为无效，返回 ``[]``。
    """
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        try:
            r = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= r <= 5 and r not in out:
            out.append(r)
    return sorted(out)


def tool_rounds_set_for_chain_step(step: dict[str, Any], auto: dict[str, Any]) -> set[int]:
    """当前链节点的道具回合；段内未配置时用全局 ``tool_rounds``。"""
    if "tool_rounds" in step:
        return set(parse_tool_rounds_list(step.get("tool_rounds")))
    return set(default_tool_rounds(auto))


def format_tool_rounds_brief(rounds: list[int] | set[int]) -> str:
    items = sorted({int(r) for r in rounds if 1 <= int(r) <= 5})
    return ",".join(str(r) for r in items) if items else "—"


def parse_automation_map_chain(auto: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 ``automation.map_chain``；无效或缺失时回退为单图 ``selected_map`` + ``selected_runs``。

    每项为 ``{"map_id": str, "runs": int, "tool_rounds": list[int]}``。
    """
    global_default = default_tool_rounds(auto)
    raw = auto.get("map_chain")
    if isinstance(raw, list) and raw:
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            mid = str(
                item.get("map_id") or item.get("map") or item.get("id") or ""
            ).strip()
            if not mid:
                continue
            try:
                runs = int(item.get("runs") or item.get("loop_count") or item.get("count") or 1)
            except (TypeError, ValueError):
                runs = 1
            if runs < 1:
                runs = 1
            if "tool_rounds" in item:
                tr = parse_tool_rounds_list(item.get("tool_rounds"))
            else:
                tr = list(global_default)
            out.append({"map_id": mid, "runs": runs, "tool_rounds": tr})
        if out:
            return out

    mid = resolve_automation_map_config_key(auto)
    try:
        runs = int(auto.get("selected_runs") or auto.get("default_runs", 1))
    except (TypeError, ValueError):
        runs = 1
    if runs < 1:
        runs = 1
    return [{"map_id": mid, "runs": runs, "tool_rounds": list(global_default)}]


def automation_run_schedule(
    auto: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, int, int, float]:
    """返回 (map_chain, runs_per_big_cycle, run_cycles, max_runs, cycle_rest_minutes)。

    - ``runs_per_big_cycle``：走完一整条 ``map_chain`` 的总局数；
    - ``run_cycles``：整条链重复次数（大循环）；
    - ``max_runs`` = ``runs_per_big_cycle`` × ``run_cycles``；
    - ``cycle_rest_minutes``：每完成一整条链后的休息分钟数（0 表示不休息）。
    """
    chain = parse_automation_map_chain(auto)
    runs_per_big = sum(int(step["runs"]) for step in chain)
    if runs_per_big < 1:
        runs_per_big = 1

    cycles_raw = auto.get("run_cycles", 1)
    try:
        cycles = int(cycles_raw)
    except (TypeError, ValueError):
        cycles = 1
    if cycles < 1:
        cycles = 1

    try:
        rest_min = float(auto.get("cycle_rest_minutes", 1.0))
    except (TypeError, ValueError):
        rest_min = 1.0
    if rest_min < 0.0:
        rest_min = 0.0

    total = runs_per_big * cycles
    if total < 1:
        total = 1
    return chain, runs_per_big, cycles, total, rest_min


def format_map_chain_plan(
    chain: list[dict[str, Any]],
    maps: dict[str, Any] | None,
    *,
    runs_per_big_cycle: int,
    run_cycles: int,
    max_runs: int,
    cycle_rest_minutes: float,
) -> str:
    """人类可读的运行计划摘要。"""
    maps = maps if isinstance(maps, dict) else {}
    parts: list[str] = []
    for step in chain:
        mid = str(step["map_id"])
        runs = int(step["runs"])
        name = str((maps.get(mid) or {}).get("name") or mid)
        tr = format_tool_rounds_brief(step.get("tool_rounds") or [])
        parts.append(f"{mid}.{name}×{runs}[道具{tr}]")
    chain_desc = " → ".join(parts) if parts else "（空）"
    return (
        f"链式：{chain_desc}；每大循环 {runs_per_big_cycle} 局 × {run_cycles} 轮"
        f" → 合计 {max_runs} 局；大循环间休息 {cycle_rest_minutes:g} 分钟"
        f"（0 表示不休息；否则 ±10% 随机）"
    )
