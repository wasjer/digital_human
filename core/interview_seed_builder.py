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
from core.llm_client import chat_completion, get_embedding
from core.soul import _build_empty_soul, _write_soul, _CORE_FIELDS, CORES

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


def _normalize_iso_timestamp(ts: str) -> str:
    """把 `2026-04-15T19:30:52.964Z` 归一为 `_days_since` 能解析的朴素 ISO。

    去掉 `Z`/`+00:00` 时区后缀和毫秒，保证 datetime.fromisoformat 可读。
    解析失败返回原字符串。
    """
    if not ts:
        return ts
    try:
        cleaned = ts.rstrip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1]
        if "+" in cleaned[10:]:
            cleaned = cleaned[: 10 + cleaned[10:].index("+")]
        if "." in cleaned:
            cleaned = cleaned.split(".", 1)[0]
        datetime.fromisoformat(cleaned)
        return cleaned
    except Exception:
        return ts


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
        "inferred_timestamp":     _normalize_iso_timestamp(parsed.get("completed_at", "")),
        "raw_quote":              None,
        "event_kind":             "meta",
        "source":                 "interview_meta",
    }


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _call_llm_for_seed(parsed: dict) -> dict:
    """LLM pass 1: 访谈 → 带 confidence 的结构化 seed + recent_self_narrative + follow_up_questions。"""
    template = _load_prompt("interview_to_seed.txt")
    user = template.format(
        agent_id         = parsed["agent_id"],
        interview_date   = parsed["completed_at"],
        duration_minutes = parsed["duration_minutes"],
        dialogue_text    = parsed["dialogue_text"],
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )
    try:
        data = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_call_llm_for_seed json parse error={e} raw={raw[:400]}")
        raise
    if not isinstance(data, dict):
        raise ValueError(f"_call_llm_for_seed expected dict, got {type(data)}")
    return data


def _call_llm_for_l1_events(parsed: dict, agent_name: str, current_age: int) -> list[dict]:
    """LLM pass 2: 访谈 → biography L1 事件列表。"""
    template = _load_prompt("interview_to_l1.txt")
    user = template.format(
        agent_name     = agent_name,
        interview_date = parsed["completed_at"],
        current_age    = current_age,
        dialogue_text  = parsed["dialogue_text"],
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )
    try:
        events = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_call_llm_for_l1_events json parse error={e} raw={raw[:400]}")
        raise
    if not isinstance(events, list):
        raise ValueError(f"_call_llm_for_l1_events expected list, got {type(events)}")
    for ev in events:
        ev.setdefault("source", "interview")
        ev.setdefault("event_kind", "biography")
    return events


def _build_soul_from_gated_seed(agent_id: str, raw_seed: dict) -> dict:
    """
    raw_seed 是 LLM pass 1 的原始输出（带 confidence）。
    按 _CORE_FIELDS 映射到 soul 三区，confidence < threshold 的字段 → None。
    返回构造好的 soul dict（未写盘）。
    """
    soul = _build_empty_soul(agent_id)

    for core in ["emotion_core", "value_core", "goal_core", "relation_core"]:
        raw_core = raw_seed.get(core) or {}
        sc       = soul[core]
        fields   = _CORE_FIELDS[core]

        for f in fields["constitutional"]:
            sc["constitutional"][f] = _gate(raw_core.get(f))
        main_const_field = fields["constitutional"][0] if fields["constitutional"] else None
        if main_const_field:
            raw_field = raw_core.get(main_const_field) or {}
            sc["constitutional"]["confidence"] = raw_field.get("confidence") if isinstance(raw_field, dict) else None
        sc["constitutional"]["source"] = "interview"

        for f in fields["slow_change"]:
            sc["slow_change"][f]["value"] = _gate(raw_core.get(f))

        for f in fields["elastic"]:
            sc["elastic"][f] = _gate(raw_core.get(f))

    cog_raw   = raw_seed.get("cognitive_core") or {}
    cog_const = soul["cognitive_core"]["constitutional"]
    conf_detail: dict = {}
    for f in _CORE_FIELDS["cognitive_core"]["constitutional"]:
        raw_field = cog_raw.get(f)
        cog_const[f] = _gate(raw_field)
        if isinstance(raw_field, dict) and isinstance(raw_field.get("confidence"), (int, float)):
            conf_detail[f] = raw_field["confidence"]
        else:
            conf_detail[f] = None
    cog_const["confidence"] = None
    cog_const["confidence_detail"] = conf_detail
    cog_const["source"] = "interview"

    return soul


