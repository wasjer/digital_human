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
    ("今天项目截止日期压力很大，连续工作12小时，感到疲惫但完成了任务", "工作"),
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
    print(f"    target_core={p['target_core']} confidence={p['confidence']}")

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
work_patterns = [p for p in patterns2 if p['source_topic'] in ('工作', 'work')]
for p in work_patterns:
    print(f"  [工作] confidence={p['confidence']} evidence_contribution={p['evidence_contribution']}")

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
