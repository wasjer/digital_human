# 数字社会模拟平台 — 阶段一完整Spec v6

> 版本：v6.0
> 日期：2026-04-01
> 状态：交付Claude Code执行
> 变更说明：基于v5，合并15项改动。记忆图正式进入阶段一；引入Claude Code经验（记忆老化语言化、情绪峰值触发、LLM reranking、会话内去重、is_derivable过滤、L2失败回滚、end_session异步化）；阶段二备忘新增embedding量化；阶段三备忘新增团队记忆隔离。

---

## 一、系统总览

### 1.1 阶段一目标

让单个数字人能够：
- 基于种子数据形成稳定人格
- 基于记忆进行自然对话
- 对简单情境做出符合人设的决策
- 记忆随时间自然衰减，重要记忆衰减慢，不重要的记忆快速消失
- L0→L1→L2→Soul 全管道可运行（L2使用简化规则引擎）
- 记忆之间形成关联网络，支持联想检索和dormant复活（v6新增）

### 1.2 阶段一不做的事（明确边界）

- 情绪增益权重：等待数字身体模块（阶段二）
- 蒙特卡洛抽样（用加权随机抽样替代）：阶段二
- 多Agent交互：阶段三
- L0感知缓冲层完整工作记忆逻辑：阶段二
- 反应系统：阶段三
- 世界模型：阶段三
- 数字身体：阶段二
- 记忆图的有向边和因果链推理：阶段二

### 1.3 阶段一管道完整性原则

> 所有层级的数据结构和接口在阶段一全部建出。L2使用极简规则引擎代替LLM聚类（同topic_axis的archived事件≥3条自动生成摘要）。Soul层缓变区更新使用积分制自动触发。记忆图使用SQLite边表实现，支持写入时建边和检索时加强边。整条 L0→L1→记忆图→L2→Soul 管道在阶段一是通的，阶段二将规则引擎替换为LLM驱动的智能版本。

---

### 1.4 四张架构图

**图一：记忆写入方向**（信息从哪里来，往哪里去）

```
外界输入（对话/事件）
        ↓ 临时暂存
      L0 感知缓冲层（阶段一简化版：仅对话暂存与提交）
        ↓ 会话结束 OR 超过TTL OR 情绪峰值触发（v6）
        ↓ LLM筛选：注入Soul层value_core，一次性打出五项分数（v6加is_derivable）
        ↓ is_derivable > 0.8 → 丢弃
        ↓ 计算importance，高→提取为事件，低→丢弃
      L1 事件层
        ↓ 同步生成索引标签（metadata字段）
        ↓ 写入时建边：与最近N条事件做相似度比较（v6记忆图）
        ↓ 竞争条件满足（importance阈值 + 同类次数，阶段一用简化规则）
      L2 慢速抽象层（阶段一：同topic archived事件≥3条→自动摘要）
        ↓ 积分制：evidence_score达标
      Soul层 L3（四核心，各含三区）
        ↓ 反向影响（阶段二完善）
      L1写入时的importance计算
        （形成闭环）
```

**图二：决策调用方向**（数字人回答问题时，记忆怎么被读取）

```
当前对话query
        ↓ 最高优先级，固定加入
      Soul层 L3 人格锚
      （宪法区+缓变区，400-500 tokens）
        ↓ 次优先级
      L1 相关事件（向量检索+图扩展+重排，300-400 tokens，5-8条）
      ├─ 向量检索 top20
      ├─ 图扩展：查邻居补充候选（v6记忆图）
      ├─ 会话内去重：排除already_surfaced事件（v6）
      ├─ 按mode选权重重排 → top 5-8条
      ├─ decision模式：LLM reranking二次筛选（v6）
      └─ 附加记忆老化文本："这段记忆是X天前的"（v6）
        ↓ 补充当前上下文
      L0 感知缓冲层
      （当前会话最近相关内容，100-200 tokens）
        ↓ 补充行为规律
      L2 慢速抽象层
      （行为规律摘要，200-300 tokens，阶段一已有内容时加入）
        ↓ 组合成完整context
      LLM生成回答
```

**图三：程序模块执行顺序**

> 详见第五节末尾的SVG架构图。文字版如下：

```
seed_parser（模块1）
        ↓ 生成种子数据
soul（模块2）
        ↑ 读取value_core → 供write_event计算importance
        ↑↓ 读写弹性区 → end_session时积分制更新
        ↑ 读取soul_anchor → 供retrieval组装context
memory_l1（模块3a）+ indexer（模块3b）
        ↑ weight_engine 横切（importance调制衰减）
        ↑↓ memory_graph（模块3d）← 写入时建边，检索时加强边（v6）
        ↓ 提供候选事件
retrieval（模块4）
        ↑ 读取soul_anchor + global_state + L0 buffer
        ↑ 图扩展：查memory_graph邻居补充候选（v6）
        ↓ 组装context（附加老化文本、会话内去重）
dialogue（模块5）
        ↓ 会话进行中：情绪峰值触发中间快照（v6）
        ↓ 会话结束时
end_session
        ├→ [同步] memory_l1写入（含is_derivable过滤 + 建边）
        ├→ [同步] L0 buffer清空
        ├→ [异步] soul弹性区更新（积分制）（v6异步化）
        ├→ [异步] L2规则引擎检查（含失败回滚）（v6异步化+回滚）
        └→ [异步] L2→Soul积分贡献（v6异步化）

横切模块：
  global_state ←→ 所有模块（当前状态、性格参数、衰减配置）
  weight_engine ←→ L1（importance调制衰减）
  memory_graph ←→ L1 + retrieval（边的读写）
```

**图四：记忆图结构**（v6新增）

```
记忆图 = L1事件节点 + 关联边

节点 = LanceDB中的L1事件（不新增存储）
边 = SQLite边表（memory_links）

建边时机：
  写入时：新事件 vs 最近N条事件，embedding相似度 > 阈值 → 建边
  检索时：同一次检索返回的多条事件，两两加强边

边的生命周期：
  strength随共同激活增强，随时间自然衰减
  当source或target事件archived时，边保留但不参与检索
  当两端事件都archived时，边标记为frozen

dormant复活：
  dormant事件的邻居中active事件 ≥ K个
  且这些邻居近7天access_count > 0
  → dormant事件status恢复为active，decay_score重置为dormant_threshold + 0.1

图扩展深度受性格影响：
  introversion高 → strength阈值低(0.2)，联想更远更深
  introversion低 → strength阈值高(0.4)，只捞强关联
```

