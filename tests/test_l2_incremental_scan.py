"""_fetch_archived_events 增量扫描：仅扫 last_l2_scan_at 之后的事件。"""
from unittest.mock import MagicMock, patch

from core import memory_l2


def test_fetch_archived_uses_last_scan_filter():
    mock_tbl = MagicMock()
    mock_tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = []

    with patch("core.memory_l1._get_table", return_value=mock_tbl), \
         patch("core.memory_l2._read_last_scan_at", return_value="2026-04-10T00:00:00"):
        memory_l2._fetch_archived_events("a1")

    where_call = mock_tbl.search.return_value.where.call_args
    query_str = where_call[0][0]
    assert "status = 'archived'" in query_str
    assert "created_at > '2026-04-10T00:00:00'" in query_str


def test_fetch_archived_without_last_scan_full_scan():
    mock_tbl = MagicMock()
    mock_tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = []

    with patch("core.memory_l1._get_table", return_value=mock_tbl), \
         patch("core.memory_l2._read_last_scan_at", return_value=None):
        memory_l2._fetch_archived_events("a1")

    query_str = mock_tbl.search.return_value.where.call_args[0][0]
    assert "status = 'archived'" in query_str
    assert "created_at >" not in query_str


def test_check_and_generate_patterns_updates_last_scan_at(monkeypatch):
    """即使无事件，也应更新 last_l2_scan_at 防止重扫。"""
    monkeypatch.setattr(memory_l2, "_fetch_archived_events", lambda a: [])
    calls = {}
    monkeypatch.setattr(memory_l2, "_write_last_scan_at",
                        lambda aid, ts: calls.setdefault("ts", ts))
    memory_l2.check_and_generate_patterns("a1")
    assert "ts" in calls
