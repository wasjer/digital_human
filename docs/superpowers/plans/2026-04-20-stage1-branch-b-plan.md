# Stage 1 Branch-B Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Branch B 范围内完成阶段一 11 项改进——先建地基（链路索引 + benchmark），修 P0 bug 6 项，做 P1 功能增强 3 项；引入 benchmark 作为回归基准。

**Architecture:** 每项由独立 subagent 完成，按文件边界严格隔离。Phase 0 建立回归手段；Phase 1 六项可并行但 git 层面串行（避免交叉 merge）；Phase 2 三项的 NEW-1 需在 Phase 1 的 1.3 之后（同文件 retrieval.py 的不同部分）。改完每项由主 agent 跑 benchmark 对齐前后差异。

**Tech Stack:** Python 3.13, LanceDB, SQLite, pytest, unittest.mock, tarfile

**Source spec:** `docs/superpowers/specs/2026-04-20-stage1-branch-b-design.md`

---

## 任务依赖与顺序

```
Phase 0 (串行):
  0-a 链路索引 md
  0-b benchmark_runner

Phase 1 (顺序执行，每完成一项跑 benchmark):
  1.6 dialogue.py 外层 try/except        ← 独立
  1.5 main_chat.py 信号/恢复             ← 独立
  6.3-2 soul.py evidence_log 上限        ← 独立
  6.3-1 memory_l2.py 增量扫描            ← 独立（touches memory_l2.py + global_state.json）
  1.2 memory_graph.py decay 改休眠       ← 独立（memory_graph.py:decay_edges）
  1.3 去掉 revived 状态                  ← touches memory_graph.py / retrieval.py / memory_l1.py / spec

Phase 2:
  1.4 边强度冷却                        ← touches memory_graph.py（与 1.2/1.3 串行）
  3.8 轻量寒暄旁路                       ← 独立（dialogue.py）
  NEW-1 软惩罚去重                       ← touches retrieval.py（必须在 1.3 之后）
```

**文件冲突风险**：
- `retrieval.py`：1.3 和 NEW-1 → 串行（1.3 先）
- `memory_graph.py`：1.2、1.3、1.4 → 串行（顺序：1.2 → 1.3 → 1.4）

**全局规则**：
- 每个 subagent 只改自己声明的文件
- 碰到 prompt 分隔符不一致、函数体内 import、`_get_table` 等小问题时**允许顺手处理**（6.4 inline），但不跨文件清理
- 每项完成后执行 `pytest tests/ -x -q`，全部通过才 commit
- commit 信息格式：`<type>(<scope>): <desc>`，参考最近 5 条 commit 风格

---

## Phase 0: 打地基

### Task 0-a: 自用链路索引文档

**Files:**
- Create: `docs/architecture/link-index.md`

**Purpose:** 一张地图，把 `chat() / retrieve() / end_session()` 每一步 + 全局参数来源 + 持久化文件对应关系画清楚。以后每次回到项目都能快速重建心智模型。

- [ ] **Step 1: 写文档**

内容框架（subagent 填实际代码路径和行号——不要复制 placeholder）：

```markdown
# 链路索引（self-reference）

> 主流程：`main_chat.py` → `core.dialogue.chat` → `core.retrieval.retrieve` → LLM → `core.dialogue.end_session`（sync + async）
> 最后更新：2026-04-20

## 1. chat() 流程（core/dialogue.py:137）

| # | 步骤 | 代码位置 | 副作用 |
|---|------|----------|--------|
| 1 | 情绪检测 | `_detect_emotion` L99 | LLM 1 次 |
| 2 | 情绪峰值快照（若 >EMOTION_SNAPSHOT_THRESHOLD） | L159 | 写 l0_buffer |
| 3 | `retrieve()` 记忆检索 | L170 | 见下 |
| 4 | 追加 user 消息到 l0_buffer | L181 | 写 l0_buffer |
| 5 | 拼 system prompt（含 soul_anchor / current_state / l2_patterns / memories） | L193 | — |
| 6 | LLM 生成回答 | L219 | LLM 1 次 |
| 7 | 追加 assistant 消息到 l0_buffer | L226 | 写 l0_buffer |

## 2. retrieve() 流程（core/retrieval.py:167）

| # | 步骤 | 代码位置 |
|---|------|----------|
| 1 | get_soul_anchor | L180 |
| 2 | 读 global_state，拼 current_state_text | L186 |
| 3 | 加载 l0_buffer → working_context | L196 |
| 4 | L2 patterns 检索 | L200 |
| 5 | query embedding（SiliconFlow bge-m3） | L206 |
| 6 | LanceDB 向量检索 top20 + session_surfaced 去重 | L211 |
| 7 | 图扩展：top5 各自 get_neighbors | L237 |
| 8 | 按 mode 权重 _score_candidate 排 top8 | L271 |
| 9 | decision 模式 LLM 精排 | L305 |
| 10 | 构建输出（freshness_text） | L315 |
| 11 | 更新 access_count | L350 |
| 12 | strengthen_links_on_retrieval | L357 |

## 3. end_session() 流程（core/dialogue.py:364）

### 同步（_end_session_sync L238）
- 拼会话文本（emotion peaks + 完整对话）
- `memory_l1.write_event(agent_id, session_text, source='session')` → LanceDB 多条事件
- 清空 l0_buffer

### 异步后台（_end_session_async L279，独立线程）
1. `update_elastic(emotion_core.current_emotional_state)` ← emotion snapshots max
2. `soul_evidence_check` LLM（拿整段会话）
3. 若是 evidence → `add_evidence`（写 soul.evidence_log，目前无上限）
4. `check_slow_change` → 若触发 → LLM 生成新值 → `apply_slow_change`
5. `memory_l2.check_and_generate_patterns` 
6. `memory_l2.contribute_to_soul`

## 4. 全局参数来源

| 参数 | 文件 | 当前值 | 备注 |
|------|------|--------|------|
| EMBEDDING_MODEL | config.py | BAAI/bge-m3 | 仅 SiliconFlow |
| LLM_PROVIDER | config.py | minimax | 影响 chat_completion 路由 |
| GRAPH_EDGE_DECAY_RATE | config.py | 0.99 | decay_edges 每日衰减率 |
| DORMANT_THRESHOLD | config.py | 0.3 | decay_score 低于此值进 dormant |
| stress_level | `data/agents/<id>/global_state.json` | 0.3（静态） | 目前无代码更新路径 |
| EMOTION_SNAPSHOT_THRESHOLD | config.py | 0.7 | — |
| IS_DERIVABLE_DISCARD_THRESHOLD | config.py | 0.8 | L1 写入前过滤 |
| L2_SAME_TOPIC_THRESHOLD | config.py | 3 | — |
| L2_SOUL_CONTRIBUTION_THRESHOLD | config.py | 0.8 | — |

## 5. 持久化文件对应关系

| 文件 | 读写者 | 内容 |
|------|--------|------|
| `data/agents/<id>/soul.json` | soul.py 全家 | 人格 4 核心（constitutional/slow_change/elastic） |
| `data/agents/<id>/global_state.json` | global_state.py | current_state + personality_params |
| `data/agents/<id>/l0_buffer.json` | dialogue.py | 本次 session 的 raw_dialogue + emotion_snapshots |
| `data/agents/<id>/l2_patterns.json` | memory_l2.py | 规律列表（≤200） |
| `data/agents/<id>/memories/` | memory_l1.py (LanceDB) | 原子事件表 `l1_events` |
| `data/agents/<id>/graph.db` | memory_graph.py (SQLite) | 记忆图 `memory_links` |

## 6. Trace 系统

- 进入：`main_chat.py --debug` → `trace.turn(agent_id, user_input, debug=True)`
- 阶段标记：`trace.mark("情绪检测")` / `trace.mark("记忆检索")` ...
- 子事件：`trace.event("llm_call", ...)` / `trace.event("embedding", ...)`
- 输出：`logs/sessions/<session_id>.md`
```

- [ ] **Step 2: 人工读一遍，确认路径/行号没写错**

