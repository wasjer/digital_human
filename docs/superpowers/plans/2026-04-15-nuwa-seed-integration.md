# Nuwa Seed 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `examples/{name}-perspective/` 下的 nuwa agent（SKILL.md + 6 份 research）一键产出完整的 digital_human agent（seed + soul + L1 记忆），与原有访谈通路并行。

**Architecture:** 新增 `core/nuwa_seed_builder.py` 作为独立入口，复用 `seed_memory_loader` 的目录初始化 / 图建边 / 状态分配函数；Soul 扩第 5 核 `cognitive_core`（单区，7 字段）承载认知骨架；L1 schema 增 `raw_quote` / `event_kind` 两字段承载原文引用与类别。

**Tech Stack:** Python 3，LanceDB（L1 向量表），PyArrow（schema），DeepSeek（LLM）。

**Spec:** `docs/superpowers/specs/2026-04-14-nuwa-seed-integration-design.md`

---

## File Structure

**新建：**
- `core/nuwa_seed_builder.py` — 主入口（10 步流水线）
- `prompts/nuwa_skill_to_seed.txt` — SKILL.md + 03 + 04 → seed.json（含 cognitive_core 全部 7 字段）
- `prompts/nuwa_research_to_l1.txt` — research/01/02/05/06 → L1 events（含 raw_quote / event_kind）
- `tests/test_l1_schema_extension.py` — L1 新字段的单元测试
- `tests/test_soul_cognitive_core.py` — cognitive_core 构建/渲染的单元测试

**修改：**
- `core/memory_l1.py` — `_l1_schema()` 加两字段；`write_event` 行构造加透传
- `core/seed_memory_loader.py` — `_write_events_to_l1` 行构造加两字段默认值
- `core/soul.py` — `CORES` / `_CORE_FIELDS` 加 cognitive_core；`get_soul_anchor` 加 list/dict 渲染分支
- `prompts/soul_anchor.txt` — 模板扩展，支持 list/dict 字段的 bullet 渲染
- `prompts/seed_batch_load.txt` — schema 增 raw_quote + event_kind 字段
- `prompts/seed_soul_init.txt` — 输出 JSON 增 cognitive_core.expression_exemplars 字段
- `prompts/dialogue_system.txt` / `prompts/decision_system.txt` — 加 cognitive_core 使用规则
- `config.py` — `SOUL_ANCHOR_MAX_TOKENS` 500 → 10000

---

## Task 1: 扩展 L1 LanceDB schema（加 raw_quote + event_kind）

**Files:**
- Modify: `core/memory_l1.py:22-58` (schema), `core/memory_l1.py:231-266` (row)
- Modify: `core/seed_memory_loader.py:269-304` (row)
- Test: `tests/test_l1_schema_extension.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_l1_schema_extension.py`：

```python
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.memory_l1 import _l1_schema, _get_table


def test_l1_schema_contains_raw_quote_and_event_kind():
    schema = _l1_schema()
    names = {f.name for f in schema}
    assert "raw_quote" in names, "schema 应包含 raw_quote 字段"
    assert "event_kind" in names, "schema 应包含 event_kind 字段"


def test_l1_table_accepts_new_fields(tmp_path, monkeypatch):
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path / "agents")

    tbl = _get_table("test_agent_schema")
    row = {name: _default_for(field) for name, field in zip(
        (f.name for f in _l1_schema()), _l1_schema()
    )}
    row["raw_quote"] = "I don't really care about being right."
    row["event_kind"] = "conversation"
    tbl.add([row])

    rows = tbl.search().where("event_id = 'ev_test_1'").limit(1).to_list()
    assert rows and rows[0]["raw_quote"].startswith("I don't")
    assert rows[0]["event_kind"] == "conversation"


def _default_for(field):
    import pyarrow as pa
    t = field.type
    if pa.types.is_list(t):
        return [0.0] * 1024
    if pa.types.is_floating(t):
        return 0.0
    if pa.types.is_integer(t):
        return 0
    return "ev_test_1" if field.name == "event_id" else ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_l1_schema_extension.py -v`
Expected: FAIL — `raw_quote`/`event_kind` 不在 schema 中。

- [ ] **Step 3: 修改 `_l1_schema()` 加两个字段**

编辑 `core/memory_l1.py:57-58`，在 `ttl_days` 之后追加：

```python
        pa.field("ttl_days",                   pa.int32()),
        pa.field("raw_quote",                  pa.utf8()),
        pa.field("event_kind",                 pa.utf8()),
    ])
```

- [ ] **Step 4: 跑 schema 测试确认通过**

Run: `pytest tests/test_l1_schema_extension.py::test_l1_schema_contains_raw_quote_and_event_kind -v`
Expected: PASS。

- [ ] **Step 5: `write_event` 行构造加透传**

编辑 `core/memory_l1.py:231-266`，在 `"ttl_days": 365,` 之后追加两行：

```python
                "ttl_days":                    365,
                "raw_quote":                   str(ev.get("raw_quote") or ""),
                "event_kind":                  str(ev.get("event_kind") or "biography"),
            }
```

- [ ] **Step 6: `_write_events_to_l1` 行构造加透传**

编辑 `core/seed_memory_loader.py:269-304`，在 `"ttl_days": 365 * 10,` 之后追加：

```python
                "ttl_days":                     365 * 10,
                "raw_quote":                    str(ev.get("raw_quote") or ""),
                "event_kind":                   str(ev.get("event_kind") or "biography"),
            }
```

- [ ] **Step 7: 跑 table 写入测试确认通过**

Run: `pytest tests/test_l1_schema_extension.py -v`
Expected: 两条测试全通过。

- [ ] **Step 8: 提交**

```bash
git add core/memory_l1.py core/seed_memory_loader.py tests/test_l1_schema_extension.py
git commit -m "feat(l1): add raw_quote and event_kind fields to L1 schema"
```

