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