Run: `grep -n "def chat\|def retrieve\|def end_session\|def _end_session" core/dialogue.py core/retrieval.py`
Expected: 行号与文档一致。

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/link-index.md
git commit -m "docs: add self-reference link index for core flows"
```

---

### Task 0-b: benchmark_runner + 标准 20 题对话集

**Files:**
- Create: `tools/benchmark_runner.py`
- Create: `tests/data/benchmark_dialogues.json`
- Create: `tests/test_benchmark_runner.py`

**Purpose:** 每次改动前后跑同一套 20 题，对比 reply / emotion / token / 耗时的 diff。跑前备份 agent 目录，跑完自动恢复。

- [ ] **Step 1: 写 benchmark_dialogues.json**

```json
[
  {"category": "寒暄", "text": "你好"},
  {"category": "寒暄", "text": "在忙什么？"},
  {"category": "寒暄", "text": "今天天气怎么样"},
  {"category": "童年经历", "text": "小时候最让你印象深的事是什么？"},
  {"category": "童年经历", "text": "家里人对你影响最大的是谁？"},
  {"category": "价值观", "text": "你觉得一个人最重要的品质是什么？"},
  {"category": "价值观", "text": "如果朋友和正义冲突，你会怎么选？"},
  {"category": "世界观", "text": "你怎么看待这个世界现在的状态？"},
  {"category": "世界观", "text": "AI 会改变人类的命运吗？"},
  {"category": "决策", "text": "如果有一份高薪但无聊的工作和一份低薪但热爱的工作，你怎么选？"},
  {"category": "决策", "text": "如果要搬去一个陌生的城市重新开始，你会考虑哪些因素？"},
  {"category": "情绪激动", "text": "我最近很崩溃，感觉自己什么都做不好"},
  {"category": "情绪激动", "text": "有个人背叛了我，我特别愤怒"},
  {"category": "跨会话记忆", "text": "上次我们聊过我的工作压力，你还记得吗？"},
  {"category": "跨会话记忆", "text": "那件事后来你有什么新的想法？"},
  {"category": "稀有词注入", "text": "你听说过紫色大象吗？"},
  {"category": "稀有词注入", "text": "如果窗外出现一头紫色大象你会怎么反应？"},
  {"category": "反问", "text": "你最近在想什么？"},
  {"category": "反问", "text": "你对我有什么印象？"},
  {"category": "告别", "text": "好的，先聊到这，再见"}
]
```

- [ ] **Step 2: 写 benchmark_runner.py**

```python
"""
benchmark_runner: 对 agent 跑标准对话集，输出 JSON 报告。
跑前备份 data/agents/<agent_id>/ 到 logs/benchmark/<agent>-<ts>.tar.gz，跑完恢复。

用法：
    python tools/benchmark_runner.py <agent_id> [--run-label baseline]
"""
import argparse
import json
import logging
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path

from core.dialogue import chat, end_session

_ROOT          = Path(__file__).parent.parent
_AGENTS_DIR    = _ROOT / "data" / "agents"
_BENCHMARK_DIR = _ROOT / "logs" / "benchmark"
_DEFAULT_DIALOGUES = _ROOT / "tests" / "data" / "benchmark_dialogues.json"

logger = logging.getLogger("benchmark_runner")


def _backup_agent(agent_id: str) -> Path:
    _BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tar_path = _BENCHMARK_DIR / f"{agent_id}-snapshot-{ts}.tar.gz"
    target = _AGENTS_DIR / agent_id
    if not target.exists():
        raise FileNotFoundError(f"agent dir not found: {target}")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(target, arcname=agent_id)
    return tar_path


def _restore_agent(agent_id: str, tar_path: Path) -> None:
    target = _AGENTS_DIR / agent_id
    if target.exists():
        shutil.rmtree(target)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(_AGENTS_DIR)


def run_benchmark(agent_id: str, dialogues_path: Path, run_label: str = "baseline") -> dict:
    with open(dialogues_path, "r", encoding="utf-8") as f:
        dialogues = json.load(f)

    backup = _backup_agent(agent_id)
    logger.info(f"benchmark backup saved: {backup}")

    results = []
    session_history: list = []
    session_surfaced: set = set()
    t_start = time.time()

    try:
        for i, q in enumerate(dialogues):
            t0 = time.monotonic()
            try:
                r = chat(agent_id, q["text"], session_history, session_surfaced)
            except Exception as e:
                logger.error(f"benchmark q{i} error: {e}")
                results.append({
                    "index": i,
                    "category": q.get("category", ""),
                    "question": q["text"],
                    "reply": None,
                    "error": str(e),
                    "elapsed_s": round(time.monotonic() - t0, 2),
                })
                continue
            elapsed = time.monotonic() - t0
            session_history.append({"role": "user", "content": q["text"]})
            session_history.append({"role": "assistant", "content": r["reply"]})
            session_surfaced = r["session_surfaced"]
            results.append({
                "index": i,
                "category": q.get("category", ""),
                "question": q["text"],
                "reply": r["reply"],
                "emotion_intensity": r["emotion_intensity"],
                "surfaced_count": len(r["session_surfaced"]),
                "elapsed_s": round(elapsed, 2),
            })
        try:
            end_session(agent_id, session_history)
        except Exception as e:
            logger.warning(f"benchmark end_session error (non-fatal): {e}")
    finally:
        _restore_agent(agent_id, backup)
        logger.info(f"benchmark restored from: {backup}")

    report = {
        "agent_id":       agent_id,
        "run_label":      run_label,
        "started_at":     datetime.now().isoformat(),
        "total_elapsed_s": round(time.time() - t_start, 2),
        "backup_tar":     str(backup),
        "question_count": len(dialogues),
        "ok_count":       sum(1 for x in results if "error" not in x),
        "results":        results,
    }
    out_path = _BENCHMARK_DIR / f"{agent_id}-{run_label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"benchmark report: {out_path}")
    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Run benchmark dialogues against an agent")
    parser.add_argument("agent_id")
    parser.add_argument("--run-label",  default="baseline")
    parser.add_argument("--dialogues",  default=str(_DEFAULT_DIALOGUES))
    args = parser.parse_args()
    run_benchmark(args.agent_id, Path(args.dialogues), args.run_label)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 写失败测试 tests/test_benchmark_runner.py**

```python
"""benchmark_runner 备份/恢复 + 报告格式 dry-run 验证。"""
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import tools.benchmark_runner as br


def _fake_chat(agent_id, msg, history, surfaced):
    return {"reply": f"echo:{msg}", "session_surfaced": set(), "emotion_intensity": 0.3}


def _fake_end_session(agent_id, history):
    return None


def test_benchmark_backup_restore_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(br, "_BENCHMARK_DIR", tmp_path / "bench")
    agent_dir = br._AGENTS_DIR / "test_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "soul.json").write_text('{"agent_id": "test_agent"}', encoding="utf-8")

    dialogues = tmp_path / "d.json"
    dialogues.write_text(json.dumps([{"text": "你好", "category": "寒暄"}]), encoding="utf-8")

    with patch.object(br, "chat", side_effect=_fake_chat), \
         patch.object(br, "end_session", side_effect=_fake_end_session):
        report = br.run_benchmark("test_agent", dialogues, run_label="t")

    # agent 目录已恢复
    assert (agent_dir / "soul.json").read_text(encoding="utf-8") == '{"agent_id": "test_agent"}'
    # 报告格式完整
    assert report["agent_id"] == "test_agent"
    assert report["question_count"] == 1
    assert report["ok_count"] == 1
    assert report["results"][0]["reply"] == "echo:你好"
    assert report["results"][0]["category"] == "寒暄"
    # 备份 tar 存在
    assert Path(report["backup_tar"]).exists()
    with tarfile.open(report["backup_tar"]) as tar:
        names = tar.getnames()
        assert any("soul.json" in n for n in names)
```

- [ ] **Step 4: 运行测试确认失败**

Run: `pytest tests/test_benchmark_runner.py -v`
Expected: ImportError/ModuleNotFoundError for `tools.benchmark_runner` — 确认模块路径正确。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_benchmark_runner.py -v`
Expected: 1 passed

- [ ] **Step 6: 跑一次真实 baseline（可选，依赖环境）**

Run: `python tools/benchmark_runner.py <你的 agent_id> --run-label baseline-pre-stage1`
Expected: 生成 `logs/benchmark/<agent>-baseline-pre-stage1-*.json`；agent 目录未被破坏（spot check soul.json）

- [ ] **Step 7: Commit**

```bash
git add tools/benchmark_runner.py tests/data/benchmark_dialogues.json tests/test_benchmark_runner.py
git commit -m "feat(benchmark): standard 20-dialogue regression runner with backup/restore"
```

---

## Phase 1: P0 修 bug

### Task 1.6: `_end_session_async` 外层总 try/except

**Files:**
- Modify: `core/dialogue.py:279-362`（`_end_session_async` 函数体）
- Test: `tests/test_end_session_async_guard.py`（新建）

**Why first:** 最无害的兜底，为后续任务提供异步稳定性。

- [ ] **Step 1: 写失败测试**

```python
"""_end_session_async 内部任何异常都不应上抛。"""
from unittest.mock import patch

from core.dialogue import _end_session_async


def test_end_session_async_swallows_import_error():
    """即使 memory_l2 import 失败，函数也必须静默返回。"""
    with patch("core.dialogue.update_elastic", side_effect=RuntimeError("boom")):
        # 不应抛出
        _end_session_async("nonexistent_agent", "session text", "sid-1", [])


