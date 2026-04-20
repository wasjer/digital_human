# Chat Trace Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `main_chat` 每轮对话的 LLM 输入/输出、检索各层命中、token 用量以"解说式链路"呈现；默认模式每轮 ~8 行摘要；`--debug` 模式在控制台展开子项并完整落盘到 `logs/sessions/<session_id>.md`。

**Architecture:** 新增 `core/trace.py`，基于 `contextvars.ContextVar` 的 per-turn trace 容器。业务文件（dialogue / retrieval / llm_client）通过**模块级 `trace.mark()` / `trace.event()` 函数**打点，未激活时自动 no-op（调用处不写 `if` 判空）。`main_chat.py` 外层一个 `with trace.turn(...)` 启停 trace。Phase A 仅覆盖 `chat()` 链路，`make_decision` / `end_session` / `seed_builder` 不动。

**Tech Stack:** Python 3.10+（用 `contextvars` / PEP 604 `X | Y` 类型注解，仓库现有代码已在用），pytest，标准库 logging，无新依赖。

**Spec 参考：** `docs/superpowers/specs/2026-04-20-chat-trace-logging-design.md`

---

## File Structure

**Create:**
- `core/trace.py` — trace 模块：`Trace` 类、`turn()` 上下文管理器、`mark()` / `event()` / `current()` 模块级函数、默认/debug 渲染器
- `tests/test_trace.py` — trace 模块纯单测（无外部依赖）
- `tests/test_chat_trace_integration.py` — 用 mock 的 LLM/检索覆盖 `chat()` 插桩链路

**Modify:**
- `core/llm_client.py` — 1) 修 logger format 硬编码；2) 静音 httpx / openai；3) `chat_completion` / `get_embedding` 捕获 usage、耗时、raw，emit `trace.event`；4) 降部分 INFO 到 DEBUG
- `core/retrieval.py` — 在 embedding / vector / graph_expand / score_rerank 4 个阶段 emit `trace.event`
- `core/dialogue.py` — `chat()` 里 4 处调用 `trace.mark`
- `main_chat.py` — argparse 加 `--debug`；每轮 `chat()` 调用外包 `with trace.turn(...)`

**Runtime-created:**
- `logs/sessions/` 目录（首次 debug 模式启动时由 `trace.py` 自动 `mkdir`）

---

## Task 1: 建立 `core/trace.py` 最小骨架与模块级 no-op API

**Files:**
- Create: `core/trace.py`
- Create: `tests/test_trace.py`

- [ ] **Step 1: 写失败测试（no-op 契约）**

创建 `tests/test_trace.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace.py -v`
Expected: `ModuleNotFoundError: No module named 'core.trace'`

- [ ] **Step 3: 实现最小骨架**

创建 `core/trace.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add core/trace.py tests/test_trace.py
git commit -m "feat(trace): add trace module skeleton with no-op API"
```

---

## Task 2: 实现 `Trace` 类与 `turn()` 上下文管理器

**Files:**
- Modify: `core/trace.py`
- Modify: `tests/test_trace.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_trace.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace.py -v`
Expected: 3 new tests fail (`AttributeError` on `Trace` fields, or assertion errors)

- [ ] **Step 3: 实现 `Trace` 类与 `turn()` 激活逻辑**

替换 `core/trace.py` 中的 `Trace` 类和 `turn()`：

```python
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Trace:
    agent_id: str
    user_message: str
    session_id: str
    debug: bool
    turn_number: int = 1
    t_start: float = field(default_factory=time.monotonic)


@contextmanager
def turn(agent_id: str, user_message: str, debug: bool = False):
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
```

导入补齐（文件顶部）：

```python
import time
import uuid
from dataclasses import dataclass, field
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add core/trace.py tests/test_trace.py
git commit -m "feat(trace): Trace dataclass + turn() context manager"
```

---

## Task 3: 实现 `mark()` 与 Step 累积

**Files:**
- Modify: `core/trace.py`
- Modify: `tests/test_trace.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_trace.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace.py -v`
Expected: 2 new tests fail

- [ ] **Step 3: 实现 `Step` dataclass + `mark()` 逻辑**

在 `core/trace.py` 里 `Trace` 之前插入 `Step`，并修改 `Trace` 和 `mark`：

```python
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
    agent_id: str
    user_message: str
    session_id: str
    debug: bool
    turn_number: int = 1
    t_start: float = field(default_factory=time.monotonic)
    steps: list[Step] = field(default_factory=list)
    _pending_events: list[dict] = field(default_factory=list)
    _last_mark_ts: float = field(default_factory=time.monotonic)


def mark(name: str, summary: str | None = None, total: int = 4) -> None:
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add core/trace.py tests/test_trace.py
git commit -m "feat(trace): mark() builds Step list with elapsed timing"
```

---

## Task 4: 实现 `event()` 累积与附着到 Step

