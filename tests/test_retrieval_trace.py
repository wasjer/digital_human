"""验证 retrieve() 在激活 trace 时 emit 各阶段事件。"""
from unittest.mock import patch, MagicMock
from core import trace


@patch("core.memory_l2.get_patterns_for_retrieval")
@patch("core.retrieval._get_table")
@patch("core.retrieval.MemoryGraph")
@patch("core.retrieval.get_event")
@patch("core.retrieval.read_global_state")
@patch("core.retrieval.get_soul_anchor")
@patch("core.retrieval.get_embedding")
def test_retrieve_emits_stage_events(
    mock_emb, mock_anchor, mock_state, mock_get_event, mock_graph_cls, mock_get_table, mock_l2
):
    mock_emb.return_value = [0.1] * 1024
    mock_anchor.return_value = "anchor"
    mock_state.return_value = {"current_state": {"mood": "ok", "energy": "high", "stress_level": 0.3}}
    mock_l2.return_value = []

    # 向量召回 2 条
    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
        {"event_id": "e1", "vector": [0.1] * 1024, "status": "active",
         "importance": 0.8, "created_at": "2026-04-20T00:00:00",
         "action": "", "actor": "", "context": "", "outcome": "", "emotion": "", "emotion_intensity": 0.2},
        {"event_id": "e2", "vector": [0.1] * 1024, "status": "active",
         "importance": 0.5, "created_at": "2026-04-19T00:00:00",
         "action": "", "actor": "", "context": "", "outcome": "", "emotion": "", "emotion_intensity": 0.1},
    ]
    mock_get_table.return_value = tbl

    graph = MagicMock()
    graph.get_neighbors.return_value = [{"event_id": "e3"}]
    mock_graph_cls.return_value = graph
    mock_get_event.return_value = {
        "event_id": "e3", "status": "active", "vector": [0.1] * 1024,
        "importance": 0.3, "created_at": "2026-04-18T00:00:00",
        "action": "", "actor": "", "context": "", "outcome": "", "emotion": "", "emotion_intensity": 0.0,
    }

    from core.retrieval import retrieve
    with trace.turn("agent_x", "q") as t:
        retrieve("agent_x", "query text", mode="dialogue")
        trace.mark("记忆检索")

    kinds = [e["kind"] for e in t.steps[0].events]
    # get_embedding is mocked, so its "embedding" event does NOT fire.
    # retrieve() itself emits "embedding_stage" to capture the stage.
    assert "embedding_stage" in kinds
    assert "vector_search" in kinds
    assert "graph_expand" in kinds
    assert "score_rerank" in kinds

    vs = next(e for e in t.steps[0].events if e["kind"] == "vector_search")
    assert vs["raw_hits"] == 2
    assert vs["after_dedup"] == 2

    ge = next(e for e in t.steps[0].events if e["kind"] == "graph_expand")
    assert ge["neighbors_added"] >= 0

    rr = next(e for e in t.steps[0].events if e["kind"] == "score_rerank")
    assert "weights" in rr
    assert rr["top_k_returned"] <= 8