def test_end_session_async_swallows_inline_import_failure():
    """memory_l2 inline import 失败（如模块临时坏掉）也应被吞掉。"""
    import builtins
    real_import = builtins.__import__

    def bad_import(name, *a, **kw):
        if name.startswith("core.memory_l2"):
            raise ImportError("simulated")
        return real_import(name, *a, **kw)

    with patch("builtins.__import__", side_effect=bad_import), \
         patch("core.dialogue.update_elastic"), \
         patch("core.dialogue.chat_completion", return_value='{"is_evidence": false}'), \
         patch("core.dialogue.check_slow_change", return_value=[]):
        _end_session_async("agent_x", "s", "sid", [])
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_end_session_async_guard.py -v`
Expected: `test_end_session_async_swallows_inline_import_failure` FAIL（ImportError 逃逸）

- [ ] **Step 3: 在 `_end_session_async` 外层加总 try/except**

Edit `core/dialogue.py`，在 `def _end_session_async(...)` 函数体的**最外层**包裹（即整个函数体都在 try 里）：

```python
def _end_session_async(agent_id: str, session_text: str,
                       session_id: str, emotion_snaps: list):
    """
    异步后台部分：更新 soul 弹性区、证据检查、缓变区更新、L2。
    内部任何异常均不向上抛出（含 import 失败）。
    """
    try:
        # ── 1. update_elastic ──
        try:
            if emotion_snaps:
                max_intensity = max(s.get("emotion_intensity", 0) for s in emotion_snaps)
                state = "情绪波动" if max_intensity > 0.6 else "轻微波动"
            else:
                state = "平稳"
            update_elastic(agent_id, "emotion_core", "current_emotional_state", state)
            logger.info(f"_end_session_async update_elastic state={state}")
        except Exception as e:
            logger.warning(f"_end_session_async update_elastic failed: {e}")

        # ── 2. soul_evidence_check ──
        try:
            evidence_user = _EVIDENCE_USR.format(session_text=session_text)
            raw = chat_completion(
                [{"role": "system", "content": _EVIDENCE_SYS},
                 {"role": "user",   "content": evidence_user}],
                max_tokens=256,
                temperature=0.1,
            )
            ev = json.loads(_strip_json(raw))
            logger.info(
                f"_end_session_async evidence is_evidence={ev.get('is_evidence')} "
                f"core={ev.get('core')} field={ev.get('field')} score={ev.get('score')}"
            )
            if ev.get("is_evidence") and ev.get("core") and ev.get("field"):
                add_evidence(
                    agent_id,
                    core=ev["core"],
                    field=ev["field"],
                    score=float(ev.get("score", 0.1)),
                    reason=ev.get("reason", ""),
                    session_id=session_id,
                )
        except Exception as e:
            logger.warning(f"_end_session_async evidence_check failed: {e}")

        # ── 3. check_slow_change → apply_slow_change ──
        try:
            triggered = check_slow_change(agent_id)
            for item in triggered:
                try:
                    new_val = chat_completion(
                        [
                            {"role": "system", "content":
                                "根据对话证据，为人格缓变字段生成一个新的描述值。"
                                "只输出新值文本，20字以内，不含任何其他内容。"},
                            {"role": "user", "content":
                                f"字段：{item['core']}.{item['field']}\n"
                                f"当前值：{item['current_value']}\n"
                                f"累积证据分：{item['evidence_score']:.2f}\n"
                                f"相关对话（节选）：{session_text[:400]}\n"
                                f"新值："},
                        ],
                        max_tokens=64,
                        temperature=0.3,
                    ).strip()
                    apply_slow_change(agent_id, item["core"], item["field"], new_val)
                    logger.info(
                        f"_end_session_async slow_change "
                        f"{item['core']}.{item['field']} -> {new_val!r}"
                    )
                except Exception as e:
                    logger.warning(
                        f"_end_session_async apply_slow_change failed "
                        f"{item['core']}.{item['field']}: {e}"
                    )
        except Exception as e:
            logger.warning(f"_end_session_async check_slow_change failed: {e}")

        # ── 4. memory_l2 ──
        try:
            from core.memory_l2 import check_and_generate_patterns, contribute_to_soul
            check_and_generate_patterns(agent_id)
            contribute_to_soul(agent_id)
        except Exception as e:
            logger.warning(f"_end_session_async memory_l2 failed: {e}")

    except Exception as e:
        logger.error(f"_end_session_async top-level guard caught: {e}")
```

- [ ] **Step 4: 确认测试通过**

Run: `pytest tests/test_end_session_async_guard.py -v`
Expected: 2 passed

- [ ] **Step 5: 跑全量测试不回归**

Run: `pytest tests/ -x -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add core/dialogue.py tests/test_end_session_async_guard.py
git commit -m "fix(dialogue): swallow all exceptions in _end_session_async top-level"
```

---

### Task 1.5: `main_chat.py` 信号捕获 + 启动自动恢复

**Files:**
- Modify: `main_chat.py`
- Test: `tests/test_main_chat_recovery.py`（新建）

**Two layers:**
1. Ctrl+C → signal handler → `end_session` 后退出
2. 启动时检查 `l0_buffer.json`：有残留则直接 `end_session` 清掉

- [ ] **Step 1: 写测试（启动恢复部分——signal 难于单测）**

```python
"""main_chat 启动时对残留 l0_buffer 自动触发 end_session。"""
import json
from pathlib import Path
from unittest.mock import patch

import main_chat


def _make_stale_buffer(agent_dir: Path, agent_id: str):
    agent_dir.mkdir(parents=True, exist_ok=True)
    buf = {
        "agent_id": agent_id,
        "session_id": "stale-sid-123",
        "created_at": "2026-04-19T10:00:00",
        "ttl_hours": 24,
        "raw_dialogue": [
            {"role": "user", "content": "aborted question"},
            {"role": "assistant", "content": "partial reply"},
        ],
        "emotion_snapshots": [],
        "working_context": {},
        "status": "simplified",
    }
    (agent_dir / "l0_buffer.json").write_text(
        json.dumps(buf, ensure_ascii=False), encoding="utf-8"
    )


def test_recover_stale_buffer_triggers_end_session(tmp_path, monkeypatch):
    agents_root = tmp_path / "agents"
    monkeypatch.setattr(main_chat, "_AGENTS_DIR", agents_root)
    agent_dir = agents_root / "agent_x"
    _make_stale_buffer(agent_dir, "agent_x")

    called = {}
    def fake_end(agent_id, history):
        called["agent_id"] = agent_id
        called["history"] = history
    monkeypatch.setattr(main_chat, "end_session", fake_end)

    main_chat._recover_stale_buffer_if_any("agent_x")

    assert called["agent_id"] == "agent_x"
    # history 从 raw_dialogue 重建
    assert len(called["history"]) == 2


def test_no_recover_when_buffer_empty(tmp_path, monkeypatch):
    agents_root = tmp_path / "agents"
    monkeypatch.setattr(main_chat, "_AGENTS_DIR", agents_root)
    (agents_root / "agent_y").mkdir(parents=True)

    called = {}
    def fake_end(agent_id, history):
        called["called"] = True
    monkeypatch.setattr(main_chat, "end_session", fake_end)

    main_chat._recover_stale_buffer_if_any("agent_y")
    assert "called" not in called
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_main_chat_recovery.py -v`
Expected: AttributeError — `_recover_stale_buffer_if_any` 不存在。

- [ ] **Step 3: 改 main_chat.py**

完整替换 `main_chat.py` 内容：

```python
import argparse
import json
import signal
import sys
from pathlib import Path

from core import trace
from core.dialogue import chat, end_session

_AGENTS_DIR = Path(__file__).parent / "data" / "agents"


def _recover_stale_buffer_if_any(agent_id: str) -> None:
    """启动时若 l0_buffer 有残留，自动 end_session 把它清进 L1。"""
    buf_path = _AGENTS_DIR / agent_id / "l0_buffer.json"
    if not buf_path.exists():
        return
    try:
        buf = json.loads(buf_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not buf.get("session_id") or not buf.get("raw_dialogue"):
        return

    # 从残留 raw_dialogue 重建 history，触发 end_session
    stale_history = list(buf.get("raw_dialogue", []))
    print(f"[recover] 检测到上次会话残留（{len(stale_history)} 条），正在写入 L1...")
    try:
        end_session(agent_id, stale_history)
        print("[recover] 残留会话已写入 L1。")
    except Exception as e:
        print(f"[recover] 恢复失败（非致命）：{e}")


def main():
    parser = argparse.ArgumentParser(description="和数字人对话（main_chat）")
    parser.add_argument("agent_id", nargs="?", default="test_agent_001",
                        help="agent 目录名（data/agents/<agent_id>）")
    parser.add_argument("--debug", action="store_true",
                        help="开启 debug 模式：控制台展开子项 + 落盘 logs/sessions/<session_id>.md")
    args = parser.parse_args()

    # 启动恢复
    _recover_stale_buffer_if_any(args.agent_id)

    session_history = []
    session_surfaced = set()

    # SIGINT：Ctrl+C 时先 end_session 再退出
    def _on_sigint(signum, frame):
        print("\n[SIGINT] 收到中断，正在保存记忆...")
        try:
            end_session(args.agent_id, session_history)
            print("[SIGINT] 完成。")
        except Exception as e:
            print(f"[SIGINT] end_session 失败：{e}")
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_sigint)

    print(f"开始和数字人对话（agent: {args.agent_id}，输入 quit 结束会话）\n")
    if args.debug:
        print("[debug] 本次会话的完整链路会写入 logs/sessions/<session_id>.md\n")

    while True:
        user_input = input("你：").strip()
        if not user_input:
            continue
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

