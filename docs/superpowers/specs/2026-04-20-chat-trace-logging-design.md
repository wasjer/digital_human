---
title: 对话链路解说式日志（Phase A = chat()）
date: 2026-04-20
status: proposed
scope: core/dialogue.py::chat() + 其直接依赖
---

# 对话链路解说式日志（Phase A）

## 1. 背景

`main_chat` 和 tests 当前每轮会打出 10+ 条扁平 INFO 日志，所有行前缀都是 `llm_client`（因
`core/llm_client.py:17` 的 format 硬编码），夹杂 httpx 的 `HTTP Request: POST ...` 行。阅读时
很难拼出"这一轮 chat 里发生了什么"——给自己调试啰嗦，给别人讲流程讲不清。

本 spec 只解决**对话链路**（`core/dialogue.py::chat()` 及其直接依赖）。`make_decision`、
`end_session` 异步部分、`seed_builder`、L2、decay 都在 **Phase A 范围外**，等基建跑顺再扩。

**非目标**：

- 不做可视化 UI。
- 不做机读 JSON / JSONL 输出（YAGNI，没有下游消费者）。
- 不接 LangSmith / LangFuse / Phoenix。
- 不改变任何业务逻辑，只改观测层。

## 2. 目标形态

### 2.1 默认模式（每轮 ~8 行）

```
═══ 轮 1 | agent=jobs_v1 | session=a3f2 | 22:15:03 ═══
[1/4] 情绪检测      → 0.15      (1.2s | tokens 45+2)
[2/4] 记忆检索      → 向量 14 / 去重 14 / 图扩展 +3 / 重排 top 8   (2.3s | 1 embed)
[3/4] 构造 prompt   → system 2340 字 / 注入历史 6 轮 / 记忆 8 条
[4/4] 对话生成      → reply 233 字    (12.1s | tokens 1820+1250→3070)
═══ 轮 1 完成 | 耗时 15.8s | LLM 调用 2 次 | 总 token 3117 ═══
```

### 2.2 Debug 模式（`python main_chat.py <agent_id> --debug`）

**控制台**每个 `[N/4]` 下缩进展开子项：

```
[2/4] 记忆检索      → 向量 14 / 去重 14 / 图扩展 +3 / 重排 top 8
  ├ query embedding  dim=1024 (0.9s)
  ├ 向量召回         候选=20 → 有效=14（已推送去重 0）
  ├ 图扩展           top5 邻居查询 → 新增 3
  ├ 评分重排         weights={relevance:0.35, importance:0.20, recency:0.25, mood_fit:0.20}
  │                 top1 score=0.67 (rel=0.82, imp=0.85, rec=0.33, mood=0.72) | "在帕洛阿尔托..."
  │                 ... (全 8 条)
  └ 命中记忆送出
```

**文件**：`logs/sessions/<session_id>.md`，每轮一个 `## 轮 N` 分节，包含：

- 每次 LLM 调用的完整 `messages`（system / user / assistant 分段贴出）
- LLM 返回的**原始文本**（含 `<think>...</think>`）+ sanitize 后的对比
- retrieve 里**全量候选**（不止 top 8，包括被过滤掉的，带分数）
- 每次调用的 provider / model / effective_max_tokens / usage

## 3. 架构

### 3.1 新增模块 `core/trace.py`

API 采用**扁平打点**设计，不用 `with` 包裹每个步骤——降低业务代码嵌套。

```python
# 伪代码，非最终 API
_current: ContextVar[Optional["Trace"]] = ContextVar("trace", default=None)

class Trace:
    session_id: str
    agent_id: str
    turn_number: int
    debug: bool
    markdown_path: Path | None         # debug 模式才有
    steps: list[Step]                  # 已完成步骤（带耗时、子事件）
    _pending_events: list[Event]       # 上次 mark 至今累积的 events
    _last_mark_ts: float               # 上次 mark 的 monotonic 时间
    _t_start: float                    # turn 开始时间

# 模块级函数（未激活 trace 时自动 no-op，调用处不需要判空）
def turn(agent_id, user_message, debug=False) -> ContextManager:
    """唯一的 with 块：包一整轮。进入时 start_turn，退出时 end_turn（含异常）。"""

def mark(name: str, summary: str | None = None, total: int = 4) -> None:
    """结束当前步骤：elapsed = now - _last_mark_ts；累积的 events 归入该 step；
    _last_mark_ts 更新为 now。summary=None 时由 trace 从 events 自动组装。"""

def event(kind: str, **data) -> None:
    """挂到当前累积区的一条事件（llm_call / embedding / vector_search / ...）。"""

def current() -> Trace | None: ...   # 插桩点偶尔需要判 debug 时才用
```