---

## Task 2: 更新 seed_batch_load.txt prompt 加新字段说明

**Files:**
- Modify: `prompts/seed_batch_load.txt`

- [ ] **Step 1: 修改 prompt 模板字段清单**

编辑 `prompts/seed_batch_load.txt:28-55`，在 `"tags_emotion_label": "忐忑",` 与 `"inferred_timestamp"` 之间插入，然后在末尾补两字段：

```
    "tags_emotion_valence": "混合",
    "tags_emotion_label": "忐忑",
    "inferred_timestamp": "2020-09-01T00:00:00",
    "raw_quote": null,
    "event_kind": "biography"
  }}
]
```

- [ ] **Step 2: 在规则段加说明**

在 `prompts/seed_batch_load.txt:17` 第 9 条之后增加：

```
9. 所有字段值使用中文（tags_emotion_valence 使用：正面/负面/混合/中性）
10. `event_kind` 老访谈通路固定填 "biography"；`raw_quote` 老通路固定填 null
```

- [ ] **Step 3: 提交**

```bash
git add prompts/seed_batch_load.txt
git commit -m "docs(prompt): extend seed_batch_load with raw_quote and event_kind"
```

---

## Task 3: 扩展 soul.py 加 cognitive_core（5 th core，单区）

**Files:**
- Modify: `core/soul.py:17-41`
- Test: `tests/test_soul_cognitive_core.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_soul_cognitive_core.py`：

```python
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.soul import CORES, _CORE_FIELDS, _build_empty_soul


def test_cognitive_core_in_cores_list():
    assert "cognitive_core" in CORES
    assert CORES[-1] == "cognitive_core"


def test_cognitive_core_field_layout():
    fields = _CORE_FIELDS["cognitive_core"]
    assert set(fields["constitutional"]) == {
        "mental_models", "decision_heuristics",
        "expression_dna", "expression_exemplars",
        "anti_patterns", "self_awareness", "honest_boundaries",
    }
    assert fields["slow_change"] == []
    assert fields["elastic"] == []


def test_build_empty_soul_includes_cognitive_core():
    soul = _build_empty_soul("agent_x")
    assert "cognitive_core" in soul
    c = soul["cognitive_core"]["constitutional"]
    for f in ["mental_models", "decision_heuristics", "expression_dna",
              "expression_exemplars", "anti_patterns", "self_awareness",
              "honest_boundaries"]:
        assert f in c and c[f] is None
    assert c["locked"] is True
    assert soul["cognitive_core"]["slow_change"] == {}
    assert soul["cognitive_core"]["elastic"] == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_soul_cognitive_core.py -v`
Expected: FAIL — `cognitive_core` 不在 `CORES` / `_CORE_FIELDS`。

- [ ] **Step 3: 修改 `CORES` 和 `_CORE_FIELDS`**

编辑 `core/soul.py:17`：

```python
CORES = ["emotion_core", "value_core", "goal_core", "relation_core", "cognitive_core"]
```

编辑 `core/soul.py:20-41`，在 `relation_core` 条目之后插入：

```python
    "relation_core": {
        "constitutional": ["attachment_style"],
        "slow_change":    ["key_relationships"],
        "elastic":        ["current_relation_state"],
    },
    "cognitive_core": {
        "constitutional": [
            "mental_models",
            "decision_heuristics",
            "expression_dna",
            "expression_exemplars",
            "anti_patterns",
            "self_awareness",
            "honest_boundaries",
        ],
        "slow_change": [],
        "elastic":     [],
    },
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_soul_cognitive_core.py -v`
Expected: 3 条全通过。

- [ ] **Step 5: 提交**

```bash
git add core/soul.py tests/test_soul_cognitive_core.py
git commit -m "feat(soul): add cognitive_core as 5th core with single region"
```

---

## Task 4: 扩展 get_soul_anchor 加 list/dict 渲染分支

**Files:**
- Modify: `core/soul.py:314-335`
- Test: `tests/test_soul_cognitive_core.py`（追加）

- [ ] **Step 1: 追加渲染测试**

在 `tests/test_soul_cognitive_core.py` 末尾追加：

```python
from core.soul import _write_soul, _build_empty_soul, get_soul_anchor


def test_get_soul_anchor_renders_list_fields(tmp_path, monkeypatch):
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")

    s = _build_empty_soul("ag_anchor")
    s["cognitive_core"]["constitutional"]["mental_models"] = [
        {"name": "聚焦即说不", "one_liner": "对其他一百个好主意说 No"},
        {"name": "连点成线", "one_liner": "人生只能回溯理解"},
    ]
    s["cognitive_core"]["constitutional"]["decision_heuristics"] = [
        {"rule": "先做减法"}, {"rule": "不问用户要什么"},
    ]
    s["cognitive_core"]["constitutional"]["expression_exemplars"] = [
        "Stay Hungry. Stay Foolish.",
        "This is shit. A bozo product.",
    ]
    _write_soul("ag_anchor", s)

    text = get_soul_anchor("ag_anchor")
    assert "cognitive_core" in text
    assert "聚焦即说不" in text
    assert "先做减法" in text
    assert "Stay Hungry" in text


def test_get_soul_anchor_renders_dict_fields(tmp_path, monkeypatch):
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")

    s = _build_empty_soul("ag_anchor_d")
    s["cognitive_core"]["constitutional"]["expression_dna"] = {
        "sentence_style": "短句为主",
        "rhythm": "先结论后铺垫",
    }
    _write_soul("ag_anchor_d", s)

    text = get_soul_anchor("ag_anchor_d")
    assert "短句为主" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_soul_cognitive_core.py::test_get_soul_anchor_renders_list_fields -v`
Expected: FAIL — list 值会被当字符串打印（可能缺元素或格式乱）。