---

## 二、完整层级定义与对照表

| 层级 | 名称 | 类比人类记忆 | 保存内容 | 作用 | 保留时间 | 进入下一层的规则 | 阶段一状态 |
|------|------|------------|---------|------|---------|----------------|-----------|
| L0 | 感知缓冲层 | 感觉记忆+即时工作记忆 | 原始对话、当前任务上下文、感知输入 | 外界信息进入记忆系统的入口，临时暂存过滤 | 会话结束或24小时TTL | 会话结束或情绪峰值时提交L1，LLM判断importance+is_derivable，通过→写入L1，否则→丢弃 | ✅ 简化版实现（对话暂存+提交+情绪峰值触发） |
| L1 | 事件层 | 情景记忆 Episodic Memory | 原子事件（含scene情景字段） | 具体经历的持久化，情景细节的载体 | 因importance而异，高importance事件可存数月 | 竞争上升：阶段一用简化规则（同topic archived事件≥3条触发L2摘要） | ✅ 实现 |
| — | 事件索引 | — | 时间/人物/主题/情绪标签 | 支持多路径检索 | 与L1事件同生命周期 | 不上升，服务于检索 | ✅ 实现（作为L1事件的metadata字段） |
| — | 记忆图 | 联想记忆 | 事件间关联边（strength, activation_count） | 联想检索、dormant复活、记忆网络拓扑 | 边随事件生命周期变化 | 不上升，服务于检索和复活 | ✅ 实现（SQLite边表）（v6新增） |
| — | 权重动力学层 | — | 权重更新规则引擎 | 统一管理所有记忆的权重变化 | 常驻引擎，不存储记忆 | 不上升，横切L1 | ✅ 实现importance调制衰减，其余预留接口 |
| L2 | 慢速抽象层 | 语义记忆形成过程 | 聚类结论、行为规律摘要 | 压缩L1，降低被抽象事件权重，向Soul层输送材料 | 数月到半年 | 抽象结论置信度>阈值，方向与Soul层宪法区不冲突，进入对应核心缓变区 | ✅ 简化规则引擎实现（含失败回滚） |
| L3 | Soul层 | 自传体记忆+人格 | 四核心（情感/价值/目标/关系），各含三区 | 人格锚，反向影响L1权重计算，决策的最终依据 | 极长期，近乎永久 | 宪法区冻结；缓变区需积分制达标；弹性区可较自由更新 | ✅ 实现 |
| — | global_state | 当前情绪状态 | 当前状态+性格参数+衰减配置 | 横切所有层的全局信号，影响检索权重和行为生成 | 常驻，持续更新 | 不上升 | ✅ 实现 |
| — | 语义记忆 | 语义记忆 Semantic Memory | 世界知识、背景知识 | 数字人对世界的一般性认知 | 长期 | 阶段二填充 | ❌ 预留空表 |
| — | 程序记忆 | 程序记忆 Procedural Memory | skill + proficiency + knowledge_boundary | 数字人的能力边界，做门控用 | 长期 | 阶段三填充 | ❌ 预留空表 |

---

## 三、数据结构定义

### 3.1 global_state.json

```json
{
  "agent_id": "uuid",
  "updated_at": "2026-04-01T14:00:00",
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
  "decay_config": {
    "base_decay_rate": 0.95,
    "decay_damping_factor": 0.6,
    "decay_interval_days": 1,
    "dormant_threshold": 0.3,
    "archive_threshold": 0.1
  },
  "graph_config": {
    "build_edge_top_n": 50,
    "build_edge_similarity_threshold": 0.6,
    "retrieval_strengthen_increment": 0.1,
    "retrieval_expand_min_strength": 0.3,
    "dormant_revival_neighbor_count": 3,
    "dormant_revival_recent_days": 7,
    "edge_decay_rate": 0.99
  }
}
```

**v6新增说明：**
- `graph_config`：记忆图的全部可调参数
  - `build_edge_top_n`：写入时与最近多少条事件比较
  - `build_edge_similarity_threshold`：相似度超过此值才建边
  - `retrieval_strengthen_increment`：检索时共现加强边的增量
  - `retrieval_expand_min_strength`：图扩展时边的最低strength
  - `dormant_revival_neighbor_count`：dormant复活需要的active邻居数
  - `dormant_revival_recent_days`：邻居近几天有访问才算
  - `edge_decay_rate`：边的strength每日自然衰减系数

---

### 3.2 L0 感知缓冲层

**阶段一行为：简化版实现（对话暂存+提交+情绪峰值触发），阶段二补全工作记忆逻辑。**

```json
{
  "agent_id": "uuid",
  "session_id": "uuid",
  "created_at": "2026-04-01T14:00:00",
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
```

**情绪峰值触发（v6新增）：**
```
对话进行中，每轮对话后检测emotion_intensity：
  if emotion_intensity > 0.7:
    立即将当前上下文快照记录到 emotion_snapshots[]
    快照内容包括：触发消息、当前情绪、前后2轮对话
    快照不立即写入L1，但在end_session时优先处理
    即使session异常中断，emotion_snapshots中的内容也不会丢失

目的：高情绪强度的对话片段不会因session异常中断而丢失
```

---

### 3.3 L1 事件数据结构

```json
{
  "event_id": "uuid",
  "agent_id": "uuid",

  "timestamp": "2026-03-28T19:30:00",
  "created_at": "2026-03-28T19:30:05",

  "actor": "张明",
  "action": "拒绝了同事的聚餐邀请",
  "context": "工作日晚上，理由是要回家陪女儿",
  "outcome": "同事表示理解，关系未受影响",

  "scene": {
    "location": "公司走廊",
    "atmosphere": "下班时间，人员嘈杂",
    "sensory_notes": "能听到远处的电话铃声",
    "subjective_experience": "有些愧疚，但内心笃定"
  },

  "emotion": "轻微愧疚，但整体平静",
  "emotion_intensity": 0.3,

  "importance": 0.35,
  "importance_breakdown": {
    "emotion_intensity": 0.3,
    "value_relevance": 0.5,
    "novelty": 0.2,
    "reusability": 0.3,
    "is_derivable": 0.1
  },

  "decay_score": 1.0,
  "access_count": 0,
  "status": "active",

  "tags": {
    "time_axis": {
      "year": 2026,
      "month": 3,
      "week": 13,
      "period_label": "2026-03"
    },
    "people_axis": ["同事李伟", "妻子"],
    "topic_axis": ["社交", "家庭优先", "拒绝", "工作"],
    "emotion_axis": {
      "valence": "负面",
      "intensity": 0.3,
      "label": "轻微愧疚"
    }
  },

  "related_events": [],
  "core_links": [],

  "source": "dialogue",
  "ttl_days": 30
}
```

