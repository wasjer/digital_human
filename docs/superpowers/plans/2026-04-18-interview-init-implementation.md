# Interview-Based Agent Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third agent-initialization pathway that consumes `interview_source/*.md` (conversational interview transcripts), producing a populated `soul.json`, L1 biography + meta events, an L0 first-person narrative, an L2 pattern pass that includes all statuses during init, and a per-run `build_report.md`. Also folds in legacy `max_tokens` cleanup and an L2 init-time time-window relaxation so all three init pipelines behave consistently.

**Architecture:** New orchestrator `core/interview_seed_builder.py` runs a 2-LLM-call pipeline (seed extraction with per-field confidence + L1 event extraction), a deterministic meta-event constructor, a confidence gate that produces the runtime `soul.json`, and a markdown report writer. Reuses existing infrastructure from `seed_memory_loader.py` (`_setup_agent_dirs`, `_write_events_to_l1`, `_build_graph`, `_update_statuses`) and `soul.py` (`_build_empty_soul`, `_write_soul`, `_CORE_FIELDS`, `CORES`). Adds one `include_all_statuses` parameter to `memory_l2.check_and_generate_patterns` and updates all three init pipelines to pass it.

**Tech Stack:** Python 3, pytest, DeepSeek API via `core/llm_client.chat_completion`, LanceDB for L1, the project's existing prompt-templating convention (`\n---\n` split).

**Spec:** `docs/superpowers/specs/2026-04-17-interview-init-design.md`

---

## Phase A — Foundation (cleanup + L2 param)

### Task 1: Add config constants

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add two new constants**

Append at the bottom of `config.py`:

```python
# LLM 输出上限（当前 DeepSeek-chat 硬限 8192；换模型时一处改）
LLM_MAX_OUTPUT_TOKENS = 8192

# 访谈通路：字段 confidence 低于此值不写入 soul.json（进"回访建议"）
INTERVIEW_CONFIDENCE_THRESHOLD = 0.5
```

- [ ] **Step 2: Verify import**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "import config; print(config.LLM_MAX_OUTPUT_TOKENS, config.INTERVIEW_CONFIDENCE_THRESHOLD)"
```
Expected: `8192 0.5`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "config: add LLM_MAX_OUTPUT_TOKENS and INTERVIEW_CONFIDENCE_THRESHOLD"
```

---

### Task 2: Replace legacy max_tokens in seed_parser.py and soul.py

**Files:**
- Modify: `core/seed_parser.py:104`
- Modify: `core/soul.py:189`

- [ ] **Step 1: Update `core/seed_parser.py:104`**

Change:
```python
raw = chat_completion(messages, max_tokens=1024, temperature=0.2)
```
to:
```python
raw = chat_completion(messages, max_tokens=config.LLM_MAX_OUTPUT_TOKENS, temperature=0.2)
```

Add `import config` at the top of the file if not already imported. Verify by reading the existing imports — `seed_parser.py` currently does not import config; add it.

- [ ] **Step 2: Update `core/soul.py:189`**

Change:
```python
raw = chat_completion(messages, max_tokens=2048, temperature=0.2)
```
to:
```python
raw = chat_completion(messages, max_tokens=config.LLM_MAX_OUTPUT_TOKENS, temperature=0.2)
```

`config` is already imported at top of `soul.py`.

- [ ] **Step 3: Leave `soul.py:320` (conflict check, 256 tokens) alone**

This call outputs a small JSON verdict; not an initialization call. Don't change.

- [ ] **Step 4: Run existing soul tests**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_soul_cognitive_core.py -v
```
Expected: all pass (no regression).

- [ ] **Step 5: Commit**

```bash
git add core/seed_parser.py core/soul.py
git commit -m "refactor: route seed_parser and soul.init_soul through LLM_MAX_OUTPUT_TOKENS"
```

---

### Task 3: Route seed_memory_loader and nuwa_seed_builder through the config constant

**Files:**
- Modify: `core/seed_memory_loader.py:60-61`
- Modify: `core/nuwa_seed_builder.py:52-53`

- [ ] **Step 1: Update `core/seed_memory_loader.py`**

Replace lines 60-61:
```python
# 初始化特殊通道：不限 token
_INIT_MAX_TOKENS  = 8192
_BATCH_MAX_TOKENS = 8192
```
with:
```python
# 初始化特殊通道：用 config 上限（LLM 输出硬限，换模型时一处改）
_INIT_MAX_TOKENS  = config.LLM_MAX_OUTPUT_TOKENS
_BATCH_MAX_TOKENS = config.LLM_MAX_OUTPUT_TOKENS
```

`config` is already imported at the top of this file (line 38).

- [ ] **Step 2: Update `core/nuwa_seed_builder.py`**

Replace lines 52-53:
```python
_INIT_MAX_TOKENS  = 8192
_BATCH_MAX_TOKENS = 8192
```
with:
```python
_INIT_MAX_TOKENS  = config.LLM_MAX_OUTPUT_TOKENS
_BATCH_MAX_TOKENS = config.LLM_MAX_OUTPUT_TOKENS
```

`config` is already imported at the top of this file.

- [ ] **Step 3: Sanity-import both modules**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "from core import seed_memory_loader, nuwa_seed_builder; print(seed_memory_loader._INIT_MAX_TOKENS, nuwa_seed_builder._INIT_MAX_TOKENS)"
```
Expected: `8192 8192`

- [ ] **Step 4: Commit**

```bash
git add core/seed_memory_loader.py core/nuwa_seed_builder.py
git commit -m "refactor: route seed/nuwa init max_tokens through LLM_MAX_OUTPUT_TOKENS"
```

---

### Task 4: Bump chat_completion default max_tokens to 4096

**Files:**
- Modify: `core/llm_client.py:75`

- [ ] **Step 1: Change the default**

Replace:
```python
def chat_completion(
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
```
with:
```python
def chat_completion(
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
```

- [ ] **Step 2: Quick sanity import**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "import inspect; from core.llm_client import chat_completion; print(inspect.signature(chat_completion))"
```
Expected: signature shows `max_tokens: int = 4096`.

- [ ] **Step 3: Commit**

```bash
git add core/llm_client.py
git commit -m "refactor(llm_client): raise chat_completion default max_tokens 1024 -> 4096"
```

---

### Task 5: Add `include_all_statuses` to `check_and_generate_patterns` + `_fetch_all_events`

**Files:**
- Modify: `core/memory_l2.py` (add helper + extend function signature)
- Test: `tests/test_memory_l2_init_mode.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_l2_init_mode.py`:

```python
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import inspect
from core import memory_l2


def test_check_and_generate_patterns_has_include_all_statuses_param():
    sig = inspect.signature(memory_l2.check_and_generate_patterns)
    assert "include_all_statuses" in sig.parameters
    # Default must be False to preserve decay-job behavior
    assert sig.parameters["include_all_statuses"].default is False


def test_fetch_all_events_exists_and_callable():
    assert hasattr(memory_l2, "_fetch_all_events")
    assert callable(memory_l2._fetch_all_events)


def test_fetch_all_events_returns_list_when_no_table(tmp_path, monkeypatch):
    # Without an existing agent table, should return []
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path / "agents")
    result = memory_l2._fetch_all_events("nonexistent_agent")
    assert result == []
```

- [ ] **Step 2: Run the test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_memory_l2_init_mode.py -v
```
Expected: FAIL — `include_all_statuses` not in signature, `_fetch_all_events` does not exist.

- [ ] **Step 3: Add `_fetch_all_events` helper**

In `core/memory_l2.py`, add immediately after `_fetch_archived_events` (around line 85):

```python
def _fetch_all_events(agent_id: str) -> list[dict]:
    """从 LanceDB 取该 agent 所有事件（忽略 status），用于初始化时的 L2 归纳。"""
    from core.memory_l1 import _get_table
    try:
        tbl  = _get_table(agent_id)
        rows = tbl.search().limit(99999).to_list()
        return rows
    except Exception as e:
        logger.warning(f"_fetch_all_events agent_id={agent_id} error={e}")
        return []
```

- [ ] **Step 4: Extend `check_and_generate_patterns` signature**

Change line 116 from:
```python
def check_and_generate_patterns(agent_id: str) -> list[str]:
```
to:
```python
def check_and_generate_patterns(
    agent_id: str,
    include_all_statuses: bool = False,
) -> list[str]:
```

Then change lines 128-132:
```python
    # 2. 取 archived 事件
    archived_events = _fetch_archived_events(agent_id)
    if not archived_events:
        logger.info(f"check_and_generate_patterns agent_id={agent_id} no archived events, skip")
        return []
```
to:
```python
    # 2. 取事件（初始化通路用 include_all_statuses=True 囊括 active/dormant）
    if include_all_statuses:
        candidate_events = _fetch_all_events(agent_id)
        reason = "all-statuses mode"
    else:
        candidate_events = _fetch_archived_events(agent_id)
        reason = "archived-only mode"
    if not candidate_events:
        logger.info(f"check_and_generate_patterns agent_id={agent_id} no events ({reason}), skip")
        return []
```

Then change line 136 from:
```python
    for ev in archived_events:
```
to:
```python
    for ev in candidate_events:
```

- [ ] **Step 5: Run the test and verify it passes**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_memory_l2_init_mode.py -v
```
Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add core/memory_l2.py tests/test_memory_l2_init_mode.py
git commit -m "feat(memory_l2): add include_all_statuses param for init-time pattern generation"
```

