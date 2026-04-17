# 从访谈记录初始化 Agent：第三条初始化通路

**日期**：2026-04-17
**状态**：设计定稿，待实施
**作者**：stone + claude

---

## 1. 背景与目标

当前 digital_human 项目有两条 agent 初始化通路：

1. **seed 通路**（`core/seed_memory_loader.py`）：从结构化的 `nodes.json`（带 importance 的节点）初始化。
2. **nuwa 通路**（`core/nuwa_seed_builder.py`）：从 `examples/<slug>-perspective/` 的 skill + research md 文件夹初始化。

本设计新增**第三条通路**：从 `interview_source/<prefix>-interview-...md`（另一工具产出的访谈对话 md）初始化 agent，使 agent 具有访谈所体现的人格并能就访谈内容展开后续对话。

**核心要求**：

- 从访谈中抽取 Soul 五核心（emotion / value / goal / relation / cognitive）
- 每字段带 confidence，**confidence < 0.5 的字段不写入 soul.json**（保持 null），但全量保留在 seed.json 作为审计层
- 低置信字段列入 `build_report.md` 的"回访建议"区，作为下一轮访谈的追问清单
- L1 长期记忆 = 受访者在访谈中叙述的人生事件 + 1 条"参加访谈本身"的 meta 事件
- L0 工作记忆注入一段第一人称摘要（`recent_self_narrative`），让 agent 首次对话有 recency 感
- L2 pattern 初始化时放宽时间限制，让近期事件也能参与归纳
- 每次构建产出 `build_report.md`，为访谈 / seed / soul 三方一致性提供单页视图
- 与现有两条通路并行存在，互不干扰

---

## 2. 架构

```
interview_source/<prefix>-interview-...md
            │
            ▼
┌─ core/interview_seed_builder.py ──────────────────────┐
│  build_from_interview(md_path, force=False)           │
│                                                       │
│  Step 1  解析 frontmatter + 分离访谈员/受访者对话      │
│  Step 2  从文件名推导 agent_id；存在性 / force 检查    │
│  Step 3  归档 md → data/seeds/<id>/interview_source/  │
│  Step 4  LLM pass 1：访谈 → seed.json（带 confidence  │
│          + recent_self_narrative + follow_up_qs）     │
│          prompts/interview_to_seed.txt                │
│  Step 5  confidence gate + 直接构造 soul.json         │
│  Step 6  _setup_agent_dirs（复用）+ 写入 L0 摘要       │
│  Step 7  LLM pass 2：访谈 → biography L1 事件          │
│          prompts/interview_to_l1.txt                  │
│  Step 8  确定性构造 1 条 meta 事件（访谈本身）         │
│  Step 9  _write_events_to_l1 + _build_graph           │
│          + _update_statuses                           │
│  Step 10 check_and_generate_patterns(                 │
│            include_all_statuses=True)                 │
│          + contribute_to_soul                         │
│  Step 11 写 build_report.md + stdout 摘要              │
└───────────────────────────────────────────────────────┘
```

### 复用 vs 新增

| 复用（不改） | 新增 |
|---|---|
| `_setup_agent_dirs` / `_write_events_to_l1` / `_build_graph` / `_update_statuses`（`seed_memory_loader.py`） | `core/interview_seed_builder.py` |
| `_build_empty_soul` / `_write_soul` / `_CORE_FIELDS` / `CORES`（`soul.py`） | `prompts/interview_to_seed.txt` |
| `init_global_state`（`global_state.py`） | `prompts/interview_to_l1.txt` |
| `check_and_generate_patterns` / `contribute_to_soul`（`memory_l2.py`，**需加参数**） | builder 内部：`_parse_interview_md` / `_apply_confidence_gate` / `_build_meta_event` / `_write_build_report` / `_derive_agent_id` |
| `chat_completion` / `get_embedding`（`llm_client.py`） | config 常量：`LLM_MAX_OUTPUT_TOKENS` / `INTERVIEW_CONFIDENCE_THRESHOLD` |

---

## 3. 输入、输出、产物

### 3.1 输入

- 位置：`interview_source/<prefix>-interview-<session_id>-<date>.md`
- 格式：YAML frontmatter + markdown body（body 按 `**受访者**` / `**小灵**` 分块，保留模块标题 `## 模块 N：...`）
- frontmatter 最少字段：`session_id`, `completed_at`, `interview_duration_minutes`, `modules_completed`