**v6变更说明：**
- `importance_breakdown` 新增 `is_derivable` 字段
- `related_events`：由记忆图（memory_graph）自动填充邻居event_id列表

**importance计算（v6更新，增加is_derivable预过滤）：**

write_event时，LLM打分prompt增加一个维度：

```
importance五项打分prompt：
{
  "emotion_intensity": 0-1,
  "value_relevance": 0-1,
  "novelty": 0-1,
  "reusability": 0-1,
  "is_derivable": 0-1      // v6新增：内容是否已在Soul层或近期L1中存在
}

过滤规则：
  is_derivable > 0.8 → 直接丢弃，不计算importance，不写入L1
  is_derivable <= 0.8 → 正常计算importance

importance = (
  emotion_intensity × 0.3 +
  value_relevance   × 0.3 +
  novelty           × 0.2 +
  reusability       × 0.2
)
```

**LLM打分prompt模板（v6更新）：**
```
你是一个记忆评估器。根据以下人物的核心价值观和已有记忆，对这段经历进行五维打分（0-1）。

【人物核心价值观】
{value_core_constitutional}

【近期已有记忆摘要（最近5条）】
{recent_events_summary}

【待评估经历】
{event_description}

请输出JSON格式：
{
  "emotion_intensity": 0-1,    // 这段经历的情绪强度
  "value_relevance": 0-1,      // 与核心价值观的相关程度
  "novelty": 0-1,              // 是否是该人物的新类型经历
  "reusability": 0-1,          // 未来决策时被参考的可能性
  "is_derivable": 0-1          // 内容是否已经在核心价值观或近期记忆中存在（高=冗余）
}
```

**衰减公式（与v5相同，importance调制衰减速率）：**
```
effective_rate = base_decay_rate ^ (1 - importance × damping_factor)
new_decay_score = decay_score × effective_rate ^ days_elapsed
```

**status四态（v6新增revived）：**
- `active`：正常参与检索
- `dormant`：decay_score < 0.3，降权参与检索，可被记忆图复活
- `revived`：从dormant恢复，decay_score重置为0.4，标记来源（v6新增）
- `archived`：decay_score < 0.1，不参与普通检索，供L2规则引擎聚类

---

### 3.4 记忆图（memory_graph）（v6新增）

**存储：SQLite边表，与LanceDB中的L1事件通过event_id关联。**

```sql
CREATE TABLE memory_links (
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

CREATE INDEX idx_links_source ON memory_links(agent_id, source_event_id, status);
CREATE INDEX idx_links_target ON memory_links(agent_id, target_event_id, status);
```

**边的status：**
- `active`：正常参与图扩展和复活检查
- `frozen`：两端事件都archived时标记，不参与检索但数据保留

**建边规则（两个时机）：**

```
写入时建边：
  新事件写入L1后，取其embedding
  与最近N条active事件（默认50条，graph_config.build_edge_top_n）做余弦相似度
  相似度 > 阈值（默认0.6，graph_config.build_edge_similarity_threshold）→ 建边
  strength = 相似度值
  不需要额外LLM调用，纯向量计算

检索时加强边：
  一次检索返回的top 5-8条事件，两两之间：
    已有边 → strength += increment（默认0.1），activation_count += 1
    无边 → 建新边，strength = increment
  strength上限 = 1.0
```

**边的衰减：**
```
在decay_job中同步执行：
  strength = strength × edge_decay_rate（默认0.99）
  strength < 0.05 → 删除边
```

**dormant复活规则：**
```
在decay_job中检查所有dormant事件：
  查边表，找到该事件的所有active邻居
  if active邻居数 >= K（默认3，graph_config.dormant_revival_neighbor_count）:
    检查这些邻居近7天的access_count是否 > 0
    if 有访问的active邻居 >= K:
      → status从dormant改为revived
      → decay_score重置为 dormant_threshold + 0.1（默认0.4）
      → 日志记录复活原因和触发邻居
```

**核心接口：**
```python
class MemoryGraph:
    def create_links_on_write(self, agent_id, new_event_id, new_embedding) -> int
        """写入时建边。返回新建边数。"""

    def strengthen_links_on_retrieval(self, agent_id, retrieved_event_ids) -> int
        """检索时加强共现边。返回更新边数。"""

    def get_neighbors(self, agent_id, event_id, min_strength=0.3) -> list[dict]
        """获取某事件的关联记忆。返回邻居事件列表。"""

    def check_dormant_revival(self, agent_id) -> list[str]
        """检查dormant事件复活条件。返回复活的event_id列表。"""

    def decay_edges(self, agent_id) -> dict
        """边的strength衰减。返回统计。"""

    def get_graph_stats(self, agent_id) -> dict
        """返回图的统计信息：节点数、边数、平均degree等。"""
```

**验证标准：**
- 写入语义相似的事件后，自动建边
- 不相似的事件之间不建边
- 多次共同被检索的事件，边的strength递增
- dormant事件满足复活条件后status变为revived
- 边的strength随时间衰减，低于阈值的边被清理

---

### 3.5 事件索引（L1事件的tags字段）

**v5变更：索引不再是独立结构，改为L1事件的tags metadata字段。indexer.py变为LanceDB查询的封装层。**

**多路径查询示例：**
```python
# indexer.py 封装LanceDB的metadata filter查询
indexer.query(agent_id, people="母亲")
indexer.query(agent_id, time_year=2025, min_importance=0.7)
indexer.query(agent_id, topic="金钱", emotion_valence="负面")
```

**说明：**
- tags随L1事件写入LanceDB，无需额外同步
- 事件status变更时，直接更新LanceDB中的status字段
- 索引数据随事件永久保留


---

### 3.6 权重动力学层

**阶段一实现importance调制衰减，其余预留接口。**

