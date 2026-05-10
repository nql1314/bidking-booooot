# -*- coding: utf-8 -*-
"""
与画板快照同目录的 ``getlog_client.json``（可选）。

历史用途为向快照写入己方 UID；当前 Ahmad 主价等逻辑已改读 ``configs/config.json`` 中的
``board_snapshot.self_user_uid``。本模块仍可供其它工具读取同级 JSON。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

CLIENT_JSON_NAME = "getlog_client.json"


def load_client_settings_beside_snapshot(snapshot_path: Optional[str]) -> Dict[str, Any]:
    """读取快照路径同级目录下的 ``getlog_client.json``；不存在或无效时返回空 dict。"""
    if not snapshot_path or not str(snapshot_path).strip():
        return {}
    path = Path(snapshot_path).expanduser().resolve().parent / CLIENT_JSON_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def sanitize_snapshot_self_identity(raw: Dict[str, Any]) -> Dict[str, Any]:
    """仅保留可写入 ``board_snapshot`` 根级的己方标识字段。"""
    uid = str(raw.get("self_user_uid") or "").strip()
    hint = str(raw.get("self_name_substring") or "").strip()
    out: Dict[str, Any] = {}
    if uid:
        out["self_user_uid"] = uid
    if hint:
        out["self_name_substring"] = hint
    return out
