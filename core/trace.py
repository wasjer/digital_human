"""Per-turn trace 模块（Phase A：仅 chat() 链路）。

用法：
    from core import trace
    with trace.turn(agent_id, user_message, debug=args.debug):
        ...
        trace.mark("步骤名", summary="一句话")
        trace.event("llm_call", provider="minimax", ...)
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Optional

_current: ContextVar[Optional[Trace]] = ContextVar("trace", default=None)


@dataclass
class Step:
    name: str
    index: int
    total: int
    elapsed_ms: int
    explicit_summary: str | None
    events: list[dict] = field(default_factory=list)


@dataclass
class Trace:
    """单轮对话的 trace 容器。字段在后续 task 逐步补齐。"""
    agent_id: str
    user_message: str
    session_id: str
    debug: bool
    turn_number: int = 1
    t_start: float = field(default_factory=time.monotonic)
    steps: list[Step] = field(default_factory=list)
    _pending_events: list[dict] = field(default_factory=list)
    _last_mark_ts: float = field(default_factory=time.monotonic)


def current() -> Optional[Trace]:
    return _current.get()


def mark(name: str, summary: str | None = None, total: int = 4) -> None:
    """结束上一步骤；未激活 trace 时 no-op。"""
    t = _current.get()
    if t is None:
        return
    now = time.monotonic()
    elapsed_ms = int((now - t._last_mark_ts) * 1000)
    step = Step(
        name=name,
        index=len(t.steps) + 1,
        total=total,
        elapsed_ms=elapsed_ms,
        explicit_summary=summary,
        events=t._pending_events,
    )
    t.steps.append(step)
    t._pending_events = []
    t._last_mark_ts = now


def event(kind: str, **data) -> None:
    """追加一条事件到当前累积区；未激活 trace 时 no-op。"""
    t = _current.get()
    if t is None:
        return
    t._pending_events.append({"kind": kind, **data})


from datetime import datetime


def _auto_summary(step: Step) -> str:
    if step.explicit_summary is not None:
        return step.explicit_summary
    kinds = {e["kind"] for e in step.events}
    # LLM 步骤（情绪检测 / 对话生成）
    if "llm_call" in kinds:
        llm = next(e for e in step.events if e["kind"] == "llm_call")
        sanitized = llm.get("sanitized") or ""
        return f"reply {len(sanitized)} 字"
    # 检索步骤
    if "vector_search" in kinds:
        vs = next(e for e in step.events if e["kind"] == "vector_search")
        ge = next((e for e in step.events if e["kind"] == "graph_expand"), {})
        rr = next((e for e in step.events if e["kind"] == "score_rerank"), {})
        return (
            f"向量 {vs.get('raw_hits', 0)} / 去重 {vs.get('after_dedup', 0)} / "
            f"图扩展 +{ge.get('neighbors_added', 0)} / 重排 top {rr.get('top_k_returned', 0)}"
        )
    return ""


def _step_extras(step: Step) -> str:
    """(耗时 | token / embed) 尾部括号内容。"""
    elapsed_s = step.elapsed_ms / 1000.0
    parts = [f"{elapsed_s:.1f}s"]
    llm_events = [e for e in step.events if e["kind"] == "llm_call"]
    emb_events = [e for e in step.events if e["kind"] == "embedding"]
    if llm_events:
        pt = sum((e.get("prompt_tokens") or 0) for e in llm_events)
        ct = sum((e.get("completion_tokens") or 0) for e in llm_events)
        tt = sum((e.get("total_tokens") or 0) for e in llm_events)
        if tt:
            if len(llm_events) == 1:
                parts.append(f"tokens {pt}+{ct}→{tt}")
            else:
                parts.append(f"tokens {tt}")
        else:
            parts.append("tokens ?")
    elif emb_events:
        parts.append(f"{len(emb_events)} embed")
    return " | ".join(parts)


def _render_step_line(step: Step) -> str:
    summary = _auto_summary(step)
    extras = _step_extras(step)
    return f"[{step.index}/{step.total}] {step.name:<10} → {summary}    ({extras})"


def _render_header(t: Trace) -> str:
    ts = datetime.now().strftime("%H:%M:%S")
    return f"═══ 轮 {t.turn_number} | agent={t.agent_id} | session={t.session_id} | {ts} ═══"


def _render_footer(t: Trace) -> str:
    total_elapsed_s = time.monotonic() - t.t_start
    all_events = [e for s in t.steps for e in s.events]
    llm_count = sum(1 for e in all_events if e["kind"] == "llm_call")
    total_tokens = sum((e.get("total_tokens") or 0) for e in all_events if e["kind"] == "llm_call")
    tok_text = f"总 token {total_tokens}" if total_tokens else "总 token ?"
    return (
        f"═══ 轮 {t.turn_number} 完成 | 耗时 {total_elapsed_s:.1f}s | "
        f"LLM 调用 {llm_count} 次 | {tok_text} ═══"
    )


def _render_default(t: Trace) -> None:
    print(_render_header(t))
    for s in t.steps:
        print(_render_step_line(s))
    print(_render_footer(t))


@contextmanager
def turn(agent_id: str, user_message: str, debug: bool = False) -> Iterator[Trace]:
    """包一整轮 chat()，进入时激活 trace，退出时结束并渲染。"""
    t = Trace(
        agent_id=agent_id,
        user_message=user_message,
        session_id=_resolve_session_id(agent_id),
        debug=debug,
    )
    token = _current.set(t)
    try:
        yield t
        _render_default(t)
    finally:
        _current.reset(token)


def _resolve_session_id(agent_id: str) -> str:
    """从 L0 buffer 读 session_id（和 L1 写入口径一致）；读不到则临时 UUID。"""
    try:
        from pathlib import Path
        import json
        l0_path = Path(__file__).parent.parent / "data" / "agents" / agent_id / "l0_buffer.json"
        if l0_path.exists():
            sid = json.loads(l0_path.read_text(encoding="utf-8")).get("session_id")
            if sid:
                return sid
    except Exception:
        pass
    return uuid.uuid4().hex[:8]