```python
class WeightEngine:

    def compute_decay(self, event, days_elapsed, decay_config) -> float:
        """
        importance调制衰减（v5更新）
        effective_rate = base_decay_rate ^ (1 - importance × damping_factor)
        new_decay_score = decay_score × effective_rate ^ days_elapsed
        
        重要事件衰减慢，不重要事件衰减快。
        """

    def compute_emotion_gain(self, event, emotion_signal) -> float:
        """情绪增益（预留，等待数字身体模块，阶段二）"""
        raise NotImplementedError

    def compute_frequency_gain(self, event) -> float:
        """使用频率增益（预留，阶段二实现，基于access_count）"""
        raise NotImplementedError

    def compute_reflection_modulation(self, event, reflection) -> float:
        """反思调制（预留，阶段二实现）"""
        raise NotImplementedError

    def update_weight(self, event, decay_config) -> float:
        """
        统一权重更新入口
        完整公式（阶段二组合）：
        新权重 = 原权重
               + 情绪增益        （预留）
               + 使用频率增益    （预留）
               - importance调制衰减（阶段一实现）
               ± 反思调制        （预留）
        阶段一：只调用compute_decay
        """
```


**decay_job（每日执行，v6扩展）：**
```python
def run_decay_job(agent_id) -> dict:
    # 1. 遍历所有active和dormant事件，更新decay_score
    # 2. decay_score < dormant_threshold → status = dormant
    # 3. decay_score < archive_threshold → status = archived
    # 4. 同步更新LanceDB中的status字段
    # 5. [v6] 执行边的strength衰减（memory_graph.decay_edges）
    # 6. [v6] 检查dormant复活（memory_graph.check_dormant_revival）
    # 7. [v6] 更新边的status（两端都archived → frozen）
    # 返回统计：{active, dormant, revived, newly_archived, edges_decayed, edges_removed, revived_events}
```

---

### 3.7 L2 慢速抽象层

**阶段一：简化规则引擎实现。增加失败回滚机制（v6）。**


```json
{
  "pattern_id": "uuid",
  "agent_id": "uuid",
  "abstract_conclusion": "倾向于拒绝社交活动，优先保证家庭时间",
  "support_event_ids": ["event_001", "event_007", "event_012"],
  "source_topic": "社交",
  "confidence": 0.6,
  "target_core": "value_core",
  "evidence_contribution": 0.0,
  "created_at": "2026-04-15T00:00:00",
  "updated_at": "2026-04-15T00:00:00",
  "status": "active",

  "sampling_weights_placeholder": {
    "alpha_connectivity": 0.25,
    "beta_emotion_intensity": 0.30,
    "gamma_time_novelty": 0.25,
    "delta_access_frequency": 0.20
  }
}
```


**阶段一简化规则引擎逻辑（v6更新，增加失败回滚）：**
```
每次end_session异步触发时：
  1. 记录当前L2 patterns状态快照（last_known_good_state）
  2. 扫描所有archived事件，按topic_axis分组
  3. 某topic下archived事件 ≥ 3条：
     → LLM生成抽象结论
     → 创建/更新L2 pattern记录
     → confidence更新
  4. 如果步骤3中LLM调用失败：
     → 回滚到last_known_good_state
     → 标记retry_needed = true
     → 日志记录失败原因
     → 下次end_session时优先重试
  5. confidence > 0.8：
     → 向对应Soul核心缓变区贡献evidence_score
```

---

### 3.8 Soul层（L3）

**结构：四核心，每个核心各含三区（宪法区/缓变区/弹性区）。**

```json
{
  "agent_id": "uuid",
  "created_at": "2026-03-31",
  "version": 1,

  "emotion_core": {
    "constitutional": {
      "base_emotional_type": {
        "value": "天生共情能力强，情绪感知敏锐",
        "locked": true,
        "source": "seed_parser",
        "confidence": 0.9
      }
    },
    "slow_change": {
      "emotional_regulation_style": {
        "value": "倾向于压抑负面情绪，独自消化",
        "locked": false,
        "change_threshold": 2.0,
        "evidence_score": 0.0,
        "evidence_decay_rate": 0.98,
        "evidence_log": [],
        "last_updated": "2026-03-31"
      }
    },
    "elastic": {
      "current_emotional_state": {
        "value": "最近有些压抑，但维持表面平静",
        "last_updated": "2026-03-31"
      }
    }
  },

  "value_core": {
    "constitutional": {
      "moral_baseline": {
        "value": "家庭稳定优先于个人发展，经济安全是底线",
        "locked": true,
        "source": "seed_parser",
        "confidence": 0.9
      }
    },
    "slow_change": {
      "value_priority_order": {
        "value": "家庭 > 经济安全 > 职业成就 > 社交",
        "locked": false,
        "change_threshold": 2.0,
        "evidence_score": 0.0,
        "evidence_decay_rate": 0.98,
        "evidence_log": [],
        "last_updated": "2026-03-31"
      }
    },
    "elastic": {
      "current_value_focus": {
        "value": "女儿的教育问题",
        "last_updated": "2026-03-31"
      }
    }
  },

  "goal_core": {
    "constitutional": {
      "life_direction": {
        "value": "追求稳定，不冒险，为家人提供安全感",
        "locked": true,
        "source": "seed_parser",
        "confidence": 0.85
      }
    },
    "slow_change": {
      "mid_term_goals": {
        "value": "在现公司晋升，提高家庭收入",
        "locked": false,
        "change_threshold": 2.0,
        "evidence_score": 0.0,
        "evidence_decay_rate": 0.98,
        "evidence_log": [],
        "last_updated": "2026-03-31"
      }
    },
    "elastic": {
      "current_phase_goal": {
        "value": "完成本季度销售目标",
        "last_updated": "2026-03-31"
      }
    }
  },

  "relation_core": {
    "constitutional": {
      "attachment_style": {
        "value": "焦虑型依附，渴望稳定关系，害怕被抛弃",
        "locked": true,
        "source": "seed_parser",
        "confidence": 0.8
      }
    },
    "slow_change": {
      "key_relationships": {
        "value": [
          {
            "person": "母亲",
            "pattern": "权威依赖，有时产生压抑感",
            "closeness": 0.6
          },
          {
            "person": "妻子",
            "pattern": "稳定但缺乏激情，维持现状",
            "closeness": 0.5
          },
          {
            "person": "女儿",
            "pattern": "保护欲强，家庭优先级第一",
            "closeness": 0.9
          }
        ],
        "locked": false,
        "change_threshold": 1.5,
        "evidence_score": 0.0,
        "evidence_decay_rate": 0.98,
        "evidence_log": [],
        "last_updated": "2026-03-31"
      }
    },
    "elastic": {
      "current_relation_state": {
        "value": "和妻子最近有些疏远，和女儿关系很好",
        "last_updated": "2026-03-31"
      }
    }
  }
}
```

