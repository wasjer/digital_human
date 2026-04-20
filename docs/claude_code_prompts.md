# Claude Code 提示词日志
> 项目：数字社会模拟平台 · 阶段一
> 记录所有发给 Claude Code 的提示词，供复盘/回滚使用

---

## 已知风险 & 待处理事项

| # | 问题 | 影响模块 | 优先级 | 状态 |
|---|------|---------|--------|------|
| 1 | 不同 LLM provider 返回 JSON 格式不统一（有的带 ```json 包裹，有的加前缀文字），直接 json.loads 会崩 | llm_client / seed_parser / soul / memory_l1 / L2 | 切换 API 前必须修复 | 待处理 |
| 2 | seed_parser.py 和 soul.py 文件权限异常（permission denied），来源未知 | core/ 目录 | 低（暂时不影响运行） | 待排查 |
| 3 | 设计待议：边被删除改为休眠（dormant）而非物理删除，保留历史连接信息 | memory_graph / decay_job | Phase 1 完成后评估 | 设计讨论 |
| 4 | 设计待议：去掉 revived 状态，复活的事件直接回到 active，简化状态机 | memory_graph / memory_l1 / retrieval | Phase 1 完成后评估 | 设计讨论 |
| 5 | L2 实现偏离 spec：Prompt #10 误用 active 事件+LLM，已在 Prompt #12 按 spec 重写（archived+规则引擎）| memory_l2 | 已修复 | ✅ 已处理 |

---

## Prompt #1
**时间：** 2026-04-02
**目标模块：** `core/llm_client.py` + `core/seed_parser.py`
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/
config.py 已配置好，不要修改它。

请按顺序实现以下两个文件：

## 第一步：core/llm_client.py

统一 LLM 调用封装，所有模块通过它调用 LLM。

要求：
- 从 config.py 读取 DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL
- 封装 chat_completion(messages, max_tokens=1024, temperature=0.7) -> str
- 封装 get_embedding(text) -> list[float]，调用本地 Ollama（EMBEDDING_BASE_URL）
- 所有调用有 retry 机制：最多3次，指数退避2秒
- 统一日志格式：{timestamp} llm_client {operation} {result}

## 第二步：core/seed_parser.py

输入：一个 nodes.json 文件路径（面试对话数据）
输入格式：JSON 数组，每个元素结构为：
{
  "node_id": int,
  "node_type": "observation",
  "content": "Interviewer: ...\n\nJoon: ...\n",
  "importance": int,
  "created": int,
  "last_retrieved": int,
  "pointer_id": null
}

任务：
- 读取 nodes.json 中 importance > 0 的节点，拼接成完整对话文本
- 调用 llm_client.chat_completion，提取结构化人物信息
- 输出 seed.json 到 data/seeds/{agent_id}/seed.json

seed.json 需包含以下字段（缺失填 null，不允许推断编造）：
{
  "agent_id": str,
  "name": str,
  "age": int or null,
  "occupation": str or null,
  "location": str or null,
  "emotion_core": {
    "base_emotional_type": str or null,
    "emotional_regulation_style": str or null,
    "current_emotional_state": str or null
  },
  "value_core": {
    "moral_baseline": str or null,
    "value_priority_order": str or null,
    "current_value_focus": str or null
  },
  "goal_core": {
    "life_direction": str or null,
    "mid_term_goals": str or null,
    "current_phase_goal": str or null
  },
  "relation_core": {
    "attachment_style": str or null,
    "key_relationships": list or null,
    "current_relation_state": str or null
  }
}

核心接口：
def parse_seed(nodes_json_path: str, agent_id: str) -> dict

验证方式：
1. 用 nodes.json 跑一次，seed.json 正确生成在对应路径
2. 所有字段存在（缺失是 null，不是被省略）
3. 不同风格的输入（长/短/残缺），输出结构始终完整
4. 日志有输出

不要实现其他模块。
所有 LLM 输出内容用中文。
```

---

## Prompt #2
**时间：** 2026-04-02
**目标模块：** `core/soul.py` + `core/global_state.py`
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/
已完成：core/llm_client.py，core/seed_parser.py，config.py
现在实现：core/soul.py 和 core/global_state.py

## core/global_state.py

管理 data/agents/{agent_id}/global_state.json 的读写。

global_state.json 结构：
{
  "agent_id": str,
  "updated_at": str,
  "current_state": {
    "mood": "平稳",
    "energy": "正常",
    "stress_level": 0.3
  },
  "personality_params": {
    "introversion": 0.7,
    "risk_aversion": 0.8,
    "curiosity": 0.5,
    "empathy": 0.6
  },
  "decay_config": {从 config.py 读取各 DECAY_* 值},
  "graph_config": {从 config.py 读取各 GRAPH_* 值}
}

接口：
def init_global_state(agent_id, personality_params=None) -> dict
def read_global_state(agent_id) -> dict
def update_global_state(agent_id, field, value) -> None
    # field 支持点路径，如 "current_state.mood"

## core/soul.py

输入：data/seeds/{agent_id}/seed.json
输出：
  - data/agents/{agent_id}/soul.json
  - data/agents/{agent_id}/global_state.json
  - data/agents/{agent_id}/l2_patterns.json（空列表 []）
  - data/agents/{agent_id}/l0_buffer.json（空结构）

l0_buffer.json 初始结构：
{
  "agent_id": str,
  "session_id": null,
  "created_at": null,
  "ttl_hours": 24,
  "raw_dialogue": [],
  "emotion_snapshots": [],
  "working_context": {
    "current_task": null,
    "active_goals": [],
    "temporary_facts": [],
    "attention_focus": null
  },
  "status": "simplified"
}

soul.json 四核心（emotion_core / value_core / goal_core / relation_core），
每个核心含三区（constitutional / slow_change / elastic）。
字段内容由 LLM 从 seed.json 提取，所有值用中文。

- constitutional：locked=true，source="seed_parser"，confidence 由 LLM 判断
- slow_change：locked=false，change_threshold=2.0，evidence_score=0.0，
               evidence_decay_rate=0.98，evidence_log=[]
- elastic：当前状态

