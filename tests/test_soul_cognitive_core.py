import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.soul import CORES, _CORE_FIELDS, _build_empty_soul
from core.soul import _write_soul, _build_empty_soul, get_soul_anchor


def test_cognitive_core_in_cores_list():
    assert "cognitive_core" in CORES
    assert CORES[-1] == "cognitive_core"


def test_cognitive_core_field_layout():
    fields = _CORE_FIELDS["cognitive_core"]
    assert set(fields["constitutional"]) == {
        "mental_models", "decision_heuristics",
        "expression_dna", "expression_exemplars",
        "anti_patterns", "self_awareness", "honest_boundaries",
    }
    assert fields["slow_change"] == []
    assert fields["elastic"] == []


def test_build_empty_soul_includes_cognitive_core():
    soul = _build_empty_soul("agent_x")
    assert "cognitive_core" in soul
    c = soul["cognitive_core"]["constitutional"]
    for f in ["mental_models", "decision_heuristics", "expression_dna",
              "expression_exemplars", "anti_patterns", "self_awareness",
              "honest_boundaries"]:
        assert f in c and c[f] is None
    assert c["locked"] is True
    assert soul["cognitive_core"]["slow_change"] == {}
    assert soul["cognitive_core"]["elastic"] == {}


def test_get_soul_anchor_renders_list_fields(tmp_path, monkeypatch):
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")

    s = _build_empty_soul("ag_anchor")
    s["cognitive_core"]["constitutional"]["mental_models"] = [
        {"name": "聚焦即说不", "one_liner": "对其他一百个好主意说 No"},
        {"name": "连点成线", "one_liner": "人生只能回溯理解"},
    ]
    s["cognitive_core"]["constitutional"]["decision_heuristics"] = [
        {"rule": "先做减法"}, {"rule": "不问用户要什么"},
    ]
    s["cognitive_core"]["constitutional"]["expression_exemplars"] = [
        "Stay Hungry. Stay Foolish.",
        "This is shit. A bozo product.",
    ]
    _write_soul("ag_anchor", s)

    text = get_soul_anchor("ag_anchor")
    assert "cognitive_core" in text
    assert "聚焦即说不" in text
    assert "先做减法" in text
    assert "Stay Hungry" in text


def test_get_soul_anchor_renders_dict_fields(tmp_path, monkeypatch):
    from core import soul as soul_mod
    monkeypatch.setattr(soul_mod, "_AGENTS_DIR", tmp_path / "agents")

    s = _build_empty_soul("ag_anchor_d")
    s["cognitive_core"]["constitutional"]["expression_dna"] = {
        "sentence_style": "短句为主",
        "rhythm": "先结论后铺垫",
    }
    _write_soul("ag_anchor_d", s)

    text = get_soul_anchor("ag_anchor_d")
    assert "短句为主" in text
