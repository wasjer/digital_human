"""验证 chat_completion 在激活 trace 时 emit llm_call 事件，未激活时无副作用。"""
from unittest.mock import patch, MagicMock
import pytest

from core import trace


def _mock_openai_resp(content="回复", pt=10, ct=5, tt=15):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = pt
    resp.usage.completion_tokens = ct
    resp.usage.total_tokens = tt
    return resp


@patch("core.llm_client._get_chat_client")
def test_chat_completion_emits_llm_call_event(mock_get_client):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_resp()
    mock_get_client.return_value = (client, "mock-model", {}, 1)

    from core.llm_client import chat_completion

    with trace.turn("a", "m") as t:
        chat_completion([{"role": "user", "content": "你好"}], max_tokens=64)
        trace.mark("generate")

    events = t.steps[0].events
    llm = [e for e in events if e["kind"] == "llm_call"]
    assert len(llm) == 1
    assert llm[0]["provider"] in ("deepseek", "minimax", "kimi", "glm", "mock")
    assert llm[0]["model"] == "mock-model"
    assert llm[0]["prompt_tokens"] == 10
    assert llm[0]["completion_tokens"] == 5
    assert llm[0]["total_tokens"] == 15
    assert llm[0]["sanitized"] == "回复"
    assert llm[0]["messages"] == [{"role": "user", "content": "你好"}]
    assert llm[0]["elapsed_ms"] >= 0
    assert llm[0]["attempt"] == 1


@patch("core.llm_client._get_chat_client")
def test_chat_completion_without_trace_is_unaffected(mock_get_client):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_resp(content="x")
    mock_get_client.return_value = (client, "mock-model", {}, 1)

    from core.llm_client import chat_completion

    # 没 turn() 激活，不应抛
    assert chat_completion([{"role": "user", "content": "hi"}]) == "x"


@patch("core.llm_client._get_chat_client")
def test_chat_completion_handles_missing_usage(mock_get_client):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "x"
    resp.usage = None
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    mock_get_client.return_value = (client, "mock-model", {}, 1)

    from core.llm_client import chat_completion
    with trace.turn("a", "m") as t:
        chat_completion([{"role": "user", "content": "hi"}])
        trace.mark("s1")
    llm = t.steps[0].events[0]
    assert llm["prompt_tokens"] is None
    assert llm["total_tokens"] is None


@patch("core.llm_client.urllib.request.urlopen")
def test_get_embedding_emits_embedding_event(mock_urlopen):
    import json as _json
    ctx = MagicMock()
    ctx.__enter__.return_value.read.return_value = _json.dumps(
        {"data": [{"embedding": [0.1] * 1024}]}
    ).encode()
    mock_urlopen.return_value = ctx

    from core.llm_client import get_embedding

    with trace.turn("a", "m") as t:
        get_embedding("你好世界")
        trace.mark("retrieve")

    emb_events = [e for e in t.steps[0].events if e["kind"] == "embedding"]
    assert len(emb_events) == 1
    assert emb_events[0]["dim"] == 1024
    assert emb_events[0]["text_len"] == 4  # "你好世界"
    assert emb_events[0]["elapsed_ms"] >= 0