_IDENTITY_FIELDS = ["name", "age", "occupation", "location"]


def _fmt_conf(raw_field) -> str:
    if isinstance(raw_field, dict) and isinstance(raw_field.get("confidence"), (int, float)):
        return f"{raw_field['confidence']:.2f}"
    return "—"


def _status_for_conf(raw_field) -> str:
    if not isinstance(raw_field, dict):
        return "—"
    val  = raw_field.get("value")
    conf = raw_field.get("confidence")
    if val is None:
        return "— 无信号"
    if not isinstance(conf, (int, float)):
        return "— confidence 异常"
    if conf >= config.INTERVIEW_CONFIDENCE_THRESHOLD:
        return "✅ 已写入"
    return "⚠️ 未写入（回访）"


def _format_value_preview(value, max_len: int = 80) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        s = value.replace("\n", " ")
    else:
        s = json.dumps(value, ensure_ascii=False)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _write_build_report(out_path: str, parsed: dict, raw_seed: dict, stats: dict) -> None:
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    biography = stats.get("biography_count", 0)
    meta      = stats.get("meta_count", 0)
    total     = biography + meta
    status    = stats.get("status_dist", {})
    a = status.get("active", 0); d = status.get("dormant", 0); z = status.get("archived", 0)

    lines: list[str] = []
    agent_id = parsed["agent_id"]
    lines.append(f"# Agent 构建报告：{agent_id}\n")
    lines.append(f"- 构建时间：{now_str}")
    lines.append(f"- 来源：`{parsed.get('source_md_rel', '(未知)')}`")
    lines.append(f"- 访谈时间：{parsed.get('completed_at','')}（时长 {parsed.get('duration_minutes',0)} 分钟）")
    lines.append(f"- 访谈 session_id：{parsed.get('session_id','')}")
    lines.append(f"- 耗时：{stats.get('elapsed_seconds', 0)}s\n")

    lines.append("## 基础身份\n")
    lines.append("| 字段 | 值 | confidence |")
    lines.append("|---|---|---|")
    for f in _IDENTITY_FIELDS:
        node = raw_seed.get(f) or {}
        val  = node.get("value") if isinstance(node, dict) else None
        lines.append(f"| {f} | {_format_value_preview(val)} | {_fmt_conf(node)} |")
    lines.append("")

    lines.append("## Soul 填充情况\n")
    SOUL_CORES_IN_REPORT = ["emotion_core", "value_core", "goal_core", "relation_core", "cognitive_core"]
    for core in SOUL_CORES_IN_REPORT:
        raw_core = raw_seed.get(core) or {}
        fields   = _CORE_FIELDS[core]
        lines.append(f"### {core}")
        lines.append("| 区 | 字段 | 状态 | conf |")
        lines.append("|---|---|---|---|")
        for zone, zone_fields in [
            ("constitutional", fields["constitutional"]),
            ("slow_change",    fields["slow_change"]),
            ("elastic",        fields["elastic"]),
        ]:
            for f in zone_fields:
                node = raw_core.get(f)
                lines.append(f"| {zone} | {f} | {_status_for_conf(node)} | {_fmt_conf(node)} |")
        lines.append("")

    lines.append("## 回访建议\n")
    lines.append("以下字段 LLM 看到了部分信号但把握不足，未写入 soul，建议下一轮访谈重点追问：\n")
    follow_ups = raw_seed.get("follow_up_questions") or {}
    threshold  = config.INTERVIEW_CONFIDENCE_THRESHOLD
    has_entries = False

    for core in SOUL_CORES_IN_REPORT:
        raw_core = raw_seed.get(core) or {}
        fields   = _CORE_FIELDS[core]
        for zone_fields in [fields["constitutional"], fields["slow_change"], fields["elastic"]]:
            for f in zone_fields:
                node = raw_core.get(f)
                if not isinstance(node, dict):
                    continue
                conf = node.get("confidence")
                if not isinstance(conf, (int, float)):
                    continue
                if conf <= 0.0 or conf >= threshold:
                    continue
                has_entries = True
                key = f"{core}.{f}"
                lines.append(f"- **{key}** (conf={conf:.2f})")
                lines.append(f"    - LLM 临时判断：{_format_value_preview(node.get('value'), max_len=120)}")
                suggested = follow_ups.get(key) or []
                if suggested:
                    for q in suggested:
                        lines.append(f"    - 建议追问：{q}")
                else:
                    lines.append("    - 建议追问：（无 LLM 建议追问）")
    if not has_entries:
        lines.append("（无 —— 所有字段 confidence 都 ≥ 阈值或无信号）")
    lines.append("")

    lines.append("## L1 记忆\n")
    lines.append(f"- Biography 事件：{biography} 条")
    lines.append(f"- Meta 事件：{meta} 条")
    lines.append(f"- 总计：{total} 条")
    lines.append(f"- 状态分布：active={a}, dormant={d}, archived={z}\n")

    topic_dist = stats.get("topic_dist") or {}
    if topic_dist:
        lines.append("### 按主题分布")
        for topic, count in sorted(topic_dist.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {topic}：{count} 条")
        lines.append("")

    lines.append("## L2 Patterns\n")
    lines.append(f"- 生成：{stats.get('l2_pattern_count', 0)} 条\n")

    lines.append("## Soul 证据贡献\n")
    lines.append(f"- L1 → Soul 缓变区积分次数：{stats.get('soul_contributions', 0)}")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"_write_build_report written to {out_path}")


