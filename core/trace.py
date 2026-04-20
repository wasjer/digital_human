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
    pass


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
