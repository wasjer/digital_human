import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from core import interview_seed_builder as isb


_SAMPLE_MD = """---
session_id: abc123
user_id: uid0
status: COMPLETED
completed_at: 2026-04-15T19:30:52.964Z
modules_completed: [0, 2, 6]
interview_duration_minutes: 81
---

# 访谈记录

## 模块 0：开场

**小灵**

你好，我叫stone，很高兴认识你。请问你现在多大了？

**受访者**

我现在42岁了，在合肥做茶叶。

## 模块 2：人生十字路口

**小灵**

你有过十字路口的时刻吗？

**受访者**

30 岁左右接手了家里的茶叶生意。
"""


def test_derive_agent_id_from_valid_filename():
    assert isb._derive_agent_id("txf-interview-cmo0d7li-2026-04-15.md") == "txf"
    assert isb._derive_agent_id("jacky_42-interview-abcd1234-2026-04-01.md") == "jacky_42"
    assert isb._derive_agent_id("interview_source/txf-interview-cmo0d7li-2026-04-15.md") == "txf"
    assert isb._derive_agent_id("/abs/path/txf-interview-cmo0d7li-2026-04-15.md") == "txf"


def test_derive_agent_id_invalid_filename_raises():
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("random.md")
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("txf-2026-04-15.md")
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("Txf-interview-xxx-2026-04-15.md")


def test_parse_interview_md_frontmatter(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))

    assert parsed["agent_id"] == "txf"
    assert parsed["session_id"] == "abc123"
    assert parsed["completed_at"] == "2026-04-15T19:30:52.964Z"
    assert parsed["duration_minutes"] == 81
    assert parsed["modules_completed"] == [0, 2, 6]


def test_parse_interview_md_dialogue_text(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))

    assert "受访者" in parsed["dialogue_text"]
    assert "我现在42岁了" in parsed["dialogue_text"]
    assert "30 岁左右接手" in parsed["dialogue_text"]


