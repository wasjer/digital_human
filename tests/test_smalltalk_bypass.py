"""轻量寒暄旁路：smalltalk/farewell 应跳过 retrieve，substantive 走原流程。"""
from unittest.mock import MagicMock, patch

from core import dialogue


def _fake_retrieve(*args, **kwargs):
    return {
        "soul_anchor": "", "current_state": "", "working_context": "",
        "l2_patterns": "", "relevant_memories": [], "surfaced_ids": [],
    }


def test_hardcoded_hello_bypasses_retrieve():
    """硬编码关键词 "你好" 应直接短路，不调用 retrieve。"""
    retrieve_called = {"n": 0}

    def tracking_retrieve(*a, **kw):
        retrieve_called["n"] += 1
        return _fake_retrieve()

    with patch("core.dialogue.retrieve", side_effect=tracking_retrieve), \
         patch("core.dialogue.chat_completion", return_value="你好呀"), \
         patch("core.dialogue._load_l0", return_value=dialogue._empty_l0("a1")), \
         patch("core.dialogue._save_l0"):
        r = dialogue.chat("a1", "你好", [])

    assert retrieve_called["n"] == 0, "smalltalk 应跳过 retrieve"
    assert r["reply"]


def test_substantive_input_still_calls_retrieve():
    retrieve_called = {"n": 0}

    def tracking_retrieve(*a, **kw):
        retrieve_called["n"] += 1
        return _fake_retrieve()

    with patch("core.dialogue.retrieve", side_effect=tracking_retrieve), \
         patch("core.dialogue.chat_completion", return_value="这是实质回复"), \
         patch("core.dialogue._load_l0", return_value=dialogue._empty_l0("a1")), \
         patch("core.dialogue._save_l0"), \
         patch("core.dialogue._classify_smalltalk", return_value="substantive"):
        dialogue.chat("a1", "我最近被工作压垮了，觉得一切都没意义", [])

    assert retrieve_called["n"] == 1