**Files:**
- Modify: `core/trace.py`
- Modify: `tests/test_trace.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_trace.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace.py -v`
Expected: 2 new tests fail

- [ ] **Step 3: 实现 `event()` 累积**

替换 `core/trace.py` 中的 `event()`：

```python
def event(kind: str, **data) -> None:
    t = _current.get()
    if t is None:
        return
    t._pending_events.append({"kind": kind, **data})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add core/trace.py tests/test_trace.py
git commit -m "feat(trace): event() accumulates to pending buffer, flushes on mark()"
```

---

## Task 5: 默认模式控制台渲染器

**Files:**
- Modify: `core/trace.py`
- Modify: `tests/test_trace.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_trace.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace.py -v`
Expected: 5 new tests fail

- [ ] **Step 3: 实现渲染器 + `turn()` 退出时调用**

在 `core/trace.py` 末尾追加渲染逻辑：

```python
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
```

修改 `turn()` 让退出时调用渲染：

```python
@contextmanager
def turn(agent_id: str, user_message: str, debug: bool = False):
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add core/trace.py tests/test_trace.py
git commit -m "feat(trace): default-mode renderer (header/step/footer) on turn exit"
```

---

## Task 6: Debug 模式 — markdown 落盘 + 控制台展开

**Files:**
- Modify: `core/trace.py`
- Modify: `tests/test_trace.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_trace.py` 末尾追加：

```python
from pathlib import Path


def test_debug_mode_writes_markdown_file(tmp_path, monkeypatch):
    # 指向 tmp 目录
    monkeypatch.setattr(trace, "_SESSIONS_DIR", tmp_path)

    with trace.turn("agent_x", "你好", debug=True) as t:
        trace.event("llm_call",
                    provider="minimax", model="minimax-m2.7-highspeed",
                    messages=[{"role": "user", "content": "你好"}],
                    raw="hi", sanitized="hi",
                    prompt_tokens=5, completion_tokens=2, total_tokens=7,
                    effective_max_tokens=8192, elapsed_ms=1200, attempt=1)
        trace.mark("情绪检测", summary="0.1")

    md_path = tmp_path / f"{t.session_id}.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "## 轮 1" in content
    assert "### [1/4] 情绪检测" in content
    assert "provider" in content and "minimax" in content
    # raw / sanitized 都应出现
    assert "hi" in content


def test_debug_mode_console_shows_subitems(capsys):
    with trace.turn("a", "m", debug=True) as t:
        trace.event("embedding", dim=1024, elapsed_ms=900)
        trace.event("vector_search", raw_hits=14, after_dedup=14, limit=20, elapsed_ms=230)
        trace.event("graph_expand", neighbors_added=3, top5_ids=["a", "b"])
        trace.event("score_rerank", top_k_returned=8,
                    weights={"relevance": 0.35, "importance": 0.20})
        trace.mark("记忆检索")
    out = capsys.readouterr().out
    # 主行仍在
    assert "[1/4] 记忆检索" in out
    # debug 子项用 ├ / └ 前缀
    assert "├" in out or "└" in out
    assert "dim=1024" in out
    assert "raw_hits=14" in out


def test_non_debug_mode_does_not_write_file(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "_SESSIONS_DIR", tmp_path)
    with trace.turn("a", "m", debug=False):
        trace.event("llm_call", total_tokens=10)
        trace.mark("s1", summary="x")
    # tmp_path 不应有任何文件
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace.py -v`
Expected: 3 new tests fail

- [ ] **Step 3: 实现 debug 模式落盘与控制台展开**

在 `core/trace.py` 顶部附近加：

```python
_SESSIONS_DIR = Path(__file__).parent.parent / "logs" / "sessions"
```

`Path` 导入补齐：

```python
from pathlib import Path
```

在 `_render_default` 之后加 debug 渲染器：

