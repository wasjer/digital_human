"""
端到端集成测试：完整模拟两次会话，验证整条管道。
运行方式（在项目根目录）：python tests/e2e_test.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

AGENT_ID        = "joon"
NODES_JSON_PATH = "/Users/stone/Downloads/nodes.json"

_SEP = "=" * 60


def section(title: str):
    print(f"\n{_SEP}")
    print(title)
    print(_SEP)


def safe(fn, label=""):
    """执行 fn()，失败时打印错误并返回 None，不中断测试。"""
    try:
        return fn()
    except Exception as e:
        print(f"  [ERROR] {label}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 准备阶段
# ─────────────────────────────────────────────────────────────
section("准备阶段：生成 agent 'joon'")

from core.seed_parser import parse_seed
from core.soul import init_soul, get_soul_anchor, read_soul, check_slow_change
from core.dialogue import chat, end_session, make_decision
from core.memory_l1 import _get_table
from core.memory_graph import MemoryGraph
from core.global_state import read_global_state

print(f"  parse_seed: {NODES_JSON_PATH} → agent_id={AGENT_ID}")
safe(lambda: parse_seed(NODES_JSON_PATH, AGENT_ID), "parse_seed")

print("  init_soul...")
safe(lambda: init_soul(AGENT_ID), "init_soul")

anchor = safe(lambda: get_soul_anchor(AGENT_ID), "get_soul_anchor")
if anchor:
    print(f"\n  soul anchor（前200字）:\n{anchor[:200]}")


# ─────────────────────────────────────────────────────────────
# Session A：工作压力 / 个人目标（5 轮）
# ─────────────────────────────────────────────────────────────
section("Session A：工作压力 / 个人目标（5 轮）")

session_a_history:  list = []
session_a_surfaced: set  = None

messages_a = [
    "你平时工作压力大吗？",
    "你怎么处理压力？",
    "你觉得你现在的研究方向是你真正想做的吗？",
    "如果可以重来，你会做不同的选择吗？",
    "你觉得什么样的生活是成功的？",
]

for i, msg in enumerate(messages_a, 1):
    print(f"\n  [A-{i}] user: {msg}")
    result = safe(
        lambda m=msg: chat(
            AGENT_ID, m,
            session_history=session_a_history,
        ),
        f"chat A-{i}",
    )
    if result:
        reply            = result["reply"]
        emotion          = result["emotion_intensity"]
        print(f"         reply: {reply[:120]}{'...' if len(reply) > 120 else ''}")
        print(f"         emotion_intensity={emotion:.3f}")
        session_a_history.append({"role": "user",      "content": msg})
        session_a_history.append({"role": "assistant",  "content": reply})

print("\n  → 调用 end_session（Session A）...")
safe(lambda: end_session(AGENT_ID, session_a_history), "end_session A")
print("  → 等待 3 秒让异步任务完成...")
time.sleep(3)

# L1 事件数
def _count_l1():
    tbl  = _get_table(AGENT_ID)
    rows = tbl.search().where("agent_id = 'joon'").limit(9999).to_list()
    return len(rows)

n_l1 = safe(_count_l1, "count L1")
print(f"  L1 事件总数（Session A 后）: {n_l1}")

# l0_buffer 确认清空
buf_path = Path("data/agents") / AGENT_ID / "l0_buffer.json"
def _check_buf():
    if not buf_path.exists():
        return "文件不存在"
    buf = json.loads(buf_path.read_text(encoding="utf-8"))
    return (f"session_id={buf.get('session_id')}  "
            f"raw_dialogue={len(buf.get('raw_dialogue', []))}条  "
            f"emotion_snapshots={len(buf.get('emotion_snapshots', []))}条")

print(f"  l0_buffer: {safe(_check_buf, 'check l0_buffer')}")


# ─────────────────────────────────────────────────────────────
# Session B：童年记忆 / 人际关系（5 轮）
# ─────────────────────────────────────────────────────────────
section("Session B：童年记忆 / 人际关系（5 轮）")

session_b_history:  list = []

messages_b = [
    "你小时候是什么样的孩子？",
    "和父母的关系怎么样？",
    "你有没有特别难忘的朋友？",
    "你觉得孤独吗？",
    "你上次觉得真正被理解是什么时候？",
]

for i, msg in enumerate(messages_b, 1):
    print(f"\n  [B-{i}] user: {msg}")
    result = safe(
        lambda m=msg: chat(
            AGENT_ID, m,
            session_history=session_b_history,
        ),
        f"chat B-{i}",
    )
    if result:
        reply            = result["reply"]
        emotion          = result["emotion_intensity"]
        print(f"         reply: {reply[:120]}{'...' if len(reply) > 120 else ''}")
        print(f"         emotion_intensity={emotion:.3f}")
        session_b_history.append({"role": "user",      "content": msg})
        session_b_history.append({"role": "assistant",  "content": reply})

print("\n  → 调用 end_session（Session B）...")
safe(lambda: end_session(AGENT_ID, session_b_history), "end_session B")
print("  → 等待 3 秒让异步任务完成...")
time.sleep(3)

# L2 patterns
patterns_path = Path("data/agents") / AGENT_ID / "l2_patterns.json"
def _print_patterns():
    if not patterns_path.exists():
        return []
    return json.loads(patterns_path.read_text(encoding="utf-8"))

patterns = safe(_print_patterns, "read l2_patterns") or []
active_patterns = [p for p in patterns if p.get("status") == "active"]
print(f"\n  L2 patterns（active）: {len(active_patterns)} 条")
for p in active_patterns:
    print(f"    [{p['pattern_type']}] conf={p['confidence']:.2f} "
          f"count={p['evidence_count']} | {p['content'][:60]}")

# soul check_slow_change
triggered = safe(lambda: check_slow_change(AGENT_ID), "check_slow_change") or []
print(f"\n  soul slow_change 触发字段数: {len(triggered)}")
for t in triggered:
    print(f"    {t['core']}.{t['field']} evidence_score={t['evidence_score']:.3f}")
if not triggered:
    print("  （积分尚未达到阈值，属正常）")


# ─────────────────────────────────────────────────────────────
# Session C：跨会话记忆验证（3 轮）
# ─────────────────────────────────────────────────────────────
section("Session C：跨会话记忆验证（3 轮）")

session_c_history:  list = []

messages_c = [
    "你还记得我们之前聊过什么吗？",
    "你之前说到了研究方向，能展开说说吗？",
    "你刚才提到的那些，我感觉你是个很有深度的人",
]

for i, msg in enumerate(messages_c, 1):
    print(f"\n  [C-{i}] user: {msg}")

    # 直接调 retrieve 来打印记忆来源
    from core.retrieval import retrieve
    retrieval_result = safe(
        lambda m=msg: retrieve(
            AGENT_ID, m,
            mode="dialogue",
        ),
        f"retrieve C-{i}",
    )
    if retrieval_result:
        mems = retrieval_result["relevant_memories"]
        src_counts = {}
        for m in mems:
            src = m.get("source", "unknown")
            src_counts[src] = src_counts.get(src, 0) + 1
        print(f"         retrieved={len(mems)} 条  "
              f"来源分布: { {k: v for k, v in src_counts.items()} }")

    result = safe(
        lambda m=msg: chat(
            AGENT_ID, m,
            session_history=session_c_history,
        ),
        f"chat C-{i}",
    )
    if result:
        reply            = result["reply"]
        emotion          = result["emotion_intensity"]
        print(f"         reply: {reply[:120]}{'...' if len(reply) > 120 else ''}")
        print(f"         emotion_intensity={emotion:.3f}")
        session_c_history.append({"role": "user",      "content": msg})
        session_c_history.append({"role": "assistant",  "content": reply})

safe(lambda: end_session(AGENT_ID, session_c_history), "end_session C")


# ─────────────────────────────────────────────────────────────
# 决策测试
# ─────────────────────────────────────────────────────────────
section("决策测试")

scenario = "有一个机会可以离开学术界去业界做AI产品，薪资翻倍但要放弃博士学位，你会怎么选择？"
print(f"  scenario: {scenario}\n")

decision_result = safe(lambda: make_decision(AGENT_ID, scenario), "make_decision")
if decision_result:
    print(f"  【决策】{decision_result['decision']}")
    print(f"\n  【推理】{decision_result['reasoning']}")
    print(f"\n  引用记忆数: {len(decision_result['relevant_memories_used'])}")


# ─────────────────────────────────────────────────────────────
# 系统状态汇总
# ─────────────────────────────────────────────────────────────
section("系统状态汇总")

# L1 统计
def _l1_stats():
    tbl  = _get_table(AGENT_ID)
    rows = tbl.search().where("agent_id = 'joon'").limit(9999).to_list()
    total = len(rows)
    counts = {}
    for r in rows:
        s = r.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    return total, counts

l1_stats = safe(_l1_stats, "l1 stats")
if l1_stats:
    total, counts = l1_stats
    print(f"\n  L1 事件总数: {total}")
    for status, cnt in sorted(counts.items()):
        print(f"    {status}: {cnt}")

# memory_graph 统计
graph_stats = safe(lambda: MemoryGraph().get_graph_stats(AGENT_ID), "graph_stats")
if graph_stats:
    print(f"\n  memory_graph:")
    print(f"    total_edges={graph_stats['total_edges']}  "
          f"strong_edges={graph_stats['strong_edges']}  "
          f"avg_strength={graph_stats['avg_strength']:.4f}")

# L2 patterns 数量
print(f"\n  L2 active patterns: {len(active_patterns)}")

# soul slow_change 各字段积分
def _soul_scores():
    from core.soul import CORES
    soul = read_soul(AGENT_ID)
    scores = {}
    for core in CORES:
        for field, data in soul[core]["slow_change"].items():
            score = data.get("evidence_score", 0.0)
            if score > 0:
                scores[f"{core}.{field}"] = round(score, 4)
    return scores

soul_scores = safe(_soul_scores, "soul scores") or {}
print(f"\n  soul slow_change 积分（>0 的字段）:")
if soul_scores:
    for k, v in soul_scores.items():
        print(f"    {k}: {v}")
else:
    print("    （暂无积分）")

# global_state
gs = safe(lambda: read_global_state(AGENT_ID), "global_state")
if gs:
    cs = gs.get("current_state", {})
    print(f"\n  global_state: mood={cs.get('mood')}  "
          f"energy={cs.get('energy')}  "
          f"stress_level={cs.get('stress_level')}")

print(f"\n{'=' * 60}")
print("=== 端到端测试完成 ===")
print(f"{'=' * 60}")
