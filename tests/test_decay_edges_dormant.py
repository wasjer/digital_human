"""decay_edges：strength < 0.05 的边改为 dormant，不删除。"""
import sqlite3

from core.memory_graph import MemoryGraph, _get_conn


def _insert_edge(conn, agent_id, link_id, strength):
    conn.execute(
        """
        INSERT INTO memory_links
        (link_id, agent_id, source_event_id, target_event_id,
         strength, activation_count, created_at, status)
        VALUES (?, ?, ?, ?, ?, 0, '2026-04-01T00:00:00', 'active')
        """,
        (link_id, agent_id, "e-src", f"e-tgt-{link_id}", strength),
    )
    conn.commit()


def test_decay_edges_dormants_instead_of_deletes(tmp_path, monkeypatch):
    import core.memory_graph as mg
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    agent_id = "a1"
    (tmp_path / agent_id).mkdir()

    conn = _get_conn(agent_id)
    _insert_edge(conn, agent_id, "link-keep", 0.10)
    _insert_edge(conn, agent_id, "link-dormant", 0.05)
    _insert_edge(conn, agent_id, "link-already-low", 0.03)
    conn.close()

    result = MemoryGraph().decay_edges(agent_id)
    assert result["decayed"] == 1
    assert result["dormanted"] == 2
    conn = _get_conn(agent_id)
    rows = conn.execute(
        "SELECT link_id, status FROM memory_links WHERE agent_id = ?", (agent_id,)
    ).fetchall()
    conn.close()
    all_link_ids = {r["link_id"] for r in rows}
    assert all_link_ids == {"link-keep", "link-dormant", "link-already-low"}
    status_map = {r["link_id"]: r["status"] for r in rows}
    assert status_map["link-keep"] == "active"
    assert status_map["link-dormant"] == "dormant"
    assert status_map["link-already-low"] == "dormant"