接口：
def init_soul(agent_id) -> dict
def read_soul(agent_id) -> dict
def update_elastic(agent_id, core, field, value) -> None
def add_evidence(agent_id, core, field, score, reason, session_id) -> None
def decay_evidence(agent_id) -> None
def check_slow_change(agent_id) -> list
def apply_slow_change(agent_id, core, field, new_value) -> None
def check_constitutional_conflict(agent_id, content) -> dict
def get_soul_anchor(agent_id) -> str  # 控制在500 tokens以内，中文
def get_value_core_constitutional(agent_id) -> str

同时创建 tests/manual_test_soul.py，包含：
1. init_soul('test_agent_001')，打印结果
2. get_soul_anchor，打印内容和字符数
3. add_evidence 累加三次（score=0.8），打印 evidence_score
4. check_slow_change，打印返回列表
5. decay_evidence，打印衰减前后对比

所有 prompt 存 prompts/ 文件夹。
从 config.py 读取所有阈值。
不要实现其他模块。
```

---

## Prompt #3
**时间：** 2026-04-03
**目标模块：** `core/llm_client.py`（重构）+ `prompts/` 文件夹（新建）
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/

## 一、重构 core/llm_client.py，支持多 provider 切换

在 config.py 新增：
LLM_PROVIDER = "deepseek"  # 可选: "deepseek" | "minimax" | "kimi" | "glm"

各 provider 配置（暂时留空的也要加）：
MINIMAX_MODEL = ""
MINIMAX_BASE_URL = ""
KIMI_MODEL = ""
KIMI_BASE_URL = ""
GLM_MODEL = ""
GLM_BASE_URL = ""

llm_client.py 根据 LLM_PROVIDER 自动路由，接口不变：
- chat_completion(messages, max_tokens=1024, temperature=0.7) -> str
- get_embedding(text) -> list[float]

切换 provider 只需改 config.py 的 LLM_PROVIDER，不动其他代码。
embedding 暂时只用 Ollama，不随 provider 切换。

## 二、新建 prompts/ 文件夹，把所有 LLM prompt 从代码中分离

在项目根目录新建 prompts/ 文件夹。
把 seed_parser.py 和 soul.py 中所有硬编码的 prompt 字符串提取出来：
  prompts/seed_extract.txt
  prompts/soul_init.txt
  prompts/soul_conflict_check.txt
  prompts/soul_anchor.txt

代码里改为从文件读取 prompt，用 {变量名} 作为占位符，str.format() 替换。

不改任何接口签名，不改任何数据结构，不实现其他模块。
```

---

## Prompt #4
**时间：** 2026-04-03
**目标模块：** `core/memory_l1.py` + `core/indexer.py`
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/
已完成：llm_client.py, seed_parser.py, soul.py, global_state.py, prompts/
现在实现：core/memory_l1.py 和 core/indexer.py

## core/memory_l1.py

LanceDB 路径：data/agents/{agent_id}/memories/，表名：l1_events

字段：
vector(list[float]), event_id(str), agent_id(str), timestamp(str),
created_at(str), actor(str), action(str), context(str), outcome(str),
scene_location(str), scene_atmosphere(str), scene_sensory_notes(str),
scene_subjective_experience(str), emotion(str), emotion_intensity(float),
importance(float), emotion_intensity_score(float), value_relevance_score(float),
novelty_score(float), reusability_score(float), is_derivable_score(float),
decay_score(float), access_count(int), status(str),
tags_time_year(int), tags_time_month(int), tags_time_week(int),
tags_time_period_label(str), tags_people(str/JSON), tags_topic(str/JSON),
tags_emotion_valence(str), tags_emotion_label(str), source(str), ttl_days(int)

写入流程：
1. soul.get_value_core_constitutional(agent_id)
2. get_recent_events_summary(agent_id, limit=5)
3. LLM 提取原子事件（prompts/l1_extract_events.txt）
4. LLM 五维打分（prompts/l1_score_event.txt）：
   {emotion_intensity, value_relevance, novelty, reusability, is_derivable}
5. is_derivable > IS_DERIVABLE_DISCARD_THRESHOLD → 丢弃
6. importance = emotion_intensity×0.3 + value_relevance×0.3 + novelty×0.2 + reusability×0.2
7. LLM 提取 scene（中文）
8. LLM 生成 tags（中文）
9. get_embedding → 写入 LanceDB
10. # TODO: memory_graph.create_links_on_write（Step 6 实现）

接口：
def write_event(agent_id, raw_text, source="dialogue") -> list[str]
def get_event(agent_id, event_id) -> dict
def update_event_status(agent_id, event_id, status) -> None
def increment_access_count(agent_id, event_id) -> None
def get_archived_by_topic(agent_id, topic) -> list[dict]
def get_recent_events_summary(agent_id, limit=5) -> str

## core/indexer.py

def query(agent_id, people=None, time_year=None, time_month=None,
          topic=None, emotion_valence=None, min_importance=None,
          status=None, limit=20) -> list[dict]

## tests/manual_test_l1.py

1. write_event 写3条事件，打印 event_id
2. get_recent_events_summary
3. indexer.query 按 topic 查询
4. update_event_status 改为 archived，再查询确认

所有 LLM 输出中文，prompt 存 prompts/，参数从 config.py 读取。
不实现其他模块，memory_graph 调用只留注释。
```

---

## Prompt #5
**时间：** 2026-04-03
**目标模块：** `core/weight_engine.py` + `jobs/decay_job.py` + `jobs/evidence_decay_job.py`
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/
已完成：llm_client, seed_parser, soul, global_state, memory_l1, indexer
现在实现：core/weight_engine.py 和 jobs/decay_job.py

## core/weight_engine.py

class WeightEngine:
    def compute_decay(self, event, days_elapsed, decay_config) -> float:
        # effective_rate = base_decay_rate ^ (1 - importance × damping_factor)
        # new_decay_score = decay_score × effective_rate ^ days_elapsed

    def compute_emotion_gain(self, event, emotion_signal) -> float:
        raise NotImplementedError("阶段二实现，等待数字身体模块")

    def compute_frequency_gain(self, event) -> float:
        raise NotImplementedError("阶段二实现，基于 access_count")

    def compute_reflection_modulation(self, event, reflection) -> float:
        raise NotImplementedError("阶段二实现")

    def update_weight(self, event, decay_config) -> float:
        # 阶段一只调用 compute_decay

## jobs/decay_job.py

def run_decay_job(agent_id) -> dict:
    # 1. 读取 global_state 获取 decay_config
    # 2. 取所有 active/dormant 事件
    # 3. 计算 days_elapsed，调用 weight_engine.compute_decay
    # 4. decay_score < dormant_threshold → dormant
    # 5. decay_score < archive_threshold → archived
    # 6. 批量更新 LanceDB
    # 7. TODO: memory_graph.decay_edges（Step 6 后补）
    # 8. TODO: memory_graph.check_dormant_revival（Step 6 后补）
    # 返回：{active, newly_dormant, newly_archived, total_processed}

## jobs/evidence_decay_job.py

def run_evidence_decay_job(agent_id) -> dict:
    # 调用 soul.decay_evidence(agent_id)
    # 返回：{cores_processed, fields_decayed}

## tests/manual_test_decay.py

1. write_event 写3条事件
2. 把其中一条的 days_elapsed mock 为60天
3. run_decay_job，打印统计
4. 查询各 status 事件数
5. run_evidence_decay_job，打印统计

从 config.py 读取所有参数，memory_graph 留 TODO 注释。
```

