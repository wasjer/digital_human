import json
import logging
import re
from datetime import datetime
from pathlib import Path

import config
from core.llm_client import chat_completion
from core.global_state import init_global_state

logger = logging.getLogger("llm_client")

_AGENTS_DIR = Path(__file__).parent.parent / "data" / "agents"
_SEEDS_DIR  = Path(__file__).parent.parent / "data" / "seeds"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

CORES = ["emotion_core", "value_core", "goal_core", "relation_core"]

# 每个核心各区的字段映射
_CORE_FIELDS = {
    "emotion_core": {
        "constitutional": ["base_emotional_type"],
        "slow_change":    ["emotional_regulation_style"],
        "elastic":        ["current_emotional_state"],
    },
    "value_core": {
        "constitutional": ["moral_baseline"],
        "slow_change":    ["value_priority_order"],
        "elastic":        ["current_value_focus"],
    },
    "goal_core": {
        "constitutional": ["life_direction"],
        "slow_change":    ["mid_term_goals"],
        "elastic":        ["current_phase_goal"],
    },
    "relation_core": {
        "constitutional": ["attachment_style"],
        "slow_change":    ["key_relationships"],
        "elastic":        ["current_relation_state"],
    },
}


# ── Prompt 加载 ───────────────────────────────────────────────────────────────

def _load_prompt(filename: str) -> tuple[str, str]:
    """读取 prompts/ 文件，按 \\n---\\n 分割为 (system, user) 两部分。"""
    text = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()


_INIT_SYSTEM, _INIT_USER_TEMPLATE       = _load_prompt("soul_init.txt")
_CONFLICT_SYSTEM, _CONFLICT_USER_TEMPLATE = _load_prompt("soul_conflict_check.txt")

# soul_anchor.txt: 3 行，依次为核心标题、宪法字段、缓变字段的格式模板
_ANCHOR_LINES = (_PROMPTS_DIR / "soul_anchor.txt").read_text(encoding="utf-8").splitlines()
_ANCHOR_CORE_FMT  = _ANCHOR_LINES[0]   # 【{core}】
_ANCHOR_CONST_FMT = _ANCHOR_LINES[1]   #   宪法/{field}: {value}
_ANCHOR_SLOW_FMT  = _ANCHOR_LINES[2]   #   缓变/{field}: {value}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _agent_dir(agent_id: str) -> Path:
    d = _AGENTS_DIR / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _soul_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / "soul.json"


