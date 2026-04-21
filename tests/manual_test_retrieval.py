"""
手动测试 core/retrieval.py。
运行方式（在项目根目录）：python tests/manual_test_retrieval.py

前置条件：manual_test_soul.py 已执行过，soul.json / global_state.json 存在。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory_l1 import write_event
from core.retrieval import retrieve

AGENT_ID = "test_agent_001"

# ── 1. 写入5条不同话题的事件 ──────────────────────────────────────────────────
print("=" * 60)
print("1. 写入 5 条不同话题的事件")
print("=" * 60)

events = [
    "最近工作压力很大，项目deadline压着，感到很焦虑，晚上睡不好觉",
    "和领导谈了晋升的事，对方态度模糊，让我很迷茫，不知道该不该继续等",
    "今天去跑步5公里，感觉身体状态不错，心情也好了很多",
    "读了一本关于职场沟通的书，学到了很多处理人际关系的技巧",
    "家人催婚，和父母大吵了一架，感到很委屈，需要时间冷静",
]
all_ids = []
for text in events:
    ids = write_event(AGENT_ID, text)
    all_ids.extend(ids)
    if ids:
        print(f"  写入: {ids[0][:8]}...  原文: {text[:25]}...")

print(f"\n共写入 {len(all_ids)} 条事件")


# ── 2. dialogue 模式检索：工作压力 ───────────────────────────────────────────
print("\n" + "=" * 60)
print('2. retrieve — mode="dialogue", query="工作压力"')
print("=" * 60)

result1 = retrieve(AGENT_ID, "工作压力", mode="dialogue")

print(f"soul_anchor（前80字）: {result1['soul_anchor'][:80]}...")
print(f"current_state: {result1['current_state']}")
print(f"working_context: {result1['working_context'] or '（空）'}")
print(f"l2_patterns: {result1['l2_patterns'] or '（空，模块未实现）'}")
print(f"\nrelevant_memories 数量: {len(result1['relevant_memories'])}")
for i, mem in enumerate(result1["relevant_memories"]):
    print(f"\n  [{i+1}] event_id={mem['event_id'][:8]}...  source={mem['source']}")
    print(f"       content: {mem['content'][:60]}...")
    print(f"       importance={mem['importance']:.3f}  emotion={mem['emotion']}")
    print(f"       freshness_text: '{mem['freshness_text']}'")

print(f"\nsurfaced_ids（共 {len(result1['surfaced_ids'])} 条）: "
      f"{[s[:8] for s in result1['surfaced_ids']]}")


# ── 4. decision 模式检索：重要决定 ───────────────────────────────────────────
print("\n" + "=" * 60)
print('4. retrieve — mode="decision", query="做一个重要决定"')
print("   （观察日志中是否有 LLM reranking 调用）")
print("=" * 60)

result3 = retrieve(AGENT_ID, "做一个重要决定", mode="decision")

print(f"relevant_memories 数量: {len(result3['relevant_memories'])}")
for i, mem in enumerate(result3["relevant_memories"]):
    print(f"  [{i+1}] {mem['event_id'][:8]}...  importance={mem['importance']:.3f}  "
          f"{mem['content'][:50]}...")
print("（请检查上方日志：应有 'decision mode: calling LLM rerank' 和 '_llm_rerank selected' 字样）")


# ── 5. 打印 freshness_text 示例，确认各档老化文本格式 ─────────────────────────
print("\n" + "=" * 60)
print("5. freshness_text 各档格式验证")
print("=" * 60)

from core.retrieval import _freshness_text

cases = [
    (0,  "active",  "0天 active"),
    (2,  "active",  "2天 active"),
    (7,  "active",  "7天 active"),
    (20, "active",  "20天 active"),
    (45, "active",  "45天 active"),
    (3,  "dormant", "3天 dormant"),
    (5,  "revived", "5天 revived"),
]
for days, status, label in cases:
    text = _freshness_text(days, status)
    print(f"  {label:15s} → '{text}'")

# 再从实际检索结果中取一条打印
if result1["relevant_memories"]:
    m = result1["relevant_memories"][0]
    print(f"\n实际事件 freshness_text: '{m['freshness_text']}'  （event_id={m['event_id'][:8]}...）")