- [ ] **Step 4: 确认测试通过**

Run: `pytest tests/test_main_chat_recovery.py -v`
Expected: 2 passed

- [ ] **Step 5: 人工冒烟验证（可选）**
- 跑 `python main_chat.py <agent_id>`，输入一句，Ctrl+C。观察提示。
- 下一次启动，确认提示 `[recover]` 且 l0_buffer 被清空（`cat data/agents/<id>/l0_buffer.json` 中 `raw_dialogue` 为空）

- [ ] **Step 6: Commit**

```bash
git add main_chat.py tests/test_main_chat_recovery.py
git commit -m "feat(main_chat): SIGINT handler + stale l0_buffer auto-recovery"
```

---

### Task 6.3-2: `soul.add_evidence` evidence_log 上限

**Files:**
- Modify: `core/soul.py:247-260`（`add_evidence`）
- Test: `tests/test_evidence_log_cap.py`（新建）

**Rule:** 每个字段的 `evidence_log` 保留最近 50 条；超过时把最旧的 append 到 `data/agents/<id>/evidence_archive.json`（可以丢失历史没关系，但要能审计）。

- [ ] **Step 1: 写失败测试**

```python
"""evidence_log 超过 50 条时截断并归档。"""
import json
from pathlib import Path

from core import soul


def _fresh_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(soul, "_AGENTS_DIR", tmp_path)
    agent_dir = tmp_path / "a1"
    agent_dir.mkdir()
    # 最小 soul 骨架
    s = soul._build_empty_soul("a1")
    (agent_dir / "soul.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return agent_dir


def test_evidence_log_cap_at_50(tmp_path, monkeypatch):
    agent_dir = _fresh_agent(tmp_path, monkeypatch)
    # 写 55 条
    for i in range(55):
        soul.add_evidence("a1", "emotion_core", "emotional_regulation_style",
                          score=0.01, reason=f"r{i}", session_id="s1")
    s = soul.read_soul("a1")
    log = s["emotion_core"]["slow_change"]["emotional_regulation_style"]["evidence_log"]
    assert len(log) == 50, f"evidence_log should cap at 50, got {len(log)}"
    # 保留最新 50 条：r5..r54
    assert log[0]["reason"] == "r5"
    assert log[-1]["reason"] == "r54"

    # 归档文件存在且含最老的 5 条
    archive = agent_dir / "evidence_archive.json"
    assert archive.exists()
    data = json.loads(archive.read_text(encoding="utf-8"))
    archived_reasons = [e["reason"] for e in data]
    assert "r0" in archived_reasons
    assert "r4" in archived_reasons
    assert len(data) == 5
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_evidence_log_cap.py -v`
Expected: FAIL（log 会有 55 条）

- [ ] **Step 3: 改 soul.py**

在 `core/soul.py` 顶部常量后加：

```python
_EVIDENCE_LOG_MAX_ENTRIES = 50


def _archive_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / "evidence_archive.json"


def _append_to_archive(agent_id: str, entries: list) -> None:
    if not entries:
        return
    p = _archive_path(agent_id)
    existing = []
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.extend(entries)
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
```

然后替换 `add_evidence`：

```python
def add_evidence(agent_id: str, core: str, field: str, score: float,
                 reason: str, session_id: str) -> None:
    """向缓变区字段追加证据分；evidence_log 仅保留最近 _EVIDENCE_LOG_MAX_ENTRIES 条，
    溢出部分归档到 evidence_archive.json。"""
    soul = read_soul(agent_id)
    entry = soul[core]["slow_change"][field]
    entry["evidence_score"] = entry.get("evidence_score", 0.0) + score
    entry["evidence_log"].append({
        "timestamp": _now(),
        "session_id": session_id,
        "score_delta": score,
        "reason": reason,
        "core": core,
        "field": field,
    })

    # 截断 + 归档
    if len(entry["evidence_log"]) > _EVIDENCE_LOG_MAX_ENTRIES:
        overflow = entry["evidence_log"][:-_EVIDENCE_LOG_MAX_ENTRIES]
        entry["evidence_log"] = entry["evidence_log"][-_EVIDENCE_LOG_MAX_ENTRIES:]
        _append_to_archive(agent_id, overflow)

    _write_soul(agent_id, soul)
    logger.info(f"add_evidence agent_id={agent_id} {core}.{field} score+={score}")
```

- [ ] **Step 4: 确认测试通过**

Run: `pytest tests/test_evidence_log_cap.py -v`
Expected: 1 passed

- [ ] **Step 5: 跑全量测试**

Run: `pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
git add core/soul.py tests/test_evidence_log_cap.py
git commit -m "fix(soul): cap evidence_log at 50 entries per field, archive overflow"
```

---

### Task 6.3-1: `memory_l2._fetch_archived_events` 增量扫描

**Files:**
- Modify: `core/memory_l2.py:75-84`（`_fetch_archived_events`）
- Modify: `core/global_state.py:38-41` — 在 `init_global_state` 里加一个新字段 `last_l2_scan_at`（默认 null）
- Test: `tests/test_l2_incremental_scan.py`（新建）

**Rule:** 在 `global_state.json` 增加 `last_l2_scan_at` 字段；`_fetch_archived_events` 查询时加 `created_at > last_l2_scan_at` 过滤；scan 完成后更新时间戳。初始值 null → 不加过滤，首次全扫。

- [ ] **Step 1: 写失败测试**

```python
"""_fetch_archived_events 增量扫描：仅扫 last_l2_scan_at 之后的事件。"""
from unittest.mock import MagicMock, patch

from core import memory_l2


def test_fetch_archived_uses_last_scan_filter():
    mock_tbl = MagicMock()
    mock_tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = []

    with patch("core.memory_l2._get_table", return_value=mock_tbl), \
         patch("core.memory_l2._read_last_scan_at", return_value="2026-04-10T00:00:00"):
        memory_l2._fetch_archived_events("a1")

    where_call = mock_tbl.search.return_value.where.call_args
    query_str = where_call[0][0]
    assert "status = 'archived'" in query_str
    assert "created_at > '2026-04-10T00:00:00'" in query_str


def test_fetch_archived_without_last_scan_full_scan():
    mock_tbl = MagicMock()
    mock_tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = []

    with patch("core.memory_l2._get_table", return_value=mock_tbl), \
         patch("core.memory_l2._read_last_scan_at", return_value=None):
        memory_l2._fetch_archived_events("a1")

    query_str = mock_tbl.search.return_value.where.call_args[0][0]
    assert "status = 'archived'" in query_str
    assert "created_at >" not in query_str


def test_check_and_generate_patterns_updates_last_scan_at(tmp_path, monkeypatch):
    # 简化：验证调用 _write_last_scan_at
    monkeypatch.setattr(memory_l2, "_fetch_archived_events", lambda a: [])
    calls = {}
    monkeypatch.setattr(memory_l2, "_write_last_scan_at",
                        lambda aid, ts: calls.setdefault("ts", ts))
    memory_l2.check_and_generate_patterns("a1")
    # 即使无事件，也应更新（防止下次全扫）
    assert "ts" in calls
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_l2_incremental_scan.py -v`
Expected: AttributeError（`_read_last_scan_at` / `_write_last_scan_at` 未定义）

- [ ] **Step 3: 改 memory_l2.py**

在 `_fetch_archived_events` 之前加 helpers（顶部附近）：

```python
def _read_last_scan_at(agent_id: str) -> str | None:
    from core.global_state import read_global_state
    try:
        state = read_global_state(agent_id)
        return state.get("last_l2_scan_at") or None
    except Exception:
        return None


def _write_last_scan_at(agent_id: str, timestamp: str) -> None:
    from core.global_state import update_global_state
    try:
        update_global_state(agent_id, "last_l2_scan_at", timestamp)
    except Exception as e:
        logger.warning(f"_write_last_scan_at failed agent_id={agent_id} error={e}")
```

替换 `_fetch_archived_events`：

```python
def _fetch_archived_events(agent_id: str) -> list[dict]:
    """增量扫：仅取 created_at > last_l2_scan_at 的 archived 事件。
    首次扫（无时间戳）时走全扫。"""
    from core.memory_l1 import _get_table
    try:
        tbl = _get_table(agent_id)
        last_at = _read_last_scan_at(agent_id)
        if last_at:
            where_clause = f"status = 'archived' AND created_at > '{last_at}'"
        else:
            where_clause = "status = 'archived'"
        rows = tbl.search().where(where_clause).limit(9999).to_list()
        return rows
    except Exception as e:
        logger.warning(f"_fetch_archived_events agent_id={agent_id} error={e}")
        return []
```