**v5变更说明（缓变区积分制）：**
- 原 `change_threshold: 5`（次数）→ 改为 `change_threshold: 2.0`（积分阈值）
- 原 `evidence_count: 0`（计数器）→ 改为 `evidence_score: 0.0`（浮点积分）
- 新增 `evidence_decay_rate: 0.98`（积分每日自然衰减系数）

**积分制规则：**
```
end_session时：
  LLM判断本次会话内容是否构成某个核心方向的evidence
  如果是：evidence_score += importance_of_evidence × direction_relevance
  evidence_score每日自然衰减：evidence_score = evidence_score × 0.98
  evidence_score > change_threshold → 触发缓变区更新

evidence_log记录格式：
  {
    "session_id": "uuid",
    "score_added": 0.15,
    "reason": "连续第三次表达对冒险的积极态度",
    "timestamp": "2026-03-31T20:00:00"
  }

L2 pattern也可贡献evidence_score：
  当L2 pattern的confidence > 0.8时：
    evidence_score += pattern.confidence × 0.3
```

**Soul层操作接口：**
```python
def read_soul(agent_id) -> dict
def update_elastic(agent_id, core, field, value) -> None
def add_evidence(agent_id, core, field, score, reason, session_id) -> None
    # 新接口：向缓变区添加积分
def decay_evidence(agent_id) -> None
    # 新接口：每日衰减所有缓变区的evidence_score
def check_slow_change(agent_id) -> list
    # 新接口：检查哪些缓变区的evidence_score超过阈值，返回待更新列表
def apply_slow_change(agent_id, core, field, new_value) -> None
    # 执行缓变区更新，重置evidence_score
def check_constitutional_conflict(agent_id, content) -> dict
    # 返回 {"conflict": bool, "reason": str, "conflicting_core": str}
def get_soul_anchor(agent_id) -> str
    # 返回所有核心宪法区+缓变区的摘要文本
    # 控制在400-500 tokens以内
def get_value_core_constitutional(agent_id) -> str
    # 新接口：返回value_core宪法区内容，供importance打分使用
```


---

### 3.9 预留空表

语义记忆（阶段二填充）
CREATE TABLE semantic_memory (
  id TEXT PRIMARY KEY,
  agent_id TEXT,
  content TEXT,
  category TEXT,
  confidence REAL,
  created_at TEXT,
  status TEXT DEFAULT 'placeholder'
);

-- 程序记忆/技能（阶段三填充）
CREATE TABLE skill_memory (
  id TEXT PRIMARY KEY,
  agent_id TEXT,
  skill_name TEXT,
  trigger_condition TEXT,
  action_pattern TEXT,
  proficiency REAL,
  knowledge_boundary TEXT,
  created_at TEXT,
  status TEXT DEFAULT 'placeholder'
);

---

## 四、决策调用时各层权重

### 4.1 层间token分配


| 层级 | token上限 | 是否必须出现 | 说明 |
|------|----------|------------|------|
| Soul层人格锚 | 400-500 tokens | ✅ 每次必须 | 宪法区+缓变区摘要，人格一致性保证 |
| L1 事件层 | 300-400 tokens | ✅ 每次必须 | 5-8条相关事件，含scene字段 |
| L0 感知缓冲层 | 100-200 tokens | ⚠️ 有内容时加入 | 当前会话最近相关内容 |
| L2 慢速抽象层 | 200-300 tokens | ⚠️ 有内容时加入 | 行为规律摘要（阶段一有内容即加入） |


### 4.2 L1层内部重排权重（三种模式）


| 权重项 | dialogue模式 | decision模式 | reflection模式 |
|-------|------------|-------------|--------------|
| relevance（语义相关） | 0.35 | 0.35 | 0.35 |
| importance（重要性） | 0.20 | 0.35 | 0.25 |
| recency（最近性） | 0.25 | 0.15 | 0.20 |
| mood_fit（情绪匹配） | 0.20 | 0.15 | 0.20 |


### 4.3 记忆老化语言化（v6新增）

**在retrieval组装context时，对每条L1事件附加人类可读的老化说明：**

```
规则：
  days_ago = (now - event.created_at).days
  
  if days_ago == 0:
    老化文本 = ""（当天的记忆不附加说明）
  elif days_ago <= 3:
    老化文本 = "（{days_ago}天前的记忆）"
  elif days_ago <= 14:
    老化文本 = "（约{days_ago}天前的记忆，细节可能模糊）"
  elif days_ago <= 30:
    老化文本 = "（约{weeks}周前的记忆，细节可能不准确）"
  else:
    老化文本 = "（{months}个月前的记忆，仅保留大致印象）"
  
  if event.status == "dormant":
    老化文本 += "（这段记忆已经很模糊了）"
  elif event.status == "revived":
    老化文本 += "（这段记忆因相关联想被重新想起）"

context中的事件格式：
  "{event_content} {老化文本}"
```

**目的：** LLM看到"47天前"会自动产生不确定感，比看到 `decay_score: 0.31` 更有效。

### 4.4 会话内去重（v6新增）

```
每次会话维护一个 already_surfaced: set[str]，记录本次会话中已推送给LLM的event_id。

检索时：
  向量召回 top20 → 排除 already_surfaced 中的事件 → 重排取 top 5-8
  
被推送的事件加入 already_surfaced。
会话结束时 already_surfaced 清空。

目的：避免多轮对话中反复推送同一条事件，让数字人表现更自然。
```

### 4.5 LLM reranking（v6新增，仅decision模式）

```
在decision模式下，向量检索+图扩展后、最终排序前，增加LLM二次筛选：
  
  将候选事件（约15-20条）的摘要打包为一个prompt：
  
  "你是一个记忆相关性评估器。以下是一个人面对'{scenario}'时的候选记忆。
   请选出最相关的5-8条，按相关性排序，输出event_id列表。
   
   候选记忆：
   {candidate_summaries}
   
   输出JSON：{"ranked_ids": ["id1", "id2", ...]}"
  
  使用 max_tokens: 256 的结构化输出，成本极低（一次LLM调用）。
  
仅decision模式使用，dialogue和reflection模式不用（控制成本）。
```

---

## 五、模块定义

### 模块0：项目初始化