---

### Task 6: Update existing init pipelines to pass `include_all_statuses=True`

**Files:**
- Modify: `core/seed_memory_loader.py` (L2 call site)
- Modify: `core/nuwa_seed_builder.py` (L2 call site)

- [ ] **Step 1: Update `seed_memory_loader.py`**

Find this line (~ line 433):
```python
    l2_updated = check_and_generate_patterns(agent_id)
```
Change to:
```python
    l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)
```

- [ ] **Step 2: Update `nuwa_seed_builder.py`**

Find this line (~ line 261):
```python
    l2_updated = check_and_generate_patterns(agent_id)
```
Change to:
```python
    l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)
```

- [ ] **Step 3: Sanity import**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "from core import seed_memory_loader, nuwa_seed_builder; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add core/seed_memory_loader.py core/nuwa_seed_builder.py
git commit -m "feat(init): seed/nuwa pipelines request all-status L2 generation"
```

---

## Phase B — Interview builder

### Task 7: Write `prompts/interview_to_seed.txt`

**Files:**
- Create: `prompts/interview_to_seed.txt`

- [ ] **Step 1: Write the prompt**

Create `prompts/interview_to_seed.txt`:

````text
你是一个深度人格建模专家。你将读取一段访谈对话（访谈员与受访者的完整 Q&A），为受访者提取结构化人格信息，每个字段带 confidence。

## 任务目标

1. 提取受访者的基础身份（name/age/occupation/location）
2. 提取五大核心（emotion/value/goal/relation/cognitive），每个核心覆盖 constitutional（天性底色）/ slow_change（长期偏好）/ elastic（当下状态）三区
3. 为每个可推断字段输出 `{"value": ..., "confidence": 0~1}`
4. 额外产出：`recent_self_narrative`（第一人称 200~400 字摘要，供 L0 注入）
5. 额外产出：`follow_up_questions`（对 confidence < 0.5 的字段给出下一轮访谈的建议追问）

## 绝对规则

1. **禁止用常识/刻板印象补空**。只允许用访谈中明确出现或强证据可推断的信息。
2. confidence 标定：
   - ≥ 0.7：访谈中有 ≥ 2 处一致证据
   - 0.5~0.7：有 1 处较明确的证据
   - < 0.5：仅凭语气/态度揣测，或孤证
   - 0.0：无任何线索
3. 没线索的字段必须输出 `{"value": null, "confidence": 0.0}`，**绝对不允许留空键**。
4. `expression_exemplars` 必须逐字抄 10 条受访者原句（完整句子，不是片段，不改写）。若访谈过短无法抄满 10 条，抄多少条就是多少，confidence 降到 0.6。
5. `recent_self_narrative` 是第一人称叙述（"我前几天参加了一次访谈…我聊到…"），不是第三人称总结。描述这次访谈聊了什么、我讲了哪些关键自述。200~400 字。
6. `follow_up_questions` 以 dict 形式给出，键为 `"<core>.<field>"`（如 `"relation_core.attachment_style"`），值为 1-2 条具体的追问文字的 list。**只列 confidence < 0.5 的字段**，confidence ≥ 0.5 的字段不要出现在这个 dict 里。
7. 只输出 JSON，不加任何解释或 markdown 代码块。
8. 所有字段值使用中文。

---

访谈基本信息：
- agent_id：{agent_id}
- 访谈时间：{interview_date}
- 访谈时长：{duration_minutes} 分钟

访谈全文：
{dialogue_text}

请输出以下 JSON 结构：

{{
  "name":       {{"value": "...", "confidence": 0.0}},
  "age":        {{"value": 0,     "confidence": 0.0}},
  "occupation": {{"value": "...", "confidence": 0.0}},
  "location":   {{"value": "...", "confidence": 0.0}},

  "emotion_core": {{
    "base_emotional_type":        {{"value": "对天生情感特质的描述（感知方式、共情模式、情绪底色）", "confidence": 0.0}},
    "emotional_regulation_style": {{"value": "长期形成的情绪处理调节方式", "confidence": 0.0}},
    "current_emotional_state":    {{"value": "当前情绪状态", "confidence": 0.0}}
  }},

  "value_core": {{
    "moral_baseline":       {{"value": "最深层的道德底线和核心价值观", "confidence": 0.0}},
    "value_priority_order": {{"value": "长期形成的价值优先级排序", "confidence": 0.0}},
    "current_value_focus":  {{"value": "当前最关注的价值方向", "confidence": 0.0}}
  }},

  "goal_core": {{
    "life_direction":     {{"value": "内心最根本的人生方向感", "confidence": 0.0}},
    "mid_term_goals":     {{"value": "当前阶段（近几年）的中期目标", "confidence": 0.0}},
    "current_phase_goal": {{"value": "当下最具体、最紧迫的阶段性目标", "confidence": 0.0}}
  }},

  "relation_core": {{
    "attachment_style":       {{"value": "依恋风格和人际关系基本模式", "confidence": 0.0}},
    "key_relationships":      {{"value": ["最重要的关系列表（可以是字符串或结构化描述）"], "confidence": 0.0}},
    "current_relation_state": {{"value": "当前主要人际关系状态", "confidence": 0.0}}
  }},

  "cognitive_core": {{
    "mental_models":        {{"value": [{{"name": "模型名", "one_liner": "一句话描述"}}], "confidence": 0.0}},
    "decision_heuristics":  {{"value": [{{"rule": "决策启发式规则"}}], "confidence": 0.0}},
    "expression_dna":       {{"value": "说话风格的一句话提炼", "confidence": 0.0}},
    "expression_exemplars": {{"value": ["受访者原句1", "受访者原句2", "...共10条"], "confidence": 0.0}},
    "anti_patterns":        {{"value": ["绝不会做的事1", "..."], "confidence": 0.0}},
    "self_awareness":       {{"value": "自我认知描述", "confidence": 0.0}},
    "honest_boundaries":    {{"value": "诚实坦诚的边界描述", "confidence": 0.0}}
  }},

  "recent_self_narrative": "第一人称 200~400 字摘要，讲述这次访谈聊了什么、我讲了哪些关键自述",

  "follow_up_questions": {{
    "relation_core.attachment_style": ["建议追问 1", "建议追问 2"]
  }}
}}
````

- [ ] **Step 2: Verify file exists and parses placeholders correctly**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "
from pathlib import Path
t = Path('prompts/interview_to_seed.txt').read_text(encoding='utf-8')
# Ensure expected placeholders exist
for k in ['{agent_id}', '{interview_date}', '{duration_minutes}', '{dialogue_text}']:
    assert k in t, f'missing {k}'
print('ok')
"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add prompts/interview_to_seed.txt
git commit -m "feat(prompts): add interview_to_seed extraction prompt"
```

---

### Task 8: Write `prompts/interview_to_l1.txt`

**Files:**
- Create: `prompts/interview_to_l1.txt`

- [ ] **Step 1: Write the prompt**

Create `prompts/interview_to_l1.txt`:

````text
你是一个记忆结构化专家。你将读取一段访谈对话（访谈员与受访者的 Q&A），把受访者**自己叙述过的过往人生事件**转化为第一人称的原子事件记忆，供 L1 长期记忆层使用。

## 核心规则

1. **只抽取受访者自己叙述过的过往人生事件**。访谈员的话只用于理解语境，不要把访谈员的总结、重述或引导问题当成事件。
2. **第一人称视角**：actor 固定为受访者的名字（或 agent_id）。
3. **原子化**：每条记忆是一件具体的、独立的事件，不是抽象总结或概括。
4. **时间推断锚点**：受访者在 `{interview_date}`（{current_age} 岁）接受访谈。据此逆推每条事件的 `tags_time_year / tags_time_month / inferred_timestamp`。能推断到月份就写月份，只能确定年份就写年份。
5. **原话留档**：`raw_quote` 填受访者说过的原话（完整句子或至少一个完整表达），不要改写、不要总结。
6. **所有字段必须填实**，无法确定的字段做最合理的估算或留空字符串（但 actor/action/context/outcome 不允许空）。
7. `event_kind` 固定填 `"biography"`。
8. 所有字段值使用中文（`tags_emotion_valence` 使用：正面 / 负面 / 混合 / 中性）。
9. 只输出 JSON 数组，不加任何解释或 markdown 代码块。

## 打分标准（0~1）

- `emotion_intensity_score`：情绪强度
- `value_relevance_score`：与核心价值观的相关度
- `novelty_score`：新奇度/转折性
- `reusability_score`：可供未来决策参考的模式性
- `importance = emotion_intensity×0.3 + value_relevance×0.3 + novelty×0.2 + reusability×0.2`

---

受访者：{agent_name}
访谈时间：{interview_date}
受访者当前年龄：{current_age} 岁

访谈全文：
{dialogue_text}

请输出 JSON 数组（每条受访者叙述过的重要事件一条，不强求每个话题都抽；宁可少、不可瞎编）：