- **只有一处 `with`**：`main_chat.py` 外层包一次 `with trace.turn(...)`；`chat()` 内部
  4 次 `trace.mark(...)` 扁平打点，没有嵌套缩进。
- 用 `contextvars.ContextVar` 存当前 trace，`llm_client` 和 `retrieval` 从上下文取，
  **不需要改函数签名**。
- 未激活 trace 时（tests 里、`seed_builder` 跑批时）`mark` / `event` 都是 no-op，
  调用处不写 `if current():` 判空。这意味着 tests 里跑 `chat()` 不会出任何解说、
  不会落盘，只剩 §6 清理后的 WARN / ERROR / DEBUG（按 `LOG_LEVEL`）。
- 线程边界：`end_session` 的后台线程不复用对话轮的 trace（Phase A 范围外），不需要
  `copy_context()`。

### 3.2 session_id 口径

从 `dialogue._load_l0(agent_id)["session_id"]` 取——和写 L1 的 session_id 一致，
以后对照 L1 事件很方便。首轮 `_load_l0` 刚好会生成 session_id 赋值进 buffer。

## 4. 插桩点（4 个文件）

| 文件 | 改动 |
|---|---|
| `main_chat.py` | argparse 加 `--debug`；每轮 `chat()` 调用外包 `with trace.turn(agent_id, user_input, debug=args.debug)` |
| `core/dialogue.py::chat()` | 4 个 `# ── N. ──` 区段末尾各加一行 `trace.mark(name, summary=...)` |
| `core/retrieval.py::retrieve()` | 每个阶段（embed / vector / graph / score / rerank）一行 `trace.event(...)` |
| `core/llm_client.py` | `chat_completion` / `get_embedding` 捕获 usage + 耗时 + messages + raw，一行 `trace.event("llm_call", ...)` / `trace.event("embedding", ...)` |

### 4.1 chat() 的 4 个步骤（扁平打点示例）

```python
def chat(agent_id, user_message, session_history, session_surfaced=None):
    ...
    emotion_intensity = _detect_emotion(user_message)
    trace.mark("情绪检测", summary=f"{emotion_intensity:.2f}")

    # L0 buffer 更新、情绪快照 —— 非 LLM/检索步骤，不单独 mark

    retrieval_result = retrieve(agent_id, user_message, mode="dialogue", ...)
    trace.mark("记忆检索")  # summary=None → trace 从 retrieve 的 events 自动组装

    messages = _build_messages(...)
    trace.mark("构造 prompt",
               summary=f"system {len(system_prompt)} 字 / 历史 {min(6,len(session_history))} 轮 / 记忆 {len(memories)} 条")

    reply = chat_completion(messages, max_tokens=512, temperature=0.7)
    trace.mark("对话生成")  # summary=None → trace 从 llm_call event 自动组装

    return {...}
```

1. `[1/4] 情绪检测` — `_detect_emotion()` 这次 LLM 调用（event 来自 llm_client）
2. `[2/4] 记忆检索` — `retrieve()` 整个（内部 events 见 §4.2）
3. `[3/4] 构造 prompt` — 拼接 system_prompt、注入 session_history、记忆块、L2 块
4. `[4/4] 对话生成` — 主 `chat_completion()` 调用

### 4.2 retrieve() 的子事件

按现有代码节拍打点：