```python
def _render_event_subline(e: dict) -> str:
    """debug 模式下一条 event 的缩进子行。"""
    kind = e["kind"]
    # 取前几个主要字段，尾端 truncate 到可读
    data = {k: v for k, v in e.items() if k != "kind"}
    # messages / raw / sanitized 太长，在控制台折叠成长度标记
    compact = {}
    for k, v in data.items():
        if k in ("messages", "raw", "sanitized"):
            if isinstance(v, str):
                compact[k] = f"<{len(v)} 字>"
            elif isinstance(v, list):
                compact[k] = f"<{len(v)} 条消息>"
        else:
            compact[k] = v
    body = " ".join(f"{k}={v}" for k, v in compact.items())
    return f"  ├ {kind:<14} {body}"


def _render_debug_console(t: Trace) -> None:
    print(_render_header(t))
    for s in t.steps:
        print(_render_step_line(s))
        for e in s.events:
            print(_render_event_subline(e))
    print(_render_footer(t))


def _fence(lang: str, body: str) -> str:
    return f"```{lang}\n{body}\n```"


def _render_markdown_turn(t: Trace) -> str:
    """一轮对话的 markdown 片段，追加写入 session 文件。"""
    lines: list[str] = []
    ts = datetime.now().strftime("%H:%M:%S")
    total_elapsed_s = time.monotonic() - t.t_start
    lines.append(f"## 轮 {t.turn_number} ({ts}, 耗时 {total_elapsed_s:.1f}s)\n")
    lines.append(f"**用户输入**：{t.user_message}\n")

    for s in t.steps:
        summary = _auto_summary(s)
        extras = _step_extras(s)
        lines.append(f"### [{s.index}/{s.total}] {s.name} → {summary} ({extras})\n")
        for e in s.events:
            if e["kind"] == "llm_call":
                lines.append(
                    f"**provider**: {e.get('provider')} | **model**: {e.get('model')} | "
                    f"**usage**: prompt={e.get('prompt_tokens')} "
                    f"completion={e.get('completion_tokens')} total={e.get('total_tokens')}\n"
                )
                msgs = e.get("messages") or []
                if msgs:
                    body = "\n".join(
                        f"[{i}] {m.get('role','')} ({len(m.get('content',''))} 字):\n{m.get('content','')}"
                        for i, m in enumerate(msgs)
                    )
                    lines.append("#### messages\n" + _fence("", body) + "\n")
                if e.get("raw") is not None:
                    lines.append("#### raw response\n" + _fence("", str(e["raw"])) + "\n")
                if e.get("sanitized") is not None:
                    lines.append("#### sanitized\n" + _fence("", str(e["sanitized"])) + "\n")
            else:
                fields = " ".join(f"{k}={v!r}" for k, v in e.items() if k != "kind")
                lines.append(f"- **{e['kind']}**: {fields}\n")

    all_events = [e for s in t.steps for e in s.events]
    llm_count = sum(1 for e in all_events if e["kind"] == "llm_call")
    emb_count = sum(1 for e in all_events if e["kind"] == "embedding")
    total_tokens = sum((e.get("total_tokens") or 0) for e in all_events if e["kind"] == "llm_call")
    lines.append(
        f"---\n轮 {t.turn_number} 小结：LLM {llm_count} 次 / embed {emb_count} 次 / "
        f"总 token {total_tokens or '?'} / 耗时 {total_elapsed_s:.1f}s\n"
    )
    return "\n".join(lines)


def _write_markdown(t: Trace) -> Path:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _SESSIONS_DIR / f"{t.session_id}.md"
    # 首轮写文件头
    if not md_path.exists():
        header = (
            f"# Session {t.session_id} (agent={t.agent_id})\n"
            f"开始于 {datetime.now().isoformat(timespec='seconds')}\n\n"
        )
        md_path.write_text(header, encoding="utf-8")
    with md_path.open("a", encoding="utf-8") as f:
        f.write(_render_markdown_turn(t))
        f.write("\n")
    return md_path
```

修改 `turn()` 根据 `debug` 分流渲染：

```python
@contextmanager
def turn(agent_id: str, user_message: str, debug: bool = False):
    t = Trace(
        agent_id=agent_id,
        user_message=user_message,
        session_id=_resolve_session_id(agent_id),
        debug=debug,
    )
    token = _current.set(t)
    try:
        yield t
        if debug:
            _render_debug_console(t)
            _write_markdown(t)
        else:
            _render_default(t)
    finally:
        _current.reset(token)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add core/trace.py tests/test_trace.py
git commit -m "feat(trace): debug mode console expansion + markdown session file"
```

---

## Task 7: 清理 `core/llm_client.py` 噪音日志

**Files:**
- Modify: `core/llm_client.py:14-20`（format + basicConfig）
- Modify: `core/llm_client.py:133-146`（`_retry` 内 INFO）
- Modify: `core/llm_client.py:162-178`（`chat_completion` 内 INFO）
- Modify: `core/llm_client.py:201-202`（`get_embedding` 内 INFO）

这个 task 只做降噪，不动业务逻辑；下一 task 才加 trace 插桩。降噪后跑 `pytest tests/` 应该看不到 `HTTP Request: POST ...` 行。

- [ ] **Step 1: 写失败测试：验证 httpx / openai logger 被静音**

在 `tests/test_llm_sanitize.py` 末尾追加（利用现有测试文件，避免新增）：

```python
import logging


def test_httpx_logger_at_warning_level():
    import core.llm_client  # noqa: F401，触发模块加载
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_openai_logger_at_warning_level():
    import core.llm_client  # noqa: F401
    assert logging.getLogger("openai").level >= logging.WARNING


def test_llm_client_log_format_uses_name():
    # basicConfig 的 format 字符串必须包含 %(name)s，而不是硬编码 "llm_client"
    import core.llm_client as c
    root = logging.getLogger()
    # 找到 StreamHandler 的 formatter
    fmt = None
    for h in root.handlers:
        if h.formatter is not None:
            fmt = h.formatter._fmt
            break
    assert fmt is not None
    assert "%(name)s" in fmt
    assert "llm_client %(" not in fmt  # 不能硬编码
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_llm_sanitize.py -v`
Expected: 3 new tests fail