**文件结构（v6更新）：**
```
digital_human/
├── core/
│   ├── seed_parser.py        # 模块1
│   ├── soul.py               # 模块2
│   ├── memory_l1.py          # 模块3a
│   ├── indexer.py            # 模块3b（LanceDB查询封装）
│   ├── memory_l2.py          # 模块3c（L2规则引擎）
│   ├── memory_graph.py       # 模块3d（记忆图，v6新增）
│   ├── weight_engine.py      # 权重动力学引擎
│   ├── retrieval.py          # 模块4
│   ├── dialogue.py           # 模块5
│   ├── global_state.py       # 横切层
│   └── llm_client.py         # 统一LLM调用封装
├── data/
│   ├── seeds/
│   └── agents/
│       └── {agent_id}/
│           ├── soul.json
│           ├── l2_patterns.json
│           ├── l0_buffer.json
│           ├── global_state.json
│           ├── graph.db                   ← SQLite（v6新增）
│           └── memories/                  ← LanceDB
├── jobs/
│   ├── decay_job.py                       # 含边衰减+dormant复活（v6扩展）
│   └── evidence_decay_job.py
├── tests/
│   ├── test_module1.py
│   ├── test_module2.py
│   ├── test_module3.py
│   ├── test_module4.py
│   ├── test_module5.py
│   ├── test_l2_engine.py
│   └── test_memory_graph.py               # v6新增
├── logs/
├── config.py
└── main.py
```

**config.py（v6更新）：**
```python
CLAUDE_API_KEY = ""
MODEL = "claude-sonnet-4-20250514"
EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_API_KEY = ""

# 衰减配置
DECAY_BASE_RATE = 0.95
DECAY_DAMPING_FACTOR = 0.6
DECAY_INTERVAL_DAYS = 1
DORMANT_THRESHOLD = 0.3
ARCHIVE_THRESHOLD = 0.1

# 记忆图配置（v6新增）
GRAPH_BUILD_EDGE_TOP_N = 50
GRAPH_BUILD_EDGE_SIMILARITY_THRESHOLD = 0.6
GRAPH_RETRIEVAL_STRENGTHEN_INCREMENT = 0.1
GRAPH_RETRIEVAL_EXPAND_MIN_STRENGTH = 0.3
GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT = 3
GRAPH_DORMANT_REVIVAL_RECENT_DAYS = 7
GRAPH_EDGE_DECAY_RATE = 0.99

# 情绪峰值触发（v6新增）
EMOTION_SNAPSHOT_THRESHOLD = 0.7

# is_derivable过滤（v6新增）
IS_DERIVABLE_DISCARD_THRESHOLD = 0.8

# L1→L2 阶段一简化规则
L2_SAME_TOPIC_THRESHOLD = 3
L2_INITIAL_CONFIDENCE = 0.6
L2_CONFIDENCE_INCREMENT = 0.1
L2_SOUL_CONTRIBUTION_THRESHOLD = 0.8

# L1→L2 阶段二完整规则（预留）
L1_TO_L2_IMPORTANCE_THRESHOLD = 0.6
L1_TO_L2_SAME_TYPE_COUNT = 3
L1_TO_L2_ACCESS_FREQUENCY = 2

# Soul层配置
SOUL_EVIDENCE_DECAY_RATE = 0.98
SOUL_ANCHOR_MAX_TOKENS = 500

# 容量限制
L1_MAX_ACTIVE = 2000
L2_MAX_PATTERNS = 200

LOG_LEVEL = "INFO"
```

---

### 模块1：种子解析器（seed_parser.py）

**输入：** 一段自然语言人物描述。
**输出：** `data/seeds/{agent_id}/seed.json`
**规则：** 缺失字段填null，不强行推断，不允许幻觉填充。
**验证标准：** 三段不同风格描述，输出结构完整，null使用正确。

---

### 模块2：Soul层初始化（soul.py）

**输入：** `seed.json`
**输出：** `soul.json` + `global_state.json` + `l2_patterns.json`(空) + `l0_buffer.json`(空)

**初始化规则：**
- 宪法区：最稳定核心特质，每个核心不超过3条，locked=true
- 缓变区：可缓慢变化的偏好，每个核心不超过6条，使用积分制
- 弹性区：当前状态，每个核心不超过3条
- 四核心允许某个核心为空

**核心接口：**
```python
def read_soul(agent_id) -> dict
def update_elastic(agent_id, core, field, value) -> None
def add_evidence(agent_id, core, field, score, reason, session_id) -> None
def decay_evidence(agent_id) -> None
def check_slow_change(agent_id) -> list
def apply_slow_change(agent_id, core, field, new_value) -> None
def check_constitutional_conflict(agent_id, content) -> dict
def get_soul_anchor(agent_id) -> str
def get_value_core_constitutional(agent_id) -> str
def read_global_state(agent_id) -> dict
def update_global_state(agent_id, field, value) -> None
```

**验证标准：**
- `add_evidence`多次调用，积分累积正确
- `decay_evidence`每日衰减后积分下降
- `check_slow_change`在积分达标时返回待更新项
- `check_constitutional_conflict`对违反人格内容返回conflict=True
- 四核心分类合理
- `get_soul_anchor`不超过500 tokens

---

### 模块3a：L1事件层（memory_l1.py）

**写入流程（v6更新）：**
```
原始文本
  ↓ 读取Soul层value_core宪法区（调用get_value_core_constitutional）
  ↓ 读取近期5条L1事件摘要（供is_derivable判断）
  ↓ LLM提取原子事件（1段→1-5个事件）
  ↓ LLM打分：注入value_core + 近期事件摘要，一次性输出五项分数
  ↓   emotion_intensity / value_relevance / novelty / reusability / is_derivable
  ↓ is_derivable > 0.8 → 丢弃该事件
  ↓ 计算importance（四项加权求和，is_derivable不参与）
  ↓ 提取scene字段
  ↓ 生成tags字段（时间/人物/主题/情绪）
  ↓ 生成embedding
  ↓ 写入LanceDB，status=active，access_count=0
  ↓ [v6] 触发记忆图建边（memory_graph.create_links_on_write）
```

**核心接口：**
```python
def write_event(agent_id, raw_text, source="dialogue") -> list[str]
    # 返回写入的event_id列表
    # v6：内部调用memory_graph.create_links_on_write
def get_event(event_id) -> dict
def update_event_status(event_id, status) -> None
def increment_access_count(event_id) -> None
def get_archived_by_topic(agent_id, topic) -> list
def get_recent_events_summary(agent_id, limit=5) -> str
    # v6新增：供is_derivable判断使用
```

