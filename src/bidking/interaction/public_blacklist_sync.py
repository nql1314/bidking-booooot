"""启动时从腾讯文档「快递黑名单公共池」汇总表同步公共黑名单 CSV。"""

from __future__ import annotations

import base64
import re
import sys
import threading
import urllib.error
import urllib.request
import zlib
from typing import Any
from urllib.parse import parse_qs, urlparse

_startup_sync_lock = threading.Lock()
_startup_sync_started = False

# 默认：快递黑名单公共池 · 汇总表
# https://docs.qq.com/sheet/DQ0hQYVVyc1dQbFJH?tab=BB08J2
_DEFAULT_SHEET_ID = "DQ0hQYVVyc1dQbFJH"
_DEFAULT_TAB = "BB08J2"
_UID_RE = re.compile(r"^\d{12,20}$")
_TOKEN_RE = re.compile(r"\d{12,20}|[\u4e00-\u9fff]{2,40}|[A-Za-z]{2,20}")


def parse_qq_sheet_url(url: str) -> tuple[str, str]:
    """从腾讯文档表格链接解析 ``(sheet_id, tab)``。"""
    raw = str(url or "").strip()
    if not raw:
        return "", ""
    path = urlparse(raw).path.strip("/")
    sheet_id = ""
    if "/sheet/" in f"/{path}":
        sheet_id = path.rsplit("/", 1)[-1].split("?")[0].strip()
    tab = (parse_qs(urlparse(raw).query).get("tab") or [""])[0].strip()
    return sheet_id, tab


def resolve_public_blacklist_sheet_source(
    config: dict[str, Any] | None,
) -> tuple[str, str, bool]:
    """
    解析同步目标。

    返回 ``(sheet_id, tab, enabled)``。配置段 ``express_emoji_public_blacklist``：
    ``enabled``（默认 true）、``source_url`` / ``url``、``sheet_id``、``tab``。
    """
    branch: dict[str, Any] = {}
    if isinstance(config, dict):
        raw = config.get("express_emoji_public_blacklist")
        if isinstance(raw, dict):
            branch = raw
    if branch.get("enabled") is False:
        return "", "", False
    sheet_id = str(branch.get("sheet_id") or "").strip()
    tab = str(branch.get("tab") or "").strip()
    url = str(branch.get("source_url") or branch.get("url") or "").strip()
    if url:
        parsed_id, parsed_tab = parse_qq_sheet_url(url)
        sheet_id = sheet_id or parsed_id
        tab = tab or parsed_tab
    sheet_id = sheet_id or _DEFAULT_SHEET_ID
    tab = tab or _DEFAULT_TAB
    return sheet_id, tab, True


def _fetch_sheet_chunk_blob(*, sheet_id: str, tab: str, timeout: float) -> bytes:
    url = f"https://docs.qq.com/dop-api/sheet/data?tab={tab}&id={sheet_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://docs.qq.com/sheet/{sheet_id}?tab={tab}",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parts: dict[str, str] = {}
    lines = raw.split("\n")
    i = 0
    while i < len(lines) - 3:
        if lines[i + 1].strip() == "text":
            try:
                int(lines[i + 2])
                parts[lines[i].strip()] = lines[i + 3]
                i += 4
                continue
            except ValueError:
                pass
        i += 1
    prefix = f"chunk_{tab}_"
    blobs: list[bytes] = []
    for key in sorted(parts):
        if not key.startswith(prefix):
            continue
        try:
            blobs.append(zlib.decompress(base64.b64decode(parts[key])))
        except (zlib.error, ValueError, TypeError):
            continue
    if not blobs:
        raise ValueError(f"未在腾讯文档响应中找到工作表 {tab!r} 的数据块")
    return b"".join(blobs)


def _ordered_tokens(blob: bytes) -> list[str]:
    text = blob.decode("utf-8", errors="ignore")
    return _TOKEN_RE.findall(text)


def parse_public_blacklist_rows_from_sheet_blob(blob: bytes) -> list[dict[str, str]]:
    """
    从汇总表压缩块解析 ``uid`` / ``name`` 行。

    表头须含 ``UID``；其后按 ``uid``、``name`` 交替出现（与线上一致）。
    """
    tokens = _ordered_tokens(blob)
    start = 0
    for idx, tok in enumerate(tokens):
        if tok.upper() == "UID":
            start = idx + 1
            break
    rows: list[dict[str, str]] = []
    i = start
    while i < len(tokens):
        uid = tokens[i]
        if not _UID_RE.fullmatch(uid):
            i += 1
            continue
        i += 1
        name = ""
        if i < len(tokens) and not _UID_RE.fullmatch(tokens[i]):
            name = tokens[i]
            i += 1
        rows.append({"uid": uid, "name": name})
    # 去重：同 uid 保留首次
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        uid = str(row.get("uid") or "").strip()
        if uid and uid in seen:
            continue
        if uid:
            seen.add(uid)
        out.append({"uid": uid, "name": str(row.get("name") or "").strip()})
    return out


def _emit_public_blacklist_sync_note(ok: bool, note: str, *, log_prefix: str) -> None:
    if not note:
        return
    print(f"{log_prefix} {note}", file=sys.stderr if not ok else sys.stdout)


def schedule_public_blacklist_sync_on_startup(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
    log_prefix: str = "[bidking]",
) -> None:
    """
    应用启动时在后台拉取公共黑名单（不阻塞 UI，同一进程只发起一次）。

    画板 / Bot 总控 / ``viewer_main`` 启动页应在创建主窗口时调用；
    无需等待用户打开画板或点击「启动 bot」。
    """
    global _startup_sync_started
    with _startup_sync_lock:
        if _startup_sync_started:
            return
        _startup_sync_started = True

    def _worker() -> None:
        try:
            cfg = config
            if cfg is None:
                from bidking.config.runtime import load_runtime

                cfg = load_runtime().raw
            ok, note = sync_public_blacklist_from_tencent_docs(cfg, timeout=timeout)
            _emit_public_blacklist_sync_note(ok, note, log_prefix=log_prefix)
        except Exception as exc:
            print(
                f"{log_prefix} 公共黑名单同步失败（保留本地 CSV）: {exc}",
                file=sys.stderr,
            )

    threading.Thread(
        target=_worker,
        name="public-blacklist-sync",
        daemon=True,
    ).start()


def sync_public_blacklist_from_tencent_docs(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 25.0,
) -> tuple[bool, str]:
    """
    拉取腾讯文档汇总表并写入 ``data/emoji_signal_public_blacklist.csv``。

    返回 ``(成功, 说明)``。失败时不覆盖已有 CSV。
    """
    from .emoji_signal_blacklist import replace_public_blacklist_csv

    sheet_id, tab, enabled = resolve_public_blacklist_sheet_source(config)
    if not enabled:
        return True, "公共黑名单远程同步已关闭（express_emoji_public_blacklist.enabled=false）"
    try:
        blob = _fetch_sheet_chunk_blob(sheet_id=sheet_id, tab=tab, timeout=timeout)
        rows = parse_public_blacklist_rows_from_sheet_blob(blob)
        if not rows:
            return False, f"汇总表 {tab} 未解析到任何 UID 行（请检查表头 UID/Name）"
        n = replace_public_blacklist_csv(rows)
        return True, f"已从腾讯文档同步公共黑名单 {n} 条（sheet={sheet_id} tab={tab}）"
    except urllib.error.URLError as exc:
        return False, f"拉取腾讯文档失败（保留本地 CSV）: {exc}"
    except Exception as exc:
        return False, f"解析腾讯文档失败（保留本地 CSV）: {exc}"
