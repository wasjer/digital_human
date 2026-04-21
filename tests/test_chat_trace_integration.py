"""集成测试：chat() 加上 mark 后应产生恰好 4 个 step，顺序正确。
使用大量 patch 隔离实盘/实 LLM。"""
from unittest.mock import patch, MagicMock
from core import trace


@patch("core.dialogue._save_l0")
@patch("core.dialogue._load_l0")
@patch("core.dialogue.retrieve")
@patch("core.dialogue.chat_completion")
def test_chat_produces_four_steps(
    mock_chat, mock_retrieve, mock_load_l0, mock_save_l0, tmp_path
):
    mock_load_l0.return_value = {
        "agent_id": "a",
        "session_id": "s1",
        "created_at": "2026-04-20T00:00:00",
        "ttl_hours": 24,
        "raw_dialogue": [],
        "emotion_snapshots": [],
        "working_context": {},
        "status": "simplified",
    }
    mock_retrieve.return_value = {
        "soul_anchor": "anchor",
        "current_state": "ok",
        "working_context": "",
        "l2_patterns": "",
        "relevant_memories": [],
        "surfaced_ids": [],
    }
    # 第一次调：smalltalk 分类；第二次调：情绪检测；第三次调：回复生成
    mock_chat.side_effect = ["substantive", "0.15", "好的"]

    from core.dialogue import chat

    with trace.turn("a", "我最近工作很忙") as t:
        result = chat("a", "我最近工作很忙", session_history=[])

    step_names = [s.name for s in t.steps]
    assert step_names == ["情绪检测", "记忆检索", "构造 prompt", "对话生成"]
    assert all(s.total == 4 for s in t.steps)
    assert result["reply"] == "好的"


def test_main_chat_accepts_debug_flag():
    # 只是 smoke 验证 argparse 不报错；不真的进入 REPL
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "main_chat.py", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "--debug" in result.stdout
