import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import lancedb

import config
from core.llm_client import chat_completion, get_embedding
from core.soul import get_value_core_constitutional

logger = logging.getLogger("memory_l1")

_AGENTS_DIR  = Path(__file__).parent.parent / "data" / "agents"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ── Schema ────────────────────────────────────────────────────────────────────

def _l1_schema() -> pa.Schema:
    return pa.schema([
        pa.field("vector",                     pa.list_(pa.float32(), config.EMBEDDING_DIM)),
        pa.field("event_id",                   pa.utf8()),
        pa.field("agent_id",                   pa.utf8()),
        pa.field("timestamp",                  pa.utf8()),
        pa.field("created_at",                 pa.utf8()),
        pa.field("actor",                      pa.utf8()),
        pa.field("action",                     pa.utf8()),
        pa.field("context",                    pa.utf8()),
        pa.field("outcome",                    pa.utf8()),
        pa.field("scene_location",             pa.utf8()),
        pa.field("scene_atmosphere",           pa.utf8()),
        pa.field("scene_sensory_notes",        pa.utf8()),
        pa.field("scene_subjective_experience",pa.utf8()),
        pa.field("emotion",                    pa.utf8()),
        pa.field("emotion_intensity",          pa.float32()),
        pa.field("importance",                 pa.float32()),
        pa.field("emotion_intensity_score",    pa.float32()),
        pa.field("value_relevance_score",      pa.float32()),
        pa.field("novelty_score",              pa.float32()),
        pa.field("reusability_score",          pa.float32()),
        pa.field("is_derivable_score",         pa.float32()),
        pa.field("decay_score",                pa.float32()),
        pa.field("access_count",               pa.int32()),
        pa.field("status",                     pa.utf8()),
        pa.field("tags_time_year",             pa.int32()),
        pa.field("tags_time_month",            pa.int32()),
        pa.field("tags_time_week",             pa.int32()),
        pa.field("tags_time_period_label",     pa.utf8()),
        pa.field("tags_people",                pa.utf8()),
        pa.field("tags_topic",                 pa.utf8()),
        pa.field("tags_emotion_valence",       pa.utf8()),
        pa.field("tags_emotion_label",         pa.utf8()),
        pa.field("source",                     pa.utf8()),
        pa.field("ttl_days",                   pa.int32()),
        pa.field("raw_quote",                  pa.utf8()),
        pa.field("event_kind",                 pa.utf8()),
    ])


# ── LanceDB 连接 ───────────────────────────────────────────────────────────────

def _get_table(agent_id: str) -> lancedb.table.Table:
    db_path = _AGENTS_DIR / agent_id / "memories"
    db_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_path))
    try:
        return db.open_table("l1_events")
    except Exception:
        return db.create_table("l1_events", schema=_l1_schema())


# ── Prompt 工具 ───────────────────────────────────────────────────────────────

def _load_prompt(filename: str) -> tuple[str, str]:
    text = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()


_EV_SYS,    _EV_USR    = _load_prompt("l1_extract_events.txt")
_SC_SYS,    _SC_USR    = _load_prompt("l1_score_event.txt")
_SCENE_SYS, _SCENE_USR = _load_prompt("l1_extract_scene.txt")
_TAG_SYS,   _TAG_USR   = _load_prompt("l1_extract_tags.txt")


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return m.group(1) if m else text


def _llm_json(system: str, user: str, max_tokens: int = 512, temperature: float = 0.2):
    raw = chat_completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=temperature,
    )
    return json.loads(_strip_json(raw))


def _now() -> str:
    return datetime.now().isoformat()


# ── 写入流程子步骤 ─────────────────────────────────────────────────────────────

def _extract_events(raw_text: str, value_core: str, recent_summary: str) -> list[dict]:
    user = _EV_USR.format(
        value_core=value_core,
        recent_summary=recent_summary or "（无近期记忆）",
        raw_text=raw_text,
    )
    data = _llm_json(_EV_SYS, user, max_tokens=1024)
    if isinstance(data, list):
        return data
    # LLM 偶尔返回 {"events": [...]}
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def _score_event(ev: dict, value_core: str) -> dict:
    user = _SC_USR.format(
        value_core=value_core,
        action=ev.get("action", ""),
        context=ev.get("context", ""),
        outcome=ev.get("outcome", ""),
        emotion=ev.get("emotion", ""),
        emotion_intensity=ev.get("emotion_intensity", 0.0),
    )
    return _llm_json(_SC_SYS, user, max_tokens=256)