- `embedding`：dim、text_len、耗时
- `vector_search`：raw_hits、after_dedup、limit（`_RETRIEVAL_TOP_K`）、耗时
- `graph_expand`：top5_ids、neighbors_added、skipped（已在 pool / already_surfaced）
- `score_rerank`：weights、candidate_pool、top_k_returned；debug 模式下附全量打分明细
- `llm_rerank`（decision 模式专有，Phase A 不会触发，但结构预留）

## 5. 输出细节

### 5.1 默认模式每行格式

- 步骤行：`[N/total] {步骤名:<10} → {summary}    ({耗时} | {tokens_or_embeds})`
- 对齐：步骤名固定宽度 10，箭头后自由写
- **summary 来源**：
  - 调用方在 `mark(name, summary=...)` 显式传入时使用调用方的
  - `mark(name, summary=None)` 时，trace 根据本步骤累积的 events 自动组装：
    - `llm_call` event 聚合 → `reply {n} 字`
    - `embedding` + `vector_search` + `graph_expand` + `score_rerank` 聚合 →
      `向量 {vector_hits} / 去重 {after_dedup} / 图扩展 +{n} / 重排 top {k}`
  - 自动组装模板在 `core/trace.py` 里集中维护，业务代码不关心

### 5.2 Debug 模式 markdown 模板

```markdown
# Session a3f2 (agent=jobs_v1)
开始于 2026-04-20T22:15:03

## 轮 1 (22:15:03, 耗时 15.8s)

**用户输入**：我今天感觉有点累

### [1/4] 情绪检测 → 0.15 (1.2s)

**provider**: minimax | **model**: minimax-m2.7-highspeed | **usage**: prompt=45 completion=2 total=47

#### messages
```
system: 分析以下消息的情绪强度...
user: 我今天感觉有点累
```

#### raw response
```
<think>用户表达了轻度疲劳...</think>
0.15
```

#### sanitized
```
0.15
```

### [2/4] 记忆检索 → 向量14/去重14/图扩展+3/重排top8 (2.3s)

#### query embedding
dim=1024, 耗时 0.9s

#### 向量召回（全 14 条，按 LanceDB 原始分数）
| # | event_id | 相似度 | 重要度 | days | content(80) |
|---|---|---|---|---|---|
| 1 | ... | 0.82 | 0.85 | 2 | ... |
...

#### 图扩展
- top5 输入：`[e1, e2, e3, e4, e5]`
- 邻居查询结果：新增 3 条、跳过 2 条（1 在 pool / 1 已推送）

#### 评分重排（全候选 17 条，按加权分数）
weights={relevance:0.35, importance:0.20, recency:0.25, mood_fit:0.20}
| # | score | rel | imp | rec | mood | source | content |
|---|---|---|---|---|---|---|---|
| 1 | 0.67 | 0.82 | 0.85 | 0.33 | 0.72 | vector | ... |
...

（顶部 8 条被送出；其余 9 条列在下面供参考）

### [3/4] 构造 prompt → system 2340 字 / 历史 6 轮 / 记忆 8 条

#### 最终 messages
```
[0] system (2340 字):
你是 Joon ...
...

[1] user (本轮前第 3 轮):
...
[2] assistant (本轮前第 3 轮):
...
...
[6] user (本轮):
我今天感觉有点累
```

### [4/4] 对话生成 → reply 233 字 (12.1s)

**provider**: minimax | **model**: minimax-m2.7-highspeed
**max_tokens**: 512×16→8192 | **usage**: prompt=1820 completion=1250 total=3070

#### raw response (含 <think>)
```
<think>
基于 Joon 的 soul anchor ... 我应该用温和的方式共情...
</think>
其实我这两天也有类似的感觉，可能是...
```

#### sanitized reply
```
其实我这两天也有类似的感觉，可能是...
```

---
轮 1 小结：LLM 2 次 / embed 1 次 / 总 token 3117 / 耗时 15.8s
```

### 5.3 落盘策略

- `logs/sessions/` 目录在首次启动 debug 模式时自动创建
- 每轮结束后**追加**写入对应 session 文件（不是全部缓冲到 quit 再写，防止中途崩溃丢失）
- quit 时在末尾追加 session 小结（总轮数、总 token、总耗时）
- 同一 `session_id` 多次启动 main_chat 会继续追加（L0 buffer 还没 end_session 前 session_id 不变）

