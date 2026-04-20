"""Per-turn trace 模块（Phase A：仅 chat() 链路）。

用法：
    from core import trace
    with trace.turn(agent_id, user_message, debug=args.debug):
        ...
        trace.mark("步骤名", summary="一句话")
        trace.event("llm_call", provider="minimax", ...)
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_current: ContextVar[Optional["Trace"]] = ContextVar("trace", default=None)


class Trace:
    """单轮对话的 trace 容器。字段在后续 task 逐步补齐。"""
    pass


def current() -> Optional[Trace]:
    return _current.get()


def mark(name: str, summary: str | None = None, total: int = 4) -> None:
    """结束上一步骤；未激活 trace 时 no-op。"""
    t = _current.get()
    if t is None:
        return
    # 占位：后续 task 实现
    pass


def event(kind: str, **data) -> None:
    """追加一条事件到当前累积区；未激活 trace 时 no-op。"""
    t = _current.get()
    if t is None:
        return
    pass


@contextmanager
def turn(agent_id: str, user_message: str, debug: bool = False):
    """包一整轮 chat()，进入时激活 trace，退出时结束并渲染。"""
    # 占位：后续 task 实现
    yield None