**验证标准（v6扩展）：**
- 10轮对话提取3-8个事件，字段完整，scene有内容
- importance_breakdown五项分数合理
- is_derivable高的重复信息被正确过滤
- 写入时自动建边（语义相似事件之间有边）
- 手动修改created_at为30天前，decay后低importance事件先进入archived

---

### 模块3b：事件索引层（indexer.py）

**v5变更：不再维护独立索引表，改为LanceDB metadata filter查询的封装。**

**核心接口：**
```python
def query(agent_id, people=None, time_year=None,
          time_month=None, topic=None,
          emotion_valence=None, min_importance=None,
          status=None) -> list
    # 封装LanceDB的metadata filter查询
```

**验证标准：**
- 写入事件后tags字段完整
- 按人物/主题/时间/情绪各维度查询，返回正确结果
- 事件archived后，status字段查询正确

---

### 模块3c：L2规则引擎（memory_l2.py）

**核心接口：**
```python
def check_and_generate_patterns(agent_id) -> list[str]
    # 扫描archived事件，按topic分组
    # 同topic ≥ 3条 → 生成/更新L2 pattern
    # 返回新生成或更新的pattern_id列表
    # 含失败回滚逻辑
   
def get_patterns(agent_id) -> list[dict]
    # 返回所有active的L2 patterns

def get_patterns_for_retrieval(agent_id, query_topics) -> list[dict]
    # 返回与query相关topic的patterns，供retrieval使用

def contribute_to_soul(agent_id) -> list[dict]
    # 检查confidence > 0.8的patterns
    # 向对应Soul核心缓变区贡献evidence_score
    # 返回贡献记录
    
def rollback_patterns(agent_id, snapshot) -> None
	# v6新增：回滚到快照状态

def mark_retry_needed(agent_id) -> None
    # v6新增：标记需要重试
```

**验证标准：**
- 写入3条同topic的archived事件后，自动生成L2 pattern
- pattern的abstract_conclusion合理概括了事件内容
- 继续添加同topic事件，confidence逐步增长
- confidence超过0.8后，对应Soul缓变区evidence_score增加
```

---

### 模块3d：记忆图（memory_graph.py）（v6新增）

（详见3.4节数据结构和接口定义。）

---

### 模块4：记忆检索引擎（retrieval.py）

**检索流程（v6更新）：**
```
query + agent_id + mode + session_surfaced_ids
  ↓ get_soul_anchor() → 人格锚（固定加入）
  ↓ read_global_state() → 当前状态 + personality_params
  ↓ L0 buffer → 当前会话上下文
  ↓ get_patterns_for_retrieval() → L2相关摘要（有内容时加入）
  ↓ query→embedding → LanceDB向量检索
  ↓ 过滤status=active OR dormant OR revived，召回top20
  ↓ [v6] 排除already_surfaced事件（会话内去重）
  ↓ [v6] 图扩展：对top5事件查memory_graph邻居
  ↓   expand_min_strength受introversion调制：
  ↓     高introversion → 阈值降低（联想更远）
  ↓     低introversion → 阈值升高（只要强关联）
  ↓   邻居事件加入候选池，去重
  ↓ 按mode选权重重排，取top 5-8条
  ↓ [v6] decision模式：LLM reranking（一次调用，max_tokens:256）
  ↓ [v6] 附加记忆老化文本（"X天前的记忆"）
  ↓ increment_access_count（被检索事件计数+1）
  ↓ [v6] strengthen_links_on_retrieval（共现加强边）
  ↓ 输出context包
```

**核心接口（v6更新）：**
```python
def retrieve(agent_id, query, mode="dialogue", 
             already_surfaced=None) -> dict
    # already_surfaced: set[str]，本次会话已推送的event_id
```

**输出格式（v6更新）：**
```json
{
  "soul_anchor": "Soul层人格锚，400-500tokens",
  "current_state": "当前状态描述",
  "working_context": "L0当前会话上下文",
  "l2_patterns": "相关行为规律摘要（有内容时）",
  "relevant_memories": [
    {
      "event_id": "uuid",
      "content": "事件描述",
      "scene": "情景描述",
      "time": "2026-03",
      "importance": 0.7,
      "emotion": "愧疚",
      "freshness_text": "（约2周前的记忆，细节可能模糊）",
      "source": "vector_search | graph_expand"
    }
  ],
  "surfaced_ids": ["id1", "id2", "..."]
}
```

**验证标准（v6扩展）：**
- 10个不同类型query，返回记忆与主题相关
- Soul层人格锚每次出现
- 图扩展有效：通过关联边召回的事件出现在结果中
- 已推送的事件不重复出现（同一会话内）
- decision模式下LLM reranking结果合理
- 老化文本正确附加

---

### 模块5：对话与决策接口（dialogue.py）

**对话流程（v6更新）：**
```
用户消息
  ↓ 检测emotion_intensity（v6）
  ↓ if emotion_intensity > 0.7 → 记录emotion_snapshot到L0
  ↓ retrieval.retrieve(mode="dialogue", already_surfaced=session_surfaced)
  ↓ 更新session_surfaced（加入本次推送的event_id）
  ↓ 构建system prompt（含老化文本）
  ↓ Claude API生成回答
  ↓ 返回用户
  ↓ 会话结束时end_session()：
      [同步操作]
        L0内容（含emotion_snapshots）提交memory_l1
        LLM筛选：is_derivable过滤 + importance计算
        高importance写入L1（含建边）
        低importance丢弃
        L0 buffer清空
      [异步操作]（v6拆分）
        更新Soul层弹性区
        LLM判断是否构成缓变区evidence → add_evidence
        L2规则引擎检查（含失败回滚）
        L2高confidence → Soul贡献积分
```

**system prompt模板：**
```
你是{name}，{age}岁，{occupation}，现居{location}。

【你的核心人格】
{soul_anchor}

【你现在的状态】
{current_state}

【你的行为规律】
{l2_patterns}

【与当前话题相关的记忆】
{relevant_memories_with_freshness_text}

【规则】
1. 用第一人称，绝对不要说"作为AI"或"我是语言模型"
2. 回答符合你的教育背景、职业经历和说话风格
3. 不确定的事，用你的人格特点推断，不编造具体事实
4. 记忆中有的事，自然表现出记得；标注"模糊"的记忆，表现出不太确定
5. 用中文回答
6. 回答长度符合对话节奏，不长篇大论
```

**核心接口（v6更新）：**
```python
def chat(agent_id, user_message, session_history, session_surfaced=None) -> str
    # session_surfaced: 会话内已推送事件集合
