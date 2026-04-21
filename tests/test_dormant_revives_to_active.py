"""dormant 事件满足条件后直接 revive 到 active（节点状态机）。
边不再有状态，邻居查询只按 strength 过滤。"""
from unittest.mock import MagicMock, patch

from core.memory_graph import MemoryGraph


def _mk_tbl_returning(dormant_rows, neighbor_rows_by_id):
    tbl = MagicMock()
    def where_handler(clause):
        search = MagicMock()
        if "status = 'dormant'" in clause:
            search.limit.return_value.to_list.return_value = dormant_rows
        else:
            import re
            m = re.search(r"event_id = '([^']+)'", clause)
            nid = m.group(1) if m else ""
            search.limit.return_value.to_list.return_value = neighbor_rows_by_id.get(nid, [])
        return search
    tbl.search.return_value.where.side_effect = where_handler
    return tbl


def test_revival_uses_active_not_revived(tmp_path, monkeypatch):
    import core.memory_graph as mg
    monkeypatch.setattr(mg, "_AGENTS_DIR", tmp_path)
    (tmp_path / "a1").mkdir()

    dormant_rows = [{"event_id": "d1"}]
    neighbors_available = {
        "n1": [{"event_id": "n1"}],
        "n2": [{"event_id": "n2"}],
        "n3": [{"event_id": "n3"}],
    }

    fake_tbl = _mk_tbl_returning(dormant_rows, neighbors_available)

    conn = mg._get_conn("a1")
    for i, nid in enumerate(["n1", "n2", "n3"]):
        conn.execute(
            "INSERT INTO memory_links (link_id, agent_id, source_event_id, target_event_id, "
            "strength, activation_count, created_at) "
            "VALUES (?, ?, ?, ?, 0.5, 1, '2026-04-01T00:00:00')",
            (f"l{i}", "a1", "d1", nid),
        )
    conn.commit()
    conn.close()

    statuses_set = []
    def capture_status(agent_id, event_id, status):
        statuses_set.append(status)

    with patch("core.memory_graph._get_table", return_value=fake_tbl), \
         patch("core.memory_graph.update_event_status", side_effect=capture_status):
        revived = MemoryGraph().check_dormant_revival("a1")

    assert revived == ["d1"]
    assert statuses_set == ["active"], \
        f"revival must set status to 'active', got {statuses_set}"
