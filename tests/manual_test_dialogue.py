"""
手动测试 core/dialogue.py。
运行方式（在项目根目录）：python tests/manual_test_dialogue.py

前置条件：manual_test_soul.py 已执行过，soul.json / global_state.json 存在。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.soul import init_soul, read_soul
from core.dialogue import chat, end_session, make_decision

AGENT_ID = "test_agent_001"

# ── 1. 确认 agent 已初始化 ────────────────────────────────────────────────────
print("=" * 60)
print("1. 确认 agent 已初始化")
print("=" * 60)
soul = read_soul(AGENT_ID)
if soul.get("emotion_core"):
    print(f"  ✓ soul.json 存在  agent_id={soul.get('agent_id')}")
    print(f"  emotion_core.constitutional: "
          f"{soul['emotion_core']['constitutional'].get('base_emotional_type')}")
else:
    print("  soul.json 不存在，正在初始化...")
    init_soul(AGENT_ID)
    print("  ✓ 初始化完成")


# ── 2. 进行5轮对话 ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. 进行 5 轮对话（童年/工作压力/家庭关系）")
print("=" * 60)

session_history:  list = []

dialogues = [
    "你小时候最开心的记忆是什么？",
    "最近工作压力特别大，项目快到deadline了，感觉撑不住了",
    "你觉得和父母的关系怎么处理比较好？",
    "如果要在事业和家庭之间做选择，你会怎么想？",
    "今天终于把项目做完了，感觉松了一口气",
]

for i, user_msg in enumerate(dialogues, 1):
    print(f"\n  [轮{i}] user: {user_msg}")
    result = chat(
        AGENT_ID,
        user_msg,
        session_history=session_history,
    )
    reply   = result["reply"]
    emotion = result["emotion_intensity"]

    print(f"         reply: {reply[:100]}{'...' if len(reply) > 100 else ''}")
    print(f"         emotion_intensity={emotion:.3f}")

    # 更新 session_history
    session_history.append({"role": "user",      "content": user_msg})
    session_history.append({"role": "assistant",  "content": reply})


# ── 3. 打印 l0_buffer.json 确认对话已暂存 ────────────────────────────────────
print("\n" + "=" * 60)
print("3. 打印 l0_buffer.json 确认对话已暂存")
print("=" * 60)

buf_path = Path("data/agents") / AGENT_ID / "l0_buffer.json"
with open(buf_path, "r", encoding="utf-8") as f:
    buf = json.load(f)

print(f"  session_id: {buf.get('session_id', '')[:16]}...")
print(f"  raw_dialogue 条数: {len(buf.get('raw_dialogue', []))}（预期 {len(dialogues)*2} 条，user+assistant各一条）")
print(f"  emotion_snapshots 条数: {len(buf.get('emotion_snapshots', []))}")
for snap in buf.get("emotion_snapshots", []):
    print(f"    - intensity={snap['emotion_intensity']:.3f}  "
          f"trigger={snap['trigger_message'][:40]}...")
print("  ✓ 对话已暂存在 l0_buffer")


# ── 4. 调用 end_session ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. 调用 end_session")
print("=" * 60)

print("  调用 end_session（同步部分写入 L1，异步部分后台执行）...")
end_session(AGENT_ID, session_history)
print("  end_session 返回（不等待后台线程）")

# 等待异步线程完成（手动测试时等几秒）
print("  等待 15s 让异步线程完成...")
time.sleep(15)


# ── 5. 确认 l0_buffer.json 已清空 ────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. 确认 l0_buffer.json 已清空")
print("=" * 60)

with open(buf_path, "r", encoding="utf-8") as f:
    buf_after = json.load(f)

dialogue_count = len(buf_after.get("raw_dialogue", []))
snapshot_count = len(buf_after.get("emotion_snapshots", []))
session_id_cleared = buf_after.get("session_id") is None

print(f"  raw_dialogue 条数: {dialogue_count}（预期 0）")
print(f"  emotion_snapshots 条数: {snapshot_count}（预期 0）")
print(f"  session_id 已清空: {session_id_cleared}")
if dialogue_count == 0 and snapshot_count == 0:
    print("  ✓ l0_buffer 已成功清空")
else:
    print("  ✗ l0_buffer 未正确清空")


# ── 6. 第二个会话，问"你还记得刚才聊的吗" ─────────────────────────────────────
print("\n" + "=" * 60)
print("6. 开始第二个会话，引用上一会话的记忆")
print("=" * 60)

session_history2: list = []

query2 = "你还记得我们刚才聊的那些事吗？比如工作压力和家庭的话题"
print(f"  user: {query2}")
result2 = chat(
    AGENT_ID,
    query2,
    session_history=session_history2,
)
print(f"  reply: {result2['reply']}")
print("  （reply 中应能自然引用上一会话的内容）")

# 清理
end_session(AGENT_ID, [
    {"role": "user",      "content": query2},
    {"role": "assistant", "content": result2["reply"]},
])


# ── 7. make_decision 测试 ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("7. make_decision：是否接受高薪但需要经常出差的工作邀请")
print("=" * 60)

scenario = "我收到了一个高薪工作邀请，薪资是现在的两倍，但需要每月出差10天以上，你会接受吗？"
print(f"  scenario: {scenario}")

decision_result = make_decision(AGENT_ID, scenario)

print(f"\n  【决策】{decision_result['decision']}")
print(f"\n  【推理】{decision_result['reasoning']}")
print(f"\n  引用记忆数: {len(decision_result['relevant_memories_used'])}")
for mid in decision_result["relevant_memories_used"]:
    print(f"    - {mid[:8]}...")
