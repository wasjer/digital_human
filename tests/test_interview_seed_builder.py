import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
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


def test_write_build_report_sections(tmp_path):
    parsed = {
        "agent_id": "txf",
        "session_id": "abc123",
        "completed_at": "2026-04-15T19:30:52.964Z",
        "duration_minutes": 81,
    }
    raw_seed = {
        "name":       {"value": "Jacky", "confidence": 0.95},
        "age":        {"value": 42,      "confidence": 0.99},
        "occupation": {"value": "茶叶",  "confidence": 0.98},
        "location":   {"value": "合肥",  "confidence": 0.99},
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
            "life_direction":     {"value": "慢生活", "confidence": 0.7},
            "mid_term_goals":     {"value": "旅行",   "confidence": 0.6},
            "current_phase_goal": {"value": "休假",   "confidence": 0.2},
        },
        "relation_core": {
            "attachment_style":       {"value": "独立", "confidence": 0.4},
            "key_relationships":      {"value": ["x"], "confidence": 0.9},
            "current_relation_state": {"value": "稳",  "confidence": 0.7},
        },
        "cognitive_core": {
            "mental_models":        {"value": [],  "confidence": 0.3},
            "decision_heuristics":  {"value": [],  "confidence": 0.35},
            "expression_dna":       {"value": "x", "confidence": 0.8},
            "expression_exemplars": {"value": [], "confidence": 0.95},
            "anti_patterns":        {"value": [], "confidence": 0.4},
            "self_awareness":       {"value": "x", "confidence": 0.8},
            "honest_boundaries":    {"value": "x", "confidence": 0.35},
        },
        "follow_up_questions": {
            "relation_core.attachment_style": ["追问 1", "追问 2"],
            "cognitive_core.honest_boundaries": ["追问边界"],
        },
    }
    stats = {
        "elapsed_seconds":   42,
        "biography_count":   17,
        "meta_count":        1,
        "status_dist":       {"active": 6, "dormant": 4, "archived": 8},
        "l2_pattern_count":  3,
        "soul_contributions":2,
        "topic_dist":        {"职业": 5, "家庭": 4},
    }
    out = tmp_path / "build_report.md"
    isb._write_build_report(str(out), parsed, raw_seed, stats)
    text = out.read_text(encoding="utf-8")

    assert "# Agent 构建报告：txf" in text
    assert "abc123" in text
    assert "81" in text
    assert "Jacky" in text and "42" in text
    for core in ["emotion_core", "value_core", "goal_core", "relation_core", "cognitive_core"]:
        assert core in text
    assert "relation_core.attachment_style" in text
    assert "追问 1" in text
    assert "value_priority_order" in text
    follow_up_section = text.split("## 回访建议", 1)[1]
    assert "current_value_focus" not in follow_up_section
    assert "17" in text and "18" in text
    assert "active=6" in text or "active: 6" in text or "6 / 4 / 8" in text
    assert "L2 Patterns" in text
    assert "42" in text


def _fake_seed_response() -> str:
    seed = {
        "name":       {"value": "Jacky", "confidence": 0.95},
        "age":        {"value": 42,       "confidence": 0.99},
        "occupation": {"value": "茶叶",  "confidence": 0.98},
        "location":   {"value": "合肥",  "confidence": 0.99},
        "emotion_core": {
            "base_emotional_type":        {"value": "内敛", "confidence": 0.8},
            "emotional_regulation_style": {"value": "散步", "confidence": 0.7},
            "current_emotional_state":    {"value": "放松", "confidence": 0.7},
        },
        "value_core": {
            "moral_baseline":       {"value": "真实", "confidence": 0.6},
            "value_priority_order": {"value": "家庭", "confidence": 0.3},
            "current_value_focus":  {"value": "孩子", "confidence": 0.8},
        },
        "goal_core": {
            "life_direction":     {"value": "慢生活",  "confidence": 0.7},
            "mid_term_goals":     {"value": "旅行",    "confidence": 0.6},
            "current_phase_goal": {"value": "休假",    "confidence": 0.2},
        },
        "relation_core": {
            "attachment_style":       {"value": "独立", "confidence": 0.4},
            "key_relationships":      {"value": ["伴侣"], "confidence": 0.9},
            "current_relation_state": {"value": "稳定",   "confidence": 0.7},
        },
        "cognitive_core": {
            "mental_models":        {"value": [], "confidence": 0.3},
            "decision_heuristics":  {"value": [], "confidence": 0.35},
            "expression_dna":       {"value": "冷静务实", "confidence": 0.8},
            "expression_exemplars": {"value": ["句1","句2","句3","句4","句5","句6","句7","句8","句9","句10"], "confidence": 0.95},
            "anti_patterns":        {"value": [], "confidence": 0.4},
            "self_awareness":       {"value": "中庸实用主义", "confidence": 0.8},
            "honest_boundaries":    {"value": "保留",        "confidence": 0.4},
        },
        "recent_self_narrative": "我前几天参加了一次访谈，和小灵聊了我做茶叶、两个孩子、一次感情清零的经历。",
        "follow_up_questions": {
            "relation_core.attachment_style": ["你在亲密关系中如何表达脆弱？"],
        },
    }
    import json as _json
    return _json.dumps(seed, ensure_ascii=False)


