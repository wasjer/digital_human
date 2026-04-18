import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from core import interview_seed_builder as isb


_SAMPLE_MD = """---
session_id: abc123
user_id: uid0
status: COMPLETED
completed_at: 2026-04-15T19:30:52.964Z
modules_completed: [0, 2, 6]
interview_duration_minutes: 81
---

# 访谈记录

## 模块 0：开场

**小灵**

你好，我叫stone，很高兴认识你。请问你现在多大了？

**受访者**

我现在42岁了，在合肥做茶叶。

## 模块 2：人生十字路口

**小灵**

你有过十字路口的时刻吗？

**受访者**

30 岁左右接手了家里的茶叶生意。
"""


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


def test_parse_interview_md_frontmatter(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))

    assert parsed["agent_id"] == "txf"
    assert parsed["session_id"] == "abc123"
    assert parsed["completed_at"] == "2026-04-15T19:30:52.964Z"
    assert parsed["duration_minutes"] == 81
    assert parsed["modules_completed"] == [0, 2, 6]


def test_parse_interview_md_dialogue_text(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))

    assert "受访者" in parsed["dialogue_text"]
    assert "我现在42岁了" in parsed["dialogue_text"]
    assert "30 岁左右接手" in parsed["dialogue_text"]


def test_parse_interview_md_module_titles(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["module_titles"][0] == "开场"
    assert parsed["module_titles"][2] == "人生十字路口"
    assert 6 not in parsed["module_titles"]


def test_parse_interview_md_interviewer_name(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(_SAMPLE_MD, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["interviewer_name"] == "小灵"


def test_parse_interview_md_missing_interviewee_block_raises(tmp_path):
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text("---\nsession_id: x\n---\n# 无受访者块", encoding="utf-8")
    with pytest.raises(ValueError, match="受访者"):
        isb._parse_interview_md(str(p))


def test_parse_interview_md_bad_frontmatter_falls_back(tmp_path):
    md = _SAMPLE_MD.replace("completed_at: 2026-04-15T19:30:52.964Z\n", "")
    p = tmp_path / "txf-interview-abc123-2026-04-15.md"
    p.write_text(md, encoding="utf-8")
    parsed = isb._parse_interview_md(str(p))
    assert parsed["completed_at"]
    assert isinstance(parsed["completed_at"], str)
    assert parsed.get("completed_at_fallback") is True