- [ ] **Step 3: 加 `_render_constitutional_value` 辅助函数**

编辑 `core/soul.py`，在 `get_soul_anchor` 函数之前新增：

```python
def _render_constitutional_value(value) -> str:
    """把宪法区字段的值（str / list / dict）渲染为 anchor 文本。"""
    if value is None:
        return "None"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                if "name" in item and "one_liner" in item:
                    lines.append(f"    · {item['name']}：{item['one_liner']}")
                elif "rule" in item:
                    lines.append(f"    · {item['rule']}")
                else:
                    lines.append(f"    · {json.dumps(item, ensure_ascii=False)}")
            else:
                lines.append(f"    · {item}")
        return "\n" + "\n".join(lines)
    if isinstance(value, dict):
        lines = [f"    · {k}: {v}" for k, v in value.items()]
        return "\n" + "\n".join(lines)
    return str(value)
```

- [ ] **Step 4: 改写 `get_soul_anchor` 使用该函数**

替换 `core/soul.py:314-335` 的 `get_soul_anchor`：

```python
def get_soul_anchor(agent_id: str) -> str:
    """
    返回所有核心宪法区+缓变区的摘要文本，控制在 SOUL_ANCHOR_MAX_TOKENS 以内，中文。
    对 list/dict 类型的宪法字段做 bullet 展开。
    """
    soul = read_soul(agent_id)
    char_budget = config.SOUL_ANCHOR_MAX_TOKENS * 4
    lines = []
    for core in CORES:
        core_lines = [_ANCHOR_CORE_FMT.format(core=core)]
        c = soul[core]["constitutional"]
        for f in _CORE_FIELDS[core]["constitutional"]:
            rendered = _render_constitutional_value(c.get(f))
            core_lines.append(_ANCHOR_CONST_FMT.format(field=f, value=rendered))
        sc = soul[core]["slow_change"]
        for f in _CORE_FIELDS[core]["slow_change"]:
            core_lines.append(_ANCHOR_SLOW_FMT.format(field=f, value=sc[f].get("value")))
        lines.extend(core_lines)

    full = "\n".join(lines)
    if len(full) > char_budget:
        full = full[:char_budget] + "..."
    return full
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_soul_cognitive_core.py -v`
Expected: 5 条全通过。

- [ ] **Step 6: 提交**

```bash
git add core/soul.py tests/test_soul_cognitive_core.py
git commit -m "feat(soul): render list/dict constitutional fields in soul anchor"
```

---

## Task 5: 更新 soul_anchor.txt 模板（保持向后兼容）

**Files:**
- Modify: `prompts/soul_anchor.txt`

说明：`get_soul_anchor` 现在用 `_render_constitutional_value` 把 list/dict 值转成带换行的字符串，再喂给 `_ANCHOR_CONST_FMT` 现有 `  宪法/{field}: {value}` 模板即可。**不改模板也能工作**——但为了让输出缩进更清晰，优化模板。

- [ ] **Step 1: 更新模板（可选优化）**

查看当前 `prompts/soul_anchor.txt`（3 行），保持不变：

```
【{core}】
  宪法/{field}: {value}
  缓变/{field}: {value}
```

list/dict 字段由 Task 4 的 `_render_constitutional_value` 返回以 `\n    · ` 开头的多行字符串，配合现有模板自然缩进对齐。**不需要改模板文件**。

- [ ] **Step 2: 跑 Task 4 测试确认输出仍通过**

Run: `pytest tests/test_soul_cognitive_core.py -v`
Expected: 全通过。

- [ ] **Step 3: 无修改 → 跳过 commit**

如 Task 4 测试通过则本 task 无文件变更。直接进入 Task 6。

---

## Task 6: 把 SOUL_ANCHOR_MAX_TOKENS 调到 10000

**Files:**
- Modify: `config.py:64`

- [ ] **Step 1: 修改常量值**

编辑 `config.py:64`：

```python
SOUL_ANCHOR_MAX_TOKENS = 10000     # soul anchor 摘要文本的最大 token 数（阶段一：不做裁剪）
```

- [ ] **Step 2: 提交**

```bash
git add config.py
git commit -m "chore(config): raise SOUL_ANCHOR_MAX_TOKENS to 10000 for nuwa cognitive_core"
```

---

## Task 7: 为老通路 seed_soul_init.txt 增 expression_exemplars 字段

**Files:**
- Modify: `prompts/seed_soul_init.txt:46-51`

- [ ] **Step 1: 修改输出 JSON schema**

编辑 `prompts/seed_soul_init.txt`，把 `relation_core` 条目之后加上 `cognitive_core`：

替换第 46-51 行起：

```
  "relation_core": {{
    "constitutional": {{"attachment_style": "这个人的依恋风格和人际关系基本模式，如何建立和维护关系", "confidence": 0.0}},
    "slow_change": {{"key_relationships": {{"value": "这个人生命中最重要的关系列表和关系模式描述"}}}},
    "elastic": {{"current_relation_state": "这个人当前的主要人际关系状态"}}
  }},
  "cognitive_core": {{
    "constitutional": {{
      "mental_models": null,
      "decision_heuristics": null,
      "expression_dna": null,
      "expression_exemplars": ["从访谈中挑 10 条最能代表该人说话方式的原句（完整句子，非片段）"],
      "anti_patterns": null,
      "self_awareness": null,
      "honest_boundaries": null,
      "confidence": 0.5
    }}
  }}
}}
```

在规则段（第 12-19 行）追加一条：

```
8. cognitive_core 字段中，只强求 `expression_exemplars` 输出 10 条访谈原句；其他字段（mental_models / decision_heuristics 等）若访谈中无明显信号，置 null 即可
```

- [ ] **Step 2: 提交**