---

## Prompt #6
**时间：** 2026-04-03
**目标模块：** `core/memory_graph.py`
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/
已完成：llm_client, seed_parser, soul, global_state, memory_l1,
        indexer, weight_engine, decay_job, evidence_decay_job
现在实现：core/memory_graph.py

SQLite 路径：data/agents/{agent_id}/graph.db

建表：
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
    UNIQUE(agent_id, source_event_id, target_event_id)
);
CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(agent_id, source_event_id, status);
CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(agent_id, target_event_id, status);

class MemoryGraph:
    def create_links_on_write(self, agent_id, new_event_id, new_embedding) -> int
        # 与最近 GRAPH_BUILD_EDGE_TOP_N 条 active 事件比较余弦相似度
        # > GRAPH_BUILD_EDGE_SIMILARITY_THRESHOLD → 建边，strength=相似度值

    def strengthen_links_on_retrieval(self, agent_id, retrieved_event_ids) -> int
        # 两两之间：有边→strength+=increment, activation_count+=1；无边→建新边
        # strength 上限 1.0

    def get_neighbors(self, agent_id, event_id, min_strength=None) -> list[dict]
        # introversion>0.6 → min_strength×0.6；introversion<0.4 → min_strength×1.4
        # 只返回 status=active 的边的邻居

    def check_dormant_revival(self, agent_id) -> list[str]
        # active邻居数 >= GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT
        # 且近 GRAPH_DORMANT_REVIVAL_RECENT_DAYS 天 access_count>0
        # → update_event_status 改为 revived，decay_score = DORMANT_THRESHOLD+0.1

    def decay_edges(self, agent_id) -> dict
        # strength × GRAPH_EDGE_DECAY_RATE，< 0.05 → 删除
        # 返回 {decayed, removed}

    def update_frozen_edges(self, agent_id) -> int
        # 两端都 archived → status=frozen

    def get_graph_stats(self, agent_id) -> dict
        # {total_edges, active_edges, frozen_edges, avg_strength}

同时补充 memory_l1.write_event 末尾的 TODO 为真实调用。
同时补充 decay_job 中两条 TODO 为真实调用。

## tests/manual_test_graph.py

1. write_event 写3条语义相似事件，确认有边建立
2. write_event 写1条不相关事件，确认无边
3. strengthen_links_on_retrieval，打印 strength 变化
4. 把一条改为 dormant，邻居 access_count+1，check_dormant_revival
5. decay_edges，打印统计

从 config.py 读取所有参数，不实现其他模块。
```

---

## Prompt #7
**时间：** 2026-04-04
**目标模块：** `core/retrieval.py`
**状态：** ✅ 完成

```
项目路径：/Users/stone/projects/digital_human/
已完成：llm_client, seed_parser, soul, global_state, memory_l1,
        indexer, weight_engine, decay_job, memory_graph
现在实现：core/retrieval.py

def retrieve(agent_id, query, mode="dialogue", already_surfaced=None) -> dict

检索流程：
1. soul.get_soul_anchor(agent_id)
2. global_state.read_global_state(agent_id) → 当前状态 + personality_params
3. 读取 l0_buffer.json → raw_dialogue 最近3条
4. memory_l2.get_patterns_for_retrieval() → try/except 保护，失败跳过
5. get_embedding(query) → LanceDB 向量检索
   - 过滤 status in (active, dormant, revived)，召回 top20
   - 排除 already_surfaced（会话内去重）
6. 图扩展：对 top5 调用 memory_graph.get_neighbors，邻居加入候选池
7. 按 mode 权重重排，取 top 5-8：
   - dialogue:   relevance×0.35, importance×0.20, recency×0.25, mood_fit×0.20
   - decision:   relevance×0.35, importance×0.35, recency×0.15, mood_fit×0.15
   - reflection: relevance×0.35, importance×0.25, recency×0.20, mood_fit×0.20
   - recency = 1/(1+days_elapsed)
   - mood_fit = 1 - |emotion_intensity - stress_level|
8. decision 模式：LLM reranking（prompts/retrieval_rerank.txt），max_tokens=256
9. 附加老化文本：
   - 0天：不附加
   - 1-3天："（{n}天前的记忆）"
   - 4-14天："（约{n}天前的记忆，细节可能模糊）"
   - 15-30天："（约{n}周前的记忆，细节可能不准确）"
   - >30天："（{n}个月前的记忆，仅保留大致印象）"
   - dormant 额外加："（这段记忆已经很模糊了）"
   - revived 额外加："（这段记忆因相关联想被重新想起）"
10. increment_access_count（被检索事件）
11. strengthen_links_on_retrieval（被检索事件两两加强边）

输出：
{
  "soul_anchor": str,
  "current_state": str,
  "working_context": str,
  "l2_patterns": str,
  "relevant_memories": [
    {
      "event_id": str,
      "content": str,
      "scene": str,
      "time": str,
      "importance": float,
      "emotion": str,
      "freshness_text": str,
      "source": str  # "vector_search" 或 "graph_expand"
    }
  ],
  "surfaced_ids": list[str]
}

## tests/manual_test_retrieval.py

1. write_event 写5条不同话题的事件
2. retrieve(mode="dialogue")，打印 relevant_memories 摘要
3. 第二次 retrieve 同一 query，传入 surfaced_ids，确认不重复
4. retrieve(mode="decision")，确认 LLM reranking 被调用
5. 打印一条事件的 freshness_text