from core.seed_memory_loader import (
    _setup_agent_dirs,
    _write_events_to_l1,
    _build_graph,
    _update_statuses,
)
from core.memory_l2 import check_and_generate_patterns, contribute_to_soul


def _write_seed_audit(seed_dir: Path, raw_seed: dict) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    with open(seed_dir / "seed.json", "w", encoding="utf-8") as f:
        json.dump(raw_seed, f, ensure_ascii=False, indent=2)


def _inject_l0_narrative(agent_id: str, narrative: str) -> None:
    """把 recent_self_narrative 写进 l0_buffer.working_context；raw_dialogue 不塞。"""
    l0_path = _AGENTS_DIR / agent_id / "l0_buffer.json"
    data = json.loads(l0_path.read_text(encoding="utf-8"))
    data.setdefault("working_context", {})
    data["working_context"]["recent_self_narrative"] = narrative or ""
    l0_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _compute_topic_dist(events: list[dict]) -> dict[str, int]:
    counter: dict[str, int] = {}
    for ev in events:
        for t in ev.get("tags_topic") or []:
            counter[str(t)] = counter.get(str(t), 0) + 1
    return counter


def build_from_interview(
    md_path: str,
    agent_id_override: str | None = None,
    force: bool = False,
) -> dict:
    """
    从访谈 md 一键构建 agent。参见 spec §2 架构图。
    """
    start = datetime.now()

    logger.info(f"Step 1/11: parse interview md path={md_path}")
    parsed = _parse_interview_md(md_path)
    if agent_id_override:
        parsed["agent_id"] = agent_id_override
    agent_id = parsed["agent_id"]

    agent_dir = _AGENTS_DIR / agent_id
    seed_dir  = _SEEDS_DIR / agent_id
    if agent_dir.exists() or seed_dir.exists():
        if not force:
            raise RuntimeError(
                f"agent_id='{agent_id}' 已存在。如需重建请加 --force。"
            )
        logger.warning(f"build_from_interview force=True 删除旧数据 agent_id={agent_id}")
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        if seed_dir.exists():
            shutil.rmtree(seed_dir)

    logger.info(f"build_from_interview START agent_id={agent_id}")

    logger.info("Step 3/11: archive source md")
    seed_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = seed_dir / "interview_source"
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(md_path, archive_dir / Path(md_path).name)
    parsed["source_md_rel"] = f"interview_source/{Path(md_path).name}"

    logger.info("Step 4/11: LLM pass 1 — interview → seed (with confidence)")
    raw_seed = _call_llm_for_seed(parsed)

    _write_seed_audit(seed_dir, raw_seed)

    logger.info("Step 5/11: confidence gate → soul.json")
    soul = _build_soul_from_gated_seed(agent_id, raw_seed)
    _write_soul(agent_id, soul)

    agent_name_field = raw_seed.get("name") or {}
    agent_name = agent_name_field.get("value") if isinstance(agent_name_field, dict) else None
    agent_name = agent_name or agent_id
    age_field  = raw_seed.get("age") or {}
    current_age = age_field.get("value") if isinstance(age_field, dict) else None
    if not isinstance(current_age, int):
        current_age = 0

    logger.info("Step 6/11: setup agent dirs + inject L0 recent_self_narrative")
    _setup_agent_dirs(agent_id)
    _inject_l0_narrative(agent_id, raw_seed.get("recent_self_narrative") or "")

    logger.info("Step 7/11: LLM pass 2 — interview → biography L1 events")
    biography_events = _call_llm_for_l1_events(parsed, agent_name, current_age)

    logger.info("Step 8/11: build deterministic meta event")
    meta_event = _build_meta_event(parsed, agent_name)
    all_events = biography_events + [meta_event]

    logger.info(f"Step 9/11: write {len(all_events)} events to L1 + graph + statuses")
    written = _write_events_to_l1(agent_id, agent_name, all_events)
    _build_graph(agent_id, written)
    status_dist = _update_statuses(agent_id, written)

    logger.info("Step 10/11: L2 patterns (include_all_statuses=True) + soul contributions")
    l2_updated = check_and_generate_patterns(agent_id, include_all_statuses=True)
    soul_contribs = contribute_to_soul(agent_id)

    logger.info("Step 11/11: write build_report.md")
    elapsed = (datetime.now() - start).seconds
    stats = {
        "elapsed_seconds":    elapsed,
        "biography_count":    len(biography_events),
        "meta_count":         1,
        "status_dist":        status_dist,
        "l2_pattern_count":   len(l2_updated),
        "soul_contributions": len(soul_contribs),
        "topic_dist":         _compute_topic_dist(biography_events + [meta_event]),
    }
    _write_build_report(str(seed_dir / "build_report.md"), parsed, raw_seed, stats)

    summary = {
        "agent_id":          agent_id,
        "agent_name":        agent_name,
        "biography_count":   len(biography_events),
        "meta_count":        1,
        "l2_pattern_count":  len(l2_updated),
        "soul_contributions":len(soul_contribs),
        "elapsed_seconds":   elapsed,
    }
    logger.info(f"build_from_interview DONE summary={summary}")
    print("\n=== interview agent 构建完成 ===")
    print(f"  Agent:        {agent_id} ({agent_name})")
    print(f"  L1 事件:      {len(biography_events)} biography + {1} meta = {len(biography_events)+1} 条  {status_dist}")
    print(f"  L2 patterns:  {len(l2_updated)} 条")
    print(f"  报告:         data/seeds/{agent_id}/build_report.md")
    print(f"  耗时:         {elapsed}s")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="从访谈 md 构建数字人 agent（带 confidence 门控和审计报告）",
    )
    parser.add_argument("md_path", help="interview_source/ 下的 md 文件路径")
    parser.add_argument("--agent-id",
                        dest="agent_id_override",
                        default=None,
                        help="文件名推导失败时的后门参数")
    parser.add_argument("--force", "-f", action="store_true", help="覆盖重建")
    args = parser.parse_args()

    if not Path(args.md_path).exists():
        print(f"错误：找不到文件 {args.md_path}", file=sys.stderr)
        sys.exit(1)

    try:
        build_from_interview(
            md_path=args.md_path,
            agent_id_override=args.agent_id_override,
            force=args.force,
        )
    except (RuntimeError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
