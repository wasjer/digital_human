import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.soul import CORES, _CORE_FIELDS, _build_empty_soul


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