- [ ] **Step 3: 修改 `core/llm_client.py`**

定位 `core/llm_client.py:14-20`，替换为：

```python
# ── 日志配置 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logger = logging.getLogger("llm_client")
```

定位 `_retry` 函数，把 success 日志降到 DEBUG：

```python
def _retry(fn, operation: str, max_retries: int = 3, base_delay: float = 2.0):
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            logger.debug(f"{operation} success attempt={attempt}")
            return result
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"{operation} failed after {max_retries} attempts error={e}")
                raise
            delay = base_delay ** attempt
            logger.warning(f"{operation} attempt={attempt} error={e} retry_in={delay}s")
            time.sleep(delay)
```

定位 `chat_completion`，把 `max_tokens` 调整 INFO 和结果 INFO 降到 DEBUG：

```python
def chat_completion(
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    def _call():
        client, model, extra_body, token_mul = _get_chat_client()
        effective_max = min(max_tokens * token_mul, config.LLM_MAX_OUTPUT_TOKENS)
        if effective_max != max_tokens:
            logger.debug(
                f"chat_completion max_tokens={max_tokens}x{token_mul}->{effective_max} "
                f"(provider reasoning budget)"
            )
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=effective_max,
            temperature=temperature,
            extra_body=extra_body or None,
        )
        return resp.choices[0].message.content

    result_raw = _retry(_call, operation="chat_completion")
    result = _sanitize(result_raw)
    trimmed = (len(result_raw) if result_raw else 0) - len(result)
    logger.debug(f"chat_completion result_len={len(result)} sanitize_trimmed={trimmed}")
    return result
```

定位 `get_embedding`，把 dim 日志降到 DEBUG：

```python
    result = _retry(_call, operation="get_embedding", max_retries=5)
    logger.debug(f"get_embedding dim={len(result)}")
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_llm_sanitize.py -v`
Expected: 14 passed（原 11 + 新 3）

- [ ] **Step 5: Commit**

```bash
git add core/llm_client.py tests/test_llm_sanitize.py
git commit -m "chore(llm_client): silence httpx/openai, drop debug-level noise, fix format"
```

---

## Task 8: `chat_completion` 捕获 usage 并 emit `trace.event("llm_call", ...)`

**Files:**
- Modify: `core/llm_client.py`（imports + `chat_completion`）
- Create: `tests/test_chat_completion_trace.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_chat_completion_trace.py`：

```python
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
    assert llm[0]["provider"] in ("deepseek", "minimax", "kimi", "glm", "mock")  # 实际由 LLM_PROVIDER 决定
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_chat_completion_trace.py -v`
Expected: 3 tests fail — llm_call event 不存在

- [ ] **Step 3: 改 `core/llm_client.py::chat_completion`**

顶部加导入：

```python
from core import trace
```

替换 `chat_completion`（保留现有清洗流程，只增加 usage 捕获 + trace.event）：

```python
def chat_completion(
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    provider = getattr(config, "LLM_PROVIDER", "deepseek")
    captured: dict = {}

    def _call():
        client, model, extra_body, token_mul = _get_chat_client()
        effective_max = min(max_tokens * token_mul, config.LLM_MAX_OUTPUT_TOKENS)
        if effective_max != max_tokens:
            logger.debug(
                f"chat_completion max_tokens={max_tokens}x{token_mul}->{effective_max} "
                f"(provider reasoning budget)"
            )
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=effective_max,
            temperature=temperature,
            extra_body=extra_body or None,
        )
        captured["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        captured["model"] = model
        captured["effective_max_tokens"] = effective_max
        captured["usage"] = getattr(resp, "usage", None)
        return resp.choices[0].message.content

    result_raw = _retry(_call, operation="chat_completion")
    result = _sanitize(result_raw)
    trimmed = (len(result_raw) if result_raw else 0) - len(result)
    logger.debug(f"chat_completion result_len={len(result)} sanitize_trimmed={trimmed}")

    usage = captured.get("usage")
    trace.event(
        "llm_call",
        provider=provider,
        model=captured.get("model"),
        messages=messages,
        raw=result_raw,
        sanitized=result,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        effective_max_tokens=captured.get("effective_max_tokens"),
        elapsed_ms=captured.get("elapsed_ms", 0),
        attempt=1,
    )
    return result
```

