"""evidence_log 超过 50 条时截断并归档。"""
import json
from pathlib import Path

from core import soul


def _fresh_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(soul, "_AGENTS_DIR", tmp_path)
    agent_dir = tmp_path / "a1"
    agent_dir.mkdir()
    s = soul._build_empty_soul("a1")
    (agent_dir / "soul.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return agent_dir


def test_evidence_log_cap_at_50(tmp_path, monkeypatch):
    agent_dir = _fresh_agent(tmp_path, monkeypatch)
    for i in range(55):
        soul.add_evidence("a1", "emotion_core", "emotional_regulation_style",
                          score=0.01, reason=f"r{i}", session_id="s1")
    s = soul.read_soul("a1")
    log = s["emotion_core"]["slow_change"]["emotional_regulation_style"]["evidence_log"]
    assert len(log) == 50, f"evidence_log should cap at 50, got {len(log)}"
    # 保留最新 50 条：r5..r54
    assert log[0]["reason"] == "r5"
    assert log[-1]["reason"] == "r54"

    archive = agent_dir / "evidence_archive.json"
    assert archive.exists()
    data = json.loads(archive.read_text(encoding="utf-8"))
    archived_reasons = [e["reason"] for e in data]
    assert "r0" in archived_reasons
    assert "r4" in archived_reasons
    assert len(data) == 5
