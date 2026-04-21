"""L2 基于 importance 累积的抽象触发行为。

覆盖点：
- mark_event_abstracted：importance × 0.5 并追加 pattern_id（幂等）
- sum(importance) < 阈值 时不触发 LLM / 不产出 pattern
- sum(importance) >= 阈值 时触发并写回 pattern
- 多 topic 事件：两个桶各自独立按 importance 累积
- 已在本 topic 下被抽象过的事件，下次扫描被该 topic 桶排除
- 种子初始化通路（include_all_statuses=True）使用较低阈值
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from core import memory_l2


# ── mark_event_abstracted ───────────────────────────────────────────────

def test_mark_event_abstracted_halves_importance_and_appends(tmp_path, monkeypatch):
    """importance × 0.5，pattern_id 被追加进 l2_pattern_ids。"""
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a1" / "memories").mkdir(parents=True)

    captured = {}

    def fake_get_event(agent_id, event_id):
        if event_id != "e1":
            return {}
        return {
            "event_id": "e1",
            "importance": 0.8,
            "l2_pattern_ids": "[]",
        }

    class FakeTable:
        def update(self, where, values):
            captured["where"]  = where
            captured["values"] = values

    def fake_get_table(agent_id):
        return FakeTable()

    monkeypatch.setattr(memory_l1, "get_event", fake_get_event)
    monkeypatch.setattr(memory_l1, "_get_table", fake_get_table)

    result = memory_l1.mark_event_abstracted("a1", "e1", "p-xyz")

    assert abs(result["importance"] - 0.4) < 1e-6, f"expected 0.4, got {result['importance']}"
    assert result["l2_pattern_ids"] == ["p-xyz"]
    assert "event_id = 'e1'" in captured["where"]
    assert captured["values"]["l2_pattern_ids"] == '["p-xyz"]'
    assert abs(captured["values"]["importance"] - 0.4) < 1e-6


def test_mark_event_abstracted_idempotent_same_pattern_id(tmp_path, monkeypatch):
    """同一 pattern_id 被标记第二次时：importance 不再衰减、pattern_ids 不再重复。"""
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a1" / "memories").mkdir(parents=True)

    calls = {"update": 0}

    def fake_get_event(agent_id, event_id):
        return {
            "event_id": "e1",
            "importance": 0.4,
            "l2_pattern_ids": '["p-xyz"]',
        }

    class FakeTable:
        def update(self, where, values):
            calls["update"] += 1

    monkeypatch.setattr(memory_l1, "get_event", fake_get_event)
    monkeypatch.setattr(memory_l1, "_get_table", lambda _: FakeTable())

    result = memory_l1.mark_event_abstracted("a1", "e1", "p-xyz")

    assert abs(result["importance"] - 0.4) < 1e-6
    assert result["l2_pattern_ids"] == ["p-xyz"]
    assert calls["update"] == 0, "idempotent call should not write to DB"


# ── check_and_generate_patterns：sum 阈值 ────────────────────────────────

def _mock_patterns_file(tmp_path, agent_id):
    agent_dir = tmp_path / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "l2_patterns.json").write_text("[]", encoding="utf-8")
    return agent_dir


def _mk_event(eid, topic, importance, pattern_ids=None):
    return {
        "event_id":       eid,
        "action":         f"action-{eid}",
        "context":        f"ctx-{eid}",
        "outcome":        "",
        "emotion":        "",
        "tags_topic":     json.dumps([topic] if isinstance(topic, str) else topic, ensure_ascii=False),
        "importance":     importance,
        "l2_pattern_ids": json.dumps(pattern_ids or [], ensure_ascii=False),
    }


def test_below_threshold_no_llm_call(tmp_path, monkeypatch):
    """sum(importance) < L2_IMPORTANCE_SUM_THRESHOLD（10）时不调 LLM，不产出 pattern。"""
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path)
    _mock_patterns_file(tmp_path, "a1")

    events = [
        _mk_event("e1", "工作", 0.8),
        _mk_event("e2", "工作", 0.7),
        _mk_event("e3", "工作", 0.6),  # sum = 2.1 << 10
    ]

    with patch.object(memory_l2, "_fetch_all_events", return_value=events), \
         patch.object(memory_l2, "chat_completion") as mock_llm:
        updated = memory_l2.check_and_generate_patterns("a1")

    assert updated == []
    mock_llm.assert_not_called()


def test_above_threshold_creates_pattern(tmp_path, monkeypatch):
    """sum(importance) >= 10 且 LLM 返回 create 时，新建 pattern 并给事件打标。"""
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path)
    agent_dir = _mock_patterns_file(tmp_path, "a1")

    events = [_mk_event(f"e{i}", "研究方向", 1.1) for i in range(10)]  # sum = 11

    marked = []

    def fake_mark(agent_id, event_id, pattern_id):
        marked.append((event_id, pattern_id))
        return {}

    llm_reply = json.dumps({
        "action": "create",
        "abstract_conclusion": "主体在研究方向上反复自省",
        "target_core": "value_core",
    })

    with patch.object(memory_l2, "_fetch_all_events", return_value=events), \
         patch.object(memory_l2, "chat_completion", return_value=llm_reply), \
         patch("core.memory_l1.mark_event_abstracted", side_effect=fake_mark):
        updated = memory_l2.check_and_generate_patterns("a1")

    assert len(updated) == 1
    saved = json.loads((agent_dir / "l2_patterns.json").read_text(encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["source_topic"] == "研究方向"
    assert saved[0]["abstract_conclusion"] == "主体在研究方向上反复自省"
    new_pid = saved[0]["pattern_id"]

    # 全部 10 条事件都应被打标到该 pattern
    assert len(marked) == 10
    assert all(pid == new_pid for _, pid in marked)


# ── 多 topic 事件 ──────────────────────────────────────────────────────

def test_multi_topic_event_counts_in_each_bucket(tmp_path, monkeypatch):
    """事件同时属于两个 topic 时，importance 完整进入每个桶。"""
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path)
    _mock_patterns_file(tmp_path, "a1")

    # 单条事件、双 topic、importance 20 —— 两个桶都应单独过 10 的阈值
    events = [
        {
            "event_id":       "e1",
            "action":         "a",
            "context":        "c",
            "outcome":        "",
            "emotion":        "",
            "tags_topic":     json.dumps(["工作", "健康"], ensure_ascii=False),
            "importance":     20.0,
            "l2_pattern_ids": "[]",
        }
    ]

    llm_calls = []

    def fake_llm(messages, **kw):
        llm_calls.append(messages[1]["content"])
        return json.dumps({
            "action": "create",
            "abstract_conclusion": "abs",
            "target_core": "goal_core",
        })

    with patch.object(memory_l2, "_fetch_all_events", return_value=events), \
         patch.object(memory_l2, "chat_completion", side_effect=fake_llm), \
         patch("core.memory_l1.mark_event_abstracted", return_value={}):
        updated = memory_l2.check_and_generate_patterns("a1")

    assert len(llm_calls) == 2, f"应对两个 topic 各调一次 LLM，实际 {len(llm_calls)}"
    assert len(updated) == 2


# ── 已抽象过的事件不再进入同 topic 桶 ─────────────────────────────────

def test_already_abstracted_event_excluded_from_same_topic_bucket(tmp_path, monkeypatch):
    """若 pattern P1 已存在且 source_topic='工作'，包含 P1 的事件不再计入 '工作' 桶。"""
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path)
    agent_dir = _mock_patterns_file(tmp_path, "a1")

    existing_pattern = {
        "pattern_id":          "P1",
        "agent_id":            "a1",
        "abstract_conclusion": "existing",
        "support_event_ids":   [],
        "source_topic":        "工作",
        "confidence":          0.6,
        "target_core":         "goal_core",
        "evidence_contribution": 0.0,
        "created_at":          "2026-01-01T00:00:00",
        "updated_at":          "2026-01-01T00:00:00",
        "status":              "active",
        "retry_needed":        False,
        "sampling_weights_placeholder": {},
    }
    (agent_dir / "l2_patterns.json").write_text(
        json.dumps([existing_pattern], ensure_ascii=False), encoding="utf-8"
    )

    # 三条事件：全属于 "工作"，都已含 P1 → "工作" 桶应为空，整体 sum=0 不触发
    events = [
        _mk_event("e1", "工作", 20.0, pattern_ids=["P1"]),
        _mk_event("e2", "工作", 20.0, pattern_ids=["P1"]),
    ]

    with patch.object(memory_l2, "_fetch_all_events", return_value=events), \
         patch.object(memory_l2, "chat_completion") as mock_llm, \
         patch("core.memory_l1.mark_event_abstracted", return_value={}):
        updated = memory_l2.check_and_generate_patterns("a1")

    assert updated == []
    mock_llm.assert_not_called()


# ── 种子初始化通路用较低阈值 ──────────────────────────────────────────

def test_seed_init_uses_lower_threshold(tmp_path, monkeypatch):
    """include_all_statuses=True 时阈值降为 SEED 值（3.0 < 10.0）。"""
    monkeypatch.setattr(memory_l2, "_AGENTS_DIR", tmp_path)
    _mock_patterns_file(tmp_path, "a1")

    # sum = 3 * 1.2 = 3.6，正好跨过 3.0 但不到 10.0
    events = [_mk_event(f"e{i}", "童年", 1.2) for i in range(3)]

    llm_reply = json.dumps({
        "action": "create",
        "abstract_conclusion": "abs",
        "target_core": "relation_core",
    })

    with patch.object(memory_l2, "_fetch_all_events", return_value=events), \
         patch.object(memory_l2, "chat_completion", return_value=llm_reply) as mock_llm, \
         patch("core.memory_l1.mark_event_abstracted", return_value={}):
        updated_normal = memory_l2.check_and_generate_patterns("a1", include_all_statuses=False)
        updated_seed   = memory_l2.check_and_generate_patterns("a1", include_all_statuses=True)

    assert updated_normal == [], "普通通路阈值 10.0，sum=3.6 不应触发"
    assert len(updated_seed) == 1, "种子通路阈值 3.0，sum=3.6 应触发"
    assert mock_llm.call_count == 1


# ── 配置存在性校验 ────────────────────────────────────────────────────

def test_config_thresholds_present():
    assert hasattr(config, "L2_IMPORTANCE_SUM_THRESHOLD")
    assert hasattr(config, "L2_IMPORTANCE_SUM_THRESHOLD_SEED")
    assert hasattr(config, "L2_ABSTRACTED_IMPORTANCE_DECAY")
    assert config.L2_IMPORTANCE_SUM_THRESHOLD_SEED < config.L2_IMPORTANCE_SUM_THRESHOLD
    assert 0 < config.L2_ABSTRACTED_IMPORTANCE_DECAY < 1