def _write_soul(agent_id: str, soul: dict) -> None:
    with open(_soul_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(soul, f, ensure_ascii=False, indent=2)


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return m.group(1) if m else text


def _now() -> str:
    return datetime.now().isoformat()


# ── Soul 结构构建 ──────────────────────────────────────────────────────────────

def _build_empty_soul(agent_id: str) -> dict:
    """构建所有值为 null 的完整 soul 骨架。"""
    soul: dict = {"agent_id": agent_id}
    for core in CORES:
        fields = _CORE_FIELDS[core]
        soul[core] = {
            "constitutional": {
                **{f: None for f in fields["constitutional"]},
                "locked": True,
                "source": "seed_parser",
                "confidence": None,
            },
            "slow_change": {
                f: {
                    "value": None,
                    "evidence_score": 0.0,
                    "evidence_decay_rate": config.SOUL_EVIDENCE_DECAY_RATE,
                    "evidence_log": [],
                    "change_threshold": 2.0,
                }
                for f in fields["slow_change"]
            },
            "elastic": {f: None for f in fields["elastic"]},
        }
    return soul


def _merge_llm_into_soul(soul: dict, llm: dict) -> dict:
    """将 LLM 输出合并进骨架，保留所有元数据默认值。"""
    for core in CORES:
        if core not in llm:
            continue
        lc = llm[core]
        sc = soul[core]

        # constitutional：合并内容字段 + confidence
        if "constitutional" in lc and isinstance(lc["constitutional"], dict):
            lcc = lc["constitutional"]
            for f in _CORE_FIELDS[core]["constitutional"]:
                if f in lcc and lcc[f] is not None:
                    sc["constitutional"][f] = lcc[f]
            if "confidence" in lcc and lcc["confidence"] is not None:
                sc["constitutional"]["confidence"] = lcc["confidence"]

        # slow_change：合并 value 字段
        if "slow_change" in lc and isinstance(lc["slow_change"], dict):
            for f in _CORE_FIELDS[core]["slow_change"]:
                if f not in lc["slow_change"]:
                    continue
                raw = lc["slow_change"][f]
                if isinstance(raw, dict) and "value" in raw:
                    sc["slow_change"][f]["value"] = raw["value"]
                elif raw is not None:
                    sc["slow_change"][f]["value"] = raw

        # elastic：直接合并
        if "elastic" in lc and isinstance(lc["elastic"], dict):
            for f in _CORE_FIELDS[core]["elastic"]:
                if f in lc["elastic"]:
                    sc["elastic"][f] = lc["elastic"][f]

    return soul


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def init_soul(agent_id: str) -> dict:
    """
    读取 seed.json，调用 LLM 生成 soul.json，
    同时创建 global_state.json / l2_patterns.json / l0_buffer.json。
    """
    seed_path = _SEEDS_DIR / agent_id / "seed.json"
    with open(seed_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    # 1. 调用 LLM
    messages = [
        {"role": "system", "content": _INIT_SYSTEM},
        {"role": "user", "content": _INIT_USER_TEMPLATE.format(
            seed_json=json.dumps(seed, ensure_ascii=False, indent=2)
        )},
    ]
    raw = chat_completion(messages, max_tokens=2048, temperature=0.2)

    try:
        llm_data = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"init_soul agent_id={agent_id} json_parse_error={e} raw={raw[:200]}")
        llm_data = {}

    # 2. 合并进骨架（保证结构完整）
    soul = _build_empty_soul(agent_id)
    soul = _merge_llm_into_soul(soul, llm_data)
    _write_soul(agent_id, soul)
    logger.info(f"init_soul agent_id={agent_id} soul written")

    # 3. global_state.json
    init_global_state(agent_id)

    # 4. l2_patterns.json
    d = _agent_dir(agent_id)
    with open(d / "l2_patterns.json", "w", encoding="utf-8") as f:
        json.dump([], f)

    # 5. l0_buffer.json
    l0 = {
        "agent_id": agent_id,
        "session_id": None,
        "created_at": None,
        "ttl_hours": 24,
        "raw_dialogue": [],
        "emotion_snapshots": [],
        "working_context": {
            "current_task": None,
            "active_goals": [],
            "temporary_facts": [],
            "attention_focus": None,
        },
        "status": "simplified",
    }
    with open(d / "l0_buffer.json", "w", encoding="utf-8") as f:
        json.dump(l0, f, ensure_ascii=False, indent=2)

    logger.info(f"init_soul agent_id={agent_id} all files created")
    return soul


def read_soul(agent_id: str) -> dict:
    with open(_soul_path(agent_id), "r", encoding="utf-8") as f:
        return json.load(f)


def update_elastic(agent_id: str, core: str, field: str, value) -> None:
    """更新弹性区字段。"""
    soul = read_soul(agent_id)
    soul[core]["elastic"][field] = value
    _write_soul(agent_id, soul)
    logger.info(f"update_elastic agent_id={agent_id} {core}.elastic.{field}")


def add_evidence(agent_id: str, core: str, field: str, score: float,
                 reason: str, session_id: str) -> None:
    """向缓变区字段追加证据分。"""
    soul = read_soul(agent_id)
    entry = soul[core]["slow_change"][field]
    entry["evidence_score"] = entry.get("evidence_score", 0.0) + score
    entry["evidence_log"].append({
        "timestamp": _now(),
        "session_id": session_id,
        "score_delta": score,
        "reason": reason,
    })
    _write_soul(agent_id, soul)
    logger.info(f"add_evidence agent_id={agent_id} {core}.{field} score+={score}")


def decay_evidence(agent_id: str) -> None:
    """所有缓变区 evidence_score *= SOUL_EVIDENCE_DECAY_RATE。"""
    soul = read_soul(agent_id)
    rate = config.SOUL_EVIDENCE_DECAY_RATE
    for core in CORES:
        for field_data in soul[core]["slow_change"].values():
            field_data["evidence_score"] = field_data.get("evidence_score", 0.0) * rate
    _write_soul(agent_id, soul)
    logger.info(f"decay_evidence agent_id={agent_id} rate={rate}")


def check_slow_change(agent_id: str) -> list:
    """返回 evidence_score > change_threshold 的字段列表。"""
    soul = read_soul(agent_id)
    result = []
    for core in CORES:
        for field, data in soul[core]["slow_change"].items():
            if data.get("evidence_score", 0.0) > data.get("change_threshold", 2.0):
                result.append({"core": core, "field": field,
                                "evidence_score": data["evidence_score"],
                                "current_value": data.get("value")})
    logger.info(f"check_slow_change agent_id={agent_id} triggered={len(result)}")
    return result


def apply_slow_change(agent_id: str, core: str, field: str, new_value) -> None:
    """更新缓变区值，重置 evidence_score，记录变更日志。"""
    soul = read_soul(agent_id)
    entry = soul[core]["slow_change"][field]
    old_value = entry.get("value")
    old_score = entry.get("evidence_score", 0.0)
    entry["value"] = new_value
    entry["evidence_score"] = 0.0
    entry["evidence_log"].append({
        "timestamp": _now(),
        "event": "apply_slow_change",
        "old_value": old_value,
        "new_value": new_value,
        "evidence_score_at_change": old_score,
    })
    _write_soul(agent_id, soul)
    logger.info(f"apply_slow_change agent_id={agent_id} {core}.{field}: {old_value!r} -> {new_value!r}")


def check_constitutional_conflict(agent_id: str, content: str) -> dict:
    """调用 LLM 判断 content 是否违反宪法区，返回冲突信息。"""
    anchor = get_soul_anchor(agent_id)
    messages = [
        {"role": "system", "content": _CONFLICT_SYSTEM},
        {"role": "user", "content": _CONFLICT_USER_TEMPLATE.format(
            anchor=anchor, content=content
        )},
    ]
    raw = chat_completion(messages, max_tokens=256, temperature=0.1)
    default = {"conflict": False, "reason": "", "conflicting_core": None}
    try:
        result = json.loads(_strip_json(raw))
        default.update(result)
    except json.JSONDecodeError as e:
        logger.error(f"check_constitutional_conflict parse_error={e}")
    logger.info(f"check_constitutional_conflict agent_id={agent_id} conflict={default['conflict']}")
    return default


def get_soul_anchor(agent_id: str) -> str:
    """
    返回所有核心宪法区+缓变区的摘要文本，控制在 SOUL_ANCHOR_MAX_TOKENS 以内，中文。
    使用字符预算（4字符 ≈ 1 token）近似控制长度。
    """
    soul = read_soul(agent_id)
    char_budget = config.SOUL_ANCHOR_MAX_TOKENS * 4
    lines = []
    for core in CORES:
        core_lines = [_ANCHOR_CORE_FMT.format(core=core)]
        c = soul[core]["constitutional"]
        for f in _CORE_FIELDS[core]["constitutional"]:
            core_lines.append(_ANCHOR_CONST_FMT.format(field=f, value=c.get(f)))
        sc = soul[core]["slow_change"]
        for f in _CORE_FIELDS[core]["slow_change"]:
            core_lines.append(_ANCHOR_SLOW_FMT.format(field=f, value=sc[f].get("value")))
        lines.extend(core_lines)

    full = "\n".join(lines)
    if len(full) > char_budget:
        full = full[:char_budget] + "..."
    return full


def get_value_core_constitutional(agent_id: str) -> str:
    """返回 value_core 宪法区内容，中文文本。"""
    soul = read_soul(agent_id)
    c = soul["value_core"]["constitutional"]
    parts = []
    for f in _CORE_FIELDS["value_core"]["constitutional"]:
        parts.append(f"{f}: {c.get(f)}")
    return "\n".join(parts)