memory_l2 调用用 try/except 保护。
所有 prompt 存 prompts/。
从 config.py 读取所有参数。
不实现其他模块。
```

---

## Prompt #8
**时间：** 2026-04-04
**目标模块：** `core/dialogue.py`
**摘要：** 实现对话与决策接口，整合所有已完成模块。chat()含情绪检测+情绪峰值快照+retrieval+L0暂存；end_session同步写L1+异步更新Soul/L2；make_decision使用decision模式。memory_l2调用全部try/except保护。做完可真正与数字人对话。

<details>
<summary>完整提示词</summary>

                                              
  项目路径：/Users/stone/projects/digital_human/
  已完成：llm_client, seed_parser, soul, global_state, memory_l1,              
          indexer, weight_engine, decay_job, memory_graph, retrieval           
  现在实现：core/dialogue.py                                                   
                                                                               
  ---                                                       
                                                                               
  ## core/dialogue.py                                       

  对话与决策接口，整合所有已完成模块。                                         
  
  ### 核心接口                                                                 
                                                            
  def chat(agent_id, user_message, session_history, session_surfaced=None) ->  
  dict
      """                                                                      
      session_history: list[{"role": str, "content": str}]  
      session_surfaced: set[str]，会话内已推送事件，首轮传 None                
      返回：{                                                                  
          "reply": str,                                                        
          "session_surfaced": set[str],   # 更新后的已推送集合，调用方下轮传回 
          "emotion_intensity": float                                           
      }                                                                        
      """                                                                      
                                                            
  def make_decision(agent_id, scenario) -> dict                                
      """
      使用 decision 模式检索，返回：                                           
      {                                                                        
          "decision": str,
          "reasoning": str,                                                    
          "relevant_memories_used": list[str]               
      }                                                                        
      """
                                                                               
  def end_session(agent_id, session_history) -> None        
      """同步+异步拆分，见下方"""
                                                                               
  def _end_session_sync(agent_id, session_history) -> None
  def _end_session_async(agent_id, session_history) -> None                    
                                                                               
  ---
                                                                               
  ### chat() 流程                                           

  1. 情绪检测：调用 LLM 检测 user_message 的 emotion_intensity（0-1）          
     prompt 存 prompts/detect_emotion.txt，max_tokens=64，只返回一个浮点数
  2. if emotion_intensity > EMOTION_SNAPSHOT_THRESHOLD：                       
     把当前上下文快照写入 l0_buffer.json 的 emotion_snapshots[]                
     快照格式：{触发消息, emotion_intensity, 前后2轮对话, timestamp}           
  3. retrieval.retrieve(agent_id, user_message, mode="dialogue",               
                        already_surfaced=session_surfaced)                     
  4. 更新 session_surfaced（加入本次 surfaced_ids）                            
  5. 更新 l0_buffer.json 的 raw_dialogue（追加本轮对话）                       
  6. 构建 system prompt（prompt 存 prompts/dialogue_system.txt）：             
     填入 soul_anchor / current_state / l2_patterns /                          
     relevant_memories（含 freshness_text）                                    
  7. 调用 llm_client.chat_completion 生成回答                                  
  8. 返回 reply + 更新后的 session_surfaced + emotion_intensity                
                                                                               
  system prompt 模板变量：                                                     
  {name} {age} {occupation} {location}   ← 从 soul.json 或 seed.json           
  读取基本信息                                                                 
  {soul_anchor}
  {current_state}                                                              
  {l2_patterns}                                             
  {relevant_memories}
                                                                               
  system prompt 规则部分（固定，中文）：                                       
  1. 用第一人称，绝对不说"作为AI"或"我是语言模型"                              
  2. 回答符合教育背景、职业经历和说话风格                                      
  3. 不确定的事用人格特点推断，不编造具体事实                                  
  4. 记忆中有的事自然表现出记得；标注"模糊"的记忆表现出不太确定                
  5. 用中文回答                                                                
  6. 回答长度符合对话节奏，不长篇大论                                          
                                                                               
  ---                                                       
                                                                               
  ### end_session() 拆分                                    

  _end_session_sync（必须完成）：                                              
  1. 读取 l0_buffer.json（raw_dialogue + emotion_snapshots）
  2. 拼接完整会话文本（emotion_snapshots 优先处理）                            
  3. 调用 memory_l1.write_event 写入 L1                                        
  4. 清空 l0_buffer.json（恢复初始空结构）                                     
                                                                               
  _end_session_async（后台执行，失败不影响主流程）：                           
  1. soul.update_elastic 更新弹性区当前状态                 
  2. LLM 判断本次会话是否构成缓变区 evidence                                   
     prompt 存 prompts/soul_evidence_check.txt                                 
     输出：{"is_evidence": bool, "core": str, "field": str,                    
            "score": float, "reason": str}                                     
  3. 若 is_evidence=true：soul.add_evidence(...)                               
  4. soul.check_slow_change → 若有达标字段：                                   
     LLM 生成新值 → soul.apply_slow_change                                     
  5. memory_l2 调用（用 try/except 保护，模块未完成时跳过）：                  
     memory_l2.check_and_generate_patterns(agent_id)                           
     memory_l2.contribute_to_soul(agent_id)                                    
                                                                               
  end_session() 主函数：                                                       
    _end_session_sync(agent_id, session_history)                               
    使用 threading.Thread 在后台执行 _end_session_async     
    立即返回，不等待异步完成                                                   
  
  ---                                                                          
                                                            
  ### make_decision() 流程                                                     
  
  1. retrieval.retrieve(agent_id, scenario, mode="decision")                   
  2. 构建决策 prompt（prompts/decision_system.txt）         
  3. LLM 生成决策和推理过程                                                    
  4. 返回结果                                                                  
                                                                               
  ---                                                                          
                                                            
  ## tests/manual_test_dialogue.py                                             
  
  1. init_soul 确认 agent 已初始化                                             
  2. 进行5轮对话（用 chat()），每轮打印 reply 和 emotion_intensity
     对话内容涵盖：童年经历 / 工作压力 / 家庭关系                              
  3. 打印 l0_buffer.json 确认对话已暂存                                        
  4. 调用 end_session，等待完成                                                
  5. 确认 l0_buffer.json 已清空                                                
  6. 开始第二个会话，问"你还记得我们刚才聊的吗"                                
     打印 reply，确认能引用上一个会话写入的 L1 事件                            
  7. make_decision 测试："是否接受一个高薪但需要经常出差的工作邀请"            
     打印决策结果                                                              
                                                                               
  ---                                                                          
                                                            
  注意：
  - memory_l2 所有调用用 try/except 保护
  - 所有 prompt 存 prompts/ 文件夹                                             
  - 基本信息（name/age 等）优先从 seed.json 读取
  - 不实现其他模块                                           

</details>

---

## Prompt #9
**时间：** 2026-04-04
**目标模块：** `prompts/dialogue_system.txt`（风格修复）
**摘要：** 对话回复太书面、太冷漠，修改 system prompt 规则：口语化、有温度、简短自然、用"你"不用"您"、不说套话。

<details>
<summary>完整提示词</summary>

```
修改 prompts/dialogue_system.txt，在规则部分替换或补充以下内容：