在 `check_and_generate_patterns` 函数末尾（`_write_patterns` 之后、`return` 之前）加：

```python
    # 推进 last_l2_scan_at（即使没 pattern 也更新，避免下次重扫）
    _write_last_scan_at(agent_id, _now())
```

- [ ] **Step 4: 改 global_state.py**

在 `init_global_state` 返回的 dict 里加一个字段（现有结构顶层）：

```python
    state = {
        "agent_id": agent_id,
        "updated_at": datetime.now().isoformat(),
        "current_state": { ... },
        "personality_params": { ... },
        "decay_config": _collect_config("DECAY_"),
        "graph_config": _collect_config("GRAPH_"),
        "last_l2_scan_at": None,   # ← 新增
    }
```

注意：现有 agent 的 `global_state.json` 不会自动补字段。`update_global_state` 的 setter 仅当路径存在时才能写。因此：

改 `update_global_state`（global_state.py:66），让顶层字段即使不存在也能创建：

```python
def update_global_state(agent_id: str, field: str, value) -> None:
    """
    更新指定字段，支持点路径（如 "current_state.mood"）。
    顶层字段不存在时自动创建；中间节点不存在时抛出 KeyError。
    """
    state = read_global_state(agent_id)
    parts = field.split(".")
    obj = state
    for part in parts[:-1]:
        if part not in obj:
            raise KeyError(f"global_state: invalid field path segment '{part}' in '{field}'")
        obj = obj[part]
    obj[parts[-1]] = value
    state["updated_at"] = datetime.now().isoformat()
    _write(agent_id, state)
    logger.info(f"update_global_state agent_id={agent_id} field={field}")
```

（其实原函数已经支持顶层字段的创建，因为最后一段直接 `obj[parts[-1]] = value`——验证后无需改。若原代码已 OK，跳过此步。）

- [ ] **Step 5: 确认测试通过**

Run: `pytest tests/test_l2_incremental_scan.py -v`
Expected: 3 passed

- [ ] **Step 6: 跑全量测试**

Run: `pytest tests/ -x -q`

- [ ] **Step 7: Commit**

```bash
git add core/memory_l2.py core/global_state.py tests/test_l2_incremental_scan.py
git commit -m "perf(memory_l2): incremental archived-event scan via last_l2_scan_at"
```

---

### Task 1.2: 边 strength < 0.05 改休眠

**Files:**
- Modify: `core/memory_graph.py:338-374`（`decay_edges`）
- Test: `tests/test_decay_edges_dormant.py`（新建）

**Rule:** 原来 DELETE 改为 `UPDATE status='dormant'`。返回 dict 改为 `{"decayed": int, "dormanted": int}`。

- [ ] **Step 1: 写失败测试**

```python
"""decay_edges：strength < 0.05 的边改为 dormant，不删除。"""
import sqlite3

from core.memory_graph import MemoryGraph, _get_conn


def _insert_edge(conn, agent_id, link_id, strength):
    conn.execute(
        """
        INSERT INTO memory_links
        (link_id, agent_id, source_event_id, target_event_id,
         strength, activation_count, created_at, status)
        VALUES (?, ?, ?, ?, ?, 0, '2026-04-01T00:00:00', 'active')
        """,
        (link_id, agent_id, "e-src", f"e-tgt-{link_id}", strength),
    )
    conn.commit()


def test_decay_edges_dormants_instead_of_deletes(tmp_path, monkeypatch):
    import core.memory_graph as mg
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    agent_id = "a1"
    (tmp_path / agent_id).mkdir()

    conn = _get_conn(agent_id)
    # 0.10 * 0.99 = 0.099 → 保持 decayed
    _insert_edge(conn, agent_id, "link-keep", 0.10)
    # 0.05 * 0.99 = 0.0495 → < 0.05 → dormant
    _insert_edge(conn, agent_id, "link-dormant", 0.05)
    # 0.03 * 0.99 = 0.0297 → dormant
    _insert_edge(conn, agent_id, "link-already-low", 0.03)
    conn.close()

    result = MemoryGraph().decay_edges(agent_id)
    assert result["decayed"] == 1
    assert result["dormanted"] == 2
    # 重要：没有被物理删除
    conn = _get_conn(agent_id)
    rows = conn.execute(
        "SELECT link_id, status FROM memory_links WHERE agent_id = ?", (agent_id,)
    ).fetchall()
    conn.close()
    all_link_ids = {r["link_id"] for r in rows}
    assert all_link_ids == {"link-keep", "link-dormant", "link-already-low"}
    status_map = {r["link_id"]: r["status"] for r in rows}
    assert status_map["link-keep"] == "active"
    assert status_map["link-dormant"] == "dormant"
    assert status_map["link-already-low"] == "dormant"
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_decay_edges_dormant.py -v`
Expected: FAIL（低强度边被 DELETE）

- [ ] **Step 3: 改 `decay_edges`**

替换 `core/memory_graph.py:338-374`：

```python
    def decay_edges(self, agent_id: str) -> dict:
        """
        边的 strength 每日衰减：
          strength = strength × GRAPH_EDGE_DECAY_RATE
          strength < 0.05 → 改为 dormant（保留边，不删除）
        返回：{"decayed": int, "dormanted": int}
        """
        decay_rate = config.GRAPH_EDGE_DECAY_RATE
        dormant_threshold = 0.05

        conn = _get_conn(agent_id)
        try:
            rows = conn.execute(
                "SELECT link_id, strength FROM memory_links "
                "WHERE agent_id = ? AND status = 'active'",
                (agent_id,),
            ).fetchall()

            decayed = 0
            dormanted = 0
            for row in rows:
                new_strength = row["strength"] * decay_rate
                if new_strength < dormant_threshold:
                    conn.execute(
                        "UPDATE memory_links SET strength = ?, status = 'dormant' "
                        "WHERE link_id = ?",
                        (new_strength, row["link_id"]),
                    )
                    dormanted += 1
                else:
                    conn.execute(
                        "UPDATE memory_links SET strength = ? WHERE link_id = ?",
                        (new_strength, row["link_id"]),
                    )
                    decayed += 1
            conn.commit()
        finally:
            conn.close()

        logger.info(f"decay_edges agent_id={agent_id} decayed={decayed} dormanted={dormanted}")
        return {"decayed": decayed, "dormanted": dormanted}
```

- [ ] **Step 4: 确认测试通过 + 全量测试**

Run: `pytest tests/test_decay_edges_dormant.py -v`
Expected: 1 passed

Run: `pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add core/memory_graph.py tests/test_decay_edges_dormant.py
git commit -m "fix(memory_graph): dormant instead of delete for edges below 0.05"
```

---

### Task 1.3: 去掉 revived 状态

**Files:**
- Modify: `core/memory_graph.py:245-336`（`check_dormant_revival`）
- Modify: `core/retrieval.py:96-101`（`_freshness_text`）、`core/retrieval.py:214`、`core/retrieval.py:255`
- Modify: `core/memory_l1.py:300`（docstring）
- Modify: `docs/digital_human_spec_v6-2.md`（status 四态 → 三态段落）
- Test: `tests/test_dormant_revives_to_active.py`（新建）

**Rule:** dormant 复活直接回 `active`（不再有 `revived` 状态）；retrieval 的 where 条件和 freshness_text 分支同步更新；docstring / spec 同步。

- [ ] **Step 1: 写失败测试**

```python
"""dormant 事件满足条件后直接 revive 到 active，不再有 revived 状态。"""
from unittest.mock import MagicMock, patch

from core.memory_graph import MemoryGraph


def _mk_tbl_returning(dormant_rows, neighbor_rows_by_id):
    tbl = MagicMock()
    def where_handler(clause):
        search = MagicMock()
        if "status = 'dormant'" in clause:
            search.limit.return_value.to_list.return_value = dormant_rows
        else:
            # 邻居 active 查询
            import re
            m = re.search(r"event_id = '([^']+)'", clause)
            nid = m.group(1) if m else ""
            search.limit.return_value.to_list.return_value = neighbor_rows_by_id.get(nid, [])
        return search
    tbl.search.return_value.where.side_effect = where_handler
    return tbl


def test_revival_uses_active_not_revived(tmp_path, monkeypatch):
    import core.memory_graph as mg
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a1").mkdir()

    # 一条 dormant 事件 + 3 个 active 邻居（满足阈值）
    dormant_rows = [{"event_id": "d1"}]
    neighbors_available = {
        "n1": [{"event_id": "n1"}],
        "n2": [{"event_id": "n2"}],
        "n3": [{"event_id": "n3"}],
    }

    fake_tbl = _mk_tbl_returning(dormant_rows, neighbors_available)

    # 在 graph.db 里放三条边连到 d1
    conn = mg._get_conn("a1")
    for i, nid in enumerate(["n1", "n2", "n3"]):
        conn.execute(
            "INSERT INTO memory_links (link_id, agent_id, source_event_id, target_event_id, "
            "strength, activation_count, created_at, status) "
            "VALUES (?, ?, ?, ?, 0.5, 1, '2026-04-01T00:00:00', 'active')",
            (f"l{i}", "a1", "d1", nid),
        )
    conn.commit()
    conn.close()

    statuses_set = []
    def capture_status(agent_id, event_id, status):
        statuses_set.append(status)

    with patch("core.memory_graph._get_table", return_value=fake_tbl), \
         patch("core.memory_graph.update_event_status", side_effect=capture_status):
        revived = MemoryGraph().check_dormant_revival("a1")

    assert revived == ["d1"]
    assert statuses_set == ["active"], \
        f"revival must set status to 'active', got {statuses_set}"
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_dormant_revives_to_active.py -v`
Expected: FAIL（当前设置 "revived"）