### 3.2 产物

```
data/seeds/<agent_id>/
  seed.json                  # 带 confidence 的 LLM 原始输出（审计层）
  interview_source/
    <原文件名>.md            # 原访谈归档
  build_report.md            # 本次构建报告

data/agents/<agent_id>/
  soul.json                  # confidence ≥ 0.5 才填入；低分字段 null
  l0_buffer.json             # 含 working_context.recent_self_narrative（第一人称摘要）
  l2_patterns.json           # L2 归纳产出
  global_state.json          # init_global_state
  memories/                  # LanceDB（life events + meta event）
  graph.db                   # memory graph sqlite
```

### 3.3 agent_id 推导规则

文件名模式：`^([a-z0-9_]+)-interview-[a-z0-9]+-\d{4}-\d{2}-\d{2}\.md$`
`agent_id` = 第一捕获组（如 `txf-interview-cmo0d7li-2026-04-15.md` → `txf`）
不匹配则报错退出，提示使用 `--agent-id <id>` 后门参数显式指定。

---

## 4. Prompt 设计

### 4.1 `prompts/interview_to_seed.txt`（新建）

**输入占位符**：`{agent_id}`, `{interview_date}`, `{duration_minutes}`, `{dialogue_text}`

**输出 JSON 结构**（每个可推断字段为 `{"value": ..., "confidence": 0.0~1.0}`）：

```json
{
  "name": {"value": "...", "confidence": 0.95},
  "age": {"value": 42, "confidence": 0.99},
  "occupation": {"value": "...", "confidence": 0.98},
  "location": {"value": "...", "confidence": 0.99},

  "emotion_core": {
    "base_emotional_type":        {"value": "...", "confidence": ...},
    "emotional_regulation_style": {"value": "...", "confidence": ...},
    "current_emotional_state":    {"value": "...", "confidence": ...}
  },
  "value_core":    { ... },
  "goal_core":     { ... },
  "relation_core": { ... },

  "cognitive_core": {
    "mental_models":        {"value": [...], "confidence": ...},
    "decision_heuristics":  {"value": [...], "confidence": ...},
    "expression_dna":       {"value": "...",  "confidence": ...},
    "expression_exemplars": {"value": ["原句1", ...10条], "confidence": ...},
    "anti_patterns":        {"value": [...], "confidence": ...},
    "self_awareness":       {"value": "...",  "confidence": ...},
    "honest_boundaries":    {"value": "...",  "confidence": ...}
  },

  "recent_self_narrative": "200~400 字第一人称摘要，描述这次访谈聊了什么、我讲了哪些关键自述",

  "follow_up_questions": {
    "<core>.<field>": ["针对 conf < 0.5 字段的追问 1", "..."],
    ...
  }
}
```

**Prompt 核心规则**：

1. 只允许用访谈中明确出现或强证据可推断的信息
2. 没有线索的字段 → `{"value": null, "confidence": 0.0}`
3. confidence 标定：≥ 2 处一致证据给 ≥ 0.7；仅 1 处孤证或语气揣测给 ≤ 0.5；无证据给 0.0
4. 禁止用常识 / 刻板印象补空
5. `expression_exemplars` 必须逐字抄 10 条受访者原句，不是片段、不改写
6. `recent_self_narrative` 是第一人称叙述（"我前几天…我聊到…"），不是第三人称总结
7. `follow_up_questions` 只列 confidence < 0.5 的字段，每字段 1–2 条具体追问

### 4.2 `prompts/interview_to_l1.txt`（新建）

借鉴 `seed_batch_load.txt`，但针对对话叙事体做三处改动：

1. 输入是整段访谈，明确告诉 LLM：**提取受访者自己叙述过的过往人生事件**；访谈员的话只作语境理解，不要把访谈员的总结 / 重述当成事件
2. 时间推断锚点：`受访者在 {interview_date}（{current_age} 岁）接受访谈`，逆推 `tags_time_year / inferred_timestamp`
3. `event_kind = "biography"`；`raw_quote` **填受访者原话**（与老通路的 null 不同，访谈有原句可抓）

写入 LanceDB 时 `source = "interview"`（区别于老通路的 `"seed"`）。

### 4.3 Confidence gate 执行

