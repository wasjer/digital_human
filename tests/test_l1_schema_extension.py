import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.memory_l1 import _l1_schema, _get_table


def test_l1_schema_contains_raw_quote_and_event_kind():
    schema = _l1_schema()
    names = {f.name for f in schema}
    assert "raw_quote" in names, "schema 应包含 raw_quote 字段"
    assert "event_kind" in names, "schema 应包含 event_kind 字段"


def test_l1_table_accepts_new_fields(tmp_path, monkeypatch):
    from core import memory_l1
    monkeypatch.setattr(memory_l1, "_AGENTS_DIR", tmp_path / "agents")

    tbl = _get_table("test_agent_schema")
    row = {name: _default_for(field) for name, field in zip(
        (f.name for f in _l1_schema()), _l1_schema()
    )}
    row["raw_quote"] = "I don't really care about being right."
    row["event_kind"] = "conversation"
    tbl.add([row])

    rows = tbl.search().where("event_id = 'ev_test_1'").limit(1).to_list()
    assert rows and rows[0]["raw_quote"].startswith("I don't")
    assert rows[0]["event_kind"] == "conversation"


def _default_for(field):
    import pyarrow as pa
    t = field.type
    if pa.types.is_list(t) or pa.types.is_fixed_size_list(t):
        return [0.0] * 1024
    if pa.types.is_floating(t):
        return 0.0
    if pa.types.is_integer(t):
        return 0
    return "ev_test_1" if field.name == "event_id" else ""
