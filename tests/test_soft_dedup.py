"""软惩罚去重：already_surfaced 的记忆被扣分而非硬过滤。"""
from datetime import datetime
from unittest.mock import MagicMock, patch

from core import retrieval


def _mk_row(eid, importance=0.5, vec=None):
    return {
        "event_id": eid, "vector": vec or [0.1] * 1024, "status": "active",
        "importance": importance, "created_at": "2026-04-20T00:00:00",
        "action": "", "actor": "", "context": "", "outcome": "",
        "emotion": "", "emotion_intensity": 0.3,
    }


def test_already_surfaced_is_scored_not_filtered():
    """已 surface 的事件也进入打分，只是分数被扣。"""
    rows = [_mk_row(f"e{i}", importance=0.5) for i in range(5)]

    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = rows

    with patch("core.retrieval.get_embedding", return_value=[0.1] * 1024), \
         patch("core.retrieval.get_soul_anchor", return_value=""), \
         patch("core.retrieval.read_global_state",
               return_value={"current_state": {"mood": "", "energy": "", "stress_level": 0.3}}), \
         patch("core.retrieval._get_table", return_value=tbl), \
         patch("core.retrieval.get_event"), \
         patch("core.retrieval.MemoryGraph") as mg, \
         patch("core.retrieval.increment_access_count"), \
         patch("core.memory_l2.get_patterns_for_retrieval", return_value=[]):
        mg.return_value.get_neighbors.return_value = []

        result = retrieval.retrieve("a1", "query", mode="dialogue",
                                    already_surfaced={"e0", "e1", "e2"})
    surfaced_ids = result["surfaced_ids"]
    assert len(surfaced_ids) == 5
    assert surfaced_ids[-3:] == ["e0", "e1", "e2"] or \
           set(surfaced_ids[-3:]) == {"e0", "e1", "e2"}


def test_high_relevance_surfaced_can_still_win():
    """importance 高很多的已 surface 记忆仍可排在前面。"""
    high = _mk_row("e_high", importance=0.95)
    low  = _mk_row("e_low",  importance=0.20)

    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = [high, low]

    with patch("core.retrieval.get_embedding", return_value=[0.1] * 1024), \
         patch("core.retrieval.get_soul_anchor", return_value=""), \
         patch("core.retrieval.read_global_state",
               return_value={"current_state": {"mood": "", "energy": "", "stress_level": 0.3}}), \
         patch("core.retrieval._get_table", return_value=tbl), \
         patch("core.retrieval.get_event"), \
         patch("core.retrieval.MemoryGraph") as mg, \
         patch("core.retrieval.increment_access_count"), \
         patch("core.memory_l2.get_patterns_for_retrieval", return_value=[]):
        mg.return_value.get_neighbors.return_value = []
        result = retrieval.retrieve("a1", "query", mode="dialogue",
                                    already_surfaced={"e_high"})

    assert result["surfaced_ids"][0] == "e_high"
