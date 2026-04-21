"""_end_session_async 内部任何异常都不应上抛。"""
from unittest.mock import patch

from core.dialogue import _end_session_async


def test_end_session_async_swallows_update_elastic_error():
    """update_elastic 抛错时，函数静默返回。"""
    with patch("core.dialogue.update_elastic", side_effect=RuntimeError("boom")), \
         patch("core.dialogue.chat_completion", return_value='{"is_evidence": false}'), \
         patch("core.dialogue.check_slow_change", return_value=[]), \
         patch("core.memory_l2.check_and_generate_patterns"), \
         patch("core.memory_l2.contribute_to_soul"):
        # 不应抛出
        _end_session_async("agent_x", "session text", "sid-1",
                           [{"emotion_intensity": 0.8}])


def test_end_session_async_swallows_memory_l2_import_failure():
    """memory_l2 inline import 失败（如模块临时坏掉）也应被吞掉。"""
    import builtins
    real_import = builtins.__import__

    def bad_import(name, *a, **kw):
        if name.startswith("core.memory_l2"):
            raise ImportError("simulated")
        return real_import(name, *a, **kw)

    with patch("builtins.__import__", side_effect=bad_import), \
         patch("core.dialogue.update_elastic"), \
         patch("core.dialogue.chat_completion", return_value='{"is_evidence": false}'), \
         patch("core.dialogue.check_slow_change", return_value=[]):
        _end_session_async("agent_x", "s", "sid", [])


def test_end_session_async_swallows_memory_l2_runtime_error():
    """memory_l2 call 失败时也应被吞掉。"""
    with patch("core.dialogue.update_elastic"), \
         patch("core.dialogue.chat_completion", return_value='{"is_evidence": false}'), \
         patch("core.dialogue.check_slow_change", return_value=[]), \
         patch("core.memory_l2.check_and_generate_patterns",
               side_effect=RuntimeError("l2 failed")):
        _end_session_async("agent_x", "s", "sid", [])
