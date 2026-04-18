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


def _gate(node, threshold: float | None = None):
    """
    LLM 输出 {"value": ..., "confidence": ...} → 过阈值则原值，否则 None。

    - value 为 None 时一律 None（无论 confidence 多高）
    - confidence 非数字 / 缺失 一律视作 0
    """
    if threshold is None:
        threshold = config.INTERVIEW_CONFIDENCE_THRESHOLD
    if not isinstance(node, dict):
        return None
    value = node.get("value")
    if value is None:
        return None
    conf = node.get("confidence")
    if not isinstance(conf, (int, float)):
        return None
    return value if conf >= threshold else None


def _year_from_iso(ts: str) -> int:
    try:
        return int(ts[:4])
    except Exception:
        return datetime.now().year


def _month_from_iso(ts: str) -> int:
    try:
        return int(ts[5:7])
    except Exception:
        return 0


def _build_meta_event(parsed: dict, agent_name: str) -> dict:
    """
    用访谈 frontmatter 确定性构造一条 L1 meta 事件（无 LLM）。
    该事件让 agent "知道"自己是通过一次访谈被唤醒的，利于连续性叙事。
    """
    duration = parsed.get("duration_minutes") or 0
    modules  = parsed.get("modules_completed") or []
    titles   = parsed.get("module_titles") or {}
    interviewer = parsed.get("interviewer_name") or "访谈员"

    ordered_titles = [
        titles.get(mod_id) or f"模块 {mod_id}"
        for mod_id in modules
    ]
    modules_text = "、".join(ordered_titles) if ordered_titles else "多个话题"

    return {
        "actor":              agent_name,
        "action":             "参加了一次关于人生经历的深度访谈",
        "context":            f"在一个对话式访谈系统里和访谈员'{interviewer}'聊了约 {duration} 分钟",
        "outcome":            f"按顺序聊了 {len(modules)} 个模块：{modules_text}",
        "scene_location":     "家中/线上对话",
        "scene_atmosphere":   "安静、回顾式",
        "scene_sensory_notes":"",
        "scene_subjective_experience": "一次难得的对自己经历的系统梳理",
        "emotion":            "平静、略带回顾感",
        "emotion_intensity":  0.3,
        "importance":         0.6,
        "emotion_intensity_score": 0.3,
        "value_relevance_score":   0.5,
        "novelty_score":           0.7,
        "reusability_score":       0.4,
        "tags_time_year":     _year_from_iso(parsed.get("completed_at", "")),
        "tags_time_month":    _month_from_iso(parsed.get("completed_at", "")),
        "tags_time_week":     0,
        "tags_time_period_label": "近期",
        "tags_people":            [interviewer],
        "tags_topic":             ["访谈", "自我叙述"],
        "tags_emotion_valence":   "中性",
        "tags_emotion_label":     "回顾",
        "inferred_timestamp":     parsed.get("completed_at", ""),
        "raw_quote":              None,
        "event_kind":             "meta",
        "source":                 "interview_meta",
    }