注：`attempt=1` 是简化口径（成功那次的 attempt 总是最后一次；Phase A 不追踪中间失败 attempt，`_retry` 内部已经 logger.warning 了错误）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_chat_completion_trace.py tests/test_llm_sanitize.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add core/llm_client.py tests/test_chat_completion_trace.py
git commit -m "feat(llm_client): emit trace.event(llm_call) with usage + raw/sanitized"
```

---

## Task 9: `get_embedding` emit `trace.event("embedding", ...)`

**Files:**
- Modify: `core/llm_client.py::get_embedding`
- Modify: `tests/test_chat_completion_trace.py`（复用文件加测试）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_chat_completion_trace.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_chat_completion_trace.py -v`
Expected: 1 new test fails

- [ ] **Step 3: 修改 `core/llm_client.py::get_embedding`**

替换 `get_embedding`：

```python
def get_embedding(text: str) -> list[float]:
    t0 = time.monotonic()

    def _call():
        api_key = config.SILICONFLOW_API_KEY or os.environ.get("SILICONFLOW_API_KEY", "")
        if not api_key:
            raise RuntimeError("SILICONFLOW_API_KEY 未配置（config.py 或环境变量）")
        payload = json.dumps({"model": config.EMBEDDING_MODEL, "input": text}).encode()
        req = urllib.request.Request(
            f"{config.EMBEDDING_BASE_URL}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["data"][0]["embedding"]

    result = _retry(_call, operation="get_embedding", max_retries=5)
    logger.debug(f"get_embedding dim={len(result)}")
    trace.event(
        "embedding",
        dim=len(result),
        text_len=len(text),
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_chat_completion_trace.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add core/llm_client.py tests/test_chat_completion_trace.py
git commit -m "feat(llm_client): emit trace.event(embedding) with dim/text_len/elapsed"
```

---

## Task 10: `retrieval.retrieve` 在 5 个阶段 emit 事件

**Files:**
- Modify: `core/retrieval.py`
- Create: `tests/test_retrieval_trace.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_retrieval_trace.py`：

```python
"""验证 retrieve() 在激活 trace 时 emit 各阶段事件。"""
from unittest.mock import patch, MagicMock
from core import trace


@patch("core.retrieval._get_table")
@patch("core.retrieval.MemoryGraph")
@patch("core.retrieval.get_event")
@patch("core.retrieval.read_global_state")
@patch("core.retrieval.get_soul_anchor")
@patch("core.retrieval.get_embedding")
def test_retrieve_emits_stage_events(
    mock_emb, mock_anchor, mock_state, mock_get_event, mock_graph_cls, mock_get_table
):
    mock_emb.return_value = [0.1] * 1024
    mock_anchor.return_value = "anchor"
    mock_state.return_value = {"current_state": {"mood": "ok", "energy": "high", "stress_level": 0.3}}

    # 向量召回 2 条
    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
        {"event_id": "e1", "vector": [0.1] * 1024, "status": "active",
         "importance": 0.8, "created_at": "2026-04-20T00:00:00",
         "action": "", "actor": "", "context": "", "outcome": "", "emotion": "", "emotion_intensity": 0.2},
        {"event_id": "e2", "vector": [0.1] * 1024, "status": "active",
         "importance": 0.5, "created_at": "2026-04-19T00:00:00",
         "action": "", "actor": "", "context": "", "outcome": "", "emotion": "", "emotion_intensity": 0.1},
    ]
    mock_get_table.return_value = tbl

    graph = MagicMock()
    graph.get_neighbors.return_value = [{"event_id": "e3"}]
    mock_graph_cls.return_value = graph
    mock_get_event.return_value = {
        "event_id": "e3", "status": "active", "vector": [0.1] * 1024,
        "importance": 0.3, "created_at": "2026-04-18T00:00:00",
        "action": "", "actor": "", "context": "", "outcome": "", "emotion": "", "emotion_intensity": 0.0,
    }

    from core.retrieval import retrieve
    with trace.turn("agent_x", "q") as t:
        retrieve("agent_x", "query text", mode="dialogue")
        trace.mark("记忆检索")

    kinds = [e["kind"] for e in t.steps[0].events]
    assert "embedding" in kinds  # 来自 get_embedding mock (已 patch 所以不 emit —— 但 retrieve 里直接 emit)
    assert "vector_search" in kinds
    assert "graph_expand" in kinds
    assert "score_rerank" in kinds

    vs = next(e for e in t.steps[0].events if e["kind"] == "vector_search")
    assert vs["raw_hits"] == 2
    assert vs["after_dedup"] == 2

    ge = next(e for e in t.steps[0].events if e["kind"] == "graph_expand")
    assert ge["neighbors_added"] >= 0

    rr = next(e for e in t.steps[0].events if e["kind"] == "score_rerank")
    assert "weights" in rr
    assert rr["top_k_returned"] <= 8
```

注：`get_embedding` 被 patch 掉后不会再 emit `embedding` event。为了让 retrieve 自己也打点"做了一次 embedding"，我们在 retrieve 内部也 emit 一个 `embedding_stage` event（有别于 llm_client 的 `embedding`）。调整测试断言：