```python
def _gate(node, threshold: float = None):
    """LLM 输出 {"value":..., "confidence":...} → 过阈则返回原值，否则 None"""
    threshold = threshold or config.INTERVIEW_CONFIDENCE_THRESHOLD
    if not isinstance(node, dict):
        return None
    value = node.get("value")
    conf  = node.get("confidence") or 0.0
    if not isinstance(conf, (int, float)):
        conf = 0.0
    return value if (value is not None and conf >= threshold) else None
```

按 `_CORE_FIELDS` 映射：constitutional / slow_change / elastic 三区分别取值后走 `_build_empty_soul` → 填入 → `_write_soul`。constitutional 区的 `confidence` 元数据写 LLM 的原始分（即使过阈也记录）；`source` 设为 `"interview"`。

**`confidence_detail` 的使用**：五核心中只有 `cognitive_core` 的 constitutional 区有多字段（mental_models / decision_heuristics / expression_dna / expression_exemplars / anti_patterns / self_awareness / honest_boundaries 共 7 字段），用 `confidence_detail: {field: conf, ...}` dict 记录每字段分。其他四核心（emotion / value / goal / relation）constitutional 区只有 1 字段，直接用单一 `confidence` 标量即可，不设 `confidence_detail`。现有代码不读 `confidence_detail`，加这个字段不会回归。

---

## 5. Meta 事件（确定性构造，无 LLM）

```python
meta_event = {
    "actor": agent_name,
    "action": "参加了一次关于人生经历的深度访谈",
    "context": f"在一个对话式访谈系统里和访谈员'小灵'聊了约 {duration_minutes} 分钟",
    "outcome": f"按顺序聊了 {len(modules_completed)} 个模块：开场、人生十字路口、"
               "对未来的希望、价值观与信念、当下的生活、重要的人、人生故事、收尾",
    "emotion": "平静、略带回顾感",
    "emotion_intensity": 0.3,
    "importance": 0.6,
    "novelty_score": 0.7,
    "reusability_score": 0.4,
    "inferred_timestamp": completed_at,
    "tags_topic": ["访谈", "自我叙述"],
    "source": "interview_meta",
    "event_kind": "meta",
    "raw_quote": None,
    ...
}
```

`event_kind = "meta"` 是新类别值（LanceDB schema 字段为 utf8，无需改 schema），用于日后筛选。

**模块标题与访谈员名字的来源**：
- 模块标题（"开场 / 人生十字路口 / ..."）从 md body 解析 `^## 模块 (\d+)：(.+)$` 得到编号 → 标题的映射，再按 `modules_completed` 列表顺序拼接。避免硬编码，兼容不同访谈模块集。
- 访谈员名字（当前实现为"小灵"）从 md 中第一处 `**(\S+?)**\n` 出现且非"受访者"的发言块提取；提取失败回退为固定字符串 `"访谈员"`。

---

## 6. L0 注入

`l0_buffer.json.working_context.recent_self_narrative` 字段（新增，不改原 schema）写入 LLM pass 1 产出的第一人称摘要。`raw_dialogue` 保持空列表（**不塞访谈原文**）。

**设计依据**：
- 全量注入 `raw_dialogue` 会导致：(a) 每轮对话 prompt ~20–40k tokens；(b) 24 小时后 TTL 过期退化；(c) end_session 的 L0→L1 consolidation 会把访谈二次抽成 L1，产生重复；(d) 访谈员"小灵"被误认为当前用户，串角色
- 只注入第一人称摘要：agent 首次对话有 recency，token 成本可控，无串角色，无重复抽取。逐字引用走 L1 `raw_quote` 字段

---

## 7. L2 初始化放宽

`core/memory_l2.py` 修改 `check_and_generate_patterns`：

```python
def check_and_generate_patterns(
    agent_id: str,
    include_all_statuses: bool = False,
) -> list[str]:
    ...
    if include_all_statuses:
        events = _fetch_all_events(agent_id)       # 新增
    else:
        events = _fetch_archived_events(agent_id)  # 原行为不变
    ...
```

**三条初始化通路**（`seed_memory_loader` / `nuwa_seed_builder` / 新 `interview_seed_builder`）调用时传 `include_all_statuses=True`；`decay_job` 等运行期调用保持默认 False。