- [ ] **Step 3: 改 memory_graph.py `check_dormant_revival`**

找到 `core/memory_graph.py:320`，将 `update_event_status(agent_id, event_id, "revived")` 改为 `update_event_status(agent_id, event_id, "active")`。

同时更新该函数 docstring（L245-253）：

```python
    def check_dormant_revival(self, agent_id: str) -> list[str]:
        """
        检查 dormant 事件是否满足复活条件：
          active 邻居数 >= GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT
          且这些邻居的 access_count > 0，created_at 在近 7 天内
        满足条件：
          → 调用 memory_l1.update_event_status 改为 active（从 dormant 直接恢复）
          → 更新 decay_score 为 DORMANT_THRESHOLD + 0.1
        返回被复活的 event_id 列表。
        """
```

- [ ] **Step 4: 改 retrieval.py**

**4.1** `_freshness_text`（L82-101）去掉 revived 分支：

```python
def _freshness_text(days_elapsed: int, status: str) -> str:
    if days_elapsed == 0:
        base = ""
    elif days_elapsed <= 3:
        base = f"（{days_elapsed}天前的记忆）"
    elif days_elapsed <= 14:
        base = f"（约{days_elapsed}天前的记忆，细节可能模糊）"
    elif days_elapsed <= 30:
        weeks = max(1, round(days_elapsed / 7))
        base = f"（约{weeks}周前的记忆，细节可能不准确）"
    else:
        months = max(1, round(days_elapsed / 30))
        base = f"（{months}个月前的记忆，仅保留大致印象）"

    if status == "dormant":
        base += "（这段记忆已经很模糊了）"

    return base
```

**4.2** where 子句（L214）：
```python
            .where("status = 'active' OR status = 'dormant'")
```

**4.3** 图扩展邻居状态过滤（L255）：
```python
                if nrow and nrow.get("status") in ("active", "dormant"):
```

- [ ] **Step 5: 改 memory_l1.py 文档串**

`core/memory_l1.py:300` docstring：
```python
    """更新事件状态字段（active / dormant / archived）。"""
```

- [ ] **Step 6: 改 spec 文档**

在 `docs/digital_human_spec_v6-2.md` 中搜索 "四态" 关键词，把相关章节改为三态。关键改动：
- L376 `**status四态（v6新增revived）：**` → `**status 三态：**`
- L379 删除 `- revived：从 dormant 恢复 ...` 这一行
- L442 `→ status 从 dormant 改为 revived` → `→ status 从 dormant 直接恢复为 active`
- L473 `dormant 事件满足复活条件后 status 变为 revived` → `... 变为 active`
- L867 附近的 `elif event.status == "revived":` 伪代码段删除或合并到 dormant 分支

不要扩写：spec 是参考文档，只做最小必要同步。

- [ ] **Step 7: 确认测试通过 + 全量测试**

Run: `pytest tests/test_dormant_revives_to_active.py -v`
Expected: 1 passed

Run: `pytest tests/ -x -q`
Expected: 全部通过（若有既有 test 期待 "revived"，一并更新）

- [ ] **Step 8: Commit**

```bash
git add core/memory_graph.py core/retrieval.py core/memory_l1.py docs/digital_human_spec_v6-2.md tests/test_dormant_revives_to_active.py
git commit -m "refactor: remove revived status, dormant events restore to active"
```

---

## Phase 2: P1 功能

### Task 1.4: 边强度提升冷却机制

**Files:**
- Modify: `core/memory_graph.py`（`_CREATE_TABLE_SQL` 加列 + `strengthen_links_on_retrieval`）
- Test: `tests/test_strengthen_cooldown.py`（新建）

**Rule:** 给每条边加 `strengthen_history TEXT DEFAULT '[]'` 列（JSON 时间戳列表）。每次 `strengthen_links_on_retrieval` 前先读该列，统计最近 24h/7d/30d 次数，若达上限则跳过本次增强。上限：24h/3、7d/10、30d/20。超 30 天的时间戳清理掉避免膨胀。

- [ ] **Step 1: 写失败测试**

```python
"""strengthen_links_on_retrieval 冷却：24h/3, 7d/10, 30d/20 上限。"""
import json
from datetime import datetime, timedelta

import core.memory_graph as mg


def _iso(dt):
    return dt.isoformat()


def _insert_edge_with_history(conn, agent_id, link_id, history_timestamps):
    # 确保新列存在
    conn.execute(
        "INSERT INTO memory_links (link_id, agent_id, source_event_id, target_event_id, "
        "strength, activation_count, created_at, status, strengthen_history) "
        "VALUES (?, ?, ?, ?, 0.5, 0, ?, 'active', ?)",
        (link_id, agent_id, "A", "B", _iso(datetime.now() - timedelta(days=50)),
         json.dumps(history_timestamps)),
    )
    conn.commit()


def test_cooldown_blocks_when_24h_cap_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a1").mkdir()
    conn = mg._get_conn("a1")
    now = datetime.now()
    # 24h 内已经 3 次
    history = [_iso(now - timedelta(hours=i)) for i in (1, 5, 10)]
    _insert_edge_with_history(conn, "a1", "L", history)
    conn.close()

    g = mg.MemoryGraph()
    updated = g.strengthen_links_on_retrieval("a1", ["A", "B"])
    # 冷却命中 → 不增 strength，不追加 history
    conn = mg._get_conn("a1")
    row = conn.execute(
        "SELECT strength, strengthen_history FROM memory_links WHERE link_id = 'L'"
    ).fetchone()
    conn.close()
    assert abs(row["strength"] - 0.5) < 1e-6, f"strength should not change, got {row['strength']}"
    hist = json.loads(row["strengthen_history"])
    assert len(hist) == 3, f"history length should stay 3, got {len(hist)}"


def test_no_cap_reached_still_strengthens(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a2").mkdir()
    conn = mg._get_conn("a2")
    _insert_edge_with_history(conn, "a2", "L2", [])
    conn.close()

    g = mg.MemoryGraph()
    g.strengthen_links_on_retrieval("a2", ["A", "B"])
    conn = mg._get_conn("a2")
    row = conn.execute(
        "SELECT strength, strengthen_history FROM memory_links WHERE link_id = 'L2'"
    ).fetchone()
    conn.close()
    assert row["strength"] > 0.5
    hist = json.loads(row["strengthen_history"])
    assert len(hist) == 1
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_strengthen_cooldown.py -v`
Expected: `no such column: strengthen_history`（或 schema 不对）

- [ ] **Step 3: 改 memory_graph.py**

**3.1** 加 schema 迁移 helper（文件顶部，`_get_conn` 之后）：

```python
_COOLDOWN_LIMITS = [
    ("24h", timedelta(hours=24), 3),
    ("7d",  timedelta(days=7),   10),
    ("30d", timedelta(days=30),  20),
]


def _ensure_strengthen_history_column(conn: sqlite3.Connection) -> None:
    """SQLite 不支持 ADD COLUMN IF NOT EXISTS，用 try/except 实现幂等。"""
    try:
        conn.execute(
            "ALTER TABLE memory_links ADD COLUMN strengthen_history TEXT DEFAULT '[]'"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 列已存在
```

修改 `_get_conn`，在 executescript 之后调用：

```python
def _get_conn(agent_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(agent_id)))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLE_SQL)
    _ensure_strengthen_history_column(conn)
    conn.commit()
    return conn
```

同时在 `_CREATE_TABLE_SQL` 里新增该列（让新建 agent 也有），修改后：

```python
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_links (
    link_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    activation_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_activated TEXT,
    status TEXT DEFAULT 'active',
    strengthen_history TEXT DEFAULT '[]',
    UNIQUE(agent_id, source_event_id, target_event_id)
);
CREATE INDEX IF NOT EXISTS idx_links_source
    ON memory_links(agent_id, source_event_id, status);
CREATE INDEX IF NOT EXISTS idx_links_target
    ON memory_links(agent_id, target_event_id, status);
"""
```

**3.2** 加冷却判断 helper：