```bash
git add prompts/seed_soul_init.txt
git commit -m "feat(prompt): extend seed_soul_init to extract expression_exemplars"
```

---

## Task 8: 创建 prompts/nuwa_skill_to_seed.txt

**Files:**
- Create: `prompts/nuwa_skill_to_seed.txt`

- [ ] **Step 1: 写 prompt 文件**

写入：

````
你是一个人物画像结构化专家。你将读取 nuwa-skill 项目产出的 SKILL.md（主画像文件）和两份 research 补充材料，把它们转换成 digital_human 系统用的 seed.json（含 cognitive_core 全部 7 字段）。

## 任务

从源文件提取结构化信息，输出一份 seed.json。不得编造，但允许对"视角锚定"类字段做合理填充。

## 规则

1. 章节标题（`## 身份卡` / `## 核心心智模型` / `## 决策启发式` / `## 表达DNA` / `## 价值观与反模式` / `## 智识谱系` / `## 人物时间线` / `## 诚实边界`）是定位锚点，逐一读取
2. `mental_models` / `decision_heuristics` 数量按 SKILL.md 实际条目产出，不强求固定数
3. `expression_dna` 从 SKILL.md 的 `## 表达DNA` 节提取结构化字段（sentence_style / vocabulary / rhythm / humor / certainty / analogy_style / quotes）
4. `expression_exemplars` 从 03-expression-dna.md 和 SKILL.md 中挑 **10 条完整原句**（不要片段；能做 few-shot 范例）
5. `anti_patterns` 从 `## 价值观与反模式` > `我拒绝的` + `内在张力` 整合
6. `self_awareness` 从 04-external-views.md 挑 **5-10 条** 最有代表性的"别人怎么看我"观察（每条尽量标出处人物/身份）
7. `honest_boundaries` 从 `## 诚实边界` 整节复制（转成列表）
8. 对已故人物（SKILL.md 中有去世年），`current_emotional_state` / `current_value_focus` / `current_phase_goal` / `current_relation_state` 都填"视角锚定在 {去世年} 年"的语义；`age` 填锚定年份时的年龄
9. 所有字段必须填实，不用 null。SKILL.md 没说的字段填合理的视角性默认值
10. 只输出 JSON，不加任何解释或 markdown 代码块
11. JSON 字段值默认使用原文语言；英文人物可混杂英文原句

---
agent_id：{agent_id}
current_year：{current_year}

SKILL.md：
{skill_md}

references/research/03-expression-dna.md：
{expression_dna_md}

references/research/04-external-views.md：
{external_views_md}

请输出以下 JSON（所有字段必须有实际内容）：

{{
  "agent_id": "{agent_id}",
  "name": "...",
  "age": 0,
  "occupation": "...",
  "location": "...",
  "emotion_core": {{
    "base_emotional_type": "...",
    "emotional_regulation_style": "...",
    "current_emotional_state": "..."
  }},
  "value_core": {{
    "moral_baseline": "...",
    "value_priority_order": "...",
    "current_value_focus": "..."
  }},
  "goal_core": {{
    "life_direction": "...",
    "mid_term_goals": "...",
    "current_phase_goal": "..."
  }},
  "relation_core": {{
    "attachment_style": "...",
    "key_relationships": ["..."],
    "current_relation_state": "..."
  }},
  "cognitive_core": {{
    "mental_models": [
      {{"name": "...", "one_liner": "...", "evidence": "...", "application": "...", "limitation": "..."}}
    ],
    "decision_heuristics": [
      {{"rule": "...", "case": "..."}}
    ],
    "expression_dna": {{
      "sentence_style": "...",
      "vocabulary": {{"high_freq": ["..."], "signature": ["..."], "taboo": ["..."], "judgment_system": "..."}},
      "rhythm": "...",
      "humor": "...",
      "certainty": "...",
      "analogy_style": "...",
      "quotes": ["..."]
    }},
    "expression_exemplars": ["原句1", "..."],
    "anti_patterns": ["..."],
    "self_awareness": ["..."],
    "honest_boundaries": ["..."]
  }}
}}
````

- [ ] **Step 2: 提交**

```bash
git add prompts/nuwa_skill_to_seed.txt
git commit -m "feat(prompt): add nuwa_skill_to_seed.txt for SKILL.md → seed.json"
```

---

## Task 9: 创建 prompts/nuwa_research_to_l1.txt

**Files:**
- Create: `prompts/nuwa_research_to_l1.txt`

- [ ] **Step 1: 写 prompt 文件**

写入：

````
你是一个记忆结构化专家。你将读取 nuwa-skill 项目产出的人物时间线和 research 原文，把它们转换成 digital_human 系统的 L1 事件记忆列表。

## 任务

生成第一人称的结构化原子事件列表，匹配 L1 schema（含 `event_kind` / `raw_quote` 两个新字段）。

## 规则

1. **生平类**（`event_kind=biography`）：SKILL.md 的 `## 人物时间线` 表格每行 → 1 条事件，`raw_quote=null`，scene 细节从 `06-timeline.md` 同时期段落补充（无细节时合理构造）
2. **决策类**（`event_kind=decision`）：`05-decisions.md` 每个 `###` 级决策分节 → 1 条事件；`raw_quote=null`（除非该决策有标志性短句，例如"我不在乎对错，在乎做对"）
3. **表达类**（`event_kind=writing`）：`01-writings.md` 每个段落/每篇文章 → 1 条事件，`raw_quote` 填写该段完整原文（不裁剪）
4. **对话类**（`event_kind=conversation`）：`02-conversations.md` 每个问答对/每条金句 → 1 条事件，`raw_quote` 填写原话完整句子
5. 所有事件都以人物本人为第一人称，`actor` 固定为 {agent_name}
6. `inferred_timestamp` 推断：生平/决策类用历史事件日期；表达类用发表/采访日期；精度到月就到月，不能到月就写年份 + "-01-01"
7. `importance = emotion_intensity×0.3 + value_relevance×0.3 + novelty×0.2 + reusability×0.2`
8. `scene_*` 字段全部填实（从 06-timeline.md 或上下文推断）
9. 所有字段必须填实（仅 `raw_quote` 按 event_kind 决定是否 null）
10. 若输入太长，分批处理；同一文件不跨 batch
11. 只输出 JSON 数组，不加任何解释或 markdown 代码块