[
  {{
    "actor":   "{agent_name}",
    "action":  "做了什么（具体动作/决定/经历）",
    "context": "当时的背景情况，为什么会发生这件事",
    "outcome": "事件的结果或影响",
    "scene_location":              "事件发生的具体地点或'未知'",
    "scene_atmosphere":            "当时的整体氛围或'未知'",
    "scene_sensory_notes":         "感官细节或'未知'",
    "scene_subjective_experience": "当时的主观内心体验",
    "emotion":                     "具体情绪描述",
    "emotion_intensity":      0.0,
    "importance":             0.0,
    "emotion_intensity_score":0.0,
    "value_relevance_score":  0.0,
    "novelty_score":          0.0,
    "reusability_score":      0.0,
    "tags_time_year":         2014,
    "tags_time_month":        0,
    "tags_time_week":         0,
    "tags_time_period_label": "30 岁左右",
    "tags_people":            ["相关人物（化名）"],
    "tags_topic":             ["职业转变", "家庭"],
    "tags_emotion_valence":   "混合",
    "tags_emotion_label":     "笃定",
    "inferred_timestamp":     "2014-06-01T00:00:00",
    "raw_quote":              "受访者原话",
    "event_kind":             "biography"
  }}
]
````

- [ ] **Step 2: Verify placeholders**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "
from pathlib import Path
t = Path('prompts/interview_to_l1.txt').read_text(encoding='utf-8')
for k in ['{interview_date}', '{current_age}', '{agent_name}', '{dialogue_text}']:
    assert k in t, f'missing {k}'
print('ok')
"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add prompts/interview_to_l1.txt
git commit -m "feat(prompts): add interview_to_l1 biography event extraction prompt"
```

---

### Task 9: Create `interview_seed_builder.py` skeleton + `_derive_agent_id` (TDD)

**Files:**
- Create: `core/interview_seed_builder.py` (skeleton only)
- Create: `tests/test_interview_seed_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_interview_seed_builder.py`:

```python
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from core import interview_seed_builder as isb


def test_derive_agent_id_from_valid_filename():
    assert isb._derive_agent_id("txf-interview-cmo0d7li-2026-04-15.md") == "txf"
    assert isb._derive_agent_id("jacky_42-interview-abcd1234-2026-04-01.md") == "jacky_42"
    # Full paths should work too
    assert isb._derive_agent_id("interview_source/txf-interview-cmo0d7li-2026-04-15.md") == "txf"
    assert isb._derive_agent_id("/abs/path/txf-interview-cmo0d7li-2026-04-15.md") == "txf"


def test_derive_agent_id_invalid_filename_raises():
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("random.md")
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("txf-2026-04-15.md")
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("Txf-interview-xxx-2026-04-15.md")  # uppercase not allowed
```

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: FAIL — module `core.interview_seed_builder` does not exist.

- [ ] **Step 3: Create the module skeleton**

Create `core/interview_seed_builder.py`:

```python
"""
interview_seed_builder.py

从 interview_source/<prefix>-interview-...md（访谈 Q&A）一键构建 digital_human agent：
seed.json（带 confidence 审计）+ soul.json（≥0.5 阈值）+ L1（biography + meta）+
L2（include_all_statuses）+ L0 recent_self_narrative + build_report.md。

与 seed_memory_loader.py / nuwa_seed_builder.py 平级，互不干扰。

直接运行：
  python core/interview_seed_builder.py interview_source/txf-interview-cmo0d7li-2026-04-15.md
  python core/interview_seed_builder.py <md> --force
  python core/interview_seed_builder.py <md> --agent-id custom_id
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import logging
import re
import shutil
from datetime import datetime

import config

logger = logging.getLogger("interview_seed_builder")

_PROJECT_ROOT   = Path(__file__).parent.parent
_INTERVIEW_DIR  = _PROJECT_ROOT / "interview_source"
_AGENTS_DIR     = _PROJECT_ROOT / "data" / "agents"
_SEEDS_DIR      = _PROJECT_ROOT / "data" / "seeds"
_PROMPTS_DIR    = _PROJECT_ROOT / "prompts"

_FILENAME_RE = re.compile(
    r"^([a-z0-9_]+)-interview-[a-z0-9]+-\d{4}-\d{2}-\d{2}\.md$"
)


def _derive_agent_id(md_path: str) -> str:
    """从文件名 `<prefix>-interview-<session>-<date>.md` 抠出 <prefix> 作为 agent_id。"""
    name = Path(md_path).name
    m = _FILENAME_RE.match(name)
    if not m:
        raise ValueError(
            f"无法从文件名推导 agent_id：{name}。"
            f"期望模式 `<prefix>-interview-<session>-YYYY-MM-DD.md`（prefix 小写/数字/下划线）。"
            f"如需强制指定请使用 --agent-id 参数。"
        )
    return m.group(1)
```

- [ ] **Step 4: Run test and verify it passes**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): skeleton + _derive_agent_id"
```

---

### Task 10: Add `_parse_interview_md`

**Files:**
- Modify: `core/interview_seed_builder.py`
- Modify: `tests/test_interview_seed_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interview_seed_builder.py`:

```python
_SAMPLE_MD = """---
session_id: abc123
user_id: uid0
status: COMPLETED
completed_at: 2026-04-15T19:30:52.964Z
modules_completed: [0, 2, 6]
interview_duration_minutes: 81
---

# 访谈记录

## 模块 0：开场

**小灵**

你好，我叫stone，很高兴认识你。请问你现在多大了？

**受访者**

我现在42岁了，在合肥做茶叶。

## 模块 2：人生十字路口

**小灵**

你有过十字路口的时刻吗？

**受访者**

