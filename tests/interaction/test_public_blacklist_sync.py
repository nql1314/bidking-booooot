# -*- coding: utf-8 -*-
"""腾讯文档公共黑名单同步。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from bidking.interaction import emoji_signal_blacklist as bl
from bidking.interaction import public_blacklist_sync as sync


def test_parse_qq_sheet_url() -> None:
    url = (
        "https://docs.qq.com/sheet/DQ0hQYVVyc1dQbFJH"
        "?u=9d6ba536b7384c059550281daee21ff4&tab=BB08J2"
    )
    assert sync.parse_qq_sheet_url(url) == ("DQ0hQYVVyc1dQbFJH", "BB08J2")


def test_parse_rows_from_sample_blob() -> None:
    blob = (
        "BB08J2汇总表UIDName偷快递884144787915084一切亦虚幻"
        "875279975366633吉爾伽美什"
    ).encode("utf-8")
    rows = sync.parse_public_blacklist_rows_from_sheet_blob(blob)
    assert rows == [
        {"uid": "884144787915084", "name": "一切亦虚幻"},
        {"uid": "875279975366633", "name": "吉爾伽美什"},
    ]


def test_sync_writes_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pub = tmp_path / "emoji_signal_public_blacklist.csv"
    monkeypatch.setattr(bl, "_public_path", lambda: pub)
    sample = (
        "UIDName备注884144787915084一切亦虚幻875279975366633吉爾伽美什"
    ).encode("utf-8")

    def _fake_fetch(*, sheet_id: str, tab: str, timeout: float) -> bytes:
        assert sheet_id == "DQ0hQYVVyc1dQbFJH"
        assert tab == "BB08J2"
        return sample

    monkeypatch.setattr(sync, "_fetch_sheet_chunk_blob", _fake_fetch)
    ok, note = sync.sync_public_blacklist_from_tencent_docs()
    assert ok is True
    assert "2 条" in note
    loaded = bl.load_public_blacklist()
    assert len(loaded) == 2
    assert loaded[0]["uid"] == "884144787915084"


def test_sync_disabled_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def _boom(**_k):
        called["n"] += 1
        raise AssertionError("不应请求网络")

    monkeypatch.setattr(sync, "_fetch_sheet_chunk_blob", _boom)
    ok, note = sync.sync_public_blacklist_from_tencent_docs(
        {"express_emoji_public_blacklist": {"enabled": False}}
    )
    assert ok is True
    assert called["n"] == 0
    assert "已关闭" in note
