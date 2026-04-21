"""main_chat 启动时对残留 l0_buffer 自动触发 end_session。"""
import json
from pathlib import Path
from unittest.mock import patch

import main_chat


def _make_stale_buffer(agent_dir: Path, agent_id: str):
    agent_dir.mkdir(parents=True, exist_ok=True)
    buf = {
        "agent_id": agent_id,
        "session_id": "stale-sid-123",
        "created_at": "2026-04-19T10:00:00",
        "ttl_hours": 24,
        "raw_dialogue": [
            {"role": "user", "content": "aborted question"},
            {"role": "assistant", "content": "partial reply"},
        ],
        "emotion_snapshots": [],
        "working_context": {},
        "status": "simplified",
    }
    (agent_dir / "l0_buffer.json").write_text(
        json.dumps(buf, ensure_ascii=False), encoding="utf-8"
    )


def test_recover_stale_buffer_triggers_end_session(tmp_path, monkeypatch):
    agents_root = tmp_path / "agents"
    monkeypatch.setattr(main_chat, "_AGENTS_DIR", agents_root)
    agent_dir = agents_root / "agent_x"
    _make_stale_buffer(agent_dir, "agent_x")

    called = {}
    def fake_end(agent_id, history):
        called["agent_id"] = agent_id
        called["history"] = history
    monkeypatch.setattr(main_chat, "end_session", fake_end)

    main_chat._recover_stale_buffer_if_any("agent_x")

    assert called["agent_id"] == "agent_x"
    # history 从 raw_dialogue 重建
    assert len(called["history"]) == 2


def test_no_recover_when_buffer_empty(tmp_path, monkeypatch):
    agents_root = tmp_path / "agents"
    monkeypatch.setattr(main_chat, "_AGENTS_DIR", agents_root)
    (agents_root / "agent_y").mkdir(parents=True)

    called = {}
    def fake_end(agent_id, history):
        called["called"] = True
    monkeypatch.setattr(main_chat, "end_session", fake_end)

    main_chat._recover_stale_buffer_if_any("agent_y")
    assert "called" not in called