```python
def _is_on_cooldown(history_json: str, now: datetime) -> bool:
    try:
        timestamps = json.loads(history_json or "[]")
    except Exception:
        return False
    if not timestamps:
        return False
    parsed = []
    for ts in timestamps:
        try:
            parsed.append(datetime.fromisoformat(ts))
        except Exception:
            continue
    for label, delta, cap in _COOLDOWN_LIMITS:
        cutoff = now - delta
        count = sum(1 for t in parsed if t >= cutoff)
        if count >= cap:
            return True
    return False


def _prune_strengthen_history(history_json: str, now: datetime) -> list[str]:
    """只保留最近 30 天的时间戳，避免无限增长。"""
    try:
        timestamps = json.loads(history_json or "[]")
    except Exception:
        return []
    cutoff = now - timedelta(days=30)
    kept = []
    for ts in timestamps:
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                kept.append(ts)
        except Exception:
            continue
    return kept
```

文件顶部加 `import json`（若未引入）。

**3.3** 替换 `strengthen_links_on_retrieval`：

```python
    def strengthen_links_on_retrieval(self, agent_id: str, retrieved_event_ids: list) -> int:
        """
        共现边加强，含冷却：
          同一条边在 24h/7d/30d 内达到次数上限时跳过本轮增强。
        strength 上限 1.0，单次增量 config.GRAPH_RETRIEVAL_STRENGTHEN_INCREMENT。
        """
        increment = config.GRAPH_RETRIEVAL_STRENGTHEN_INCREMENT
        ids = list(retrieved_event_ids)
        if len(ids) < 2:
            return 0

        updated = 0
        now = datetime.now()
        now_str = now.isoformat()
        conn = _get_conn(agent_id)
        try:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    src, tgt = ids[i], ids[j]
                    row = conn.execute(
                        """
                        SELECT link_id, strength, activation_count, strengthen_history
                        FROM memory_links
                        WHERE agent_id = ?
                          AND ((source_event_id = ? AND target_event_id = ?)
                            OR (source_event_id = ? AND target_event_id = ?))
                        LIMIT 1
                        """,
                        (agent_id, src, tgt, tgt, src),
                    ).fetchone()

                    if row:
                        history_json = row["strengthen_history"] or "[]"
                        if _is_on_cooldown(history_json, now):
                            logger.debug(
                                f"strengthen_links cooldown hit link_id={row['link_id']}"
                            )
                            continue
                        pruned = _prune_strengthen_history(history_json, now)
                        pruned.append(now_str)
                        new_strength = min(1.0, row["strength"] + increment)
                        conn.execute(
                            """
                            UPDATE memory_links
                            SET strength = ?,
                                activation_count = activation_count + 1,
                                last_activated = ?,
                                strengthen_history = ?
                            WHERE link_id = ?
                            """,
                            (new_strength, now_str, json.dumps(pruned), row["link_id"]),
                        )
                        updated += 1
                    else:
                        link_id = str(uuid.uuid4())
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO memory_links
                            (link_id, agent_id, source_event_id, target_event_id,
                             strength, activation_count, created_at, last_activated,
                             status, strengthen_history)
                            VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'active', ?)
                            """,
                            (link_id, agent_id, src, tgt, min(1.0, increment),
                             now_str, now_str, json.dumps([now_str])),
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            updated += 1
            conn.commit()
        finally:
            conn.close()

        logger.info(f"strengthen_links_on_retrieval agent_id={agent_id} updated={updated}")
        return updated
```

- [ ] **Step 4: 确认测试通过 + 全量测试**

Run: `pytest tests/test_strengthen_cooldown.py -v`
Expected: 2 passed

Run: `pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add core/memory_graph.py tests/test_strengthen_cooldown.py
git commit -m "feat(memory_graph): cooldown for edge strengthening (24h/7d/30d caps)"
```

---

### Task 3.8: 轻量寒暄旁路

**Files:**
- Modify: `core/dialogue.py:137-234`（`chat`），在入口加短路判断
- Create: `prompts/smalltalk_detect.txt` (轻量 LLM 判断 prompt)
- Test: `tests/test_smalltalk_bypass.py`（新建）

**Rule:** `chat()` 入口先用关键词规则判断；若不足以断定（5 字以上），调用一次快速 LLM（`max_tokens=4`）判"寒暄/告别/实质对话"三分类。寒暄/告别 → 跳过 retrieval / soul_anchor / 多次 LLM 打分，直接用简化 prompt 生成短回复；实质对话 → 走原流程。

- [ ] **Step 1: 写 prompts/smalltalk_detect.txt**

```
你是一个文本分类器。判断输入是哪一类：
- smalltalk：简单寒暄（你好/早/吃了吗/在忙啥/天气）
- farewell：告别（再见/下次聊/晚安）
- substantive：有实质内容的对话（问问题、表达情绪、描述事件、谈观点）

只输出一个词：smalltalk / farewell / substantive。不要加任何其他文本。

---

输入：{user_message}
分类：
```

- [ ] **Step 2: 写失败测试**

```python
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
        r = dialogue.chat("a1", "你好", [], set())

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
        dialogue.chat("a1", "我最近被工作压垮了，觉得一切都没意义", [], set())

    assert retrieve_called["n"] == 1
```

- [ ] **Step 3: 确认测试失败**

Run: `pytest tests/test_smalltalk_bypass.py -v`
Expected: FAIL（目前 retrieve 总被调用）

- [ ] **Step 4: 改 core/dialogue.py**

在 `_load_prompt` 调用段附近（L35）加载 smalltalk prompt：

```python
_SMALLTALK_SYS, _SMALLTALK_USR = _load_prompt("smalltalk_detect.txt")
```

加两个 helper（`_detect_emotion` 附近）：

```python
_SMALLTALK_KEYWORDS = {"你好", "您好", "早", "早上好", "晚安", "嗨", "hi", "hello"}
_FAREWELL_KEYWORDS  = {"再见", "拜拜", "下次", "先这样", "bye", "goodbye"}


def _classify_smalltalk(user_message: str) -> str:
    """返回 'smalltalk' / 'farewell' / 'substantive'。
    硬编码关键词优先；否则 1 次 LLM 快判。"""
    msg = user_message.strip().lower()
    if not msg:
        return "substantive"
    # 短输入 + 硬编码关键词
    if len(msg) <= 6:
        for kw in _SMALLTALK_KEYWORDS:
            if msg.startswith(kw) or msg == kw:
                return "smalltalk"
        for kw in _FAREWELL_KEYWORDS:
            if msg.startswith(kw) or msg == kw:
                return "farewell"
    # 调用 LLM
    try:
        raw = chat_completion(
            [{"role": "system", "content": _SMALLTALK_SYS},
             {"role": "user",   "content": _SMALLTALK_USR.format(user_message=user_message)}],
            max_tokens=4,
            temperature=0.0,
        ).strip().lower()
        if raw in ("smalltalk", "farewell", "substantive"):
            return raw
    except Exception as e:
        logger.warning(f"_classify_smalltalk failed: {e}")
    return "substantive"


def _smalltalk_reply(agent_id: str, user_message: str, kind: str,
                     session_history: list) -> str:
    """不走 retrieve / soul_anchor，直接轻量 prompt 生成。"""
    info = _get_agent_info(agent_id)
    system = (
        f"你是 {info['name']}。用户和你打招呼/告别，简短自然地回一句（1-2 句，口语化）。"
        f"不要展开话题，不要反问太深。"
    )
    messages = [{"role": "system", "content": system}]
    for msg in session_history[-4:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})
    try:
        return chat_completion(messages, max_tokens=80, temperature=0.6)
    except Exception as e:
        logger.warning(f"_smalltalk_reply fallback: {e}")
        return "嗯。" if kind == "smalltalk" else "回头聊。"
```

在 `chat()` 函数体最开始（`if session_surfaced is None:` 之后），加短路：

```python
    # ── 0. smalltalk 旁路 ──
    kind = _classify_smalltalk(user_message)
    if kind in ("smalltalk", "farewell"):
        trace.mark("smalltalk_bypass", summary=kind)
        buf = _load_l0(agent_id)
        if not buf.get("session_id"):
            buf["session_id"] = str(uuid.uuid4())
            buf["created_at"] = _now()
        buf["raw_dialogue"].append({"role": "user", "content": user_message})
        _save_l0(agent_id, buf)

        reply = _smalltalk_reply(agent_id, user_message, kind, session_history)

        buf = _load_l0(agent_id)
        buf["raw_dialogue"].append({"role": "assistant", "content": reply})
        _save_l0(agent_id, buf)
        return {
            "reply":             reply,
            "session_surfaced":  session_surfaced,
            "emotion_intensity": 0.0,
        }
```

- [ ] **Step 5: 确认测试通过 + 全量测试**

Run: `pytest tests/test_smalltalk_bypass.py -v`
Expected: 2 passed

Run: `pytest tests/ -x -q`

- [ ] **Step 6: 人工冒烟**

Run: `python main_chat.py <agent_id> --debug`，先说"你好"，再问"我最近在想职业选择的事"。前者 trace 里应有 `smalltalk_bypass` 阶段且无 retrieval，后者走完整流程。