def _fake_l1_response() -> str:
    events = [
        {
            "actor": "Jacky",
            "action": "30 岁左右从零售转到接手家里的茶叶",
            "context": "组建家庭后权衡时间与收入",
            "outcome": "慢慢接手了茶叶生意",
            "scene_location": "合肥", "scene_atmosphere": "平静",
            "scene_sensory_notes": "", "scene_subjective_experience": "水到渠成",
            "emotion": "笃定", "emotion_intensity": 0.4,
            "importance": 0.6, "emotion_intensity_score": 0.4,
            "value_relevance_score": 0.7, "novelty_score": 0.6,
            "reusability_score": 0.6,
            "tags_time_year": 2014, "tags_time_month": 6,
            "tags_time_week": 0, "tags_time_period_label": "30 岁左右",
            "tags_people": ["伴侣"], "tags_topic": ["职业"],
            "tags_emotion_valence": "中性", "tags_emotion_label": "笃定",
            "inferred_timestamp": "2014-06-01T00:00:00",
            "raw_quote": "大概是30岁左右的时候，慢慢接手的",
            "event_kind": "biography",
        }
    ]
    import json as _json
    return _json.dumps(events, ensure_ascii=False)


def test_build_from_interview_smoke(tmp_path, monkeypatch):
    md = _SAMPLE_MD
    md_path = tmp_path / "jacky-interview-abc12345-2026-04-15.md"
    md_path.write_text(md, encoding="utf-8")

    monkeypatch.setattr(isb, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(isb, "_SEEDS_DIR",  tmp_path / "seeds")
    from core import seed_memory_loader as sml
    monkeypatch.setattr(sml, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(sml, "_SEEDS_DIR",  tmp_path / "seeds")
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path / "agents")
    from core import memory_l2
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path / "agents")
    from core import global_state
    monkeypatch.setattr(global_state, "_AGENTS_DIR", tmp_path / "agents")

    call_log = []
    def fake_chat(messages, max_tokens=1024, temperature=0.7):
        call_log.append(messages)
        if len(call_log) == 1:
            return _fake_seed_response()
        if len(call_log) == 2:
            return _fake_l1_response()
        return '{"action": "skip"}'

    monkeypatch.setattr(isb, "chat_completion", fake_chat)
    monkeypatch.setattr(memory_l2, "chat_completion", fake_chat)
    monkeypatch.setattr(isb, "get_embedding", lambda t: [0.0] * __import__("config").EMBEDDING_DIM)
    monkeypatch.setattr(sml, "get_embedding", lambda t: [0.0] * __import__("config").EMBEDDING_DIM)

    summary = isb.build_from_interview(str(md_path))

    agent_id = "jacky"
    seeds_dir   = tmp_path / "seeds" / agent_id
    agents_dir  = tmp_path / "agents" / agent_id

    assert (seeds_dir / "seed.json").exists()
    assert (seeds_dir / "interview_source" / md_path.name).exists()
    assert (seeds_dir / "build_report.md").exists()

    assert (agents_dir / "soul.json").exists()
    assert (agents_dir / "l0_buffer.json").exists()
    assert (agents_dir / "l2_patterns.json").exists()
    assert (agents_dir / "global_state.json").exists()

    soul = json.loads((agents_dir / "soul.json").read_text(encoding="utf-8"))
    assert soul["emotion_core"]["constitutional"]["base_emotional_type"] == "内敛"
    assert soul["relation_core"]["constitutional"]["attachment_style"] is None

    l0 = json.loads((agents_dir / "l0_buffer.json").read_text(encoding="utf-8"))
    assert l0["working_context"].get("recent_self_narrative")
    assert "访谈" in l0["working_context"]["recent_self_narrative"]

    seed = json.loads((seeds_dir / "seed.json").read_text(encoding="utf-8"))
    assert seed["relation_core"]["attachment_style"]["confidence"] == 0.4

    assert summary["agent_id"] == agent_id
    assert summary["biography_count"] == 1
    assert summary["meta_count"] == 1
