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


import io
import contextlib


def _render_to_string(t) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        trace._render_default(t)
    return buf.getvalue()


def test_render_default_header_and_footer():
    with trace.turn("agent_x", "你好") as t:
        trace.event("llm_call", total_tokens=47, prompt_tokens=45, completion_tokens=2)
        trace.mark("情绪检测", summary="0.15")
    out = _render_to_string(t)
    # 头部：═══ 轮 1 | agent=agent_x | session=... | HH:MM:SS ═══
    assert out.splitlines()[0].startswith("═══ 轮 1 | agent=agent_x")
    # 脚部
    assert "轮 1 完成" in out
    assert "总 token 47" in out


def test_render_default_step_line_shape():
    with trace.turn("a", "m") as t:
        trace.event("llm_call", total_tokens=47, prompt_tokens=45, completion_tokens=2)
        trace.mark("情绪检测", summary="0.15")
    out = _render_to_string(t)
    # 形如：[1/4] 情绪检测      → 0.15      (0.0s | tokens 45+2→47)
    step_line = [l for l in out.splitlines() if l.startswith("[1/4]")][0]
    assert "→ 0.15" in step_line
    assert "tokens 45+2→47" in step_line


def test_render_auto_summary_for_retrieval_step():
    with trace.turn("a", "m") as t:
        trace.event("embedding", dim=1024)
        trace.event("vector_search", raw_hits=14, after_dedup=14)
        trace.event("graph_expand", neighbors_added=3)
        trace.event("score_rerank", top_k_returned=8)
        trace.mark("记忆检索")  # summary=None → 自动组装
    out = _render_to_string(t)
    step_line = [l for l in out.splitlines() if l.startswith("[1/4]")][0]
    assert "向量 14" in step_line and "去重 14" in step_line
    assert "图扩展 +3" in step_line and "top 8" in step_line


def test_render_auto_summary_for_llm_step():
    with trace.turn("a", "m") as t:
        trace.event("llm_call", sanitized="回复内容", total_tokens=100, prompt_tokens=80, completion_tokens=20)
        trace.mark("对话生成")
    out = _render_to_string(t)
    step_line = [l for l in out.splitlines() if l.startswith("[1/4]")][0]
    assert "reply 4 字" in step_line  # "回复内容" 是 4 字


def test_turn_exit_prints_to_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with trace.turn("a", "m"):
            trace.event("llm_call", total_tokens=10, prompt_tokens=8, completion_tokens=2)
            trace.mark("step1", summary="ok")
    out = buf.getvalue()
    assert "轮 1 完成" in out