def make_decision(agent_id, scenario) -> dict
    # 使用decision模式，含LLM reranking
def end_session(agent_id, session_history) -> None
    # v6：同步+异步拆分
def _end_session_sync(agent_id, session_history) -> None
    # 同步部分：L1写入、L0清空
def _end_session_async(agent_id) -> None
    # 异步部分：Soul更新、L2检查、积分贡献
```

**验证标准（v6扩展）：**
连续对话20轮，覆盖：
- 问童年经历（与seed一致）
- 问不知道的事（推断不编造）
- 价值观冲突情境（表现出抗拒）
- 提到刚才说的事（表现出记得）
- 跨会话（第二次对话能引用第一次L1事件）
- 高importance事件在数周后仍然能被检索到
- L2 patterns在context中出现后，回答体现行为规律
- [v6] 老化记忆表现出不确定感（"好像是...""大概是..."）
- [v6] 同一会话中不反复提同一件事
- [v6] 通过联想边召回的间接相关事件自然出现在对话中
- [v6] 高情绪对话片段即使session中断也不丢失

---

## 六、执行顺序

### 阶段一·前期（核心管道）

```
Step 0：初始化项目结构，验证API连接
Step 1：模块1，种子解析器，用真实数据验证
Step 2：模块2，Soul层初始化，验证四核心三区结构 + 积分制接口
Step 3：模块3a，L1事件层，验证写入和importance打分（含value_core注入 + is_derivable过滤）
Step 4：模块3b，事件索引层，验证LanceDB metadata filter查询
Step 5：weight_engine + decay_job，验证importance调制衰减 + 三态转换
Step 6：模块3d，记忆图，验证建边、图扩展、dormant复活
Step 7：模块4，检索引擎，验证三种模式 + 图扩展 + 会话内去重 + 老化文本 + LLM reranking
Step 8：模块5，对话接口，整合所有模块跑通对话（含情绪峰值触发）
```

### 阶段一·后期（管道打通 + 测试）

```
Step 9：模块3c，L2规则引擎，验证自动摘要生成、confidence增长、失败回滚
Step 10：L2→Soul积分贡献，验证整条管道
Step 11：evidence_decay_job，验证缓变区积分衰减
Step 12：end_session异步化，验证同步+异步拆分
Step 13：tests/，每个模块独立测试
Step 14：端到端测试，20轮对话 + 跨会话 + 衰减 + L2 + 记忆图 + 复活验证
```

**每步完成后独立验证，不等全部完成。**

---

## 七、给Claude Code的注意事项

1. **LLM调用统一封装**在`llm_client.py`，方便后续换模型
2. **所有LLM调用**必须有retry机制，最多3次，间隔2秒指数退避
3. **数据按agent_id完全隔离**，为多Agent阶段准备
4. **接口优先**：先写函数签名和docstring，再实现逻辑
5. **预留接口**：用NotImplementedError + 注释说明等待哪个阶段
6. **日志**：`logs/`目录，格式：`{timestamp} {module} {operation} {agent_id} {result}`
7. **LanceDB**：L1向量存储 + metadata filter查询，embedding用OpenAI text-embedding-3-small
8. **SQLite**：记忆图边表，每个agent独立的graph.db文件（v6新增）
9. **config优先**：所有阈值参数从config读取，不硬编码
10. **importance打分prompt**中必须注入Soul层value_core宪法区 + 近期事件摘要（v6更新）
11. **L2规则引擎**在end_session异步触发，失败时回滚（v6更新）
12. **end_session拆分**：L1写入和L0清空为同步必须完成；Soul更新、L2检查为异步后台（v6新增）
13. **会话状态**：dialogue.py维护session_surfaced集合，传递给retrieval（v6新增）
14. **记忆老化文本**：retrieval组装context时附加，不在存储层处理（v6新增）

---

## 八、阶段二备忘

- L2升级为LLM驱动的聚类抽象（替换规则引擎）
- L1→L2竞争上升完整三条件触发逻辑
- L2→Soul层升级机制完善（置信度+宪法区冲突检查）
- 记忆图增强：有向边、因果链推理、图遍历路径作为决策轨迹
- core_links填充（Soul层核心归属）
- 权重动力学补全：情绪增益、频率增益（access_count）、反思调制
- L0感知缓冲层完整工作记忆逻辑
- 语义记忆开始填充
- Soul层反向影响L1 importance计算（闭环完成）
- 数字身体模块
- **embedding量化**：当agent数量和事件总量增长后，引入向量量化（如TurboQuant）压缩L1事件的embedding存储，降低检索延迟和建边成本。4-bit量化可实现8倍压缩，检索质量损失可忽略（v6新增）
- retrieval增加意图感知检索（替代固定三模式），参考SimpleMem

### 阶段三备忘

- 多人化（25人小镇框架）
- 世界模型
- 程序记忆填充
- 反应系统
- **团队记忆隔离与增量同步**：基于唯一标识（agent_id / group_id）的记忆隔离方案，增量同步策略（ETag机制），写入前敏感信息扫描。参考Claude Code的teamMemorySync实现（v6新增）

---

## 九、版本历史

- v1：初始版本，基于Stanford genagents改造
- v2：补齐六层结构，加global_state横切
- v3：三张独立架构图，L0升级，索引层和权重层独立
- v4：L0改名感知缓冲层，L3改名Soul层，四核心各设三区，竞争上升机制，情景记忆scene字段，层间token权重表，层级对照总表，事件索引层恢复独立
- v5：L0定位澄清（简化版实现），衰减公式改为importance调制，importance打分注入Soul层value_core，缓变区改为积分制，索引层合并为L1 metadata，L2简化规则引擎实现（管道打通），架构图补全依赖关系，阶段一拆分前后期执行顺序
- v6：记忆图正式进入阶段一（SQLite边表+建边规则+图扩展+dormant复活），记忆老化语言化，情绪峰值中间触发，decision模式LLM reranking，会话内去重（already_surfaced），is_derivable过滤（冗余信息不入库），L2失败回滚机制，end_session同步异步拆分，阶段二备忘新增embedding量化（TurboQuant），阶段三备忘新增团队记忆隔离

*本Spec基于2026-04-01讨论定稿。*