1. 说话口语化、自然，像朋友聊天，不用书面语
2. 有温度，会关心对方，偶尔反问，不是机械式回答
3. 回答简短，1-3句为主，不长篇大论
4. 情绪自然流露，不压抑也不夸张
5. 不用"您"，用"你"
6. 绝对不说"作为AI"、"我是语言模型"、"我理解你的感受"这类套话
7. 用中文，符合说话人的教育背景和个性
```

</details>

---

## Prompt #10
**时间：** 2026-04-04
**目标模块：** `core/memory_l2.py`
**摘要：** 实现 L2 规律引擎。从多次会话 L1 事件中提炼持久规律（behavioral/emotional/relational/value），支持 confidence 累积、deprecate、向 soul 缓变区贡献积分。end_session 异步路径中已有占位调用。

<details>
<summary>完整提示词</summary>

项目路径：/Users/stone/projects/digital_human/             
  已完成：llm_client, seed_parser, soul, global_state, memory_l1,
          indexer, weight_engine, decay_job, memory_graph, retrieval, dialogue 
  现在实现：core/memory_l2.py                                                  
                                                                               
  ---                                                                          
                                                            
  ## core/memory_l2.py                                                         
   
  L2 规律引擎，从多次会话的 L1 事件中提炼持久规律，存为 l2_patterns.json。     
  路径：data/agents/{agent_id}/l2_patterns.json             
                                                                               
  ### l2_patterns.json 结构                                 
                                                                               
  [                                                         
    {               
      "pattern_id": str,
      "agent_id": str,
      "created_at": str,                                                       
      "updated_at": str,
      "pattern_type": str,     # "behavioral" | "emotional" | "relational" |   
  "value"                                                                      
      "content": str,          # 规律内容，中文，1-2句
      "confidence": float,     # 0-1，出现次数越多越高                         
      "evidence_count": int,   # 支撑该规律的 L1 事件数                        
      "source_event_ids": list[str],                                           
      "status": str            # "active" | "deprecated"                       
    }                                                                          
  ]                                                                            
                                                            
  ---               

  ### 核心接口                                                                 
   
  def check_and_generate_patterns(agent_id) -> list[dict]                      
      """                                                   
      每次 end_session 后触发（已在 dialogue._end_session_async 中占位）。     
                                                                               
      流程：        
      1. 读取最近 L2_PATTERN_MIN_EVENTS 条 L1 active 事件                      
         （从 LanceDB 按 created_at 倒序取）                                   
      2. 读取现有 l2_patterns.json                                             
      3. 拼接事件摘要 + 现有规律，调用 LLM 分析                                
         prompt 存 prompts/l2_generate_patterns.txt                            
         LLM 输出：新规律列表 + 需要更新 confidence 的规律 id                  
         输出格式：                                                            
         {                                                                     
           "new_patterns": [{"pattern_type": str, "content": str}],            
           "reinforce": [{"pattern_id": str}],                                 
           "deprecate": [{"pattern_id": str}]                                  
         }                                                                     
      4. new_patterns：生成 pattern_id，confidence=0.3，evidence_count=1，写入 
      5. reinforce：confidence += 0.1（上限1.0），evidence_count += 1，更新    
      6. deprecate：status 改为 deprecated                                     
      7. 写回 l2_patterns.json                                                 
      8. 返回 active 规律列表                                                  
      """                                                                      
                                                            
  def get_patterns_for_retrieval(agent_id, topics=[]) -> str                   
      """                                                   
      供 retrieval.py 调用（已有 try/except 保护）。                           
      返回所有 active 规律的摘要文本，中文，控制在200字以内。                  
      topics 非空时只返回匹配 pattern_type 或内容含关键词的规律。              
      """                                                                      
                                                                               
  def contribute_to_soul(agent_id) -> None                                     
      """                                                                      
      将高置信度规律贡献给 soul 缓变区积分。                
      对 confidence >= L2_SOUL_CONTRIBUTION_THRESHOLD 的 active 规律：         
        判断属于哪个 soul core（emotion/value/goal/relation）                  
        调用 soul.add_evidence(agent_id, core, field, score=confidence×0.5,    
                               reason=pattern_content, session_id="l2_engine") 
      """                                                                      
                                                                               
  ---                                                                          
                                                            
  ## tests/manual_test_l2.py

  1. 确保 test_agent_001 已有 soul.json（若无则先 init_soul）                  
  2. 用 memory_l1.write_event 写入6条事件，内容涵盖：
     工作压力（3条）、家庭关系（2条）、兴趣爱好（1条）                         
  3. 调用 check_and_generate_patterns，打印生成的规律列表                      
  4. 再写入3条工作相关事件，再次调用 check_and_generate_patterns               
     打印更新后的规律，确认 evidence_count 和 confidence 有变化                
  5. 调用 get_patterns_for_retrieval，打印摘要文本                             
  6. 调用 contribute_to_soul，                                                 
     再调用 soul.check_slow_change，确认高置信度规律有积分贡献                 
                                                                               
  ---
                                                                               
  注意：                                                    
  - 所有 LLM 输出用中文
  - 所有 prompt 存 prompts/ 文件夹                                             
  - 从 config.py 读取 L2_PATTERN_MIN_EVENTS / L2_SOUL_CONTRIBUTION_THRESHOLD
  - 不实现其他模块                                                             
                            

</details>

---

---

## Prompt #12
**时间：** 2026-04-06
**目标模块：** `core/memory_l2.py`（按 spec 重写）+ `config.py`（参数修正）+ `core/retrieval.py`（小修）
**摘要：** Prompt #10 的 L2 实现与 spec 不符，本次删除重建。改为 spec 规定的规则引擎：扫描 archived 事件→按 topic 分组→≥3条触发 LLM 生成摘要→失败回滚。同时修正 config.py 中3个错误参数值和2个缺失参数。

<details>
<summary>完整提示词</summary>

项目路径：/Users/stone/projects/digital_human/                               
  背景：Phase 1 已完成端到端测试。现在需要按照原始 spec 重写 L2 模块，
        之前的实现逻辑与设计不符（用了 active 事件+LLM，spec 要求 archived     
  事件+规则引擎）。                                                            
                                                                               
  请按以下顺序操作，不要改动其他任何文件。                                     
                                                            
  ---                                                                          
                                                            
  ## 第一步：删除并清空旧数据

  1. 删除 core/memory_l2.py                                                    
  2. 删除 prompts/l2_generate_patterns.txt
  3. 将以下文件内容改为空列表 []：                                             
     - data/agents/test_agent_001/l2_patterns.json                             
     - data/agents/joon/l2_patterns.json                                       
     （如有其他 agent 目录也一并清空）                                         
                                                                               
  ---                                                                          
                                                                               
  ## 第二步：修改 config.py                                 

  找到 L2 相关参数区域，做以下修改：                                           
  - L2_INITIAL_CONFIDENCE 改为 0.6
  - L2_CONFIDENCE_INCREMENT 改为 0.1                                           
  - L2_SOUL_CONTRIBUTION_THRESHOLD 改为 0.8                 
  - 删除 L2_PATTERN_MIN_EVENTS 这一行                                          
  - 补充以下三行：                                                             
    L1_TO_L2_IMPORTANCE_THRESHOLD = 0.6                                        
    L1_TO_L2_SAME_TYPE_COUNT = 3                                               
    L1_TO_L2_ACCESS_FREQUENCY = 2                                              
                                                                               
  ---                                                                          
                                                            
  ## 第三步：新建 prompts/l2_generate_patterns.txt                             
  
  内容如下（两段，用 [USER] 分隔）：                                           
                                                            
  [SYSTEM]                                                                     
  你是一个心理行为分析师，负责从归档记忆事件中提炼持久行为规律。
                                                                               
  分析规则：
  - 只分析同一话题下的事件群                                                   
  - abstract_conclusion 用中文，1-2句话，描述规律性行为或特征                  
  - target_core 必须是以下四个之一：emotion_core / value_core / goal_core /    
  relation_core                                                                
    - 与情绪调节、压力反应相关 → emotion_core                                  
    - 与价值观、道德判断相关 → value_core                                      
    - 与目标、规划、行为习惯相关 → goal_core                
    - 与人际关系、社交模式相关 → relation_core                                 
  - 若现有规律已能概括，仅更新 confidence，不新建                              
  - 严格输出 JSON，不附加任何解释                                              
                                                                               
  新建 pattern 时输出：                                                        
  {{"action": "create", "abstract_conclusion": "...", "target_core": "..."}}   
                                                                               
  更新现有 pattern 时输出：                                 
  {{"action": "update", "pattern_id": "...", "abstract_conclusion": "..."}}    
                                                                               
  无需改变时输出：
  {{"action": "skip"}}                                                         
                                                                               
  [USER]
  话题：{source_topic}                                                         
  归档事件列表（共 {event_count} 条）：                     
  {events_summary}                                                             
   
  现有该话题的规律（如有）：                                                   
  {existing_pattern}                                        
                                                                               
  请分析这批归档事件，判断是否需要新建或更新规律。                             
   
  ---                                                                          
                                                            
  ## 第四步：新建 core/memory_l2.py

  ### l2_patterns.json 每条记录的字段结构                                      
   
  {                                                                            
    "pattern_id": str,               # uuid                 
    "agent_id": str,                                                           
    "abstract_conclusion": str,      # 中文，1-2句，规律描述
    "support_event_ids": list[str],  # 支撑该规律的 archived event_id 列表     
    "source_topic": str,             # 规律来源的 topic，如"工作"、"家庭"      
    "confidence": float,             # 0-1，初始值 L2_INITIAL_CONFIDENCE=0.6   
    "target_core": str,              #                                         
  "emotion_core"|"value_core"|"goal_core"|"relation_core"                      
    "evidence_contribution": float,  # 已向 soul 贡献的积分，初始 0.0          
    "created_at": str,               # ISO 时间                                
    "updated_at": str,               # ISO 时间             
    "status": str,                   # "active" | "deprecated"                 
    "retry_needed": bool,            # LLM 失败时标记为 true
    "sampling_weights_placeholder": {  # 阶段二占位，固定值不计算              
      "alpha_connectivity": 0.25,                                              
      "beta_emotion_intensity": 0.30,                                          
      "gamma_time_novelty": 0.25,                                              
      "delta_access_frequency": 0.20                                           
    }                                                       
  }                                                                            
                                                            
  ### 接口实现

  def check_and_generate_patterns(agent_id: str) -> list[str]:                 
      """
      触发逻辑（规则引擎，不是 LLM 扫全部事件）：                              
      1. 快照当前 l2_patterns.json（last_known_good_state =                    
  读取当前内容的深拷贝）                                                       
      2. 从 LanceDB 取所有 status='archived' 的事件（直接查                    
  LanceDB，不调用其他模块）                                                    
      3. 解析每条事件的 tags_topic 字段（JSON 字符串），展开后按 topic 分组
      4. 对每个 topic，若 archived 事件数 >= L2_SAME_TOPIC_THRESHOLD(3)：      
         a. 检查该 topic 是否已有 active pattern：                             
            - 有 → 将现有 pattern 信息填入 prompt，让 LLM 判断 update 还是 skip
            - 无 → prompt 里 existing_pattern 填"无"，让 LLM 判断 create 还是  
  skip                                                                         
         b. 读取 prompts/l2_generate_patterns.txt，str.format() 填入变量，调用 
  llm_client.chat_completion                                                   
         c. 解析 LLM 返回的 JSON：                          
            - create → 新建                                                    
  pattern，confidence=L2_INITIAL_CONFIDENCE，evidence_count=1                  
            - update → 找到对应 pattern_id，confidence +=
  L2_CONFIDENCE_INCREMENT（上限1.0），更新 abstract_conclusion                 
            - skip   → 不做任何修改                         
            - LLM 失败或 JSON 解析失败 → rollback_patterns(agent_id,           
  last_known_good_state)，                                                     
                                          mark_retry_needed(agent_id)，跳过该
  topic，继续                                                                  
      5. 写回 l2_patterns.json                              
      6. 返回本次新增或更新的 pattern_id 列表                                  
      """                                                                      
                                                                               
  def get_patterns(agent_id: str) -> list[dict]:                               
      """返回所有 status='active' 的 patterns"""            
                                                                               
  def get_patterns_for_retrieval(agent_id: str, query_topics: list = []) ->    
  list[dict]:                                                                  
      """                                                                      
      返回 list[dict]（不是字符串）。                                          
      query_topics 为空时返回所有 active patterns。                            
      query_topics 非空时返回 source_topic 在列表中的 patterns。               
      按 confidence 降序，最多返回 5 条。                                      
      """                                                                      
                                                                               
  def contribute_to_soul(agent_id: str) -> list:                               
      """                                                   
      对 confidence >= L2_SOUL_CONTRIBUTION_THRESHOLD(0.8) 且 status='active'
  的 pattern：                                                                 
      - 根据 target_core 找到对应缓变区字段：
          emotion_core  → emotional_regulation_style                           
          value_core    → value_priority_order                                 
          goal_core     → mid_term_goals                                       
          relation_core → key_relationships                                    
      - 调用 soul.add_evidence(agent_id, core=target_core, field=对应字段,
          score=pattern['confidence'] * 0.3,                                   
          reason=pattern['abstract_conclusion'], session_id='l2_engine')       
      - 更新 pattern['evidence_contribution'] += score                         
      - 写回 l2_patterns.json                                                  
      返回贡献记录列表 [{"pattern_id": ..., "target_core": ..., "score": ...}] 
      """                                                                      
                                                            
  def rollback_patterns(agent_id: str, snapshot: list) -> None:                
      """将 l2_patterns.json 覆盖回 snapshot 内容"""        
                                                                               
  def mark_retry_needed(agent_id: str) -> None:
      """日志记录需要重试的情况（阶段一只记日志，不做复杂重试逻辑）"""         
                                                                               
  ---
                                                                               
  ## 第五步：修改 core/retrieval.py                                            
   
  找到调用 get_patterns_for_retrieval 的地方，将：                             
      l2_patterns = get_patterns_for_retrieval(agent_id, topics=[]) or ""
  改为：                                                                       
      l2_pattern_list = get_patterns_for_retrieval(agent_id, query_topics=[])
      l2_patterns = "；".join(p["abstract_conclusion"] for p in                
  l2_pattern_list) if l2_pattern_list else ""                                  
                                                                               
  ---                                                                          
                                                            
  ## 第六步：重写 tests/manual_test_l2.py                                      
   
  由于 L2 现在只对 archived 事件触发，测试需要手动设置事件状态：               
                                                            
  import json, sys                                                             
  from pathlib import Path                                  
  sys.path.insert(0, str(Path(__file__).parent.parent))                        
                                                            
  from core.soul import init_soul                                              
  from core.memory_l1 import write_event, update_event_status
  from core.memory_l2 import (check_and_generate_patterns, get_patterns,       
                               get_patterns_for_retrieval, contribute_to_soul)
  from core.soul import check_slow_change                                      
                                                            
  AGENT = "test_agent_001"                                                     
                                                            
  # 确保 agent 已初始化                                                        
  try:                                                      
      from core.soul import read_soul
      read_soul(AGENT)                                                         
  except:
      init_soul(AGENT)                                                         
                                                            
  print("=" * 60)
  print("1. 写入 9 条事件（工作3条、家庭3条、社交3条）")
  print("=" * 60)                                                              
  topics_events = [
      ("今天项目截止日期压力很大，连续工作12小时，感到疲惫但完成了任务",       
  "工作"),                                                                     
      ("和同事讨论方案时意见不合，坚持了自己的判断，最终被采纳", "工作"),
      ("月度汇报做得很好，领导表扬，但感觉自己还有很多不足", "工作"),          
      ("陪女儿做作业，发现她数学进步很大，很欣慰", "家庭"),                    
      ("和妻子因为家务分配有些争执，后来各退一步解决了", "家庭"),              
      ("父母从老家来住了一周，感觉很温馨但也有些压力", "家庭"),                
      ("朋友聚餐邀请，犹豫了很久还是去了，发现还是享受的", "社交"),            
      ("参加了一个行业交流会，认识了几个有意思的人", "社交"),                  
      ("老同学找我倾诉烦恼，陪他聊了两个小时，感到被需要", "社交"),            
  ]                                                                            
                                                                               
  event_ids = []                                                               
  for text, topic in topics_events:                                            
      ids = write_event(AGENT, text)                        
      event_ids.extend(ids)
      print(f"  写入：{text[:20]}... → {len(ids)}条事件")                      
                                                                               
  print(f"\n共写入 {len(event_ids)} 条 L1 事件")                               
                                                                               
  print("\n" + "=" * 60)                                                       
  print("2. 手动将所有事件设为 archived（模拟衰减）")       
  print("=" * 60)                                                              
  for eid in event_ids:
      update_event_status(AGENT, eid, "archived")                              
  print(f"  已将 {len(event_ids)} 条事件改为 archived")     
                                                                               
  print("\n" + "=" * 60)                                    
  print("3. 触发 check_and_generate_patterns")                                 
  print("=" * 60)                                           
  updated_ids = check_and_generate_patterns(AGENT)
  print(f"  新增/更新的 pattern_id 列表：{updated_ids}")                       
                                                                               
  patterns = get_patterns(AGENT)                                               
  print(f"\n  当前 active patterns（共 {len(patterns)} 条）：")                
  for p in patterns:                                                           
      print(f"  [{p['source_topic']}] {p['abstract_conclusion']}")
      print(f"    target_core={p['target_core']}                               
  confidence={p['confidence']}")                            
                                                                               
  print("\n" + "=" * 60)                                    
  print("4. 再追加3条工作相关 archived 事件，验证 confidence 增长")
  print("=" * 60)                                                              
  extra = [
      "今天又加班到很晚，但对结果感到满意",                                    
      "面对突发的技术问题，冷静分析并快速解决",                                
      "团队绩效评估，我的评分在前20%",                                         
  ]                                                                            
  extra_ids = []                                                               
  for text in extra:                                                           
      ids = write_event(AGENT, text)                        
      extra_ids.extend(ids)
  for eid in extra_ids:
      update_event_status(AGENT, eid, "archived")                              
   
  updated_ids2 = check_and_generate_patterns(AGENT)                            
  print(f"  新增/更新 pattern_id：{updated_ids2}")          
  patterns2 = get_patterns(AGENT)                                              
  work_patterns = [p for p in patterns2 if p['source_topic'] in ('工作',
  'work')]                                                                     
  for p in work_patterns:                                   
      print(f"  [工作] confidence={p['confidence']}                            
  evidence_contribution={p['evidence_contribution']}")                         
   
  print("\n" + "=" * 60)                                                       
  print("5. get_patterns_for_retrieval 返回 list[dict] 验证")
  print("=" * 60)                                                              
  result = get_patterns_for_retrieval(AGENT)
  print(f"  返回类型：{type(result)}")                                         
  print(f"  条数：{len(result)}")                           
  if result:                                                                   
      print(f"  第一条字段：{list(result[0].keys())}")      
                                                                               
  print("\n" + "=" * 60)
  print("6. contribute_to_soul + check_slow_change")                           
  print("=" * 60)                                                              
  contributions = contribute_to_soul(AGENT)
  print(f"  贡献记录：{contributions}")                                        
  slow = check_slow_change(AGENT)                                              
  print(f"  soul 待更新字段：{slow}")
                                                                               
  print("\n=== manual_test_l2 完成 ===")                    
                                                                               
  ---                                                                          
   
  注意：                                                                       
  - 只改动上述6处，不修改其他任何文件（特别不要动           
  dialogue.py、memory_l1.py、soul.py）                                         
  - 所有 LLM 输出用中文
  - 保持现有日志格式不变  

</details>

---

## Prompt #11
**时间：** 2026-04-04
**目标模块：** `tests/e2e_test.py`（端到端集成测试）
**摘要：** 完整模拟三次会话（工作压力/童年记忆/跨会话记忆验证）+ 决策测试 + 系统状态汇总。验证整条管道：seed→soul→L0→L1→L2→retrieval→dialogue→graph→decay。

<details>
<summary>完整提示词</summary>

项目路径：/Users/stone/projects/digital_human/                               
  所有模块已完成。现在创建端到端集成测试文件。
                                                                               
  创建 tests/e2e_test.py，完整模拟两次会话，验证整条管道。                     
                                                                               
  ---                                                                          
                                                            
  ## 测试结构

  ### 准备阶段                                                                 
   
  1. 用 /Users/stone/Downloads/nodes.json 重新生成 agent "joon"：              
     - seed_parser.parse_seed(nodes_json_path, "joon")      
     - soul.init_soul("joon")                                                  
     - 打印 soul.get_soul_anchor("joon")，确认人格锚是中文                     
                                                                               
  ---                                                                          
                                                                               
  ### 第一次会话（Session A，5轮对话）                                         
   
  话题围绕：工作压力、个人目标                                                 
  用 dialogue.chat() 逐轮推进，每轮打印：                   
    - user: [消息]                                                             
    - reply: [回答]                                                            
    - emotion_intensity: [值]                                                  
                                                                               
  5条消息：                                                 
    "你平时工作压力大吗？"                                                     
    "你怎么处理压力？"                                                         
    "你觉得你现在的研究方向是你真正想做的吗？"
    "如果可以重来，你会做不同的选择吗？"                                       
    "你觉得什么样的生活是成功的？"                                             
                                                                               
  会话结束后：                                                                 
    - 调用 dialogue.end_session("joon", session_history)                       
    - 等待3秒（给异步任务时间完成）                                            
    - 打印 L1 事件数量（查 LanceDB 中 agent_id="joon" 的事件总数）             
    - 打印 l0_buffer.json 确认已清空                                           
                                                                               
  ---                                                                          
                                                                               
  ### 第二次会话（Session B，5轮对话）                      

  话题围绕：童年记忆、人际关系
  5条消息：
    "你小时候是什么样的孩子？"                                                 
    "和父母的关系怎么样？"
    "你有没有特别难忘的朋友？"                                                 
    "你觉得孤独吗？"                                        
    "你上次觉得真正被理解是什么时候？"                                         
                                                            
  会话结束后：                                                                 
    - 调用 end_session，等待3秒                             
    - 打印 L2 patterns（读取 l2_patterns.json）                                
    - 打印 soul.check_slow_change("joon")，看有没有字段达到积分阈值            
                                                                               
  ---                                                                          
                                                                               
  ### 跨会话记忆验证（Session C，3轮）                                         
   
  3条消息：                                                                    
    "你还记得我们之前聊过什么吗？"                          
    "你之前说到了研究方向，能展开说说吗？"
    "你刚才提到的那些，我感觉你是个很有深度的人"                               
                                                                               
  每轮打印 retrieval 取回的 relevant_memories 数量和 source 字段               
  （确认有来自 Session A/B 的事件被检索到）                                    
                                                                               
  ---                                                       
                                                                               
  ### 决策测试                                              

  make_decision("joon", "有一个机会可以离开学术界去业界做AI产品，薪资翻倍但要放
  弃博士学位，你会怎么选择？")
  打印完整决策结果                                                             
                                                            
  ---

  ### 系统状态汇总

  打印最终统计：                                                               
  - L1 事件总数
  - 各 status 数量（active/dormant/archived）                                  
  - memory_graph 边数和平均强度                                                
  - L2 patterns 数量                                                           
  - soul slow_change 各字段当前积分                                            
  - global_state 当前 mood/energy/stress_level                                 
                                                                               
  ---                                                                          
                                                                               
  注意：                                                    
  - 每个阶段开头打印明显分隔线，方便阅读
  - 任何步骤报错不要中断，打印错误后继续                                       
  - 测试完成打印"=== 端到端测试完成 ==="                                       
                          

</details>

---