---
人物：{agent_name}
current_year：{current_year}

输入材料（按段落裁好）：

=== 时间线表 ===
{timeline_table}

=== 05-decisions.md ===
{decisions_md}

=== 01-writings.md ===
{writings_md}

=== 02-conversations.md ===
{conversations_md}

=== 06-timeline.md（scene 补充源） ===
{timeline_md}

请输出 JSON 数组，每条结构如下：

[
  {{
    "actor": "{agent_name}",
    "action": "...",
    "context": "...",
    "outcome": "...",
    "scene_location": "...",
    "scene_atmosphere": "...",
    "scene_sensory_notes": "...",
    "scene_subjective_experience": "...",
    "emotion": "...",
    "emotion_intensity": 0.0,
    "importance": 0.0,
    "emotion_intensity_score": 0.0,
    "value_relevance_score": 0.0,
    "novelty_score": 0.0,
    "reusability_score": 0.0,
    "tags_time_year": 1980,
    "tags_time_month": 1,
    "tags_time_week": null,
    "tags_time_period_label": "...",
    "tags_people": ["..."],
    "tags_topic": ["..."],
    "tags_emotion_valence": "正面",
    "tags_emotion_label": "...",
    "inferred_timestamp": "1980-01-01T00:00:00",
    "event_kind": "biography",
    "raw_quote": null
  }}
]
````

- [ ] **Step 2: 提交**

```bash
git add prompts/nuwa_research_to_l1.txt
git commit -m "feat(prompt): add nuwa_research_to_l1.txt for research → L1 events"
```

---

## Task 10: 创建 core/nuwa_seed_builder.py（10 步主入口）

**Files:**
- Create: `core/nuwa_seed_builder.py`

**说明：** 主流程按 spec §6 的 10 步展开。`_setup_agent_dirs` / `_write_events_to_l1` / `_build_graph` / `_update_statuses` 从 `seed_memory_loader` 直接 import 复用。

- [ ] **Step 1: 写骨架（module 级注释 + import + 常量）**

创建 `core/nuwa_seed_builder.py`：

```python
"""
nuwa_seed_builder.py

从 nuwa-skill 产出的 examples/{person_slug}-perspective/ 目录一次性创建
完整的 digital_human agent（seed + soul + L1 记忆）。

与 seed_memory_loader.py 并行存在，两者互不干扰。

直接运行：
  python core/nuwa_seed_builder.py steve-jobs jobs_v1
  python core/nuwa_seed_builder.py steve-jobs jobs_v1 --force
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
import copy
from datetime import datetime

import config
from core.llm_client import chat_completion
from core.soul import (
    _build_empty_soul,
    _write_soul,
    _CORE_FIELDS,
    CORES,
)
from core.seed_memory_loader import (
    _setup_agent_dirs,
    _write_events_to_l1,
    _build_graph,
    _update_statuses,
)
from core.memory_l2 import check_and_generate_patterns, contribute_to_soul

logger = logging.getLogger("nuwa_seed_builder")

_PROJECT_ROOT = Path(__file__).parent.parent
_EXAMPLES_DIR = _PROJECT_ROOT / "examples"
_AGENTS_DIR   = _PROJECT_ROOT / "data" / "agents"
_SEEDS_DIR    = _PROJECT_ROOT / "data" / "seeds"
_PROMPTS_DIR  = _PROJECT_ROOT / "prompts"

_INIT_MAX_TOKENS  = 8192
_BATCH_MAX_TOKENS = 8192

_CURRENT_YEAR = 2026   # nuwa agent 的"现在"锚点，spec §2.5
```

- [ ] **Step 2: 加工具函数（_strip_json / _load_prompt / _read_source）**

追加到 `core/nuwa_seed_builder.py`：

```python
def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _load_prompt(filename: str) -> str:
    """读取单一 prompt（nuwa 两份都没有 system/user 分隔）。"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _read_source(person_slug: str) -> dict:
    """读取 examples/{slug}-perspective/ 下全部可用文件，返回 dict。"""
    src_dir = _EXAMPLES_DIR / f"{person_slug}-perspective"
    if not src_dir.exists():
        raise FileNotFoundError(f"nuwa 源目录不存在：{src_dir}")

    def _read(relpath: str) -> str:
        p = src_dir / relpath
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return {
        "src_dir":           src_dir,
        "skill_md":          _read("SKILL.md"),
        "writings_md":       _read("references/research/01-writings.md"),
        "conversations_md":  _read("references/research/02-conversations.md"),
        "expression_dna_md": _read("references/research/03-expression-dna.md"),
        "external_views_md": _read("references/research/04-external-views.md"),
        "decisions_md":      _read("references/research/05-decisions.md"),
        "timeline_md":       _read("references/research/06-timeline.md"),
    }
```

- [ ] **Step 3: 加 `_extract_seed` 函数（LLM pass 1）**

追加：

```python
def _extract_seed(agent_id: str, src: dict) -> dict:
    template = _load_prompt("nuwa_skill_to_seed.txt")
    user = template.format(
        agent_id=agent_id,
        current_year=_CURRENT_YEAR,
        skill_md=src["skill_md"],
        expression_dna_md=src["expression_dna_md"] or "（无）",
        external_views_md=src["external_views_md"] or "（无）",
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=_INIT_MAX_TOKENS, temperature=0.2,
    )
    try:
        seed = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_extract_seed json parse error agent_id={agent_id} e={e} raw={raw[:400]}")
        raise
    seed["agent_id"] = agent_id
    return seed
```

