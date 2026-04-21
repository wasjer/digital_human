"""decay_edges：strength × decay_rate，保留所有边（不删除、不切换状态）。"""
from core.memory_graph import MemoryGraph, _get_conn


def _insert_edge(conn, agent_id, link_id, strength):
    conn.execute(
        """
        INSERT INTO memory_links
        (link_id, agent_id, source_event_id, target_event_id,
         strength, activation_count, created_at)
        VALUES (?, ?, ?, ?, ?, 0, '2026-04-01T00:00:00')
        """,
        (link_id, agent_id, "e-src", f"e-tgt-{link_id}", strength),
    )
    conn.commit()


def test_decay_edges_multiplies_strength(tmp_path, monkeypatch):
    import config
    import core.memory_graph as mg
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    agent_id = "a1"
    (tmp_path / agent_id).mkdir()

    conn = _get_conn(agent_id)
    _insert_edge(conn, agent_id, "link-hi", 0.80)
    _insert_edge(conn, agent_id, "link-mid", 0.30)
    _insert_edge(conn, agent_id, "link-low", 0.03)
    conn.close()

    result = MemoryGraph().decay_edges(agent_id)
    assert result == {"decayed": 3}

    conn = _get_conn(agent_id)
    rows = dict(conn.execute(
        "SELECT link_id, strength FROM memory_links WHERE agent_id = ?", (agent_id,)
    ).fetchall())
    conn.close()

    rate = config.GRAPH_EDGE_DECAY_RATE
    assert abs(rows["link-hi"] - 0.80 * rate) < 1e-6
    assert abs(rows["link-mid"] - 0.30 * rate) < 1e-6
    assert abs(rows["link-low"] - 0.03 * rate) < 1e-6