- [ ] **Step 7: Commit**

```bash
git add core/dialogue.py prompts/smalltalk_detect.txt tests/test_smalltalk_bypass.py
git commit -m "feat(dialogue): lightweight smalltalk/farewell bypass skipping retrieval"
```

---

### Task NEW-1: 软惩罚去重

**Files:**
- Modify: `core/retrieval.py`（`_score_candidate` + `retrieve` 去掉硬过滤）
- Test: `tests/test_soft_dedup.py`（新建）

**Rule:** 不再硬过滤 `already_surfaced`——改为在 `_score_candidate` 里对已 surface 的记忆扣分。惩罚系数 α = 0.15（先取常量，后续可迁移到 per-agent 参数）。这样高相关度的记忆仍有机会再次上榜，低相关度的被自然排挤。

- [ ] **Step 1: 写失败测试**

```python
"""软惩罚去重：already_surfaced 的记忆被扣分而非硬过滤。"""
from datetime import datetime
from unittest.mock import MagicMock, patch

from core import retrieval


def _mk_row(eid, importance=0.5, vec=None):
    return {
        "event_id": eid, "vector": vec or [0.1] * 1024, "status": "active",
        "importance": importance, "created_at": "2026-04-20T00:00:00",
        "action": "", "actor": "", "context": "", "outcome": "",
        "emotion": "", "emotion_intensity": 0.3,
    }


def test_already_surfaced_is_scored_not_filtered():
    """已 surface 的事件也进入打分，只是分数被扣。"""
    rows = [_mk_row(f"e{i}", importance=0.5) for i in range(5)]

    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = rows

    with patch("core.retrieval.get_embedding", return_value=[0.1] * 1024), \
         patch("core.retrieval.get_soul_anchor", return_value=""), \
         patch("core.retrieval.read_global_state",
               return_value={"current_state": {"mood": "", "energy": "", "stress_level": 0.3}}), \
         patch("core.retrieval._get_table", return_value=tbl), \
         patch("core.retrieval.get_event"), \
         patch("core.retrieval.MemoryGraph") as mg, \
         patch("core.retrieval.increment_access_count"), \
         patch("core.memory_l2.get_patterns_for_retrieval", return_value=[]):
        mg.return_value.get_neighbors.return_value = []

        # 把 e0,e1,e2 标为已 surfaced
        result = retrieval.retrieve("a1", "query", mode="dialogue",
                                    already_surfaced={"e0", "e1", "e2"})
    surfaced_ids = result["surfaced_ids"]
    # 候选池仍然是 5 条——不再硬过滤
    assert len(surfaced_ids) == 5
    # 已 surface 的 3 条在末尾（因为被扣分）
    assert surfaced_ids[-3:] == ["e0", "e1", "e2"] or \
           set(surfaced_ids[-3:]) == {"e0", "e1", "e2"}


def test_high_relevance_surfaced_can_still_win():
    """importance 高很多的已 surface 记忆仍可排在前面。"""
    high = _mk_row("e_high", importance=0.95)
    low  = _mk_row("e_low",  importance=0.20)

    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = [high, low]

    with patch("core.retrieval.get_embedding", return_value=[0.1] * 1024), \
         patch("core.retrieval.get_soul_anchor", return_value=""), \
         patch("core.retrieval.read_global_state",
               return_value={"current_state": {"mood": "", "energy": "", "stress_level": 0.3}}), \
         patch("core.retrieval._get_table", return_value=tbl), \
         patch("core.retrieval.get_event"), \
         patch("core.retrieval.MemoryGraph") as mg, \
         patch("core.retrieval.increment_access_count"), \
         patch("core.memory_l2.get_patterns_for_retrieval", return_value=[]):
        mg.return_value.get_neighbors.return_value = []
        result = retrieval.retrieve("a1", "query", mode="dialogue",
                                    already_surfaced={"e_high"})

    # e_high 被扣 0.15，但 importance 差距 0.75 很可能仍排第一
    assert result["surfaced_ids"][0] == "e_high"
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/test_soft_dedup.py -v`
Expected: `test_already_surfaced_is_scored_not_filtered` FAIL（硬过滤只返回 2 条）

- [ ] **Step 3: 改 retrieval.py**

**3.1** 顶部常量区加：

```python
_SURFACED_PENALTY = 0.15    # already_surfaced 的软惩罚系数
```

**3.2** 替换 `_score_candidate`（L104-128）签名和实现：

```python
def _score_candidate(row: dict, query_embedding, stress_level: float,
                     weights: dict, now: datetime,
                     already_surfaced: set | None = None) -> tuple[float, int]:
    vector = row.get("vector")
    relevance = _cosine_sim(query_embedding, vector) if vector else 0.0

    importance = float(row.get("importance", 0.0))

    created_at = row.get("created_at", "")
    try:
        dt = datetime.fromisoformat(created_at)
        days_elapsed = max(0, (now - dt).days)
    except Exception:
        days_elapsed = 0
    recency = 1.0 / (1.0 + days_elapsed)

    emotion_intensity = float(row.get("emotion_intensity", 0.0))
    mood_fit = max(0.0, min(1.0, 1.0 - abs(emotion_intensity - stress_level)))

    score = (
        relevance    * weights["relevance"]
        + importance * weights["importance"]
        + recency    * weights["recency"]
        + mood_fit   * weights["mood_fit"]
    )

    # 软惩罚：已在本会话 surface 过的记忆扣分（不过滤）
    if already_surfaced and row.get("event_id") in already_surfaced:
        score = max(0.0, score - _SURFACED_PENALTY)

    return score, days_elapsed
```

**3.3** 去掉硬过滤（L222-223），保留原注释位置：

```python
    # 不再硬过滤 already_surfaced：改为 _score_candidate 里软惩罚，保持候选池宽度
    vector_results = raw_results
```

**3.4** 图扩展邻居去重处（L252）也松一下——邻居**候选**中即使是 surfaced 也可以进：

```python
                if nid in candidate_map:
                    continue
                # 注意：already_surfaced 不再在此硬过滤
```

**3.5** `_score_candidate` 的调用处（L278）传入 already_surfaced：

```python
        score, days_elapsed = _score_candidate(
            item["row"], query_embedding, stress_level, weights, now,
            already_surfaced=already_surfaced,
        )
```

**3.6** 更新 trace 事件描述（L224-230），把 `after_dedup` 保留但意义改为"进入打分池"：

```python
    trace.event(
        "vector_search",
        raw_hits=len(raw_results),
        after_dedup=len(vector_results),   # 软惩罚后不再缩减，但保留字段便于对比
        limit=_RETRIEVAL_TOP_K,
        already_surfaced=len(already_surfaced),
    )
```

- [ ] **Step 4: 确认测试通过 + 全量测试**

Run: `pytest tests/test_soft_dedup.py -v`
Expected: 2 passed

Run: `pytest tests/ -x -q`
Expected: 全部通过（注意 `test_retrieval_trace.py` 的 `after_dedup==2` 断言仍成立，因为 vector 返回 2 条未 surface）

- [ ] **Step 5: 人工冒烟——确认不再 3 轮归零**

跑 `python main_chat.py <agent_id> --debug`，连续 5-6 轮同主题对话，每轮 trace 里 `score_rerank.candidate_pool` 应始终 ≥ 5，不再跌到 0。

- [ ] **Step 6: Commit**

```bash
git add core/retrieval.py tests/test_soft_dedup.py
git commit -m "feat(retrieval): soft penalty for already-surfaced memories, no hard filter"
```

---

## 完成核查清单

所有 subagent 任务完成后，主 agent 执行：

- [ ] 跑 benchmark 对比（`python tools/benchmark_runner.py <agent> --run-label stage1-complete`）
- [ ] 手工 diff 对比：`logs/benchmark/<agent>-baseline-*.json` vs `logs/benchmark/<agent>-stage1-complete-*.json`
  - 预期：`ok_count` 相同，无崩溃；寒暄题 `elapsed_s` 显著下降；同主题长对话 `surfaced_count` 不再归零
- [ ] 全量 pytest：`pytest tests/ -v`
- [ ] 链路索引 md 的"当前值/行号"抽查 3 条仍准确
- [ ] spec 文档（`digital_human_spec_v6-2.md`）中 revived 状态已清除
- [ ] `git log --oneline embedding_switch_to_siliconflow` 11 条 commit（+ Phase 0 的 2 条）清晰成序

## 暂缓项提醒（不在本轮范围）

- 2.3 Config 三层重构 → 下一轮统一做，期间新增参数用 config.py 顶部常量先放着
- 3.1/3.2/3.7 per-agent 参数 → 依赖 2.3
- 3.5 主动提问 → 等心跳模块
- 3.6 中英文混合 → 接受现状
- 4.1 LLM 全链路日志 → trace 已覆盖
- emotion_intensity 闭环 → 阶段二情绪模块
