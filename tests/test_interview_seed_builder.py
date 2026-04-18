import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from core import interview_seed_builder as isb


def test_derive_agent_id_from_valid_filename():
    assert isb._derive_agent_id("txf-interview-cmo0d7li-2026-04-15.md") == "txf"
    assert isb._derive_agent_id("jacky_42-interview-abcd1234-2026-04-01.md") == "jacky_42"
    assert isb._derive_agent_id("interview_source/txf-interview-cmo0d7li-2026-04-15.md") == "txf"
    assert isb._derive_agent_id("/abs/path/txf-interview-cmo0d7li-2026-04-15.md") == "txf"


def test_derive_agent_id_invalid_filename_raises():
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("random.md")
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("txf-2026-04-15.md")
    with pytest.raises(ValueError, match="无法从文件名推导 agent_id"):
        isb._derive_agent_id("Txf-interview-xxx-2026-04-15.md")
