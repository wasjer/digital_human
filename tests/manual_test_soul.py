"""
手动测试 soul.py 核心功能。
运行方式（在项目根目录）：python tests/manual_test_soul.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.soul import (
    init_soul,
    read_soul,
    get_soul_anchor,
    add_evidence,
    check_slow_change,
    decay_evidence,
)

AGENT_ID = "test_agent_001"

# ── 准备 seed.json（避免依赖 seed_parser / LLM 数据） ─────────────────────────
seed_dir = Path(__file__).parent.parent / "data" / "seeds" / AGENT_ID
seed_dir.mkdir(parents=True, exist_ok=True)
_seed = {
    "agent_id": AGENT_ID,
    "name": "测试用户",
    "age": 30,
    "occupation": "工程师",
    "location": "北京",
    "emotion_core": {
        "base_emotional_type": "平稳型",
        "emotional_regulation_style": "理性分析",
        "current_emotional_state": "平静",
    },
    "value_core": {
        "moral_baseline": "诚实守信",
        "value_priority_order": "家庭 > 事业 > 个人成长",
        "current_value_focus": "职业发展",
    },
    "goal_core": {
        "life_direction": "技术专家",
        "mid_term_goals": "三年内成为架构师",
        "current_phase_goal": "掌握系统设计",
    },
    "relation_core": {
        "attachment_style": "安全型",
        "key_relationships": ["家人", "同事"],
        "current_relation_state": "稳定",
    },
}
with open(seed_dir / "seed.json", "w", encoding="utf-8") as _f:
    json.dump(_seed, _f, ensure_ascii=False, indent=2)

# ── 1. init_soul ──────────────────────────────────────────────────────────────
print("=" * 60)
print("1. init_soul('test_agent_001')")
print("=" * 60)
soul = init_soul(AGENT_ID)
print(json.dumps(soul, ensure_ascii=False, indent=2))

# ── 2. get_soul_anchor ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. get_soul_anchor('test_agent_001')")
print("=" * 60)
anchor = get_soul_anchor(AGENT_ID)
print(anchor)
print(f"\n字符数: {len(anchor)}")

# ── 3. add_evidence × 3 ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. add_evidence × 3  (core=value_core, field=value_priority_order, score=0.8)")
print("=" * 60)
for i in range(1, 4):
    add_evidence(
        AGENT_ID,
        core="value_core",
        field="value_priority_order",
        score=0.8,
        reason=f"测试证据 {i}",
        session_id=f"session_{i:03d}",
    )
    current_score = read_soul(AGENT_ID)["value_core"]["slow_change"]["value_priority_order"]["evidence_score"]
    print(f"  第{i}次后 evidence_score = {current_score:.4f}")

# ── 4. check_slow_change ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. check_slow_change('test_agent_001')")
print("=" * 60)
changes = check_slow_change(AGENT_ID)
print(changes)

# ── 5. decay_evidence ─────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. decay_evidence('test_agent_001')")
print("=" * 60)
before_score = read_soul(AGENT_ID)["value_core"]["slow_change"]["value_priority_order"]["evidence_score"]
print(f"  衰减前 evidence_score = {before_score:.6f}")
decay_evidence(AGENT_ID)
after_score = read_soul(AGENT_ID)["value_core"]["slow_change"]["value_priority_order"]["evidence_score"]
print(f"  衰减后 evidence_score = {after_score:.6f}")
print(f"  衰减率 = {after_score / before_score:.4f}  (config.SOUL_EVIDENCE_DECAY_RATE={0.98})")
