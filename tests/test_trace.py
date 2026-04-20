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


def test_mark_accumulates_steps():
    with trace.turn("a", "m") as t:
        trace.mark("情绪检测", summary="0.15")
        trace.mark("记忆检索", summary="向量 14 / top 8")
        assert len(t.steps) == 2
        assert t.steps[0].name == "情绪检测"
        assert t.steps[0].index == 1
        assert t.steps[0].total == 4
        assert t.steps[0].explicit_summary == "0.15"
        assert t.steps[0].elapsed_ms >= 0
        assert t.steps[1].index == 2


def test_mark_without_summary_leaves_none():
    with trace.turn("a", "m") as t:
        trace.mark("记忆检索")
        assert t.steps[0].explicit_summary is None


def test_events_between_marks_attach_to_next_step():
    with trace.turn("a", "m") as t:
        trace.event("llm_call", provider="minimax", total_tokens=47)
        trace.mark("情绪检测")
        # 第二批
        trace.event("vector_search", raw_hits=14, after_dedup=14)
        trace.event("graph_expand", neighbors_added=3)
        trace.mark("记忆检索")

    assert len(t.steps[0].events) == 1
    assert t.steps[0].events[0]["kind"] == "llm_call"
    assert t.steps[0].events[0]["total_tokens"] == 47
    assert len(t.steps[1].events) == 2
    assert {e["kind"] for e in t.steps[1].events} == {"vector_search", "graph_expand"}


def test_event_before_any_mark_still_attaches_to_first_step():
    with trace.turn("a", "m") as t:
        trace.event("llm_call", provider="x")
        trace.mark("step1")
        assert len(t.steps[0].events) == 1