把测试里 `assert "embedding" in kinds` 改成 `assert "embedding_stage" in kinds`。

（最终测试版本见 Step 3 实现后的第二次跑测结果。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_retrieval_trace.py -v`
Expected: 失败（缺对应 events）

- [ ] **Step 3: 修改 `core/retrieval.py`**

顶部加导入：

```python
import time
from core import trace
```

在 `retrieve()` 里现有的 5 个位置插入 event（保持现有代码结构，只在关键节点加行）：

- **5. Query embedding**（第 202-203 行附近）：

```python
# 5. Query embedding
_t0 = time.monotonic()
query_embedding = get_embedding(query)
trace.event("embedding_stage", dim=len(query_embedding), elapsed_ms=int((time.monotonic()-_t0)*1000))
```

- **6. LanceDB 向量检索**（第 220-221 行附近）— 替换原 `logger.info(...)`：

```python
vector_results = [r for r in raw_results if r.get("event_id") not in already_surfaced]
trace.event(
    "vector_search",
    raw_hits=len(raw_results),
    after_dedup=len(vector_results),
    limit=_RETRIEVAL_TOP_K,
    already_surfaced=len(already_surfaced),
)
logger.debug(f"retrieve vector_hits={len(raw_results)} after_dedup={len(vector_results)}")
```

- **7. 图扩展**（第 249-251 行附近）— 加 event，保留原 logger.info 但降到 debug：

```python
neighbors_added = len(candidate_map) - len(vector_results)
trace.event(
    "graph_expand",
    top5_ids=top5_ids,
    neighbors_added=neighbors_added,
)
logger.debug(
    f"retrieve candidate_pool={len(candidate_map)} "
    f"(vector={len(vector_results)} + graph_expand={neighbors_added})"
)
```

- **8. 评分重排**（第 270 行 `top_candidates = scored[:_FINAL_TOP_K]` 之后）：

```python
trace.event(
    "score_rerank",
    weights=dict(weights),
    candidate_pool=len(scored),
    top_k_returned=len(top_candidates),
    top_scored=[
        {
            "event_id": s["event_id"],
            "score": round(s["score"], 3),
            "source": s["source"],
        }
        for s in top_candidates
    ],
)
```

- **9. LLM rerank**（decision 模式，Phase A 不会触发但预留）— 在 `_llm_rerank` 调用后加：

```python
    if mode == "decision" and top_candidates:
        logger.debug(f"retrieve decision mode: calling LLM rerank on {len(top_candidates)} candidates")
        reranked_ids = _llm_rerank(query, top_candidates)
        id_to_item   = {c["event_id"]: c for c in top_candidates}
        reranked = [id_to_item[rid] for rid in reranked_ids if rid in id_to_item]
        if reranked:
            top_candidates = reranked
            trace.event("llm_rerank", selected=len(reranked))