def _extract_scene(ev: dict, raw_text: str) -> dict:
    user = _SCENE_USR.format(
        action=ev.get("action", ""),
        context=ev.get("context", ""),
        outcome=ev.get("outcome", ""),
        raw_text=raw_text,
    )
    return _llm_json(_SCENE_SYS, user, max_tokens=256)


def _extract_tags(ev: dict, raw_text: str) -> dict:
    now = datetime.now()
    user = _TAG_USR.format(
        action=ev.get("action", ""),
        context=ev.get("context", ""),
        outcome=ev.get("outcome", ""),
        emotion=ev.get("emotion", ""),
        raw_text=raw_text,
        current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return _llm_json(_TAG_SYS, user, max_tokens=256)


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def write_event(agent_id: str, raw_text: str, source: str = "dialogue") -> list[str]:
    """
    从 raw_text 提取原子事件并写入 LanceDB l1_events 表。
    返回写入成功的 event_id 列表。
    """
    tbl = _get_table(agent_id)

    # 1. 获取价值观锚点
    try:
        value_core = get_value_core_constitutional(agent_id)
    except Exception as e:
        logger.warning(f"write_event get_value_core failed agent_id={agent_id} error={e}")
        value_core = ""

    # 2. 获取近期事件摘要
    recent_summary = get_recent_events_summary(agent_id, limit=5)

    # 3. LLM 提取原子事件
    try:
        events = _extract_events(raw_text, value_core, recent_summary)
    except Exception as e:
        logger.error(f"write_event extract_events failed agent_id={agent_id} error={e}")
        return []

    logger.info(f"write_event agent_id={agent_id} extracted={len(events)} events")

    written_ids: list[str] = []
    now_str = _now()

    for ev in events:
        event_id = str(uuid.uuid4())
        try:
            # 4. 打五维分
            scores = _score_event(ev, value_core)

            # 5. is_derivable 过滤
            is_derivable = float(scores.get("is_derivable", 0.0))
            if is_derivable > config.IS_DERIVABLE_DISCARD_THRESHOLD:
                logger.info(f"write_event discard is_derivable={is_derivable:.2f} event={ev.get('action', '')[:40]}")
                continue

            emotion_intensity = float(scores.get("emotion_intensity", ev.get("emotion_intensity", 0.0)))
            value_relevance   = float(scores.get("value_relevance", 0.0))
            novelty           = float(scores.get("novelty", 0.0))
            reusability       = float(scores.get("reusability", 0.0))

            # 6. importance 计算
            importance = (
                emotion_intensity * 0.3
                + value_relevance  * 0.3
                + novelty          * 0.2
                + reusability      * 0.2
            )

            # 7. scene 提取
            scene = _extract_scene(ev, raw_text)

            # 8. tags 提取
            tags = _extract_tags(ev, raw_text)

            # 9. embedding
            embed_text = f"{ev.get('action', '')} {ev.get('context', '')} {ev.get('outcome', '')}"
            vector = get_embedding(embed_text)

            # 10. 写入 LanceDB
            people_json = json.dumps(tags.get("people", []), ensure_ascii=False)
            topic_json  = json.dumps(tags.get("topic",  []), ensure_ascii=False)

            row = {
                "vector":                      [float(x) for x in vector],
                "event_id":                    event_id,
                "agent_id":                    agent_id,
                "timestamp":                   now_str,
                "created_at":                  now_str,
                "actor":                       str(ev.get("actor") or ""),
                "action":                      str(ev.get("action") or ""),
                "context":                     str(ev.get("context") or ""),
                "outcome":                     str(ev.get("outcome") or ""),
                "scene_location":              str(scene.get("location") or ""),
                "scene_atmosphere":            str(scene.get("atmosphere") or ""),
                "scene_sensory_notes":         str(scene.get("sensory_notes") or ""),
                "scene_subjective_experience": str(scene.get("subjective_experience") or ""),
                "emotion":                     str(ev.get("emotion") or ""),
                "emotion_intensity":           emotion_intensity,
                "importance":                  float(importance),
                "emotion_intensity_score":     emotion_intensity,
                "value_relevance_score":       value_relevance,
                "novelty_score":               novelty,
                "reusability_score":           reusability,
                "is_derivable_score":          is_derivable,
                "decay_score":                 1.0,
                "access_count":                0,
                "status":                      "active",
                "tags_time_year":              int(tags.get("time_year") or datetime.now().year),
                "tags_time_month":             int(tags.get("time_month") or datetime.now().month),
                "tags_time_week":              int(tags.get("time_week") or 1),
                "tags_time_period_label":      str(tags.get("time_period_label") or ""),
                "tags_people":                 people_json,
                "tags_topic":                  topic_json,
                "tags_emotion_valence":        str(tags.get("emotion_valence") or ""),
                "tags_emotion_label":          str(tags.get("emotion_label") or ""),
                "source":                      source,
                "ttl_days":                    365,
                "raw_quote":                   str(ev.get("raw_quote") or ""),
                "event_kind":                  str(ev.get("event_kind") or "biography"),
            }
            tbl.add([row])

            # 11. 建立记忆图关联边
            try:
                from core.memory_graph import MemoryGraph
                graph = MemoryGraph()
                graph.create_links_on_write(agent_id, event_id, vector)
            except Exception as e:
                logger.warning(f"write_event create_links failed agent_id={agent_id} event_id={event_id} error={e}")

            written_ids.append(event_id)
            logger.info(f"write_event agent_id={agent_id} event_id={event_id} importance={importance:.3f}")

        except Exception as e:
            logger.error(f"write_event skip event agent_id={agent_id} event_id={event_id} error={e}")
            continue

    logger.info(f"write_event agent_id={agent_id} written={len(written_ids)}/{len(events)}")
    return written_ids


def get_event(agent_id: str, event_id: str) -> dict:
    """按 event_id 精确查询，返回事件 dict；不存在则返回空 dict。"""
    tbl = _get_table(agent_id)
    rows = tbl.search().where(f"event_id = '{event_id}'").limit(1).to_list()
    return rows[0] if rows else {}


def update_event_status(agent_id: str, event_id: str, status: str) -> None:
    """更新事件状态字段（active / dormant / archived）。"""
    tbl = _get_table(agent_id)
    tbl.update(where=f"event_id = '{event_id}'", values={"status": status})
    logger.info(f"update_event_status agent_id={agent_id} event_id={event_id} status={status}")


def increment_access_count(agent_id: str, event_id: str) -> None:
    """access_count + 1。"""
    row = get_event(agent_id, event_id)
    if not row:
        logger.warning(f"increment_access_count event not found event_id={event_id}")
        return
    tbl = _get_table(agent_id)
    tbl.update(
        where=f"event_id = '{event_id}'",
        values={"access_count": int(row.get("access_count", 0)) + 1},
    )
    logger.info(f"increment_access_count agent_id={agent_id} event_id={event_id}")


def get_archived_by_topic(agent_id: str, topic: str) -> list[dict]:
    """返回 status=archived 且 tags_topic 包含 topic 的事件列表。"""
    tbl = _get_table(agent_id)
    topic_escaped = topic.replace("'", "''")
    rows = (
        tbl.search()
        .where(f"status = 'archived' AND tags_topic LIKE '%{topic_escaped}%'")
        .limit(50)
        .to_list()
    )
    return rows


def get_recent_events_summary(agent_id: str, limit: int = 5) -> str:
    """
    返回最近 limit 条 active 事件的简短摘要文本，供 is_derivable 判断用。
    按 created_at 倒序取最近记录。
    """
    tbl = _get_table(agent_id)
    try:
        rows = (
            tbl.search()
            .where("status = 'active'")
            .limit(limit * 4)   # 多取一些再在 Python 侧排序
            .to_list()
        )
        if not rows:
            return ""
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        rows = rows[:limit]
        parts = []
        for r in rows:
            action  = r.get("action", "")
            emotion = r.get("emotion", "")
            parts.append(f"- {action}（情绪：{emotion}）")
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"get_recent_events_summary agent_id={agent_id} error={e}")
        return ""
