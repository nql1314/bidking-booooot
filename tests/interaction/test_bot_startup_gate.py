# -*- coding: utf-8 -*-
"""Bot 启动门禁。"""

from __future__ import annotations

import pytest

from bidking.interaction import bot_startup_gate as gate


@pytest.fixture(autouse=True)
def _clear_gate_cache() -> None:
    gate.reset_bot_gate_cache_for_tests()
    yield
    gate.reset_bot_gate_cache_for_tests()


def test_parse_compact_json() -> None:
    text = '{"enable":false,"msg":"Bot已下线，暂时不可使用"}'
    obj = gate.parse_bot_gate_payload(text)
    assert obj == {"enable": False, "msg": "Bot已下线，暂时不可使用"}


def test_parse_pretty_json_with_nbsp() -> None:
    text = """
    {
        "enable":\u00a0true,
        "msg": "Bot正常上线",
        "banner": "2群1076496131 有问题先检查操作顺序"
    }
    """
    obj = gate.parse_bot_gate_payload(text)
    assert obj is not None
    assert obj["enable"] is True
    assert "1076496131" in obj["banner"]


def test_status_enable_true_with_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = """
    {
        "enable": true,
        "msg": "Bot正常上线",
        "banner": "测试公告"
    }
    """
    monkeypatch.setattr(gate, "fetch_bot_gate_remote_text", lambda *_a, **_k: sample)
    st = gate.load_bot_gate_status()
    assert st.allowed is True
    assert st.banner == "测试公告"
    assert st.fetch_ok is True


def test_status_enable_false_uses_msg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate,
        "fetch_bot_gate_remote_text",
        lambda *_a, **_k: '{"enable":false,"msg":"维护中"}',
    )
    st = gate.load_bot_gate_status()
    assert st.allowed is False
    assert st.message == "维护中"


def test_status_fetch_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a, **_k):
        raise OSError("network down")

    monkeypatch.setattr(gate, "fetch_bot_gate_remote_text", _boom)
    st = gate.load_bot_gate_status()
    assert st.allowed is False
    assert st.message == gate._DEFAULT_OFFLINE_HINT
    assert st.fetch_ok is False


def test_prime_cache_single_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _fetch(*_a, **_k):
        calls["n"] += 1
        return '{"enable":true,"msg":"","banner":"A"}'

    monkeypatch.setattr(gate, "fetch_bot_gate_remote_text", _fetch)
    gate.prime_bot_gate_cache()
    gate.ensure_bot_startup_allowed()
    assert calls["n"] == 1
    assert gate.get_bot_gate_status() is not None
    assert gate.get_bot_gate_status().banner == "A"


def test_ensure_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate,
        "fetch_bot_gate_remote_text",
        lambda *_a, **_k: '{"enable":false,"msg":"已停服"}',
    )
    gate.prime_bot_gate_cache()
    with pytest.raises(gate.BotStartupBlocked, match="已停服"):
        gate.ensure_bot_startup_allowed()


def test_default_config_url() -> None:
    url = gate.resolve_bot_gate_config_url(None)
    assert url == gate._obfuscated_bot_config_url()
    assert "bidking-buddy.oss-cn-shanghai.aliyuncs.com" in url
    assert url.endswith("/bot.config")


def test_config_url_override() -> None:
    custom = "https://example.com/bot.config"
    assert gate.resolve_bot_gate_config_url(
        {"bot_gate": {"config_url": custom}}
    ) == custom


def test_resolve_bot_gate_request_log_disabled() -> None:
    assert (
        gate.resolve_bot_gate_request_log_path({"bot_gate": {"request_log": False}})
        is None
    )


def test_fetch_bot_gate_logs_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[dict] = []

    def _capture(log_path, **kwargs):
        logged.append({"path": log_path, **kwargs})

    monkeypatch.setattr(gate, "resolve_bot_gate_request_log_path", lambda *_a, **_k: None)
    monkeypatch.setattr(gate, "log_http_exchange", _capture)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return '{"enable":true,"msg":"","banner":"hi"}'.encode()

    monkeypatch.setattr(gate.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    text = gate.fetch_bot_gate_remote_text()
    assert "enable" in text
    assert len(logged) == 1
    assert logged[0]["tag"] == "bot-gate-config"
    assert logged[0]["status"] == "ok"
    assert logged[0]["response"]["gate"]["enable"] is True