## 6. 噪音清理

不依赖新 trace，但不做会抵消效果：

- `core/llm_client.py:17` format 硬编码 `"llm_client"` → 改成 `%(name)s`
- `logging.getLogger("httpx").setLevel(logging.WARNING)`、`openai` 同样处理
- 以下日志降到 DEBUG（`LOG_LEVEL=DEBUG` 时仍可见，平时不刷屏）：
  - `_retry` 里的 `success attempt=1`
  - `chat_completion result_len=X sanitize_trimmed=Y`
  - `chat_completion max_tokens=AxB->C (provider reasoning budget)`
  - `retrieve vector_hits=...`、`retrieve candidate_pool=...`、`retrieve done ...`
  - `get_embedding dim=...`、`get_embedding success attempt=1`
- `basicConfig` 用 `force=False`（默认），避免被测试框架二次 import 时覆盖

## 7. Token 捕获

`chat_completion()` 不改返回签名，在内部拿到 `resp.usage` 后调用模块级 `trace.event`
（未激活时自动 no-op，**无需 `if` 判空**）：

```python
usage = getattr(resp, "usage", None)
trace.event(
    "llm_call",
    provider=provider, model=model,
    messages=messages, raw=raw, sanitized=result,
    prompt_tokens=getattr(usage, "prompt_tokens", None),
    completion_tokens=getattr(usage, "completion_tokens", None),
    total_tokens=getattr(usage, "total_tokens", None),
    effective_max_tokens=effective_max,
    elapsed_ms=..., attempt=...,
)
```

- 所有字段用 `getattr(..., None)`；某些 provider 不返回 usage 时汇总显示 `tokens=?`
- 轮次结尾汇总 = 本轮所有 `llm_call` event 的 `total_tokens` 之和（None 跳过并标注）

## 8. CLI 变更（`main_chat.py`）

```
python main_chat.py <agent_id>              # 默认模式
python main_chat.py <agent_id> --debug      # debug 模式（控制台展开 + 落盘）
```

- 使用 `argparse`（目前是 `sys.argv`）
- `--debug` 开启时提示："[debug] log: logs/sessions/<session_id>.md"
- 不引入其他 flag（`-v` / `--trace` 等都 YAGNI）

## 9. 不做 / 延后

- `make_decision` / `end_session` 异步 / `seed_builder` / L2 / decay → Phase B 再说
- JSON / JSONL 输出 → 真有评估脚本需求再加
- Web UI / Mermaid 图 → 讨论过，现阶段调试优先，不做
- 把 LLM 的 `<think>` 内容单独渲染成可折叠块 → markdown 里已经 fenced，够看了
- 跨进程 / 分布式 trace → 单进程应用，不需要

## 10. 验收

1. `python main_chat.py jobs_v1` 随便聊一轮 → 控制台 7–9 行，结构对应 §2.1
2. `python main_chat.py jobs_v1 --debug` 聊一轮 → 控制台展开子项，`logs/sessions/<id>.md`
   写入一份内容对应 §5.2 模板的 markdown
3. `pytest tests/` 跑完 → 输出里没有 `HTTP Request: POST ...`、没有成片的
   `chat_completion success attempt=1`；ERROR / WARN 仍然可见
4. 某次 LLM 调用异常 / retry → 默认模式仍然打出错误行，debug 模式 markdown 里能看到每次
   attempt 的 raw（含报错）
5. 修改 `config.LLM_PROVIDER` 切换 provider → 日志里的 provider / model / usage 正确反映
   当前 provider；不需要改任何 trace 代码

## 11. 文件改动清单

- **新增**：`core/trace.py`
- **修改**：`main_chat.py`、`core/dialogue.py`、`core/retrieval.py`、`core/llm_client.py`
- **新增目录**：`logs/sessions/`（运行时创建）
- **测试**：`tests/test_trace.py`（trace 模块单测）、`tests/test_dialogue_trace.py`
  （跑一轮 chat 验证输出结构——用 mock provider 避免真调 LLM）