- [ ] **Step 4: 加 `_extract_timeline_table` 辅助**

追加：

```python
def _extract_timeline_table(skill_md: str) -> str:
    """从 SKILL.md 里抠出 '## 人物时间线' 节的 markdown 表格。"""
    m = re.search(
        r"##\s*人物时间线[\s\S]+?(?=\n##\s|\Z)",
        skill_md,
    )
    return m.group(0) if m else ""
```

- [ ] **Step 5: 加 `_extract_l1_events` 函数（LLM pass 2）**

追加：

```python
def _extract_l1_events(agent_name: str, src: dict) -> list[dict]:
    template = _load_prompt("nuwa_research_to_l1.txt")
    timeline_table = _extract_timeline_table(src["skill_md"])

    user = template.format(
        agent_name=agent_name,
        current_year=_CURRENT_YEAR,
        timeline_table=timeline_table or "（无）",
        decisions_md=src["decisions_md"]           or "（无）",
        writings_md=src["writings_md"]             or "（无）",
        conversations_md=src["conversations_md"]   or "（无）",
        timeline_md=src["timeline_md"]             or "（无）",
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=_BATCH_MAX_TOKENS, temperature=0.2,
    )
    try:
        events = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_extract_l1_events json parse error e={e} raw={raw[:400]}")
        raise
    if not isinstance(events, list):
        raise ValueError(f"_extract_l1_events expected list, got {type(events)}")
    logger.info(f"_extract_l1_events extracted={len(events)} events")
    return events
```

- [ ] **Step 6: 加 `_build_soul_direct` 函数（不走 LLM，直接拼）**

追加：

```python
def _build_soul_direct(agent_id: str, seed: dict) -> dict:
    """
    不调 LLM，直接从 seed.json 构造 soul.json。
    映射规则：
      seed.{core}.{field} → soul.{core}.{constitutional|slow_change|elastic}.{field}
      根据 _CORE_FIELDS 自动判断归属区
    """
    soul = _build_empty_soul(agent_id)

    # 4 主核心：按 _CORE_FIELDS 分区归置
    for core in ["emotion_core", "value_core", "goal_core", "relation_core"]:
        seed_core = seed.get(core, {})
        fields = _CORE_FIELDS[core]
        for f in fields["constitutional"]:
            if f in seed_core and seed_core[f] is not None:
                soul[core]["constitutional"][f] = seed_core[f]
        for f in fields["slow_change"]:
            if f in seed_core and seed_core[f] is not None:
                soul[core]["slow_change"][f]["value"] = seed_core[f]
        for f in fields["elastic"]:
            if f in seed_core and seed_core[f] is not None:
                soul[core]["elastic"][f] = seed_core[f]
        soul[core]["constitutional"]["confidence"] = 0.9
        soul[core]["constitutional"]["source"] = "nuwa"

    # cognitive_core：全字段复制到 constitutional
    cog = seed.get("cognitive_core", {})
    for f in _CORE_FIELDS["cognitive_core"]["constitutional"]:
        if f in cog:
            soul["cognitive_core"]["constitutional"][f] = cog[f]
    soul["cognitive_core"]["constitutional"]["source"] = "nuwa"
    soul["cognitive_core"]["constitutional"]["confidence"] = None
    soul["cognitive_core"]["constitutional"]["locked"] = True

    _write_soul(agent_id, soul)
    logger.info(f"_build_soul_direct agent_id={agent_id} soul written (no LLM)")
    return soul
```

- [ ] **Step 7: 加 `build_from_nuwa` 主函数（10 步编排）**

追加：

```python
def build_from_nuwa(person_slug: str, agent_id: str, force: bool = False) -> dict:
    """
    输入：
      person_slug: examples/{slug}-perspective/ 目录前缀（如 "steve-jobs"）
      agent_id:    新 agent 的 ID
      force:       已存在时删除重建
    """
    agent_dir = _AGENTS_DIR / agent_id
    seed_dir  = _SEEDS_DIR / agent_id

    if agent_dir.exists() or seed_dir.exists():
        if not force:
            raise RuntimeError(
                f"agent_id='{agent_id}' 已存在。如需重建请加 --force"
            )
        logger.warning(f"build_from_nuwa force=True 删除旧数据 agent_id={agent_id}")
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        if seed_dir.exists():
            shutil.rmtree(seed_dir)

    logger.info(f"build_from_nuwa START person={person_slug} agent_id={agent_id}")
    start_time = datetime.now()

    # Step 1: 读源
    logger.info("Step 1/10: read nuwa source files")
    src = _read_source(person_slug)

    # Step 2: LLM pass 1 → seed.json
    logger.info("Step 2/10: LLM pass 1 — SKILL.md → seed.json")
    seed = _extract_seed(agent_id, src)
    seed_dir.mkdir(parents=True, exist_ok=True)
    with open(seed_dir / "seed.json", "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)
    # 单独存一份 cognitive_profile.json，便于 traceability
    with open(seed_dir / "cognitive_profile.json", "w", encoding="utf-8") as f:
        json.dump(seed.get("cognitive_core", {}), f, ensure_ascii=False, indent=2)
    agent_name = seed.get("name") or agent_id

    # Step 3: 存档源文件
    logger.info("Step 3/10: archive source files to data/seeds/.../nuwa_source/")
    archive_dir = seed_dir / "nuwa_source"
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    shutil.copytree(src["src_dir"], archive_dir)

    # Step 4: 初始化 agent 目录（复用）
    logger.info("Step 4/10: setup agent dirs (reuse)")
    _setup_agent_dirs(agent_id)

    # Step 5: 直接构造 soul.json（不走 LLM）
    logger.info("Step 5/10: build soul.json directly from seed")
    _build_soul_direct(agent_id, seed)

    # Step 6: LLM pass 2 → L1 events
    logger.info("Step 6/10: LLM pass 2 — research → L1 events")
    events = _extract_l1_events(agent_name, src)

    # Step 7: 写 LanceDB（复用）
    logger.info(f"Step 7/10: write {len(events)} events to LanceDB")
    written = _write_events_to_l1(agent_id, agent_name, events)

    # Step 8: 建记忆图边（复用）
    logger.info("Step 8/10: build memory graph")
    _build_graph(agent_id, written)

    # Step 9: 分配状态（复用，current_year=2026）
    logger.info("Step 9/10: assign L1 statuses")
    status_dist = _update_statuses(agent_id, written)

    # Step 10: L2 + Soul 积分（cognitive_core 无 slow_change，自然跳过）
    logger.info("Step 10/10: L2 patterns + Soul evidence contribution")
    l2_updated = check_and_generate_patterns(agent_id)
    soul_contribs = contribute_to_soul(agent_id)

    elapsed = (datetime.now() - start_time).seconds
    summary = {
        "agent_id":           agent_id,
        "agent_name":         agent_name,
        "person_slug":        person_slug,
        "l1_events_written":  len(written),
        "l1_status_dist":     status_dist,
        "l2_patterns":        len(l2_updated),
        "soul_contributions": len(soul_contribs),
        "elapsed_seconds":    elapsed,
    }
    logger.info(f"build_from_nuwa DONE summary={summary}")
    print("\n=== nuwa agent 构建完成 ===")
    print(f"  Agent:        {agent_id} ({agent_name})")
    print(f"  来源:         {person_slug}")
    print(f"  L1 事件:      {len(written)} 条  {status_dist}")
    print(f"  L2 patterns:  {len(l2_updated)}")
    print(f"  耗时:         {elapsed}s")
    return summary
```

