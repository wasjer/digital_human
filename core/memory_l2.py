import copy
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import config
from core.llm_client import chat_completion

logger = logging.getLogger("memory_l2")

_AGENTS_DIR  = Path(__file__).parent.parent / "data" / "agents"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# target_core → soul slow_change field
_SOUL_FIELD_MAP = {
    "emotion_core":  "emotional_regulation_style",
    "value_core":    "value_priority_order",
    "goal_core":     "mid_term_goals",
    "relation_core": "key_relationships",
}

_SAMPLING_WEIGHTS_PLACEHOLDER = {
    "alpha_connectivity":    0.25,
    "beta_emotion_intensity": 0.30,
    "gamma_time_novelty":    0.25,
    "delta_access_frequency": 0.20,
}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _patterns_path(agent_id: str) -> Path:
    return _AGENTS_DIR / agent_id / "l2_patterns.json"


def _read_patterns(agent_id: str) -> list[dict]:
    p = _patterns_path(agent_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_patterns(agent_id: str, patterns: list[dict]) -> None:
    p = _patterns_path(agent_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now().isoformat()


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return m.group(1) if m else text


def _load_prompt() -> tuple[str, str]:
    """从 l2_generate_patterns.txt 解析 [SYSTEM] 和 [USER] 两段。"""
    text = (_PROMPTS_DIR / "l2_generate_patterns.txt").read_text(encoding="utf-8")
    sys_match = re.search(r"\[SYSTEM\]\s*(.*?)(?=\[USER\])", text, re.DOTALL)
    usr_match  = re.search(r"\[USER\]\s*(.*)",               text, re.DOTALL)
    sys_prompt   = sys_match.group(1).strip() if sys_match else ""
    usr_template = usr_match.group(1).strip() if usr_match else text.strip()
    return sys_prompt, usr_template


def _read_last_scan_at(agent_id: str) -> str | None:
    from core.global_state import read_global_state
    try:
        state = read_global_state(agent_id)
        return state.get("last_l2_scan_at") or None
    except Exception:
        return None


def _write_last_scan_at(agent_id: str, timestamp: str) -> None:
    from core.global_state import update_global_state
    try:
        update_global_state(agent_id, "last_l2_scan_at", timestamp)
    except Exception as e:
        logger.warning(f"_write_last_scan_at failed agent_id={agent_id} error={e}")


def _fetch_archived_events(agent_id: str) -> list[dict]:
    """增量扫：仅取 created_at > last_l2_scan_at 的 archived 事件。
    首次扫（无时间戳）时走全扫。"""
    from core.memory_l1 import _get_table
    try:
        tbl = _get_table(agent_id)
        last_at = _read_last_scan_at(agent_id)
        if last_at:
            where_clause = f"status = 'archived' AND created_at > '{last_at}'"
        else:
            where_clause = "status = 'archived'"
        rows = tbl.search().where(where_clause).limit(9999).to_list()
        return rows
    except Exception as e:
        logger.warning(f"_fetch_archived_events agent_id={agent_id} error={e}")
        return []


def _fetch_all_events(agent_id: str) -> list[dict]:
    """从 LanceDB 取该 agent 所有事件（忽略 status），用于初始化时的 L2 归纳。"""
    from core.memory_l1 import _get_table
    try:
        tbl  = _get_table(agent_id)
        rows = tbl.search().limit(99999).to_list()
        return rows
    except Exception as e:
        logger.warning(f"_fetch_all_events agent_id={agent_id} error={e}")
        return []


def _parse_topics(tags_topic_str: str) -> list[str]:
    """解析 tags_topic 字段（JSON 字符串或裸字符串），返回 topic 列表。"""
    if not tags_topic_str:
        return []
    try:
        val = json.loads(tags_topic_str)
        if isinstance(val, list):
            return [str(t) for t in val if t]
        if isinstance(val, str):
            return [val] if val else []
    except Exception:
        pass
    stripped = tags_topic_str.strip()
    return [stripped] if stripped else []


def _events_to_summary(events: list[dict]) -> str:
    parts = []
    for i, ev in enumerate(events, 1):
        action  = ev.get("action", "")
        context = ev.get("context", "")
        emotion = ev.get("emotion", "")
        eid     = ev.get("event_id", "")
        parts.append(f"{i}. [event_id={eid}] 行为：{action}；背景：{context}；情绪：{emotion}")
    return "\n".join(parts) if parts else "（无事件）"


# ── 核心接口 ──────────────────────────────────────────────────────────────────

def check_and_generate_patterns(
    agent_id: str,
    include_all_statuses: bool = False,
) -> list[str]:
    """
    触发逻辑（规则引擎，不是 LLM 扫全部事件）：
    1. 快照当前 l2_patterns.json
    2. 取事件（默认 archived；初始化通路传 include_all_statuses=True 囊括 active/dormant）
    3. 按 tags_topic 分组
    4. 对每个 topic，若事件数 >= L2_SAME_TOPIC_THRESHOLD，调用 LLM
    5. 写回，返回本次新增或更新的 pattern_id 列表
    """
    # 1. 快照
    last_known_good_state = copy.deepcopy(_read_patterns(agent_id))

    # 2. 取事件
    if include_all_statuses:
        candidate_events = _fetch_all_events(agent_id)
        reason = "all-statuses mode"
    else:
        candidate_events = _fetch_archived_events(agent_id)
        reason = "archived-only mode"
    if not candidate_events:
        logger.info(f"check_and_generate_patterns agent_id={agent_id} no events ({reason}), skip")
        if not include_all_statuses:
            _write_last_scan_at(agent_id, _now())
        return []

    # 3. 按 topic 分组
    topic_events: dict[str, list[dict]] = {}
    for ev in candidate_events:
        for topic in _parse_topics(ev.get("tags_topic", "")):
            topic_events.setdefault(topic, []).append(ev)

    # 4. 加载 prompt 模板
    sys_prompt, usr_template = _load_prompt()

    patterns    = copy.deepcopy(last_known_good_state)
    updated_ids: list[str] = []
    now = _now()

    for topic, events in topic_events.items():
        if len(events) < config.L2_SAME_TOPIC_THRESHOLD:
            continue

        # 检查该 topic 是否已有 active pattern
        existing = [
            p for p in patterns
            if p.get("source_topic") == topic and p.get("status") == "active"
        ]
        if existing:
            existing_pattern_str = json.dumps(
                [{"pattern_id": p["pattern_id"], "abstract_conclusion": p["abstract_conclusion"]}
                 for p in existing],
                ensure_ascii=False,
            )
        else:
            existing_pattern_str = "无"

        event_ids     = [ev.get("event_id", "") for ev in events if ev.get("event_id")]
        events_summary = _events_to_summary(events)

        user_msg = usr_template.format(
            source_topic    = topic,
            event_count     = len(events),
            events_summary  = events_summary,
            existing_pattern= existing_pattern_str,
        )

        # 调用 LLM
        try:
            raw    = chat_completion(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user",   "content": user_msg}],
                max_tokens=512,
                temperature=0.3,
            )
            result = json.loads(_strip_json(raw))
        except Exception as e:
            logger.error(
                f"check_and_generate_patterns llm/parse failed "
                f"agent_id={agent_id} topic={topic} error={e}"
            )
            rollback_patterns(agent_id, last_known_good_state)
            mark_retry_needed(agent_id)
            continue

        action = result.get("action", "skip")

        if action == "create":
            abstract    = result.get("abstract_conclusion", "").strip()
            target_core = result.get("target_core", "goal_core")
            if not abstract:
                continue
            new_pattern = {
                "pattern_id":          str(uuid.uuid4()),
                "agent_id":            agent_id,
                "abstract_conclusion": abstract,
                "support_event_ids":   event_ids,
                "source_topic":        topic,
                "confidence":          config.L2_INITIAL_CONFIDENCE,
                "target_core":         target_core,
                "evidence_contribution": 0.0,
                "created_at":          now,
                "updated_at":          now,
                "status":              "active",
                "retry_needed":        False,
                "sampling_weights_placeholder": dict(_SAMPLING_WEIGHTS_PLACEHOLDER),
            }
            patterns.append(new_pattern)
            updated_ids.append(new_pattern["pattern_id"])
            logger.info(
                f"check_and_generate_patterns create pattern "
                f"agent_id={agent_id} topic={topic} abstract={abstract[:40]}"
            )

        elif action == "update":
            pid     = result.get("pattern_id", "")
            pid_map = {p["pattern_id"]: p for p in patterns}
            if pid in pid_map:
                p            = pid_map[pid]
                new_abstract = result.get("abstract_conclusion", "").strip()
                if new_abstract:
                    p["abstract_conclusion"] = new_abstract
                p["confidence"] = min(1.0, p["confidence"] + config.L2_CONFIDENCE_INCREMENT)
                p["updated_at"] = now
                existing_eids   = set(p.get("support_event_ids", []))
                for eid in event_ids:
                    if eid not in existing_eids:
                        p.setdefault("support_event_ids", []).append(eid)
                        existing_eids.add(eid)
                updated_ids.append(pid)
                logger.info(
                    f"check_and_generate_patterns update pattern "
                    f"agent_id={agent_id} pattern_id={pid[:8]} confidence={p['confidence']:.2f}"
                )
            else:
                logger.warning(
                    f"check_and_generate_patterns update: pattern_id={pid} not found, skip"
                )

        else:  # skip
            logger.info(f"check_and_generate_patterns skip topic={topic} agent_id={agent_id}")

    # 5. 写回
    _write_patterns(agent_id, patterns)
    if not include_all_statuses:
        _write_last_scan_at(agent_id, _now())
    logger.info(
        f"check_and_generate_patterns done agent_id={agent_id} updated={len(updated_ids)}"
    )
    return updated_ids


def get_patterns(agent_id: str) -> list[dict]:
    """返回所有 status='active' 的 patterns。"""
    return [p for p in _read_patterns(agent_id) if p.get("status") == "active"]


def get_patterns_for_retrieval(agent_id: str, query_topics: list = []) -> list[dict]:
    """
    返回 list[dict]（不是字符串）。
    query_topics 为空时返回所有 active patterns。
    query_topics 非空时返回 source_topic 在列表中的 patterns。
    按 confidence 降序，最多返回 5 条。
    """
    active = [p for p in _read_patterns(agent_id) if p.get("status") == "active"]
    if query_topics:
        active = [p for p in active if p.get("source_topic") in query_topics]
    active.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)
    return active[:5]


def contribute_to_soul(agent_id: str) -> list:
    """
    对 confidence >= L2_SOUL_CONTRIBUTION_THRESHOLD 且 status='active' 的 pattern
    向 soul 缓变区贡献积分。
    返回贡献记录列表 [{"pattern_id": ..., "target_core": ..., "score": ...}]。
    """
    from core.soul import add_evidence

    patterns      = _read_patterns(agent_id)
    threshold     = config.L2_SOUL_CONTRIBUTION_THRESHOLD
    contributions = []
    now           = _now()

    for p in patterns:
        if p.get("status") != "active":
            continue
        if p.get("confidence", 0.0) < threshold:
            continue

        target_core = p.get("target_core", "")
        field       = _SOUL_FIELD_MAP.get(target_core)
        if not field:
            logger.warning(
                f"contribute_to_soul unknown target_core={target_core} "
                f"pattern_id={p.get('pattern_id', '')[:8]}"
            )
            continue

        score = p["confidence"] * 0.3

        try:
            add_evidence(
                agent_id   = agent_id,
                core       = target_core,
                field      = field,
                score      = score,
                reason     = p.get("abstract_conclusion", ""),
                session_id = "l2_engine",
            )
            p["evidence_contribution"] = p.get("evidence_contribution", 0.0) + score
            p["updated_at"] = now
            contributions.append({
                "pattern_id":  p["pattern_id"],
                "target_core": target_core,
                "score":       score,
            })
            logger.info(
                f"contribute_to_soul agent_id={agent_id} "
                f"pattern_id={p['pattern_id'][:8]} core={target_core} score={score:.3f}"
            )
        except Exception as e:
            logger.warning(
                f"contribute_to_soul add_evidence failed agent_id={agent_id} "
                f"pattern_id={p.get('pattern_id', '')[:8]} error={e}"
            )

    _write_patterns(agent_id, patterns)
    logger.info(f"contribute_to_soul agent_id={agent_id} contributed={len(contributions)}")
    return contributions


def rollback_patterns(agent_id: str, snapshot: list) -> None:
    """将 l2_patterns.json 覆盖回 snapshot 内容。"""
    _write_patterns(agent_id, snapshot)
    logger.info(
        f"rollback_patterns agent_id={agent_id} rolled back to {len(snapshot)} patterns"
    )


def mark_retry_needed(agent_id: str) -> None:
    """日志记录需要重试的情况（阶段一只记日志，不做复杂重试逻辑）。"""
    logger.warning(
        f"mark_retry_needed agent_id={agent_id}: "
        f"LLM failure detected, retry needed for l2 pattern generation"
    )
