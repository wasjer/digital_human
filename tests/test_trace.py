"""trace 模块单测：覆盖 API 语义与 no-op 降级行为。"""
import pytest
from core import trace


def test_mark_without_active_turn_is_noop():
    # 没进 turn() 就调 mark，不应抛异常
    trace.mark("任意步骤", summary="x")


def test_event_without_active_turn_is_noop():
    trace.event("llm_call", foo="bar")


def test_current_returns_none_without_active_turn():
    assert trace.current() is None


def test_turn_activates_and_deactivates_trace():
    assert trace.current() is None
    with trace.turn("agent_x", "你好", debug=False):
        t = trace.current()
        assert t is not None
        assert t.agent_id == "agent_x"
        assert t.user_message == "你好"
        assert t.debug is False
        assert t.session_id  # 非空字符串
    # 退出后还原
    assert trace.current() is None


def test_turn_allows_debug_flag():
    with trace.turn("agent_x", "hi", debug=True):
        t = trace.current()
        assert t.debug is True


def test_nested_turns_restore_previous(tmp_path, monkeypatch):
    # 嵌套场景不是 phase A 目标，但 ContextVar 语义必须正确
    with trace.turn("a", "m1"):
        outer = trace.current()
        with trace.turn("b", "m2"):
            assert trace.current() is not outer
        assert trace.current() is outer
