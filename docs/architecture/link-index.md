# 链路索引（self-reference）

> 主流程：`main_chat.py` → `core.dialogue.chat` → `core.retrieval.retrieve` → LLM → `core.dialogue.end_session`（sync + async）
> 最后更新：2026-04-20

## 1. chat() 流程（core/dialogue.py:137）

| # | 步骤 | 代码位置 | 副作用 |
|---|------|----------|--------|
| 1 | 情绪检测 | `_detect_emotion` L150 | LLM 1 次 |
| 2 | 情绪峰值快照（若 > EMOTION_SNAPSHOT_THRESHOLD） | L159–166 | 写 l0_buffer |
| 3 | `retrieve()` 记忆检索 | L170 | 见下 |
| 4 | 更新 session_surfaced + `trace.mark("记忆检索")` | L177–178 | — |
| 5 | 追加 user 消息到 l0_buffer | L181 | 写 l0_buffer |
| 6 | 拼 system prompt（含 soul_anchor / current_state / l2_patterns / memories） | L184–210 | — |
| 7 | LLM 生成回答 | L219 | LLM 1 次 |
| 8 | 追加 assistant 消息到 l0_buffer | L226–228 | 写 l0_buffer |

## 2. retrieve() 流程（core/retrieval.py:167）

| # | 步骤 | 代码位置 |
|---|------|----------|
| 1 | get_soul_anchor | L180 |
| 2 | 读 global_state，拼 current_state_text | L186–193 |
| 3 | 加载 l0_buffer → working_context | L196–197 |
| 4 | L2 patterns 检索 | L200–202 |
| 5 | query embedding（SiliconFlow bge-m3） | L205–207 |
| 6 | LanceDB 向量检索 top20 + session_surfaced 去重 | L210–230 |
| 7 | 图扩展：top5 各自 get_neighbors | L233–268 |
| 8 | 按 mode 权重 _score_candidate 排 top8 | L272–302 |
| 9 | decision 模式 LLM 精排 | L305–312 |
| 10 | 构建输出（freshness_text） | L314–347 |
| 11 | 更新 access_count | L349–354 |
| 12 | strengthen_links_on_retrieval | L357–361 |

## 3. end_session() 流程（core/dialogue.py:364）

### 同步（_end_session_sync L238）
- 拼会话文本（emotion peaks + 完整对话）
- `memory_l1.write_event(agent_id, session_text, source='session')` → LanceDB 多条事件
- 清空 l0_buffer

### 异步后台（_end_session_async L279，独立线程）
1. 根据 emotion_snapshots 的最大值派生状态标签（"情绪波动" / "轻微波动" / "平稳"），调用 `update_elastic(agent_id, "emotion_core", "current_emotional_state", <label>)` 写入 soul 的 elastic 区
2. `soul_evidence_check` LLM（拿整段会话）
3. 若是 evidence → `add_evidence`（写 soul.evidence_log，目前无上限）
4. `check_slow_change` → 若触发 → LLM 生成新值 → `apply_slow_change`
5. `memory_l2.check_and_generate_patterns`
6. `memory_l2.contribute_to_soul`

## 4. 全局参数来源

| 参数 | 文件 | 当前值 | 备注 |
|------|------|--------|------|
| EMBEDDING_MODEL | config.py | `"BAAI/bge-m3"` | 仅 SiliconFlow |
| LLM_PROVIDER | config.py | `"minimax"` | 影响 chat_completion 路由 |
| GRAPH_EDGE_DECAY_RATE | config.py | `0.99` | decay_edges 每日衰减率 |
| DORMANT_THRESHOLD | config.py | `0.3` | decay_score 低于此值进 dormant |
| stress_level | `data/agents/<id>/global_state.json` | 读取自 `current_state.stress_level`（默认 0.3） | 目前无代码更新路径 |
| EMOTION_SNAPSHOT_THRESHOLD | config.py | `0.7` | — |
| IS_DERIVABLE_DISCARD_THRESHOLD | config.py | `0.8` | L1 写入前过滤 |
| L2_SAME_TOPIC_THRESHOLD | config.py | `3` | — |
| L2_SOUL_CONTRIBUTION_THRESHOLD | config.py | `0.8` | — |

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
- 子事件：`trace.event("embedding", ...)` / `trace.event("vector_search", ...)` / `trace.event("graph_expand", ...)` / `trace.event("score_rerank", ...)` / `trace.event("llm_rerank", ...)` / `trace.event("llm_call", ...)` 等
- 输出：`logs/sessions/<session_id>.md`