30 岁左右接手了家里的茶叶生意。
"""


def test_parse_interview_md_frontmatter(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))

    assert parsed["agent_id"] == "txf"
    assert parsed["session_id"] == "abc123"
    assert parsed["completed_at"] == "2026-04-15T19:30:52.964Z"
    assert parsed["duration_minutes"] == 81
    assert parsed["modules_completed"] == [0, 2, 6]


def test_parse_interview_md_dialogue_text(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))

    # dialogue_text should include both interviewer and interviewee blocks
    # (the LLM needs context from questions to understand answers)
    assert "受访者" in parsed["dialogue_text"]
    assert "我现在42岁了" in parsed["dialogue_text"]
    assert "30 岁左右接手" in parsed["dialogue_text"]


def test_parse_interview_md_module_titles(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    # module_titles maps int -> title
    assert parsed["module_titles"][0] == "开场"
    assert parsed["module_titles"][2] == "人生十字路口"
    assert parsed["module_titles"][6] == "对未来的希望"  # NOT present in body, should be missing or ""
    # We only parse what is present; 6 may or may not be present. Use .get(), allow missing.


def test_parse_interview_md_interviewer_name(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["interviewer_name"] == "小灵"


def test_parse_interview_md_missing_interviewee_block_raises(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text("---\nsession_id: x\n---\n# 无受访者块", encoding="utf-8")
    with pytest.raises(ValueError, match="受访者"):
        isb._parse_interview_md(str(p))


def test_parse_interview_md_bad_frontmatter_falls_back(tmp_path):
    # Missing completed_at -> should warn and fall back to now
    md = _SAMPLE_MD.replace("completed_at: 2026-04-15T19:30:52.964Z\n", "")
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(md, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    # completed_at should be present (fallback value), as an isoformat string
    assert parsed["completed_at"]
    assert isinstance(parsed["completed_at"], str)
    assert parsed.get("completed_at_fallback") is True
```

**Note on test_parse_interview_md_module_titles**: the sample only has module 0 and 2 and 6's heading is not in body. Delete the assertion about module 6:

```python
def test_parse_interview_md_module_titles(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["module_titles"][0] == "开场"
    assert parsed["module_titles"][2] == "人生十字路口"
    # Module 6 heading isn't in body in this sample; should not appear
    assert 6 not in parsed["module_titles"]
```

Replace the earlier version with this corrected version before running tests.

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: the new tests FAIL — `_parse_interview_md` does not exist.

- [ ] **Step 3: Implement `_parse_interview_md`**

Append to `core/interview_seed_builder.py`:

```python
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_MODULE_HEADING_RE = re.compile(r"^##\s*模块\s*(\d+)\s*[:：]\s*(.+?)\s*$", re.MULTILINE)
_INTERVIEWEE_BLOCK_RE = re.compile(r"\*\*受访者\*\*")
# Captures first speaker that is not "受访者" — used to infer interviewer name.
_SPEAKER_BLOCK_RE = re.compile(r"^\*\*([^\*\n]+?)\*\*\s*$", re.MULTILINE)


def _parse_yaml_lite(text: str) -> dict:
    """轻量 YAML 解析：只处理 `key: value` 和 `key: [a, b, c]` 形式。"""
    data: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key   = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items: list = []
            if inner:
                for tok in inner.split(","):
                    tok = tok.strip()
                    if tok.isdigit() or (tok.startswith("-") and tok[1:].isdigit()):
                        items.append(int(tok))
                    else:
                        items.append(tok.strip("'\""))
            data[key] = items
        elif value.isdigit():
            data[key] = int(value)
        else:
            data[key] = value.strip("'\"")
    return data


def _parse_interview_md(md_path: str) -> dict:
    """
    解析访谈 md，返回 dict：
      agent_id, session_id, completed_at, completed_at_fallback,
      duration_minutes, modules_completed (list[int]),
      module_titles (dict[int, str]), interviewer_name,
      dialogue_text (全文含访谈员+受访者 blocks)
    """
    path = Path(md_path)
    raw  = path.read_text(encoding="utf-8")
    agent_id = _derive_agent_id(str(path))

    # ── Frontmatter ─────────────────────────────────────────────────────────
    fm_match = _FRONTMATTER_RE.match(raw)
    fm_data: dict = {}
    if fm_match:
        fm_data = _parse_yaml_lite(fm_match.group(1))
    body = raw[fm_match.end():] if fm_match else raw

    completed_at          = fm_data.get("completed_at")
    completed_at_fallback = False
    if not completed_at:
        logger.warning(f"_parse_interview_md missing completed_at, falling back to now() for {path.name}")
        completed_at = datetime.now().isoformat()
        completed_at_fallback = True

    # Keep completed_at as a string in ISO8601 form; no datetime parsing here.

    modules_completed = fm_data.get("modules_completed") or []
    if isinstance(modules_completed, list):
        modules_completed = [int(x) if not isinstance(x, int) else x for x in modules_completed]

    # ── 必须有受访者块 ───────────────────────────────────────────────────────
    if not _INTERVIEWEE_BLOCK_RE.search(body):
        raise ValueError(f"访谈 md 里找不到 '**受访者**' 块：{path.name}")

    # ── 模块标题映射 ─────────────────────────────────────────────────────────
    module_titles: dict[int, str] = {}
    for m in _MODULE_HEADING_RE.finditer(body):
        module_titles[int(m.group(1))] = m.group(2).strip()

    # ── 访谈员名 ─────────────────────────────────────────────────────────────
    interviewer_name = "访谈员"
    for m in _SPEAKER_BLOCK_RE.finditer(body):
        candidate = m.group(1).strip()
        if candidate and candidate != "受访者":
            interviewer_name = candidate
            break

    return {
        "agent_id":              agent_id,
        "session_id":            fm_data.get("session_id", ""),
        "completed_at":          completed_at,
        "completed_at_fallback": completed_at_fallback,
        "duration_minutes":      int(fm_data.get("interview_duration_minutes") or 0),
        "modules_completed":     modules_completed,
        "module_titles":         module_titles,
        "interviewer_name":      interviewer_name,
        "dialogue_text":         body.strip(),
    }
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): add _parse_interview_md"
```

---

### Task 11: Add `_apply_confidence_gate`

**Files:**
- Modify: `core/interview_seed_builder.py`
- Modify: `tests/test_interview_seed_builder.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interview_seed_builder.py`:

```python
def test_gate_above_threshold_returns_value():
    assert isb._gate({"value": "x", "confidence": 0.7}) == "x"
    assert isb._gate({"value": "x", "confidence": 0.5}) == "x"  # boundary


def test_gate_below_threshold_returns_none():
    assert isb._gate({"value": "x", "confidence": 0.49}) is None
    assert isb._gate({"value": "x", "confidence": 0.0}) is None


def test_gate_null_value_returns_none_regardless_of_confidence():
    assert isb._gate({"value": None, "confidence": 0.9}) is None


def test_gate_bad_types_return_none():
    assert isb._gate(None) is None
    assert isb._gate("not a dict") is None
    assert isb._gate({"value": "x", "confidence": "high"}) is None  # non-numeric conf
    assert isb._gate({"value": "x"}) is None                         # missing conf


def test_gate_custom_threshold():
    assert isb._gate({"value": "x", "confidence": 0.3}, threshold=0.2) == "x"
    assert isb._gate({"value": "x", "confidence": 0.1}, threshold=0.2) is None
```

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: the 5 new tests FAIL — `_gate` not defined.

- [ ] **Step 3: Implement `_gate`**

Append to `core/interview_seed_builder.py`:

```python
def _gate(node, threshold: float | None = None):
    """
    LLM 输出 {"value": ..., "confidence": ...} → 过阈值则原值，否则 None。

    - value 为 None 时一律 None（无论 confidence 多高）
    - confidence 非数字 / 缺失 一律视作 0
    """
    if threshold is None:
        threshold = config.INTERVIEW_CONFIDENCE_THRESHOLD
    if not isinstance(node, dict):
        return None
    value = node.get("value")
    if value is None:
        return None
    conf = node.get("confidence")
    if not isinstance(conf, (int, float)):
        return None
    return value if conf >= threshold else None
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): add _gate confidence-threshold helper"
```

---

### Task 12: Add `_build_meta_event` (deterministic, no LLM)

**Files:**
- Modify: `core/interview_seed_builder.py`
- Modify: `tests/test_interview_seed_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interview_seed_builder.py`:

```python
def test_build_meta_event_basic():
    parsed = {
        "agent_id": "txf",
        "completed_at": "2026-04-15T19:30:52.964Z",
        "duration_minutes": 81,
        "modules_completed": [0, 2, 6, 5, 4, 3, 1, 7],
        "module_titles": {
            0: "开场", 1: "人生故事", 2: "人生十字路口",
            3: "重要的人", 4: "当下的生活", 5: "价值观与信念",
            6: "对未来的希望", 7: "收尾",
        },
        "interviewer_name": "小灵",
    }
    event = isb._build_meta_event(parsed, agent_name="Jacky")

    assert event["actor"] == "Jacky"
    assert event["event_kind"] == "meta"
    assert event["source"] == "interview_meta"
    assert event["inferred_timestamp"] == "2026-04-15T19:30:52.964Z"
    assert "81" in event["context"]
    assert "小灵" in event["context"]
    # outcome should list modules in completed order
    assert "开场" in event["outcome"]
    assert event["outcome"].index("开场") < event["outcome"].index("人生十字路口")
    # fixed scores
    assert event["importance"] == 0.6
    assert event["emotion_intensity"] == 0.3
    assert event["raw_quote"] is None
    # tags
    assert "访谈" in event["tags_topic"]


def test_build_meta_event_missing_titles_falls_back_to_number():
    parsed = {
        "agent_id": "txf",
        "completed_at": "2026-04-15T19:30:52.964Z",
        "duration_minutes": 30,
        "modules_completed": [0, 99],
        "module_titles": {0: "开场"},   # 99 missing
        "interviewer_name": "小灵",
    }
    event = isb._build_meta_event(parsed, agent_name="Jacky")
    assert "开场" in event["outcome"]
    assert "模块 99" in event["outcome"]   # graceful fallback
```

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: the 2 new tests FAIL — `_build_meta_event` not defined.

- [ ] **Step 3: Implement `_build_meta_event`**

Append to `core/interview_seed_builder.py`:

```python
def _build_meta_event(parsed: dict, agent_name: str) -> dict:
    """
    用访谈 frontmatter 确定性构造一条 L1 meta 事件（无 LLM）。
    该事件让 agent "知道"自己是通过一次访谈被唤醒的，利于连续性叙事。
    """
    duration = parsed.get("duration_minutes") or 0
    modules  = parsed.get("modules_completed") or []
    titles   = parsed.get("module_titles") or {}
    interviewer = parsed.get("interviewer_name") or "访谈员"

    ordered_titles = [
        titles.get(mod_id) or f"模块 {mod_id}"
        for mod_id in modules
    ]
    modules_text = "、".join(ordered_titles) if ordered_titles else "多个话题"

    return {
        "actor":              agent_name,
        "action":             "参加了一次关于人生经历的深度访谈",
        "context":            f"在一个对话式访谈系统里和访谈员'{interviewer}'聊了约 {duration} 分钟",
        "outcome":            f"按顺序聊了 {len(modules)} 个模块：{modules_text}",
        "scene_location":     "家中/线上对话",
        "scene_atmosphere":   "安静、回顾式",
        "scene_sensory_notes":"",
        "scene_subjective_experience": "一次难得的对自己经历的系统梳理",
        "emotion":            "平静、略带回顾感",
        "emotion_intensity":  0.3,
        "importance":         0.6,
        "emotion_intensity_score": 0.3,
        "value_relevance_score":   0.5,
        "novelty_score":           0.7,
        "reusability_score":       0.4,
        "tags_time_year":     _year_from_iso(parsed.get("completed_at", "")),
        "tags_time_month":    _month_from_iso(parsed.get("completed_at", "")),
        "tags_time_week":     0,
        "tags_time_period_label": "近期",
        "tags_people":            [interviewer],
        "tags_topic":             ["访谈", "自我叙述"],
        "tags_emotion_valence":   "中性",
        "tags_emotion_label":     "回顾",
        "inferred_timestamp":     parsed.get("completed_at", ""),
        "raw_quote":              None,
        "event_kind":             "meta",
        "source":                 "interview_meta",
    }


def _year_from_iso(ts: str) -> int:
    try:
        return int(ts[:4])
    except Exception:
        return datetime.now().year


def _month_from_iso(ts: str) -> int:
    try:
        return int(ts[5:7])
    except Exception:
        return 0
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): add deterministic _build_meta_event"
```

---

### Task 13: Add LLM-calling internals (seed + L1) and soul construction from gated seed

**Files:**
- Modify: `core/interview_seed_builder.py`
- Modify: `tests/test_interview_seed_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interview_seed_builder.py`:

```python
def test_build_soul_from_gated_seed_fills_above_threshold_only(tmp_path, monkeypatch):
    # Isolate soul writes to tmp
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")

    raw_seed = {
        "name":       {"value": "Jacky", "confidence": 0.95},
        "age":        {"value": 42,       "confidence": 0.99},
        "occupation": {"value": "茶叶",   "confidence": 0.98},
        "location":   {"value": "合肥",   "confidence": 0.99},
        "emotion_core": {
            "base_emotional_type":        {"value": "内敛", "confidence": 0.8},
            "emotional_regulation_style": {"value": "散步", "confidence": 0.4},   # below
            "current_emotional_state":    {"value": "放松", "confidence": 0.7},
        },
        "value_core": {
            "moral_baseline":       {"value": "真实", "confidence": 0.6},
            "value_priority_order": {"value": "家庭", "confidence": 0.3},          # below
            "current_value_focus":  {"value": "孩子", "confidence": 0.8},
        },
        "goal_core": {
            "life_direction":     {"value": "慢生活",  "confidence": 0.7},
            "mid_term_goals":     {"value": "带娃旅行", "confidence": 0.6},
            "current_phase_goal": {"value": "休假",    "confidence": 0.2},        # below
        },
        "relation_core": {
            "attachment_style":       {"value": "独立", "confidence": 0.4},        # below
            "key_relationships":      {"value": ["伴侣","孩子"], "confidence": 0.9},
            "current_relation_state": {"value": "稳定", "confidence": 0.7},
        },
        "cognitive_core": {
            "mental_models":        {"value": [{"name":"m","one_liner":"x"}], "confidence": 0.55},
            "decision_heuristics":  {"value": [{"rule":"稳"}], "confidence": 0.35},  # below
            "expression_dna":       {"value": "冷静务实", "confidence": 0.75},
            "expression_exemplars": {"value": ["原句"]*10, "confidence": 0.95},
            "anti_patterns":        {"value": ["冲动"], "confidence": 0.40},        # below
            "self_awareness":       {"value": "中庸实用主义", "confidence": 0.80},
            "honest_boundaries":    {"value": "保留", "confidence": 0.35},           # below
        },
    }

    soul = isb._build_soul_from_gated_seed("txf", raw_seed)

    # Passed gate (≥0.5)
    assert soul["emotion_core"]["constitutional"]["base_emotional_type"] == "内敛"
    assert soul["emotion_core"]["elastic"]["current_emotional_state"] == "放松"
    assert soul["value_core"]["elastic"]["current_value_focus"] == "孩子"
    assert soul["goal_core"]["slow_change"]["mid_term_goals"]["value"] == "带娃旅行"
    # Below gate -> None
    assert soul["emotion_core"]["slow_change"]["emotional_regulation_style"]["value"] is None
    assert soul["value_core"]["slow_change"]["value_priority_order"]["value"] is None
    assert soul["goal_core"]["elastic"]["current_phase_goal"] is None
    assert soul["relation_core"]["constitutional"]["attachment_style"] is None

    # cognitive_core field-level gating
    cog = soul["cognitive_core"]["constitutional"]
    assert cog["mental_models"] == [{"name":"m","one_liner":"x"}]
    assert cog["decision_heuristics"] is None
    assert cog["expression_dna"] == "冷静务实"
    assert cog["expression_exemplars"] == ["原句"]*10
    assert cog["anti_patterns"] is None
    assert cog["self_awareness"] == "中庸实用主义"
    assert cog["honest_boundaries"] is None

    # Source is "interview"
    assert soul["emotion_core"]["constitutional"]["source"] == "interview"

    # confidence_detail present for cognitive_core with per-field scores
    assert "confidence_detail" in cog
    assert cog["confidence_detail"]["expression_exemplars"] == 0.95
    assert cog["confidence_detail"]["decision_heuristics"] == 0.35
```

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py::test_build_soul_from_gated_seed_fills_above_threshold_only -v
```
Expected: FAIL — `_build_soul_from_gated_seed` not defined.

- [ ] **Step 3: Implement seed extraction, L1 extraction, and soul construction**

Append to `core/interview_seed_builder.py`:

```python
from core.llm_client import chat_completion, get_embedding  # noqa: E402  (after local helpers)
from core.soul import _build_empty_soul, _write_soul, _CORE_FIELDS, CORES


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _call_llm_for_seed(parsed: dict) -> dict:
    """LLM pass 1: 访谈 → 带 confidence 的结构化 seed + recent_self_narrative + follow_up_questions。"""
    template = _load_prompt("interview_to_seed.txt")
    user = template.format(
        agent_id         = parsed["agent_id"],
        interview_date   = parsed["completed_at"],
        duration_minutes = parsed["duration_minutes"],
        dialogue_text    = parsed["dialogue_text"],
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )
    try:
        data = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_call_llm_for_seed json parse error={e} raw={raw[:400]}")
        raise
    if not isinstance(data, dict):
        raise ValueError(f"_call_llm_for_seed expected dict, got {type(data)}")
    return data


def _call_llm_for_l1_events(parsed: dict, agent_name: str, current_age: int) -> list[dict]:
    """LLM pass 2: 访谈 → biography L1 事件列表。"""
    template = _load_prompt("interview_to_l1.txt")
    user = template.format(
        agent_name     = agent_name,
        interview_date = parsed["completed_at"],
        current_age    = current_age,
        dialogue_text  = parsed["dialogue_text"],
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )
    try:
        events = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_call_llm_for_l1_events json parse error={e} raw={raw[:400]}")
        raise
    if not isinstance(events, list):
        raise ValueError(f"_call_llm_for_l1_events expected list, got {type(events)}")
    # Ensure source is set to interview for all extracted events
    for ev in events:
        ev.setdefault("source", "interview")
        ev.setdefault("event_kind", "biography")
    return events


def _build_soul_from_gated_seed(agent_id: str, raw_seed: dict) -> dict:
    """
    raw_seed 是 LLM pass 1 的原始输出（带 confidence）。
    按 _CORE_FIELDS 映射到 soul 三区，confidence < threshold 的字段 → None。
    返回构造好的 soul dict（未写盘）。
    """
    soul = _build_empty_soul(agent_id)

    # 4 主核心：每区一字段，直接 _gate 映射
    for core in ["emotion_core", "value_core", "goal_core", "relation_core"]:
        raw_core = raw_seed.get(core) or {}
        sc       = soul[core]
        fields   = _CORE_FIELDS[core]

        for f in fields["constitutional"]:
            sc["constitutional"][f] = _gate(raw_core.get(f))
        # constitutional 单字段 confidence 元数据：写 LLM 原始分（无论过没过阈）
        main_const_field = fields["constitutional"][0] if fields["constitutional"] else None
        if main_const_field:
            raw_field = raw_core.get(main_const_field) or {}
            sc["constitutional"]["confidence"] = raw_field.get("confidence") if isinstance(raw_field, dict) else None
        sc["constitutional"]["source"] = "interview"

        for f in fields["slow_change"]:
            sc["slow_change"][f]["value"] = _gate(raw_core.get(f))

        for f in fields["elastic"]:
            sc["elastic"][f] = _gate(raw_core.get(f))

    # cognitive_core：7 个 constitutional 字段，confidence_detail 记录每字段分
    cog_raw   = raw_seed.get("cognitive_core") or {}
    cog_const = soul["cognitive_core"]["constitutional"]
    conf_detail: dict = {}
    for f in _CORE_FIELDS["cognitive_core"]["constitutional"]:
        raw_field = cog_raw.get(f)
        cog_const[f] = _gate(raw_field)
        if isinstance(raw_field, dict) and isinstance(raw_field.get("confidence"), (int, float)):
            conf_detail[f] = raw_field["confidence"]
        else:
            conf_detail[f] = None
    cog_const["confidence"] = None  # 多字段核心不用单一 confidence
    cog_const["confidence_detail"] = conf_detail
    cog_const["source"] = "interview"

    return soul
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): add LLM callers and gated soul construction"
```

---

### Task 14: Add `_write_build_report`

**Files:**
- Modify: `core/interview_seed_builder.py`
- Modify: `tests/test_interview_seed_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interview_seed_builder.py`:

```python
def test_write_build_report_sections(tmp_path):
    parsed = {
        "agent_id": "txf",
        "session_id": "abc123",
        "completed_at": "2026-04-15T19:30:52.964Z",
        "duration_minutes": 81,
    }
    raw_seed = {
        "name":       {"value": "Jacky", "confidence": 0.95},
        "age":        {"value": 42,      "confidence": 0.99},
        "occupation": {"value": "茶叶",  "confidence": 0.98},
        "location":   {"value": "合肥",  "confidence": 0.99},
        "emotion_core": {
            "base_emotional_type":        {"value": "内敛", "confidence": 0.8},
            "emotional_regulation_style": {"value": "散步", "confidence": 0.4},
            "current_emotional_state":    {"value": "放松", "confidence": 0.7},
        },
        "value_core": {
            "moral_baseline":       {"value": "真实", "confidence": 0.6},
            "value_priority_order": {"value": "家庭", "confidence": 0.3},
            "current_value_focus":  {"value": "孩子", "confidence": 0.8},
        },
        "goal_core": {
            "life_direction":     {"value": "慢生活", "confidence": 0.7},
            "mid_term_goals":     {"value": "旅行",   "confidence": 0.6},
            "current_phase_goal": {"value": "休假",   "confidence": 0.2},
        },
        "relation_core": {
            "attachment_style":       {"value": "独立", "confidence": 0.4},
            "key_relationships":      {"value": ["x"], "confidence": 0.9},
            "current_relation_state": {"value": "稳",  "confidence": 0.7},
        },
        "cognitive_core": {
            "mental_models":        {"value": [],  "confidence": 0.3},
            "decision_heuristics":  {"value": [],  "confidence": 0.35},
            "expression_dna":       {"value": "x", "confidence": 0.8},
            "expression_exemplars": {"value": [], "confidence": 0.95},
            "anti_patterns":        {"value": [], "confidence": 0.4},
            "self_awareness":       {"value": "x", "confidence": 0.8},
            "honest_boundaries":    {"value": "x", "confidence": 0.35},
        },
        "follow_up_questions": {
            "relation_core.attachment_style": ["追问 1", "追问 2"],
            "cognitive_core.honest_boundaries": ["追问边界"],
        },
    }
    stats = {
        "elapsed_seconds":   42,
        "biography_count":   17,
        "meta_count":        1,
        "status_dist":       {"active": 6, "dormant": 4, "archived": 8},
        "l2_pattern_count":  3,
        "soul_contributions":2,
        "topic_dist":        {"职业": 5, "家庭": 4},
    }
    out = tmp_path / "build_report.md"
    isb._write_build_report(str(out), parsed, raw_seed, stats)
    text = out.read_text(encoding="utf-8")

    # Header
    assert "# Agent 构建报告：txf" in text
    assert "abc123" in text
    assert "81" in text
    # Identity table
    assert "Jacky" in text and "42" in text
    # Soul sections present for each core
    for core in ["emotion_core", "value_core", "goal_core", "relation_core", "cognitive_core"]:
        assert core in text
    # Follow-up section lists conf < 0.5 fields only
    assert "relation_core.attachment_style" in text
    assert "追问 1" in text
    # value_priority_order has conf 0.3 (<0.5) but was not in follow_up_questions dict;
    # report still surfaces it under 回访建议 (LLM-provided追问 optional, so show "（无 LLM 建议追问）")
    assert "value_priority_order" in text
    # Fields with conf >= 0.5 should not appear in follow-up list
    # (They appear as ✅ in the Soul tables but not in 回访建议 bullets.)
    follow_up_section = text.split("## 回访建议", 1)[1]
    assert "current_value_focus" not in follow_up_section  # conf 0.8
    # L1 / L2 numbers
    assert "17" in text and "18" in text   # biography + total
    assert "active=6" in text or "active: 6" in text or "6 / 4 / 8" in text
    assert "L2 Patterns" in text
    # Build time / duration
    assert "42" in text
```

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py::test_write_build_report_sections -v
```
Expected: FAIL — `_write_build_report` not defined.

- [ ] **Step 3: Implement `_write_build_report`**

Append to `core/interview_seed_builder.py`:

```python
_IDENTITY_FIELDS = ["name", "age", "occupation", "location"]


def _fmt_conf(raw_field) -> str:
    if isinstance(raw_field, dict) and isinstance(raw_field.get("confidence"), (int, float)):
        return f"{raw_field['confidence']:.2f}"
    return "—"


def _status_for_conf(raw_field) -> str:
    if not isinstance(raw_field, dict):
        return "—"
    val  = raw_field.get("value")
    conf = raw_field.get("confidence")
    if val is None:
        return "— 无信号"
    if not isinstance(conf, (int, float)):
        return "— confidence 异常"
    if conf >= config.INTERVIEW_CONFIDENCE_THRESHOLD:
        return "✅ 已写入"
    return "⚠️ 未写入（回访）"


def _format_value_preview(value, max_len: int = 80) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        s = value.replace("\n", " ")
    else:
        s = json.dumps(value, ensure_ascii=False)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _write_build_report(out_path: str, parsed: dict, raw_seed: dict, stats: dict) -> None:
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    biography = stats.get("biography_count", 0)
    meta      = stats.get("meta_count", 0)
    total     = biography + meta
    status    = stats.get("status_dist", {})
    a = status.get("active", 0); d = status.get("dormant", 0); z = status.get("archived", 0)

    lines: list[str] = []
    agent_id = parsed["agent_id"]
    lines.append(f"# Agent 构建报告：{agent_id}\n")
    lines.append(f"- 构建时间：{now_str}")
    lines.append(f"- 来源：`{parsed.get('source_md_rel', '(未知)')}`")
    lines.append(f"- 访谈时间：{parsed.get('completed_at','')}（时长 {parsed.get('duration_minutes',0)} 分钟）")
    lines.append(f"- 访谈 session_id：{parsed.get('session_id','')}")
    lines.append(f"- 耗时：{stats.get('elapsed_seconds', 0)}s\n")

    # 基础身份
    lines.append("## 基础身份\n")
    lines.append("| 字段 | 值 | confidence |")
    lines.append("|---|---|---|")
    for f in _IDENTITY_FIELDS:
        node = raw_seed.get(f) or {}
        val  = node.get("value") if isinstance(node, dict) else None
        lines.append(f"| {f} | {_format_value_preview(val)} | {_fmt_conf(node)} |")
    lines.append("")

    # Soul 填充情况
    lines.append("## Soul 填充情况\n")
    SOUL_CORES_IN_REPORT = ["emotion_core", "value_core", "goal_core", "relation_core", "cognitive_core"]
    for core in SOUL_CORES_IN_REPORT:
        raw_core = raw_seed.get(core) or {}
        fields   = _CORE_FIELDS[core]
        lines.append(f"### {core}")
        lines.append("| 区 | 字段 | 状态 | conf |")
        lines.append("|---|---|---|---|")
        for zone, zone_fields in [
            ("constitutional", fields["constitutional"]),
            ("slow_change",    fields["slow_change"]),
            ("elastic",        fields["elastic"]),
        ]:
            for f in zone_fields:
                node = raw_core.get(f)
                lines.append(f"| {zone} | {f} | {_status_for_conf(node)} | {_fmt_conf(node)} |")
        lines.append("")

    # 回访建议（0 < conf < 0.5 的字段）
    lines.append("## 回访建议\n")
    lines.append("以下字段 LLM 看到了部分信号但把握不足，未写入 soul，建议下一轮访谈重点追问：\n")
    follow_ups = raw_seed.get("follow_up_questions") or {}
    threshold  = config.INTERVIEW_CONFIDENCE_THRESHOLD
    has_entries = False

    for core in SOUL_CORES_IN_REPORT:
        raw_core = raw_seed.get(core) or {}
        fields   = _CORE_FIELDS[core]
        for zone_fields in [fields["constitutional"], fields["slow_change"], fields["elastic"]]:
            for f in zone_fields:
                node = raw_core.get(f)
                if not isinstance(node, dict):
                    continue
                conf = node.get("confidence")
                if not isinstance(conf, (int, float)):
                    continue
                if conf <= 0.0 or conf >= threshold:
                    continue
                has_entries = True
                key = f"{core}.{f}"
                lines.append(f"- **{key}** (conf={conf:.2f})")
                lines.append(f"    - LLM 临时判断：{_format_value_preview(node.get('value'), max_len=120)}")
                suggested = follow_ups.get(key) or []
                if suggested:
                    for q in suggested:
                        lines.append(f"    - 建议追问：{q}")
                else:
                    lines.append("    - 建议追问：（无 LLM 建议追问）")
    if not has_entries:
        lines.append("（无 —— 所有字段 confidence 都 ≥ 阈值或无信号）")
    lines.append("")

    # L1 记忆
    lines.append("## L1 记忆\n")
    lines.append(f"- Biography 事件：{biography} 条")
    lines.append(f"- Meta 事件：{meta} 条")
    lines.append(f"- 总计：{total} 条")
    lines.append(f"- 状态分布：active={a}, dormant={d}, archived={z}\n")

    # 主题分布
    topic_dist = stats.get("topic_dist") or {}
    if topic_dist:
        lines.append("### 按主题分布")
        for topic, count in sorted(topic_dist.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {topic}：{count} 条")
        lines.append("")

    # L2
    lines.append("## L2 Patterns\n")
    lines.append(f"- 生成：{stats.get('l2_pattern_count', 0)} 条\n")

    # Soul 贡献
    lines.append("## Soul 证据贡献\n")
    lines.append(f"- L1 → Soul 缓变区积分次数：{stats.get('soul_contributions', 0)}")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"_write_build_report written to {out_path}")
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): add _write_build_report"
```

---

### Task 15: Wire `build_from_interview` orchestrator + CLI + end-to-end smoke test

**Files:**
- Modify: `core/interview_seed_builder.py` (add orchestrator + CLI)
- Modify: `tests/test_interview_seed_builder.py` (end-to-end smoke with mocked LLM)

- [ ] **Step 1: Write the failing smoke test**

Append to `tests/test_interview_seed_builder.py`:

```python
def _fake_seed_response() -> str:
    seed = {
        "name":       {"value": "Jacky", "confidence": 0.95},
        "age":        {"value": 42,       "confidence": 0.99},
        "occupation": {"value": "茶叶",  "confidence": 0.98},
        "location":   {"value": "合肥",  "confidence": 0.99},
        "emotion_core": {
            "base_emotional_type":        {"value": "内敛", "confidence": 0.8},
            "emotional_regulation_style": {"value": "散步", "confidence": 0.7},
            "current_emotional_state":    {"value": "放松", "confidence": 0.7},
        },
        "value_core": {
            "moral_baseline":       {"value": "真实", "confidence": 0.6},
            "value_priority_order": {"value": "家庭", "confidence": 0.3},
            "current_value_focus":  {"value": "孩子", "confidence": 0.8},
        },
        "goal_core": {
            "life_direction":     {"value": "慢生活",  "confidence": 0.7},
            "mid_term_goals":     {"value": "旅行",    "confidence": 0.6},
            "current_phase_goal": {"value": "休假",    "confidence": 0.2},
        },
        "relation_core": {
            "attachment_style":       {"value": "独立", "confidence": 0.4},
            "key_relationships":      {"value": ["伴侣"], "confidence": 0.9},
            "current_relation_state": {"value": "稳定",   "confidence": 0.7},
        },
        "cognitive_core": {
            "mental_models":        {"value": [], "confidence": 0.3},
            "decision_heuristics":  {"value": [], "confidence": 0.35},
            "expression_dna":       {"value": "冷静务实", "confidence": 0.8},
            "expression_exemplars": {"value": ["句1","句2","句3","句4","句5","句6","句7","句8","句9","句10"], "confidence": 0.95},
            "anti_patterns":        {"value": [], "confidence": 0.4},
            "self_awareness":       {"value": "中庸实用主义", "confidence": 0.8},
            "honest_boundaries":    {"value": "保留",        "confidence": 0.4},
        },
        "recent_self_narrative": "我前几天参加了一次访谈，和小灵聊了我做茶叶、两个孩子、一次感情清零的经历。",
        "follow_up_questions": {
            "relation_core.attachment_style": ["你在亲密关系中如何表达脆弱？"],
        },
    }
    import json as _json
    return _json.dumps(seed, ensure_ascii=False)


def _fake_l1_response() -> str:
    events = [
        {
            "actor": "Jacky",
            "action": "30 岁左右从零售转到接手家里的茶叶",
            "context": "组建家庭后权衡时间与收入",
            "outcome": "慢慢接手了茶叶生意",
            "scene_location": "合肥", "scene_atmosphere": "平静",
            "scene_sensory_notes": "", "scene_subjective_experience": "水到渠成",
            "emotion": "笃定", "emotion_intensity": 0.4,
            "importance": 0.6, "emotion_intensity_score": 0.4,
            "value_relevance_score": 0.7, "novelty_score": 0.6,
            "reusability_score": 0.6,
            "tags_time_year": 2014, "tags_time_month": 6,
            "tags_time_week": 0, "tags_time_period_label": "30 岁左右",
            "tags_people": ["伴侣"], "tags_topic": ["职业"],
            "tags_emotion_valence": "中性", "tags_emotion_label": "笃定",
            "inferred_timestamp": "2014-06-01T00:00:00",
            "raw_quote": "大概是30岁左右的时候，慢慢接手的",
            "event_kind": "biography",
        }
    ]
    import json as _json
    return _json.dumps(events, ensure_ascii=False)


def test_build_from_interview_smoke(tmp_path, monkeypatch):
    # --- Fixture md ---
    md = _SAMPLE_MD
    md_path = tmp_path / "jacky-interview-abc12345-2026-04-15.md"
    md_path.write_text(md, encoding="utf-8")

    # --- Redirect project dirs to tmp_path ---
    monkeypatch.setattr(isb, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(isb, "_SEEDS_DIR",  tmp_path / "seeds")
    from core import seed_memory_loader as sml
    monkeypatch.setattr(sml, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(sml, "_SEEDS_DIR",  tmp_path / "seeds")
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path / "agents")
    from core import memory_l2
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path / "agents")
    from core import global_state
    monkeypatch.setattr(global_state, "_AGENTS_DIR", tmp_path / "agents")

    # --- Mock LLM calls ---
    call_log = []
    def fake_chat(messages, max_tokens=1024, temperature=0.7):
        call_log.append(messages)
        # First call = seed, second = L1 events, further calls = L2 generation (may be 0)
        if len(call_log) == 1:
            return _fake_seed_response()
        if len(call_log) == 2:
            return _fake_l1_response()
        # L2 generate returns a skip action
        return '{"action": "skip"}'

    monkeypatch.setattr(isb, "chat_completion", fake_chat)
    monkeypatch.setattr(memory_l2, "chat_completion", fake_chat)
    # Also ensure the seed_memory_loader L1 write path uses fake embedding (no real API)
    monkeypatch.setattr(isb, "get_embedding", lambda t: [0.0] * __import__("config").EMBEDDING_DIM)
    monkeypatch.setattr(sml, "get_embedding", lambda t: [0.0] * __import__("config").EMBEDDING_DIM)

    # --- Run ---
    summary = isb.build_from_interview(str(md_path))

    # --- Assertions on produced artifacts ---
    agent_id = "jacky"
    seeds_dir   = tmp_path / "seeds" / agent_id
    agents_dir  = tmp_path / "agents" / agent_id

    assert (seeds_dir / "seed.json").exists()
    assert (seeds_dir / "interview_source" / md_path.name).exists()
    assert (seeds_dir / "build_report.md").exists()

    assert (agents_dir / "soul.json").exists()
    assert (agents_dir / "l0_buffer.json").exists()
    assert (agents_dir / "l2_patterns.json").exists()
    assert (agents_dir / "global_state.json").exists()

    # soul.json content: passed-threshold fields filled, below-threshold NULL
    soul = json.loads((agents_dir / "soul.json").read_text(encoding="utf-8"))
    assert soul["emotion_core"]["constitutional"]["base_emotional_type"] == "内敛"
    # attachment_style had conf 0.4 -> should be None
    assert soul["relation_core"]["constitutional"]["attachment_style"] is None

    # L0 buffer has recent_self_narrative
    l0 = json.loads((agents_dir / "l0_buffer.json").read_text(encoding="utf-8"))
    assert l0["working_context"].get("recent_self_narrative")
    assert "访谈" in l0["working_context"]["recent_self_narrative"]

    # seed.json retains raw LLM output with confidence
    seed = json.loads((seeds_dir / "seed.json").read_text(encoding="utf-8"))
    assert seed["relation_core"]["attachment_style"]["confidence"] == 0.4

    # Summary contains key counts
    assert summary["agent_id"] == agent_id
    assert summary["biography_count"] == 1
    assert summary["meta_count"] == 1
```

- [ ] **Step 2: Run test and verify it fails**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py::test_build_from_interview_smoke -v
```
Expected: FAIL — `build_from_interview` not defined.

- [ ] **Step 3: Implement the orchestrator + CLI**

Append to `core/interview_seed_builder.py`:

```python
from core.seed_memory_loader import (
    _setup_agent_dirs,
    _write_events_to_l1,
    _build_graph,
    _update_statuses,
)
from core.memory_l2 import check_and_generate_patterns, contribute_to_soul


def _write_seed_audit(seed_dir: Path, raw_seed: dict) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    # Attach agent_id for convenience at the top
    with open(seed_dir / "seed.json", "w", encoding="utf-8") as f:
        json.dump(raw_seed, f, ensure_ascii=False, indent=2)


def _inject_l0_narrative(agent_id: str, narrative: str) -> None:
    """把 recent_self_narrative 写进 l0_buffer.working_context；raw_dialogue 不塞。"""
    l0_path = _AGENTS_DIR / agent_id / "l0_buffer.json"
    data = json.loads(l0_path.read_text(encoding="utf-8"))
    data.setdefault("working_context", {})
    data["working_context"]["recent_self_narrative"] = narrative or ""
    l0_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _compute_topic_dist(events: list[dict]) -> dict[str, int]:
    counter: dict[str, int] = {}
    for ev in events:
        for t in ev.get("tags_topic") or []:
            counter[str(t)] = counter.get(str(t), 0) + 1
    return counter


def build_from_interview(
    md_path: str,
    agent_id_override: str | None = None,
    force: bool = False,
) -> dict:
    """
    从访谈 md 一键构建 agent。参见 spec §2 架构图。
    """
    start = datetime.now()

    # Step 1: 解析 md
    logger.info(f"Step 1/11: parse interview md path={md_path}")
    parsed = _parse_interview_md(md_path)
    if agent_id_override:
        parsed["agent_id"] = agent_id_override
    agent_id = parsed["agent_id"]

    # Step 2: 存在性检查 / force
    agent_dir = _AGENTS_DIR / agent_id
    seed_dir  = _SEEDS_DIR / agent_id
    if agent_dir.exists() or seed_dir.exists():
        if not force:
            raise RuntimeError(
                f"agent_id='{agent_id}' 已存在。如需重建请加 --force。"
            )
        logger.warning(f"build_from_interview force=True 删除旧数据 agent_id={agent_id}")
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        if seed_dir.exists():
            shutil.rmtree(seed_dir)

    logger.info(f"build_from_interview START agent_id={agent_id}")

    # Step 3: 归档原 md
    logger.info("Step 3/11: archive source md")
    seed_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = seed_dir / "interview_source"
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(md_path, archive_dir / Path(md_path).name)
    parsed["source_md_rel"] = f"interview_source/{Path(md_path).name}"

    # Step 4: LLM pass 1 → seed (with confidence)
    logger.info("Step 4/11: LLM pass 1 — interview → seed (with confidence)")
    raw_seed = _call_llm_for_seed(parsed)

    # Persist audit seed.json (raw LLM output verbatim)
    _write_seed_audit(seed_dir, raw_seed)

    # Step 5: Confidence gate → soul.json
    logger.info("Step 5/11: confidence gate → soul.json")
    _build_soul_from_gated_seed(agent_id, raw_seed)      # builds soul
    soul = _build_soul_from_gated_seed(agent_id, raw_seed)  # re-build (idempotent, no LLM)
    _write_soul(agent_id, soul)

    agent_name_field = raw_seed.get("name") or {}
    agent_name = agent_name_field.get("value") if isinstance(agent_name_field, dict) else None
    agent_name = agent_name or agent_id
    age_field  = raw_seed.get("age") or {}
    current_age = age_field.get("value") if isinstance(age_field, dict) else None
    if not isinstance(current_age, int):
        current_age = 0

    # Step 6: 目录骨架 + L0 摘要注入
    logger.info("Step 6/11: setup agent dirs + inject L0 recent_self_narrative")
    _setup_agent_dirs(agent_id)
    _inject_l0_narrative(agent_id, raw_seed.get("recent_self_narrative") or "")

    # Step 7: LLM pass 2 → biography L1 events
    logger.info("Step 7/11: LLM pass 2 — interview → biography L1 events")
    biography_events = _call_llm_for_l1_events(parsed, agent_name, current_age)

    # Step 8: 确定性 meta 事件
    logger.info("Step 8/11: build deterministic meta event")
    meta_event = _build_meta_event(parsed, agent_name)
    all_events = biography_events + [meta_event]

    # Step 9: 写 L1 + 建图 + 状态
    logger.info(f"Step 9/11: write {len(all_events)} events to L1 + graph + statuses")
    written = _write_events_to_l1(agent_id, agent_name, all_events)
    _build_graph(agent_id, written)
    status_dist = _update_statuses(agent_id, written)

    # Step 10: L2 + soul 贡献（初始化时放宽时间限制）
    logger.info("Step 10/11: L2 patterns (include_all_statuses=True) + soul contributions")
    l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)
    soul_contribs = contribute_to_soul(agent_id)

    # Step 11: 构建报告
    logger.info("Step 11/11: write build_report.md")
    elapsed = (datetime.now() - start).seconds
    stats = {
        "elapsed_seconds":    elapsed,
        "biography_count":    len(biography_events),
        "meta_count":         1,
        "status_dist":        status_dist,
        "l2_pattern_count":   len(l2_updated),
        "soul_contributions": len(soul_contribs),
        "topic_dist":         _compute_topic_dist(biography_events + [meta_event]),
    }
    _write_build_report(str(seed_dir / "build_report.md"), parsed, raw_seed, stats)

    summary = {
        "agent_id":          agent_id,
        "agent_name":        agent_name,
        "biography_count":   len(biography_events),
        "meta_count":        1,
        "l2_pattern_count":  len(l2_updated),
        "soul_contributions":len(soul_contribs),
        "elapsed_seconds":   elapsed,
    }
    logger.info(f"build_from_interview DONE summary={summary}")
    print("\n=== interview agent 构建完成 ===")
    print(f"  Agent:        {agent_id} ({agent_name})")
    print(f"  L1 事件:      {len(biography_events)} biography + {1} meta = {len(biography_events)+1} 条  {status_dist}")
    print(f"  L2 patterns:  {len(l2_updated)} 条")
    print(f"  报告:         data/seeds/{agent_id}/build_report.md")
    print(f"  耗时:         {elapsed}s")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="从访谈 md 构建数字人 agent（带 confidence 门控和审计报告）",
    )
    parser.add_argument("md_path", help="interview_source/ 下的 md 文件路径")
    parser.add_argument("--agent-id",
                        dest="agent_id_override",
                        default=None,
                        help="文件名推导失败时的后门参数")
    parser.add_argument("--force", "-f", action="store_true", help="覆盖重建")
    args = parser.parse_args()

    if not Path(args.md_path).exists():
        print(f"错误：找不到文件 {args.md_path}", file=sys.stderr)
        sys.exit(1)

    try:
        build_from_interview(
            md_path=args.md_path,
            agent_id_override=args.agent_id_override,
            force=args.force,
        )
    except (RuntimeError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 4: Run all tests and verify they pass**

Run:
```bash
cd /Users/stone/projects/digital_human && python -m pytest tests/test_interview_seed_builder.py tests/test_memory_l2_init_mode.py tests/test_soul_cognitive_core.py tests/test_l1_schema_extension.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/interview_seed_builder.py tests/test_interview_seed_builder.py
git commit -m "feat(interview): wire build_from_interview orchestrator + CLI"
```

---

## Phase C — Live verification

### Task 16: Real LLM run against `txf` interview + human spot-check

**Files:**
- Run: `python core/interview_seed_builder.py interview_source/txf-interview-cmo0d7li-2026-04-15.md`
- Inspect: `data/seeds/txf/seed.json` / `data/seeds/txf/build_report.md` / `data/agents/txf/soul.json` / `data/agents/txf/l0_buffer.json`

- [ ] **Step 1: Check prerequisites**

Run:
```bash
cd /Users/stone/projects/digital_human && ls interview_source/ && grep -c "txf" config.py || true
```
Expected: `txf-interview-cmo0d7li-2026-04-15.md` listed.

- [ ] **Step 2: Ensure no stale txf agent**

Run:
```bash
cd /Users/stone/projects/digital_human && ls data/agents/ data/seeds/ 2>&1 | grep -E "^txf$" || echo "no stale txf"
```
If there IS a stale one and you expected a clean run, pass `--force`. Do NOT run `rm -rf` manually.

- [ ] **Step 3: Execute the pipeline**

Run:
```bash
cd /Users/stone/projects/digital_human && python core/interview_seed_builder.py interview_source/txf-interview-cmo0d7li-2026-04-15.md
```
Expected: prints "=== interview agent 构建完成 ===" with non-zero L1 event counts, no stack traces.

- [ ] **Step 4: Read build_report.md**

Run:
```bash
cd /Users/stone/projects/digital_human && cat data/seeds/txf/build_report.md
```
Inspect:
- Basic identity (name/age/occupation/location) matches interview content
- Every soul core has a table with statuses
- "回访建议" lists only fields with 0 < conf < 0.5
- L1 counts look reasonable (expect ~8–20 biography + 1 meta)

- [ ] **Step 5: Cross-check seed / soul consistency**

Run:
```bash
cd /Users/stone/projects/digital_human && python -c "
import json
seed = json.load(open('data/seeds/txf/seed.json', encoding='utf-8'))
soul = json.load(open('data/agents/txf/soul.json', encoding='utf-8'))
# Sample a slow_change field: seed has it with conf, soul shows it only if conf >= 0.5
field = seed['emotion_core']['emotional_regulation_style']
soul_val = soul['emotion_core']['slow_change']['emotional_regulation_style']['value']
print(f'seed conf={field[\"confidence\"]}  soul_val={soul_val!r}')
assert (field['confidence'] >= 0.5) == (soul_val is not None), '阈值逻辑错误'
print('gate consistency OK')
"
```
Expected: prints confidence/value pair and `gate consistency OK`.

- [ ] **Step 6: Chat with the new agent (sanity check, not automated)**

Run:
```bash
cd /Users/stone/projects/digital_human && python main_chat.py txf
```
Try:
- "你最近在忙什么？" — reply should reference tea business / kids / interview topics
- "你能说几句你前几天访谈里说过的话吗？" — agent should reference the interview (via L1 raw_quote retrieval)

Type `quit` when done.

If cognitive_core replies feel off (e.g., rigid textbook phrasing instead of casual "中庸实用主义" tone), iterate on `prompts/interview_to_seed.txt` and re-run with `--force`. That's a **prompt-tuning loop**, not a plan failure.

- [ ] **Step 7: Commit the spec verification outcome (only if prompts were tweaked)**

If Step 6 required prompt tweaks, commit them:
```bash
git add prompts/interview_to_seed.txt prompts/interview_to_l1.txt
git commit -m "tune(prompts): iterate interview_to_seed based on txf verification"
```
Otherwise, no commit.

---

## Self-Review Notes (post-plan)

- Spec §1 goals — Task 7/8/9/10/11/12/13/14/15 cover all of: soul extraction with confidence, L1 biography+meta, L0 narrative injection, build_report, per-file placement.
- Spec §7 L2 init relaxation — Task 5/6 cover the memory_l2 change and all three init pipelines; Task 15 orchestrator uses `include_all_statuses=True`.
- Spec §10 max_tokens cleanup — Task 1/2/3/4 cover every item in spec §10.2.
- Spec §11 CLI — Task 15 implements `--force` and `--agent-id`. File-name derivation tested in Task 9.
- Spec §12 tests 1–8 — mapped: Task 9 (tests 1, 2), Task 10 (extended 1, 2), Task 11 (test 3), Task 12 (test 4), Task 14 (test 5), Task 15 (test 6), Task 5 (tests 7, 8).
- `confidence_detail` for cognitive_core (spec §4.3) — Task 13 writes it; Task 13 test asserts it.
- All placeholders, signatures, function names (`_derive_agent_id`, `_parse_interview_md`, `_gate`, `_build_meta_event`, `_call_llm_for_seed`, `_call_llm_for_l1_events`, `_build_soul_from_gated_seed`, `_write_build_report`, `build_from_interview`, `_fetch_all_events`) consistent across tasks.
