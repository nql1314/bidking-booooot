"""Bot 启动门禁：从 OSS ``bot.config`` 读取 ``enable`` / ``msg`` / ``banner``。"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bidking.tools.tencent_sheet_v3 import (
    log_http_exchange,
    resolve_tencent_sheet_v3_log_path,
    summarize_for_request_log,
)

_DEFAULT_OFFLINE_HINT = "Bot已下线，暂时不可使用"
# 常见非标准空白（含 NBSP、全角空格、零宽等）→ 普通空格，便于 ``json.loads``
_NON_STANDARD_SPACES = (
    "\u00a0",
    "\u1680",
    "\u2000",
    "\u2001",
    "\u2002",
    "\u2003",
    "\u2004",
    "\u2005",
    "\u2006",
    "\u2007",
    "\u2008",
    "\u2009",
    "\u200a",
    "\u202f",
    "\u205f",
    "\u3000",
    "\ufeff",
)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_cached_status: BotGateStatus | None = None


class BotStartupBlocked(RuntimeError):
    """远程开关禁止启动。"""


@dataclass(frozen=True)
class BotGateStatus:
    """远程开关与公告（启动阶段拉取后缓存）。"""

    allowed: bool
    message: str
    banner: str
    fetch_ok: bool

    @property
    def offline_hint(self) -> str:
        return self.message or _DEFAULT_OFFLINE_HINT


def _obfuscated_bot_config_url() -> str:
    """默认 OSS 地址（分段拼接，避免单处明文）。"""
    scheme = chr(104) + chr(116) + chr(116) + chr(112) + chr(115)
    bucket = bytes((98, 105, 100, 107, 105, 110, 103, 45, 98, 117, 100, 100, 121)).decode()
    region = (
        ".oss-cn-shanghai"
        + ".aliyuncs"
        + ".com"
    )
    return f"{scheme}://{bucket}{region}/bot.config"


def resolve_bot_gate_config_url(config: dict[str, Any] | None) -> str:
    """
    解析 ``bot.config`` 拉取地址。

    配置项 ``bot_gate.config_url`` / ``bot_gate.url``；未配置则用内置默认 OSS
    （``bidking-buddy.oss-cn-shanghai.aliyuncs.com/bot.config``）。
    """
    branch = (config or {}).get("bot_gate")
    if isinstance(branch, dict):
        raw = str(
            branch.get("config_url") or branch.get("url") or ""
        ).strip()
        if raw:
            return raw
    return _obfuscated_bot_config_url()


def resolve_bot_gate_request_log_path(
    config: dict[str, Any] | None = None,
) -> Path | None:
    """
    Bot 配置请求日志路径。

    优先 ``bot_gate.request_log*``，否则与 ``sheet_merge.openapi`` 共用
    ``logs/tencent_sheet_v3.log``。
    """
    branch = (config or {}).get("bot_gate")
    if isinstance(branch, dict):
        if branch.get("request_log") is False:
            return None
        raw = str(branch.get("request_log_path") or "").strip()
        if raw:
            p = Path(raw).expanduser()
            if p.is_absolute():
                return p.resolve()
            from bidking.config.paths import project_root

            return (project_root() / p).resolve()
    openapi: dict[str, Any] | None = None
    sheet_merge = (config or {}).get("sheet_merge")
    if isinstance(sheet_merge, dict):
        cand = sheet_merge.get("openapi")
        if isinstance(cand, dict):
            openapi = cand
    return resolve_tencent_sheet_v3_log_path(openapi)


def normalize_gate_text(text: str) -> str:
    raw = str(text or "")
    for ch in _NON_STANDARD_SPACES:
        raw = raw.replace(ch, " ")
    return raw


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    """从混杂正文中按花括号配对提取 JSON 对象。"""
    raw = normalize_gate_text(text)
    objects: list[dict[str, Any]] = []
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        closed_at: int | None = None
        for j in range(i, n):
            ch = raw[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    closed_at = j
                    break
        if closed_at is None:
            i += 1
            continue
        chunk = raw[i : closed_at + 1]
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
        i = closed_at + 1
    return objects


def parse_bot_gate_payload(text: str) -> dict[str, Any] | None:
    """解析含 ``enable`` 字段的 JSON。"""
    raw = normalize_gate_text(text).strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "enable" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    for obj in _extract_json_objects(raw):
        if "enable" in obj:
            return obj
    return None


def _summarize_gate_response(text: str) -> dict[str, Any]:
    payload = parse_bot_gate_payload(text)
    summary: dict[str, Any] = {"body_chars": len(text)}
    if payload is not None:
        summary["gate"] = summarize_for_request_log(payload)
    else:
        summary["gate"] = None
    return summary


def _parse_enable(value: Any) -> bool:
    if value is True:
        return True
    if value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _status_from_payload(payload: dict[str, Any] | None, *, fetch_ok: bool) -> BotGateStatus:
    if not payload:
        return BotGateStatus(
            allowed=False,
            message=_DEFAULT_OFFLINE_HINT,
            banner="",
            fetch_ok=fetch_ok,
        )
    allowed = _parse_enable(payload.get("enable"))
    msg = str(payload.get("msg") or "").strip()
    banner = str(payload.get("banner") or "").strip()
    if allowed:
        return BotGateStatus(
            allowed=True,
            message="",
            banner=banner,
            fetch_ok=True,
        )
    return BotGateStatus(
        allowed=False,
        message=msg or _DEFAULT_OFFLINE_HINT,
        banner=banner,
        fetch_ok=True,
    )


def fetch_bot_gate_remote_text(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
) -> str:
    """拉取 OSS ``bot.config`` 正文。"""
    url = resolve_bot_gate_config_url(config)
    headers = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*"}
    log_path = resolve_bot_gate_request_log_path(config)
    req = urllib.request.Request(url, headers=headers, method="GET")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        log_http_exchange(
            log_path,
            tag="bot-gate-config",
            method="GET",
            url=url,
            headers=headers,
            status=f"HTTP {exc.code}",
            response={"body_chars": len(detail), "preview": detail[:240]},
            elapsed_ms=elapsed_ms,
            error=detail[:500] if detail else str(exc),
        )
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        log_http_exchange(
            log_path,
            tag="bot-gate-config",
            method="GET",
            url=url,
            headers=headers,
            status="error",
            response=None,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )
        raise
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log_http_exchange(
        log_path,
        tag="bot-gate-config",
        method="GET",
        url=url,
        headers=headers,
        status="ok",
        response=_summarize_gate_response(raw),
        elapsed_ms=elapsed_ms,
    )
    return raw


def load_bot_gate_status(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
) -> BotGateStatus:
    """拉取并解析远程开关（不读写缓存）。"""
    try:
        text = fetch_bot_gate_remote_text(config, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return BotGateStatus(
            allowed=False,
            message=_DEFAULT_OFFLINE_HINT,
            banner="",
            fetch_ok=False,
        )
    payload = parse_bot_gate_payload(text)
    if payload is None:
        return BotGateStatus(
            allowed=False,
            message=_DEFAULT_OFFLINE_HINT,
            banner="",
            fetch_ok=False,
        )
    return _status_from_payload(payload, fetch_ok=True)


def prime_bot_gate_cache(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
    force: bool = False,
) -> BotGateStatus:
    """程序启动阶段调用：拉取远程配置并写入进程内缓存。"""
    global _cached_status
    if _cached_status is not None and not force:
        return _cached_status
    _cached_status = load_bot_gate_status(config, timeout=timeout)
    return _cached_status


def get_bot_gate_status() -> BotGateStatus | None:
    """返回已缓存状态；未 ``prime`` 时为 ``None``。"""
    return _cached_status


def ensure_bot_startup_allowed(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
) -> BotGateStatus:
    """
    使用启动阶段缓存；若尚未 ``prime`` 则拉取一次。

    不允许启动时抛出 :class:`BotStartupBlocked`。
    """
    status = _cached_status
    if status is None:
        status = prime_bot_gate_cache(config, timeout=timeout)
    if status.allowed:
        return status
    raise BotStartupBlocked(status.offline_hint)


def exit_if_bot_startup_blocked(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
) -> BotGateStatus:
    """打印提示并以退出码 1 结束进程（CLI）。"""
    try:
        return ensure_bot_startup_allowed(config, timeout=timeout)
    except BotStartupBlocked as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def reset_bot_gate_cache_for_tests() -> None:
    """仅测试：清空缓存。"""
    global _cached_status
    _cached_status = None
