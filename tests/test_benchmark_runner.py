"""benchmark_runner 备份/恢复 + 报告格式 dry-run 验证。"""
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import tools.benchmark_runner as br


def _fake_chat(agent_id, msg, history):
    return {"reply": f"echo:{msg}", "emotion_intensity": 0.3}


def _fake_end_session(agent_id, history):
    return None


def test_benchmark_backup_restore_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(br, "_BENCHMARK_DIR", tmp_path / "bench")
    agent_dir = br._AGENTS_DIR / "test_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "soul.json").write_text('{"agent_id": "test_agent"}', encoding="utf-8")

    dialogues = tmp_path / "d.json"
    dialogues.write_text(json.dumps([{"text": "你好", "category": "寒暄"}]), encoding="utf-8")

    with patch.object(br, "chat", side_effect=_fake_chat), \
         patch.object(br, "end_session", side_effect=_fake_end_session):
        report = br.run_benchmark("test_agent", dialogues, run_label="t")

    # agent 目录已恢复
    assert (agent_dir / "soul.json").read_text(encoding="utf-8") == '{"agent_id": "test_agent"}'
    # 报告格式完整
    assert report["agent_id"] == "test_agent"
    assert report["question_count"] == 1
    assert report["ok_count"] == 1
    assert report["results"][0]["reply"] == "echo:你好"
    assert report["results"][0]["category"] == "寒暄"
    # 备份 tar 存在
    assert Path(report["backup_tar"]).exists()
    with tarfile.open(report["backup_tar"]) as tar:
        names = tar.getnames()
        assert any("soul.json" in n for n in names)


def test_benchmark_restores_on_chat_exception(tmp_path, monkeypatch):
    """即使 chat() 抛异常，agent 目录也必须被恢复，错误被记录到 results 而不是吞掉。"""
    monkeypatch.setattr(br, "_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(br, "_BENCHMARK_DIR", tmp_path / "bench")
    agent_dir = br._AGENTS_DIR / "test_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "soul.json").write_text('{"agent_id": "test_agent"}', encoding="utf-8")

    dialogues = tmp_path / "d.json"
    dialogues.write_text(json.dumps([{"text": "你好", "category": "寒暄"}]), encoding="utf-8")

    with patch.object(br, "chat", side_effect=RuntimeError("boom")), \
         patch.object(br, "end_session", side_effect=_fake_end_session):
        report = br.run_benchmark("test_agent", dialogues, run_label="err")

    # 1) agent 目录被恢复（soul.json 原样存在）
    assert (agent_dir / "soul.json").read_text(encoding="utf-8") == '{"agent_id": "test_agent"}'
    # 2) 错误被记录而非吞掉
    assert report["ok_count"] == 0
    assert report["results"][0]["error"] == "boom"
    assert report["results"][0]["reply"] is None
