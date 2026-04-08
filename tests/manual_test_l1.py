"""
手动测试 memory_l1.py 和 indexer.py。
运行方式（在项目根目录）：python tests/manual_test_l1.py

前置条件：tests/manual_test_soul.py 已执行过，
          data/agents/test_agent_001/soul.json 存在。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory_l1 import (
    write_event,
    get_event,
    get_recent_events_summary,
    update_event_status,
)
import core.indexer as indexer

AGENT_ID = "test_agent_001"

# ── 1. 写入第一条事件 ──────────────────────────────────────────────────────────
print("=" * 60)
print("1. write_event — 和朋友吃饭聊工作")
print("=" * 60)
ids1 = write_event(AGENT_ID, "今天和朋友吃饭，聊到了工作压力，感到有些焦虑")
print("写入 event_id 列表:", ids1)

# ── 2. 再写两条不同内容的事件 ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. write_event — 读书")
print("=" * 60)
ids2 = write_event(AGENT_ID, "晚上读了一本关于系统设计的书，感觉收获很大，对架构有了新的理解")
print("写入 event_id 列表:", ids2)

print("\n" + "=" * 60)
print("2. write_event — 家人通话")
print("=" * 60)
ids3 = write_event(AGENT_ID, "给父母打了视频电话，聊了很久，感到温暖和放松")
print("写入 event_id 列表:", ids3)

all_ids = ids1 + ids2 + ids3

# ── 3. get_recent_events_summary ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. get_recent_events_summary")
print("=" * 60)
summary = get_recent_events_summary(AGENT_ID, limit=5)
print(summary if summary else "（无活跃事件）")

# ── 4. indexer.query 按 topic 查询 ────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. indexer.query — topic 包含 '工作'")
print("=" * 60)
results = indexer.query(AGENT_ID, topic="工作", limit=10)
print(f"命中 {len(results)} 条")
for r in results:
    print(f"  event_id={r['event_id'][:8]}... action={r['action']} importance={r['importance']:.3f}")

# ── 5. update_event_status → archived，再查询确认 ─────────────────────────────
print("\n" + "=" * 60)
print("5. update_event_status → archived")
print("=" * 60)
if all_ids:
    target_id = all_ids[0]
    print(f"  将 event_id={target_id[:8]}... 改为 archived")
    update_event_status(AGENT_ID, target_id, "archived")

    ev = get_event(AGENT_ID, target_id)
    print(f"  查询确认 status={ev.get('status')}")

    archived = indexer.query(AGENT_ID, status="archived", limit=10)
    print(f"  archived 总数: {len(archived)}")
else:
    print("  无可用 event_id，跳过")
