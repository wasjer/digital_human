"""
手动测试 weight_engine / decay_job / evidence_decay_job。
运行方式（在项目根目录）：python tests/manual_test_decay.py

前置条件：manual_test_soul.py 已执行过，soul.json / global_state.json 存在。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory_l1 import write_event, _get_table, get_event
from core.indexer import query
from jobs.decay_job import run_decay_job
from jobs.evidence_decay_job import run_evidence_decay_job
from core.soul import read_soul

AGENT_ID = "test_agent_001"

# ── 1. 写入3条事件 ─────────────────────────────────────────────────────────────
print("=" * 60)
print("1. 写入 3 条事件")
print("=" * 60)

ids1 = write_event(AGENT_ID, "今天和同事开了一个不太重要的例会，内容很普通")
ids2 = write_event(AGENT_ID, "认真研究了系统架构设计，感到非常有收获，对未来职业发展很有价值")
ids3 = write_event(AGENT_ID, "随手看了几条新闻，没什么特别感觉")

all_ids = ids1 + ids2 + ids3
print(f"写入 event_id 列表（共 {len(all_ids)} 条）:")
for eid in all_ids:
    ev = get_event(AGENT_ID, eid)
    print(f"  {eid[:8]}... importance={ev.get('importance', 0):.3f} action={ev.get('action', '')}")

# ── 2. 把第一条的 created_at 改为60天前 ───────────────────────────────────────
print("\n" + "=" * 60)
print("2. 将第一条事件的 created_at 改为 60 天前")
print("=" * 60)

if all_ids:
    old_target = all_ids[0]
    sixty_days_ago = (datetime.now() - timedelta(days=60)).isoformat()
    tbl = _get_table(AGENT_ID)
    tbl.update(
        where=f"event_id = '{old_target}'",
        values={"created_at": sixty_days_ago},
    )
    ev_check = get_event(AGENT_ID, old_target)
    print(f"  event_id={old_target[:8]}... created_at 已改为: {ev_check.get('created_at', '')[:19]}")
    print(f"  importance={ev_check.get('importance', 0):.3f}  decay_score={ev_check.get('decay_score', 1):.4f}")

# ── 3. 运行 run_decay_job ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. run_decay_job")
print("=" * 60)
stats = run_decay_job(AGENT_ID)
print(f"统计结果: {json.dumps(stats, ensure_ascii=False, indent=2)}")

# ── 4. 查询各 status 事件数量 ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. 查询各 status 事件数量")
print("=" * 60)
for st in ("active", "dormant", "archived"):
    rows = query(AGENT_ID, status=st, limit=200)
    print(f"  {st}: {len(rows)} 条")

# 确认60天前那条事件的新状态
if all_ids:
    ev_after = get_event(AGENT_ID, all_ids[0])
    print(f"\n  60天前事件 event_id={all_ids[0][:8]}... "
          f"decay_score={ev_after.get('decay_score', 0):.4f} "
          f"status={ev_after.get('status', '')}")

# ── 5. 运行 run_evidence_decay_job ────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. run_evidence_decay_job")
print("=" * 60)

soul_before = read_soul(AGENT_ID)
sample_score_before = (
    soul_before["value_core"]["slow_change"]["value_priority_order"]["evidence_score"]
)
print(f"  衰减前 value_core.value_priority_order.evidence_score = {sample_score_before:.6f}")

ev_stats = run_evidence_decay_job(AGENT_ID)
print(f"  统计结果: {json.dumps(ev_stats, ensure_ascii=False)}")

soul_after = read_soul(AGENT_ID)
sample_score_after = (
    soul_after["value_core"]["slow_change"]["value_priority_order"]["evidence_score"]
)
print(f"  衰减后 value_core.value_priority_order.evidence_score = {sample_score_after:.6f}")