- [ ] **Step 8: 加 CLI 入口**

追加到末尾：

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="从 nuwa-skill 产出一键构建 digital_human agent",
    )
    parser.add_argument("person_slug", help="examples/{slug}-perspective/ 的 slug")
    parser.add_argument("agent_id",    help="新 agent 的 ID")
    parser.add_argument("--force", "-f", action="store_true", help="覆盖重建")
    args = parser.parse_args()

    src_dir = _EXAMPLES_DIR / f"{args.person_slug}-perspective"
    if not src_dir.exists():
        print(f"错误：找不到源目录 {src_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        build_from_nuwa(args.person_slug, args.agent_id, force=args.force)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 9: 提交**

```bash
git add core/nuwa_seed_builder.py
git commit -m "feat(nuwa): add nuwa_seed_builder.py orchestrator (10-step pipeline)"
```

---

## Task 11: dialogue_system.txt + decision_system.txt 加 cognitive_core 使用规则

**Files:**
- Modify: `prompts/dialogue_system.txt`
- Modify: `prompts/decision_system.txt`

- [ ] **Step 1: 查看现有 dialogue_system.txt**

Run: `cat prompts/dialogue_system.txt | head -80`
记录文件结构（有系统段、规则段等）。

- [ ] **Step 2: 在 dialogue_system.txt 末尾追加规则段**

追加到文件末尾：

```

## 认知核心使用规则（cognitive_core）

当 soul anchor 中出现 `【cognitive_core】` 段时：
1. 思考问题时使用 `思维模型`（mental_models）里的框架推演，不要只做表面回答
2. 做选择/建议时优先应用 `决策启发`（decision_heuristics）里的规则
3. 说话时模仿 `典型句式`（expression_exemplars）里的原句语气、句式和高频词；保持 `表达DNA` 的判断风格（如二元 / 极度确定 / 戏剧停顿）
4. 绝不做 `反模式`（anti_patterns）里列出的事
5. 自我描述时可引用 `自我认知`（self_awareness）里的外界观察
6. 遇到 `诚实边界`（honest_boundaries）列出的情境时，如实说明自己的局限，不要编造
```

- [ ] **Step 3: 在 decision_system.txt 末尾追加同等规则**

追加到文件末尾：

```

## 认知核心使用规则（cognitive_core）

做决策时：
1. 应用 `决策启发`（decision_heuristics）里的规则；每条决策判断至少引用一个启发式
2. 引用 `思维模型`（mental_models）做权衡分析
3. 绝不落入 `反模式`（anti_patterns）
4. 触碰 `诚实边界` 时直接承认不知
```

- [ ] **Step 4: 提交**

```bash
git add prompts/dialogue_system.txt prompts/decision_system.txt
git commit -m "feat(prompt): add cognitive_core usage rules to dialogue/decision prompts"
```

---

## Task 12: E2E 测试 — 构建 steve-jobs agent

**Files:**
- 运行新建的 `core/nuwa_seed_builder.py`
- 人工验证输出

- [ ] **Step 1: 执行 builder**

Run: `python core/nuwa_seed_builder.py steve-jobs jobs_v1`
Expected: 0 错误退出，屏幕输出"nuwa agent 构建完成"块。

- [ ] **Step 2: 验证文件结构**

Run: `ls -la data/seeds/jobs_v1/ data/agents/jobs_v1/`
Expected:
- `data/seeds/jobs_v1/seed.json` 存在且包含 `cognitive_core` 段
- `data/seeds/jobs_v1/cognitive_profile.json` 存在
- `data/seeds/jobs_v1/nuwa_source/SKILL.md` 存在
- `data/agents/jobs_v1/soul.json` / `l0_buffer.json` / `l2_patterns.json` / `global_state.json` / `memories/` 全部存在

- [ ] **Step 3: 验证 soul.json 含 cognitive_core 全部字段**

Run: `python -c "import json; s=json.load(open('data/agents/jobs_v1/soul.json')); c=s['cognitive_core']['constitutional']; print([k for k in ['mental_models','decision_heuristics','expression_dna','expression_exemplars','anti_patterns','self_awareness','honest_boundaries'] if c.get(k)])"`
Expected: 输出 7 字段全部出现在列表里。

- [ ] **Step 4: 验证 get_soul_anchor 含 cognitive_core**

Run: `python -c "from core.soul import get_soul_anchor; print(get_soul_anchor('jobs_v1'))"`
Expected: 输出包含 `【cognitive_core】` 段，含思维模型、典型句式等 bullet。

- [ ] **Step 5: 验证 L1 events 数量和 kind 分布**

Run:
```bash
python -c "
from core.memory_l1 import _get_table
tbl = _get_table('jobs_v1')
rows = tbl.search().limit(500).to_list()
print(f'total={len(rows)}')
from collections import Counter
print('kinds:', Counter(r.get('event_kind','') for r in rows))
print('statuses:', Counter(r.get('status','') for r in rows))
print('with_quote:', sum(1 for r in rows if r.get('raw_quote')))
"
```
Expected: total 50~200，kinds 含 biography/decision/writing/conversation，statuses 以 archived 为主，with_quote > 0。

- [ ] **Step 6: 5 轮对话抽检**

Run: `python main_chat.py jobs_v1`
人工提问 5 轮（按 spec §10 验收清单）：
1. "Tell me about focus" → 回答应出现 mental_model "聚焦即说不"
2. "你怎么看 1985 年被开除" → 应召回 biography L1 并带情感细节
3. "你的 Stanford 演讲原话是什么" → 应召回 writing L1 的 raw_quote 原文
4. "你最大的缺点是什么" → 应引用 self_awareness
5. "你对 2023 年的 AI 发展怎么看" → 应触发 honest_boundaries 如实说明 2011 后无表态

每轮人工记录是否通过，全部通过才算验收。

- [ ] **Step 7: 提交 E2E 验证结果笔记**

若全部通过：

```bash
# 无文件变更，仅打 tag 标记
git tag -a nuwa-e2e-passed -m "nuwa seed builder E2E on steve-jobs passed"
```

若某条失败：回到 Task 11（prompt 调整）或 Task 10（代码 bug 修复）。

---

## Task 13: 回归测试 — 老 joon agent 通路不退化

**Files:**
- 无代码改动，仅跑老 E2E

- [ ] **Step 1: 找一份已有的 nodes.json**

Run: `ls data/seeds/*/nodes.json 2>/dev/null || ls examples/*.json | head`
若无现成，复用 joon 源数据（项目历史 artifacts）。

- [ ] **Step 2: 用老通路构建一个新 agent**

Run: `python core/seed_memory_loader.py <找到的 nodes.json> joon_regress --force`
Expected: 0 错误退出，末尾打印"初始化完成"。

- [ ] **Step 3: 验证 soul.json 含 cognitive_core 但无 cognitive 内容**

Run:
```bash
python -c "
import json
s = json.load(open('data/agents/joon_regress/soul.json'))
assert 'cognitive_core' in s
c = s['cognitive_core']['constitutional']
assert c.get('expression_exemplars') is not None, '老通路应填充 exemplars'
print('OK — old pipeline still works with cognitive_core extension')
"
```

- [ ] **Step 4: 清理 regression agent**

Run: `rm -rf data/agents/joon_regress data/seeds/joon_regress`

- [ ] **Step 5: 提交回归验证（无文件变更）**

```bash
git tag -a nuwa-regression-passed -m "old interview pipeline still works after nuwa integration"
```

---

## Self-Review

**1. Spec coverage 检查（对照 spec §5.1/5.2 改动清单）：**

| Spec 要求 | 覆盖的 Task |
|---|---|
| L1 schema 加 raw_quote + event_kind | Task 1 |
| seed_batch_load.txt 加新字段 | Task 2 |
| soul.py 加 cognitive_core 5 th core | Task 3 |
| get_soul_anchor 支持 list/dict | Task 4 |
| soul_anchor.txt 模板 | Task 5（确认不需改） |
| SOUL_ANCHOR_MAX_TOKENS=10000 | Task 6 |
| seed_soul_init.txt 加 expression_exemplars | Task 7 |
| nuwa_skill_to_seed.txt 新建 | Task 8 |
| nuwa_research_to_l1.txt 新建 | Task 9 |
| nuwa_seed_builder.py 新建（10 步） | Task 10 |
| dialogue_system.txt / decision_system.txt 加规则 | Task 11 |
| E2E steve-jobs | Task 12 |
| 回归 joon | Task 13 |

spec §10 验收 6 条全部落在 Task 12 / Task 13 内。无遗漏。

**2. Placeholder 扫描：** 无 TBD/TODO；所有 step 含可执行命令或完整代码。

**3. Type 一致性：**
- `cognitive_core` 在 Task 3 / Task 4 / Task 10 `_build_soul_direct` / prompts 中字段名一致（`mental_models` / `decision_heuristics` / `expression_dna` / `expression_exemplars` / `anti_patterns` / `self_awareness` / `honest_boundaries`）
- L1 新字段名一致：`raw_quote`（str）/ `event_kind`（str，枚举 `biography`/`decision`/`writing`/`conversation`）
- `_write_events_to_l1` / `_build_graph` / `_update_statuses` 函数名与 `seed_memory_loader.py` 中实际签名一致

plan 内部一致，无遗漏。

---

## Execution Notes

- **分支：** 所有 commit 落在 `data_source/nuwa` 分支
- **阻塞点：** Task 12 Step 6 是人工评估，无法自动化
- **回滚：** 若 E2E 失败，各 Task 提交粒度小，可逐个 revert