**不改**：`L2_SAME_TOPIC_THRESHOLD = 3`、`L2_SOUL_CONTRIBUTION_THRESHOLD = 0.8`。只放时间限制，不松样本 / 置信度阈值。

---

## 8. `build_report.md` 结构

```markdown
# Agent 构建报告：<agent_id>

- 构建时间：<now>
- 来源：interview_source/<filename>.md
- 访谈时间：<completed_at>（时长 <duration> 分钟）
- 访谈 session_id：<session_id>
- 耗时：<elapsed>s

## 基础身份

| 字段 | 值 | confidence |
|---|---|---|

## Soul 填充情况（每核一节）

### emotion_core / value_core / goal_core / relation_core / cognitive_core
| 区 | 字段 | 状态（✅ 已写入 / ⚠️ 未写入-回访） | conf |
|---|---|---|---|

## 回访建议（下次访谈重点追问）

列出所有 0 < confidence < 0.5 的字段，含：
- LLM 临时判断值
- 主要证据摘录
- LLM 建议的追问（来自 follow_up_questions）

## L1 记忆

- Biography 事件数 / Meta 事件数 / 总计
- 状态分布：active / dormant / archived
- 按 tags_topic 聚合分布

## L2 Patterns

- 生成数 + 每条 one-liner 摘要

## Soul 证据贡献

- L1 → Soul 缓变区积分次数
- 触发 slow_change 字段数
```

---

## 9. 错误处理

| 场景 | 处理 |
|---|---|
| 文件名不符合 `<prefix>-interview-...` 模式 | 报错退出，提示用 `--agent-id` 后门参数 |
| frontmatter 缺失 / `completed_at` 无法解析 | 警告 + 回退 `datetime.now()`，报告注明 |
| md 找不到"受访者"块 | 硬报错退出，不留半成品 |
| LLM pass 1 返回非 JSON / 关键字段缺失 | 记录 `raw[:400]` 到 log，构建失败退出 |
| LLM pass 2 部分 batch 失败 | 记录 error 继续剩余 batch（沿袭老通路行为） |
| 字段 `confidence` 非数字 / 缺失 | 视为 `0.0`，不写 soul，进回访清单 |
| 低 confidence 字段 LLM 给了 value | 仍收入 seed.json 与报告，soul 留 null |
| `agent_id` 已存在 + 无 `--force` | 报错退出 |
| `--force` 时 | 删除 `data/agents/<id>/` 和 `data/seeds/<id>/` 重建 |

---

## 10. 老代码清理（本任务并做）

### 10.1 新建 config 常量

```python
# config.py 新增
LLM_MAX_OUTPUT_TOKENS = 8192
INTERVIEW_CONFIDENCE_THRESHOLD = 0.5
```

### 10.2 遗留 max_tokens 统一

| 文件:行 | 原值 | 改为 |
|---|---|---|
| `core/seed_parser.py:104` | `max_tokens=1024` | `config.LLM_MAX_OUTPUT_TOKENS` |
| `core/soul.py:189` | `max_tokens=2048` | `config.LLM_MAX_OUTPUT_TOKENS` |
| `core/seed_memory_loader.py` `_INIT_MAX_TOKENS`、`_BATCH_MAX_TOKENS` | 8192 | `config.LLM_MAX_OUTPUT_TOKENS` |
| `core/nuwa_seed_builder.py` `_INIT_MAX_TOKENS`、`_BATCH_MAX_TOKENS` | 8192 | `config.LLM_MAX_OUTPUT_TOKENS` |
| `core/llm_client.py:75` `chat_completion` 默认 `max_tokens` | 1024 | **4096**（安全兜底） |

**不动**：`dialogue.py` / `retrieval.py` / `memory_l1.py` / `memory_l2.py` 运行期调用的 max_tokens（16 / 64 / 256 / 512），不属于初始化范围。

### 10.3 `memory_l2.py` 加参数

- `check_and_generate_patterns` 签名：`(agent_id: str, include_all_statuses: bool = False)`
- 新增 `_fetch_all_events(agent_id)` 辅助函数（取所有 status 的事件）

### 10.4 三条 init 通路调用点更新

```python
# seed_memory_loader.py Step 8
l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)

# nuwa_seed_builder.py Step 10
l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)

# interview_seed_builder.py Step 10（新）
l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)
```

---

