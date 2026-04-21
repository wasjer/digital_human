"""end_session(wait_async=True) 必须阻塞到 L2 / soul_update 完成。

默认 wait_async=False 保持原有 daemon 异步行为；benchmark / 离线任务
显式传 True，避免主进程退出时 daemon 线程被 kill。
"""
import threading
import time
from unittest.mock import patch

from core import dialogue


def test_wait_async_true_blocks_until_l2_done(tmp_path, monkeypatch):
    """wait_async=True 时：end_session 直到 check_and_generate_patterns 返回才退出。"""
    # 不实际写盘，_end_session_sync 的 IO 全部打桩
    monkeypatch.setattr(dialogue, "_end_session_sync",
                        lambda a, h: ("session text", "sid-1", []))

    l2_started_at = {}
    l2_done_at = {}

    def slow_l2(agent_id):
        l2_started_at["t"] = time.monotonic()
        time.sleep(0.3)
        l2_done_at["t"] = time.monotonic()

    with patch("core.dialogue.update_elastic"), \
         patch("core.dialogue.chat_completion", return_value='{"is_evidence": false}'), \
         patch("core.dialogue.check_slow_change", return_value=[]), \
         patch("core.memory_l2.check_and_generate_patterns", side_effect=slow_l2), \
         patch("core.memory_l2.contribute_to_soul"):
        t0 = time.monotonic()
        dialogue.end_session("agent_x", [], wait_async=True)
        t1 = time.monotonic()

    # L2 至少跑完了
    assert "t" in l2_done_at, "check_and_generate_patterns 没被调用"
    # end_session 返回时间晚于 L2 完成时间（等了异步线程）
    assert t1 >= l2_done_at["t"], \
        f"end_session 应等到 L2 完成；实际 return={t1:.3f} L2_done={l2_done_at['t']:.3f}"
    # 确实有阻塞（至少 0.25s）
    assert t1 - t0 >= 0.25


def test_wait_async_false_returns_immediately(tmp_path, monkeypatch):
    """默认 wait_async=False：end_session 立即返回，异步还在后台跑。"""
    monkeypatch.setattr(dialogue, "_end_session_sync",
                        lambda a, h: ("session text", "sid-1", []))

    l2_started = threading.Event()
    l2_can_finish = threading.Event()

    def blocking_l2(agent_id):
        l2_started.set()
        l2_can_finish.wait(timeout=2.0)

    with patch("core.dialogue.update_elastic"), \
         patch("core.dialogue.chat_completion", return_value='{"is_evidence": false}'), \
         patch("core.dialogue.check_slow_change", return_value=[]), \
         patch("core.memory_l2.check_and_generate_patterns", side_effect=blocking_l2), \
         patch("core.memory_l2.contribute_to_soul"):
        t0 = time.monotonic()
        dialogue.end_session("agent_x", [])
        t1 = time.monotonic()

        # 返回得很快（不等异步）
        assert t1 - t0 < 0.3, f"默认应立即返回，实际耗时 {t1-t0:.3f}s"
        # 异步其实还没完，放行
        l2_can_finish.set()