def test_parse_interview_md_module_titles(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["module_titles"][0] == "开场"
    assert parsed["module_titles"][2] == "人生十字路口"
    assert 6 not in parsed["module_titles"]


def test_parse_interview_md_interviewer_name(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["interviewer_name"] == "小灵"


def test_parse_interview_md_missing_interviewee_block_raises(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text("---\nsession_id: x\n---\n# 无受访者块", encoding="utf-8")
    with pytest.raises(ValueError, match="受访者"):
        isb._parse_interview_md(str(p))


def test_parse_interview_md_bad_frontmatter_falls_back(tmp_path):
    md = _SAMPLE_MD.replace("completed_at: 2026-04-15T19:30:52.964Z\n", "")
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(md, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["completed_at"]
    assert isinstance(parsed["completed_at"], str)
    assert parsed.get("completed_at_fallback") is True


def test_gate_above_threshold_returns_value():
    assert isb._gate({"value": "x", "confidence": 0.7}) == "x"
    assert isb._gate({"value": "x", "confidence": 0.5}) == "x"


def test_gate_below_threshold_returns_none():
    assert isb._gate({"value": "x", "confidence": 0.49}) is None
    assert isb._gate({"value": "x", "confidence": 0.0}) is None


def test_gate_null_value_returns_none_regardless_of_confidence():
    assert isb._gate({"value": None, "confidence": 0.9}) is None


def test_gate_bad_types_return_none():
    assert isb._gate(None) is None
    assert isb._gate("not a dict") is None
    assert isb._gate({"value": "x", "confidence": "high"}) is None
    assert isb._gate({"value": "x"}) is None


def test_gate_custom_threshold():
    assert isb._gate({"value": "x", "confidence": 0.3}, threshold=0.2) == "x"
    assert isb._gate({"value": "x", "confidence": 0.1}, threshold=0.2) is None


def test_build_meta_event_basic():
    parsed = {
        "agent_id": "txf",
        "completed_at": "2026-04-15T19:30:52.964Z",
        "duration_minutes": 81,
        "modules_completed": [0, 2, 6, 5, 4, 3, 1, 7],
        "module_titles": {
            0: "开场", 1: "人生故事", 2: "人生十字路口",
            3: "重要的人", 4: "当下的生活", 5: "价值观与信念",
            6: "对未来的希望", 7: "收尾",
        },
        "interviewer_name": "小灵",
    }
    event = isb._build_meta_event(parsed, agent_name="Jacky")

    assert event["actor"] == "Jacky"
    assert event["event_kind"] == "meta"
    assert event["source"] == "interview_meta"
    assert event["inferred_timestamp"] == "2026-04-15T19:30:52.964Z"
    assert "81" in event["context"]
    assert "小灵" in event["context"]
    assert "开场" in event["outcome"]
    assert event["outcome"].index("开场") < event["outcome"].index("人生十字路口")
    assert event["importance"] == 0.6
    assert event["emotion_intensity"] == 0.3
    assert event["raw_quote"] is None
    assert "访谈" in event["tags_topic"]


def test_build_meta_event_missing_titles_falls_back_to_number():
    parsed = {
        "agent_id": "txf",
        "completed_at": "2026-04-15T19:30:52.964Z",
        "duration_minutes": 30,
        "modules_completed": [0, 99],
        "module_titles": {0: "开场"},
        "interviewer_name": "小灵",
    }
    event = isb._build_meta_event(parsed, agent_name="Jacky")
    assert "开场" in event["outcome"]
    assert "模块 99" in event["outcome"]


def test_build_soul_from_gated_seed_fills_above_threshold_only(tmp_path, monkeypatch):
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")

    raw_seed = {
        "name":       {"value": "Jacky", "confidence": 0.95},
        "age":        {"value": 42,       "confidence": 0.99},
        "occupation": {"value": "茶叶",   "confidence": 0.98},
        "location":   {"value": "合肥",   "confidence": 0.99},
        "emotion_core": {
            "base_emotional_type":        {"value": "内敛", "confidence": 0.8},
            "emotional_regulation_style": {"value": "散步", "confidence": 0.4},
            "current_emotional_state":    {"value": "放松", "confidence": 0.7},
        },
        "value_core": {
            "moral_baseline":       {"value": "真实", "confidence": 0.6},
            "value_priority_order": {"value": "家庭", "confidence": 0.3},
            "current_value_focus":  {"value": "孩子", "confidence": 0.8},
        },
        "goal_core": {
            "life_direction":     {"value": "慢生活",  "confidence": 0.7},
            "mid_term_goals":     {"value": "带娃旅行", "confidence": 0.6},
            "current_phase_goal": {"value": "休假",    "confidence": 0.2},
        },
        "relation_core": {
            "attachment_style":       {"value": "独立", "confidence": 0.4},
            "key_relationships":      {"value": ["伴侣","孩子"], "confidence": 0.9},
            "current_relation_state": {"value": "稳定", "confidence": 0.7},
        },
        "cognitive_core": {
            "mental_models":        {"value": [{"name":"m","one_liner":"x"}], "confidence": 0.55},
            "decision_heuristics":  {"value": [{"rule":"稳"}], "confidence": 0.35},
            "expression_dna":       {"value": "冷静务实", "confidence": 0.75},
            "expression_exemplars": {"value": ["原句"]*10, "confidence": 0.95},
            "anti_patterns":        {"value": ["冲动"], "confidence": 0.40},
            "self_awareness":       {"value": "中庸实用主义", "confidence": 0.80},
            "honest_boundaries":    {"value": "保留", "confidence": 0.35},
        },
    }

    soul = isb._build_soul_from_gated_seed("txf", raw_seed)

    assert soul["emotion_core"]["constitutional"]["base_emotional_type"] == "内敛"
    assert soul["emotion_core"]["elastic"]["current_emotional_state"] == "放松"
    assert soul["value_core"]["elastic"]["current_value_focus"] == "孩子"
    assert soul["goal_core"]["slow_change"]["mid_term_goals"]["value"] == "带娃旅行"
    assert soul["emotion_core"]["slow_change"]["emotional_regulation_style"]["value"] is None
    assert soul["value_core"]["slow_change"]["value_priority_order"]["value"] is None
    assert soul["goal_core"]["elastic"]["current_phase_goal"] is None
    assert soul["relation_core"]["constitutional"]["attachment_style"] is None

    cog = soul["cognitive_core"]["constitutional"]
    assert cog["mental_models"] == [{"name":"m","one_liner":"x"}]
    assert cog["decision_heuristics"] is None
    assert cog["expression_dna"] == "冷静务实"
    assert cog["expression_exemplars"] == ["原句"]*10
    assert cog["anti_patterns"] is None
    assert cog["self_awareness"] == "中庸实用主义"
    assert cog["honest_boundaries"] is None

    assert soul["emotion_core"]["constitutional"]["source"] == "interview"

    assert "confidence_detail" in cog
    assert cog["confidence_detail"]["expression_exemplars"] == 0.95
    assert cog["confidence_detail"]["decision_heuristics"] == 0.35
