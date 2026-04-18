"""
interview_seed_builder.py

从 interview_source/<prefix>-interview-...md（访谈 Q&A）一键构建 digital_human agent：
seed.json（带 confidence 审计）+ soul.json（>=0.5 阈值）+ L1（biography + meta）+
L2（include_all_statuses）+ L0 recent_self_narrative + build_report.md。

与 seed_memory_loader.py / nuwa_seed_builder.py 平级，互不干扰。

直接运行：
  python core/interview_seed_builder.py interview_source/txf-interview-cmo0d7li-2026-04-15.md
  python core/interview_seed_builder.py <md> --force
  python core/interview_seed_builder.py <md> --agent-id custom_id
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import logging
import re
import shutil
from datetime import datetime

import config

logger = logging.getLogger("interview_seed_builder")

_PROJECT_ROOT   = Path(__file__).parent.parent
_INTERVIEW_DIR  = _PROJECT_ROOT / "interview_source"
_AGENTS_DIR     = _PROJECT_ROOT / "data" / "agents"
_SEEDS_DIR      = _PROJECT_ROOT / "data" / "seeds"
_PROMPTS_DIR    = _PROJECT_ROOT / "prompts"

_FILENAME_RE = re.compile(
    r"^([a-z0-9_]+)-interview-[a-z0-9]+-\d{4}-\d{2}-\d{2}\.md$"
)


def _derive_agent_id(md_path: str) -> str:
    """从文件名 `<prefix>-interview-<session>-<date>.md` 抠出 <prefix> 作为 agent_id。"""
    name = Path(md_path).name
    m = _FILENAME_RE.match(name)
    if not m:
        raise ValueError(
            f"无法从文件名推导 agent_id：{name}。"
            f"期望模式 `<prefix>-interview-<session>-YYYY-MM-DD.md`（prefix 小写/数字/下划线）。"
            f"如需强制指定请使用 --agent-id 参数。"
        )
    return m.group(1)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_MODULE_HEADING_RE = re.compile(r"^##\s*模块\s*(\d+)\s*[:：]\s*(.+?)\s*$", re.MULTILINE)
_INTERVIEWEE_BLOCK_RE = re.compile(r"\*\*受访者\*\*")
_SPEAKER_BLOCK_RE = re.compile(r"^\*\*([^\*\n]+?)\*\*\s*$", re.MULTILINE)


def _parse_yaml_lite(text: str) -> dict:
    """轻量 YAML 解析：只处理 `key: value` 和 `key: [a, b, c]` 形式。"""
    data: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key   = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items: list = []
            if inner:
                for tok in inner.split(","):
                    tok = tok.strip()
                    if tok.isdigit() or (tok.startswith("-") and tok[1:].isdigit()):
                        items.append(int(tok))
                    else:
                        items.append(tok.strip("'\""))
            data[key] = items
        elif value.isdigit():
            data[key] = int(value)
        else:
            data[key] = value.strip("'\"")
    return data


def _parse_interview_md(md_path: str) -> dict:
    """
    解析访谈 md，返回 dict：
      agent_id, session_id, completed_at, completed_at_fallback,
      duration_minutes, modules_completed (list[int]),
      module_titles (dict[int, str]), interviewer_name,
      dialogue_text (全文含访谈员+受访者 blocks)
    """
    path = Path(md_path)
    raw  = path.read_text(encoding="utf-8")
    agent_id = _derive_agent_id(str(path))

    fm_match = _FRONTMATTER_RE.match(raw)
    fm_data: dict = {}
    if fm_match:
        fm_data = _parse_yaml_lite(fm_match.group(1))
    body = raw[fm_match.end():] if fm_match else raw

    completed_at          = fm_data.get("completed_at")
    completed_at_fallback = False
    if not completed_at:
        logger.warning(f"_parse_interview_md missing completed_at, falling back to now() for {path.name}")
        completed_at = datetime.now().isoformat()
        completed_at_fallback = True

    modules_completed = fm_data.get("modules_completed") or []
    if isinstance(modules_completed, list):
        modules_completed = [int(x) if not isinstance(x, int) else x for x in modules_completed]

    if not _INTERVIEWEE_BLOCK_RE.search(body):
        raise ValueError(f"访谈 md 里找不到 '**受访者**' 块：{path.name}")

    module_titles: dict[int, str] = {}
    for m in _MODULE_HEADING_RE.finditer(body):
        module_titles[int(m.group(1))] = m.group(2).strip()

    interviewer_name = "访谈员"
    for m in _SPEAKER_BLOCK_RE.finditer(body):
        candidate = m.group(1).strip()
        if candidate and candidate != "受访者":
            interviewer_name = candidate
            break

    return {
        "agent_id":              agent_id,
        "session_id":            fm_data.get("session_id", ""),
        "completed_at":          completed_at,
        "completed_at_fallback": completed_at_fallback,
        "duration_minutes":      int(fm_data.get("interview_duration_minutes") or 0),
        "modules_completed":     modules_completed,
        "module_titles":         module_titles,
        "interviewer_name":      interviewer_name,
        "dialogue_text":         body.strip(),
    }
