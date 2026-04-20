---
title: 阶段一复盘后的第一轮改动（Branch B）
date: 2026-04-20
status: approved-scope
source_doc: ~/obsidian vault/Projects/东部世界/工程专用/阶段一复盘与改进计划-opus.md
---

# 本轮执行范围

## 背景

用户已维护一份完整的"阶段一复盘与改进计划-opus.md"（含 P0/P1/P2/P3 分级和依赖分析）。
本 spec 只定义**本轮**要落地的子集，不重述全部设计细节——具体条目定义见源文档。

## 本轮目标

在不引入跨模块大重构（Config 三层重构暂缓）的前提下：

1. 先建立控制手段（链路索引 + benchmark）
2. 修 P0 bug
3. 做不依赖 Config 重构的 P1 功能增强
4. 加上本次对话新发现的一项（软惩罚去重）

## 范围决策（对话确认）

- **走分支 B**：不做 2.3 Config 三层重构，因此 3.1 top_K、3.2 is_derivable、3.7 importance 下限 全部**暂缓**——它们依赖 Config 重构
- **4.4 benchmark_runner 从 P2 提到 P1 最前**：先有体检仪再改代码
- **加一项链路索引 md**：自用地图，Phase 0
- **4.1 LLM 全链路日志取消**：trace 系统已覆盖（llm_call / embedding 事件、按 session 写盘）
- **6.4 代码可读性统一**：不单独开一轮，subagent 改各自文件时顺手处理碰到的小问题
- **emotion_intensity 闭环暂缓**：阶段二做专门情绪模块，本轮不动，保留现状
- **1.1 JSON 格式统一 / 7.4 API 格式对齐**：用户已自行处理，不入本轮

## 本轮条目清单（13 项）

### Phase 0 — 打地基（必须先做）

| ID | 内容 | 涉及文件 |
|---|---|---|
| 0-a | 自用链路索引 md（chat 四步 / retrieval 七步 / end_session sync+async / 全局参数来源） | `docs/architecture/link-index.md`（新建） |
| 0-b | 4.4 benchmark_runner + 标准 20 题对话集（备份→跑对话→恢复快照） | `tools/benchmark_runner.py`（新建）+ `tests/data/benchmark_dialogues.json` |

### Phase 1 — P0 修 bug（6 项）

| ID | 内容 | 涉及文件 |
|---|---|---|
| 1.2 | 边 < 0.05 改休眠不删除 | `core/memory_graph.py` |
| 1.3 | 去掉 revived 状态 | `core/memory_graph.py` / `core/retrieval.py` / `core/memory_l1.py` + spec 文档 |
| 1.5 | Ctrl+C 信号捕获 + 启动时自动恢复 l0_buffer | `main_chat.py` |
| 1.6 | `_end_session_async` 外层总 try/except | `core/dialogue.py` |
| 6.3-1 | `_fetch_archived_events` 增量扫描 | `core/memory_l2.py` + `global_state.json` 新增 `last_l2_scan_at` |
| 6.3-2 | `evidence_log` 上限 50 条 + 归档 | `core/soul.py` + `evidence_archive.json` |

### Phase 2 — P1 功能（5 项）

| ID | 内容 | 涉及文件 |
|---|---|---|
| 1.4 | 边强度提升冷却（24h/7d/30d 次数上限） | `core/memory_graph.py` + 边表 schema 扩字段 |
| 3.5 | 主动提问 —— 改 prompt 规则 | `prompts/dialogue_system.txt` |
| 3.6 | 中英文混合 —— 强化中文输出规则 | `prompts/l1_extract_events.txt` / `l1_extract_tags.txt` / `l1_extract_scene.txt` |
| 3.8 | 轻量寒暄旁路（跳过 retrieval） | `core/dialogue.py` `chat()` 入口 |
| NEW-1 | 软惩罚去重（本次对话新增） | `core/retrieval.py` `_score_candidate` + 去掉硬过滤 |

### 跨项原则

- **每项由一个 subagent 独立完成**，只碰声明的文件，完成后清空上下文
- **主 agent 审查**：每项完成后跑 benchmark（Phase 0 完成之后），并核对 diff
- **6.4 顺手**：subagent 改自己文件时若碰到 `_get_table` → `get_table`、prompt 分隔符不一致、函数体内 import 等可一并处理，不跨文件

## 依赖 & 顺序

```
Phase 0  (必须最先):
   0-a 链路索引  ← 独立
   0-b benchmark ← 独立

Phase 1  (可并行，6 项互不依赖):
   1.2, 1.3, 1.5, 1.6, 6.3-1, 6.3-2

Phase 2  (可并行，5 项):
   1.4  ← 独立（edge schema 改动）
   3.5  ← 独立（仅 prompt）
   3.6  ← 独立（仅 prompt）
   3.8  ← 独立（dialogue.py 入口）
   NEW-1 ← 独立（retrieval.py 打分）
```

**唯一可能的文件冲突**：NEW-1 和 Phase 1 的 1.3（都碰 `retrieval.py`）——串行，先做 1.3，再做 NEW-1。

## 成功标准

- 全部 13 项通过 benchmark_runner，与改动前基线对比：
  - 无崩溃 / 无异常日志新增
  - token 消耗、记忆召回数基本稳定（轻量寒暄旁路除外）
  - 对 20 题回复真人 A/B 评分不劣于基线
- 链路索引 md 覆盖三条主流程 + 全局参数表
- `docs/digital_human_spec_v6-2.md` 中 status 四态改为三态（1.3 附带）

## 暂缓项（显式记录，避免遗忘）

- 1.1 JSON 格式统一、7.4 API 对齐（已自处理）
- 2.3 Config 三层重构 + 3.1/3.2/3.7 per-agent 参数（依赖 2.3）
- 3.3 注意力机制（搁置）
- 4.1 LLM 全链路日志（trace 已覆盖）
- 4.2 Obsidian 式可视化、4.6 双数字人互聊（P2/P3）
- 6.1 反译对比、6.2 dead code 清理（提醒项）
- 6.3-3 decay_edges 全表扫描（100 天内不爆）
- emotion_intensity 真正闭环（阶段二专门模块）
- 5.x 全部未来应用 / P3 架构项