## 11. CLI

```bash
python core/interview_seed_builder.py interview_source/txf-interview-cmo0d7li-2026-04-15.md
python core/interview_seed_builder.py <md_path> --force
python core/interview_seed_builder.py <md_path> --agent-id custom_id   # 文件名推导失败时的后门
```

---

## 12. 测试

`tests/test_interview_seed_builder.py`（mock LLM，不跑真 API）：

1. `_parse_interview_md` 正常路径（txf fixture）
2. `_parse_interview_md` 异常分支：文件名不合法 / frontmatter 缺失 / 找不到受访者块
3. `_apply_confidence_gate` 边界：≥ 0.5 通过、< 0.5 置 None、= 0 / 缺失 / 异常 conf
4. `_build_meta_event` 字段正确：`event_kind="meta"` / `source="interview_meta"` / `inferred_timestamp=completed_at`
5. `_write_build_report`：回访建议只列 0 < conf < 0.5，格式正确
6. 端到端 smoke（mock 两次 `chat_completion` + `get_embedding`）：所有产物文件齐全，`l0_buffer.recent_self_narrative` 非空
7. `check_and_generate_patterns(agent_id, include_all_statuses=True)` 覆盖 active/dormant 事件
8. `check_and_generate_patterns(agent_id)` 默认行为保持旧（只 archived）

**不测**：LLM 输出语义质量（prompt 调优范畴，肉眼验收）。

---

## 13. 实施顺序

| Step | 动作 | 验证 |
|---|---|---|
| 1 | `config.py` 加两个常量 | 跑 `import config` |
| 2 | 三处遗留 max_tokens 改成 config 常量 | 现有测试不回归 |
| 3 | `llm_client.py` 默认 `max_tokens` 1024 → 4096 | 现有测试不回归 |
| 4 | `memory_l2.check_and_generate_patterns` 加 `include_all_statuses` 参数 + `_fetch_all_events` | 单元测试 2 条（新旧行为） |
| 5 | 三条 init 通路调用点更新为 `include_all_statuses=True` | 现有 seed / nuwa 测试不回归 |
| 6 | 新建 `prompts/interview_to_seed.txt` + `prompts/interview_to_l1.txt` | 人工读 prompt |
| 7 | 新建 `core/interview_seed_builder.py` 骨架 + `_parse_interview_md` + `_derive_agent_id` | 单元测试 1 / 2 |
| 8 | 加 `_apply_confidence_gate` + `_build_meta_event` | 单元测试 3 / 4 |
| 9 | 加 LLM 调用函数 + `_write_build_report` | 单元测试 5 |
| 10 | 串联成 `build_from_interview()` + CLI 入口 | smoke test 6 |
| 11 | 真 LLM 跑 txf，肉眼验收 seed.json / soul.json / build_report.md / L0 摘要 | 手动 |
| 12 | 如 cognitive_core 质量不达标，迭代 prompt 重跑（`--force`） | 手动迭代 |

---

## 14. 风险与约束

1. **Prompt 质量依赖**：`cognitive_core` 和低置信字段的判定完全靠 prompt。第一次跑需要 2–3 轮调优，之后报告扫一眼即可
2. **DeepSeek output 上限 8192 是硬限**：超长访谈（> 25k 输入）可能导致 seed 输出被截断。此时要考虑拆 cognitive_core 单独一次调用，但本版本不做，留 TODO
3. **meta event 的时间锚点**：用 `completed_at`，`_update_statuses` 会判成 active（< 1 年），预期行为
4. **L2 可能仍为空**：即使放开了 status，同话题事件仍需 ≥ 3 条才归纳。信息密度低的访谈可能产 0 条 pattern，属正常
5. **与老通路的隔离**：`interview_seed_builder` 不 import 任何 `_init_soul_from_nodes` / `_extract_events_batch` 等老 LLM 调用，只复用不含 LLM 的基础设施函数（`_setup_agent_dirs` / `_write_events_to_l1` / `_build_graph` / `_update_statuses`）

---

## 15. 未来扩展（不做）

- 支持多份访谈合并初始化同一 agent（增量模式）
- 回访后合并新 seed 到已有 soul（而非 `--force` 重建）
- build_report.md 导出 HTML / 可视化
- 真 LLM 跑完后的自动语义一致性检查（而非人工）