```

- **原 `retrieve done` INFO**（第 330-331 行）降 debug：

```python
logger.debug(f"retrieve done agent_id={agent_id} mode={mode} "
             f"returned={len(relevant_memories)} surfaced={len(surfaced_ids)}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_retrieval_trace.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add core/retrieval.py tests/test_retrieval_trace.py
git commit -m "feat(retrieval): emit trace events for embedding/vector/graph/rerank stages"
```

---

## Task 11: `dialogue.chat()` 加 4 处 `trace.mark`

**Files:**
- Modify: `core/dialogue.py`
- Create: `tests/test_chat_trace_integration.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_chat_trace_integration.py`：

```python
"""集成测试：chat() 加上 mark 后应产生恰好 4 个 step，顺序正确。
使用大量 patch 隔离实盘/实 LLM。"""
from unittest.mock import patch, MagicMock
from core import trace


@patch("core.dialogue._save_l0")
@patch("core.dialogue._load_l0")
@patch("core.dialogue.retrieve")
@patch("core.dialogue.chat_completion")
def test_chat_produces_four_steps(
    mock_chat, mock_retrieve, mock_load_l0, mock_save_l0, tmp_path
):
    mock_load_l0.return_value = {
        "agent_id": "a",
        "session_id": "s1",
        "created_at": "2026-04-20T00:00:00",
        "ttl_hours": 24,
        "raw_dialogue": [],
        "emotion_snapshots": [],
        "working_context": {},
        "status": "simplified",
    }
    mock_retrieve.return_value = {
        "soul_anchor": "anchor",
        "current_state": "ok",
        "working_context": "",
        "l2_patterns": "",
        "relevant_memories": [],
        "surfaced_ids": [],
    }
    # 第一次调：情绪检测；第二次调：回复生成
    mock_chat.side_effect = ["0.15", "好的"]

    from core.dialogue import chat

    with trace.turn("a", "你好") as t:
        result = chat("a", "你好", session_history=[])

    step_names = [s.name for s in t.steps]
    assert step_names == ["情绪检测", "记忆检索", "构造 prompt", "对话生成"]
    assert all(s.total == 4 for s in t.steps)
    assert result["reply"] == "好的"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_chat_trace_integration.py -v`
Expected: `step_names == []` 失败（没有 mark 调用）

- [ ] **Step 3: 修改 `core/dialogue.py::chat()`**

顶部导入：

```python
from core import trace
```

在 `chat()` 的 4 个节拍末尾各加一行 `trace.mark(...)`：

定位 §1 情绪检测之后（当前 `logger.info("chat agent_id=...")` 行位置，第 149-150 行附近），改为：

```python
    emotion_intensity = _detect_emotion(user_message)
    trace.mark("情绪检测", summary=f"{emotion_intensity:.2f}")
```

（去掉原 `logger.info(f"chat agent_id={agent_id} emotion_intensity=...")` — 已经进 trace 了）

定位 §3 检索之后（第 170-176 行附近，`session_surfaced = session_surfaced | ...` 之后）：

```python
    session_surfaced = session_surfaced | set(retrieval_result["surfaced_ids"])
    trace.mark("记忆检索")
```

定位 §6 构造 prompt 之后（第 201 行 system_prompt 赋值之后）：

```python
    system_prompt = _DIALOGUE_TPL.format(
        ...
    )
    trace.mark(
        "构造 prompt",
        summary=(
            f"system {len(system_prompt)} 字 / 历史 {min(6, len(session_history))} 轮 / "
            f"记忆 {len(retrieval_result['relevant_memories'])} 条"
        ),
    )
```

定位 §7 对话生成之后（第 209-213 行 try/except 之后）：

```python
    try:
        reply = chat_completion(messages, max_tokens=512, temperature=0.7)
    except Exception as e:
        logger.error(f"chat LLM generation failed: {e}")
        reply = "（系统错误，无法生成回复）"
    trace.mark("对话生成")
```

去掉函数末尾的 `logger.info(f"chat done agent_id=... reply_len=...")` —— 已被 trace footer 取代。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_chat_trace_integration.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add core/dialogue.py tests/test_chat_trace_integration.py
git commit -m "feat(dialogue): mark 4 steps in chat() for trace visibility"
```

---

## Task 12: `main_chat.py` 加 `--debug` 并外包 `trace.turn`

**Files:**
- Modify: `main_chat.py`

- [ ] **Step 1: 写失败测试（argparse smoke）**

在 `tests/test_chat_trace_integration.py` 末尾追加：

```python
def test_main_chat_accepts_debug_flag():
    # 只是 smoke 验证 argparse 不报错；不真的进入 REPL
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "main_chat.py", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "--debug" in result.stdout
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_chat_trace_integration.py::test_main_chat_accepts_debug_flag -v`
Expected: FAIL（`--debug` 不在 help 输出）

- [ ] **Step 3: 修改 `main_chat.py`**

完整替换为：

```python
import argparse
import sys

from core import trace
from core.dialogue import chat, end_session


def main():
    parser = argparse.ArgumentParser(description="和数字人对话（main_chat）")
    parser.add_argument("agent_id", nargs="?", default="test_agent_001",
                        help="agent 目录名（data/agents/<agent_id>）")
    parser.add_argument("--debug", action="store_true",
                        help="开启 debug 模式：控制台展开子项 + 落盘 logs/sessions/<session_id>.md")
    args = parser.parse_args()

    session_history = []
    session_surfaced = set()

    print(f"开始和数字人对话（agent: {args.agent_id}，输入 quit 结束会话）\n")
    if args.debug:
        print("[debug] 本次会话的完整链路会写入 logs/sessions/<session_id>.md\n")

    while True:
        user_input = input("你：").strip()
        if user_input.lower() == "quit":
            print("\n会话结束，正在保存记忆...")
            end_session(args.agent_id, session_history)
            print("完成。")
            break

        try:
            with trace.turn(args.agent_id, user_input, debug=args.debug):
                result = chat(args.agent_id, user_input, session_history, session_surfaced)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n出错了：{e}，请继续输入或输入 quit 退出\n")
            continue

        reply = result["reply"]
        session_surfaced = result["session_surfaced"]

        session_history.append({"role": "user", "content": user_input})
        session_history.append({"role": "assistant", "content": reply})

        print(f"\n数字人：{reply}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_chat_trace_integration.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add main_chat.py tests/test_chat_trace_integration.py
git commit -m "feat(main_chat): argparse + --debug flag wrapping chat() in trace.turn"
```

---

## Task 13: 手动冒烟 + `logs/sessions/` 归入 `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 检查 `.gitignore` 已忽略 `logs/`**

Run:

```bash
grep -n "^logs" .gitignore
```

Expected: 能看到 `logs/` 或 `logs` 一行。若没有，下一步加上。

- [ ] **Step 2: 如需要，追加 `logs/sessions/` 忽略**

如果 `.gitignore` 里没有 `logs/`，追加：

```
logs/
```

（已经有就跳过此步）

- [ ] **Step 3: 跑完整 pytest**

Run: `pytest tests/ -v --ignore=tests/manual_test_provider_switch.py --ignore=tests/manual_test_decay.py --ignore=tests/manual_test_dialogue.py --ignore=tests/manual_test_graph.py --ignore=tests/manual_test_l1.py --ignore=tests/manual_test_l2.py --ignore=tests/manual_test_retrieval.py --ignore=tests/manual_test_soul.py --ignore=tests/e2e_test.py`

Expected: 所有单测 / 集成测试通过，控制台**不出现** `HTTP Request: POST ...` 行。

- [ ] **Step 4: 手动冒烟（对应 spec §10 验收）**

以下属于手动步骤，需要真实 API KEY 环境。做一次人工验证：

```bash
# 1. 默认模式：控制台 ~8 行
python main_chat.py jobs_v1
# （输入 "你好"，观察 ═══ 轮 1 ═══ 开头的 5 行，步骤号 [1/4]..[4/4]；输入 quit 退出）

# 2. debug 模式：控制台展开 + 落盘
python main_chat.py jobs_v1 --debug
# （输入 "你好"，观察子项 ├ / └；退出后检查 logs/sessions/<session_id>.md）
ls -la logs/sessions/
```

手动验收清单：

- [ ] 默认模式每轮 7-9 行，结构对应 spec §2.1
- [ ] debug 模式控制台每 step 下有 ├ 子项，对应 spec §2.2
- [ ] `logs/sessions/<id>.md` 文件内容对应 spec §5.2 模板：有 `## 轮 N`、`### [N/4]`、provider/usage、messages fence、raw fence、sanitized fence
- [ ] 切 `config.LLM_PROVIDER` 到 `glm` / `deepseek`，日志里的 provider/model/usage 反映正确

- [ ] **Step 5: 最终 commit**

```bash
git status  # 若有 .gitignore 修改
git add .gitignore  # 若需要
git commit -m "chore: ignore logs/sessions/ output" --allow-empty
```

---

## Self-Review

**Spec coverage check**（逐节比对 `2026-04-20-chat-trace-logging-design.md`）：

- §1 背景 → 整个计划就是解决它 ✓
- §2.1 默认输出 → Task 5 renderer + Task 11 dialogue marks 合作实现 ✓
- §2.2 Debug 输出 → Task 6 debug renderer + markdown writer ✓
- §3.1 Trace API → Task 1-4 逐步实现（`turn`, `mark`, `event`, `current`）✓
- §3.2 session_id 口径 → Task 2 `_resolve_session_id` 从 L0 buffer 读 ✓
- §4 插桩点 4 个文件 → Task 7-12 覆盖 ✓
- §4.1 chat() 4 步 → Task 11 ✓
- §4.2 retrieve 子事件 → Task 10（embedding_stage / vector_search / graph_expand / score_rerank / llm_rerank）✓
- §5.1 默认格式 → Task 5 `_render_step_line` / `_auto_summary` / `_step_extras` ✓
- §5.2 markdown 模板 → Task 6 `_render_markdown_turn` ✓
- §5.3 落盘策略（目录自动创建、追加写、同 session_id 继续追加）→ Task 6 `_write_markdown` 处理 ✓
- §6 噪音清理 → Task 7 ✓
- §7 token 捕获 → Task 8 ✓
- §8 CLI → Task 12 ✓
- §9 不做清单 → 本计划刻意不涉及 make_decision/end_session/seed_builder ✓
- §10 验收 → Task 13 Step 3-4 ✓
- §11 文件改动清单 → 与本计划 File Structure 一致 ✓

**Placeholder scan**：已搜本文档内无 TBD / TODO / "implement later" / "similar to"。所有 code 步骤都给了完整片段（不是伪代码）。

**Type/name consistency**：

- `Trace` / `Step` 字段名贯穿 Task 2-6 一致（`session_id`, `steps`, `_pending_events`, `_last_mark_ts`, `index`, `total`, `elapsed_ms`, `explicit_summary`, `events`）✓
- `trace.event` 的 `kind` 命名统一：`llm_call` / `embedding` / `embedding_stage` / `vector_search` / `graph_expand` / `score_rerank` / `llm_rerank` ✓
- `_render_default` / `_render_debug_console` / `_render_markdown_turn` / `_write_markdown` / `_render_step_line` / `_auto_summary` / `_step_extras` / `_render_header` / `_render_footer` 函数名在 Task 5-6 内部调用一致 ✓
- `trace.turn()` / `trace.mark()` / `trace.event()` 在 Task 7-12 的业务文件中保持一致调用方式 ✓

发现并修正：无。

---
