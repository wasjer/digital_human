import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import inspect
from core import memory_l2


def test_check_and_generate_patterns_has_include_all_statuses_param():
    sig = inspect.signature(memory_l2.check_and_generate_patterns)
    assert "include_all_statuses" in sig.parameters
    assert sig.parameters["include_all_statuses"].default is False


def test_fetch_all_events_exists_and_callable():
    assert hasattr(memory_l2, "_fetch_all_events")
    assert callable(memory_l2._fetch_all_events)


def test_fetch_all_events_returns_list_when_no_table(tmp_path, monkeypatch):
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path / "agents")
    result = memory_l2._fetch_all_events("nonexistent_agent")
    assert result == []
