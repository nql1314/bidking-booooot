# -*- coding: utf-8 -*-
"""
与画板快照同目录的客户端配置（如 bot 用的 ``self_user_uid``），供 getlog 写入 ``board_snapshot`` 的 ``aisha_client`` 块。

默认文件名 ``getlog_client.json``，与 ``DEFAULT_BOARD_SNAPSHOT_PATH`` 所在目录并列放置。
示例::

    {"self_user_uid": "123456", "self_name_substring": ""}
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


def sanitize_aisha_client_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """仅保留写入快照的安全字段。"""
    uid = str(raw.get("self_user_uid") or "").strip()
    hint = str(raw.get("self_name_substring") or "").strip()
    out: Dict[str, Any] = {}
    if uid:
        out["self_user_uid"] = uid
    if hint:
        out["self_name_substring"] = hint
    return out
