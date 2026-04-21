"""strengthen_links_on_retrieval 冷却：24h/3, 7d/10, 30d/20 上限。"""
import json
from datetime import datetime, timedelta

import core.memory_graph as mg


def _iso(dt):
    return dt.isoformat()


def _insert_edge_with_history(conn, agent_id, link_id, history_timestamps):
    conn.execute(
        "INSERT INTO memory_links (link_id, agent_id, source_event_id, target_event_id, "
        "strength, activation_count, created_at, status, strengthen_history) "
        "VALUES (?, ?, ?, ?, 0.5, 0, ?, 'active', ?)",
        (link_id, agent_id, "A", "B", _iso(datetime.now() - timedelta(days=50)),
         json.dumps(history_timestamps)),
    )
    conn.commit()


def test_cooldown_blocks_when_24h_cap_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a1").mkdir()
    conn = mg._get_conn("a1")
    now = datetime.now()
    history = [_iso(now - timedelta(hours=i)) for i in (1, 5, 10)]
    _insert_edge_with_history(conn, "a1", "L", history)
    conn.close()

    g = mg.MemoryGraph()
    g.strengthen_links_on_retrieval("a1", ["A", "B"])
    conn = mg._get_conn("a1")
    row = conn.execute(
        "SELECT strength, strengthen_history FROM memory_links WHERE link_id = 'L'"
    ).fetchone()
    conn.close()
    assert abs(row["strength"] - 0.5) < 1e-6, f"strength should not change, got {row['strength']}"
    hist = json.loads(row["strengthen_history"])
    assert len(hist) == 3, f"history length should stay 3, got {len(hist)}"


def test_no_cap_reached_still_strengthens(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a2").mkdir()
    conn = mg._get_conn("a2")
    _insert_edge_with_history(conn, "a2", "L2", [])
    conn.close()

    g = mg.MemoryGraph()
    g.strengthen_links_on_retrieval("a2", ["A", "B"])
    conn = mg._get_conn("a2")
    row = conn.execute(
        "SELECT strength, strengthen_history FROM memory_links WHERE link_id = 'L2'"
    ).fetchone()
    conn.close()
    assert row["strength"] > 0.5
    hist = json.loads(row["strengthen_history"])
    assert len(hist) == 1
