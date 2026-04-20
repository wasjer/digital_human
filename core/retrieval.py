import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import config
from core import trace
from core.llm_client import chat_completion, get_embedding
from core.soul import get_soul_anchor
from core.global_state import read_global_state
from core.memory_l1 import _get_table, get_event, increment_access_count
from core.memory_graph import MemoryGraph

logger = logging.getLogger("retrieval")

_AGENTS_DIR  = Path(__file__).parent.parent / "data" / "agents"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ── Prompt ────────────────────────────────────────────────────────────────────

def _load_prompt(filename: str) -> tuple[str, str]:
    text = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()

_RERANK_SYS, _RERANK_USR = _load_prompt("retrieval_rerank.txt")

# ── 常量 ──────────────────────────────────────────────────────────────────────

_RETRIEVAL_TOP_K     = 20   # 向量召回上限
_GRAPH_EXPAND_TOP_N  = 5    # 图扩展取前 N 条做邻居查询
_FINAL_TOP_K         = 8    # 最终返回上限

_MODE_WEIGHTS = {
    "dialogue":   {"relevance": 0.35, "importance": 0.20, "recency": 0.25, "mood_fit": 0.20},
    "decision":   {"relevance": 0.35, "importance": 0.35, "recency": 0.15, "mood_fit": 0.15},
    "reflection": {"relevance": 0.35, "importance": 0.25, "recency": 0.20, "mood_fit": 0.20},
}

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _cosine_sim(a, b) -> float:
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _load_l0_buffer(agent_id: str) -> dict:
    path = _AGENTS_DIR / agent_id / "l0_buffer.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _format_working_context(buffer: dict) -> str:
    lines = []
    raw_dialogue = buffer.get("raw_dialogue", [])[-3:]
    if raw_dialogue:
        lines.append("当前对话：")
        for d in raw_dialogue:
            role    = d.get("role", "")
            content = d.get("content", "")
            lines.append(f"  {role}: {content}")
    wc = buffer.get("working_context", {})
    if wc.get("current_task"):
        lines.append(f"当前任务：{wc['current_task']}")
    if wc.get("attention_focus"):
        lines.append(f"注意焦点：{wc['attention_focus']}")
    return "\n".join(lines)


def _freshness_text(days_elapsed: int, status: str) -> str:
    if days_elapsed == 0:
        base = ""
    elif days_elapsed <= 3:
        base = f"（{days_elapsed}天前的记忆）"
    elif days_elapsed <= 14:
        base = f"（约{days_elapsed}天前的记忆，细节可能模糊）"
    elif days_elapsed <= 30:
        weeks = max(1, round(days_elapsed / 7))
        base = f"（约{weeks}周前的记忆，细节可能不准确）"
    else:
        months = max(1, round(days_elapsed / 30))
        base = f"（{months}个月前的记忆，仅保留大致印象）"

    if status == "dormant":
        base += "（这段记忆已经很模糊了）"
    elif status == "revived":
        base += "（这段记忆因相关联想被重新想起）"

    return base


def _score_candidate(row: dict, query_embedding, stress_level: float,
                     weights: dict, now: datetime) -> tuple[float, int]:
    vector = row.get("vector")
    relevance = _cosine_sim(query_embedding, vector) if vector else 0.0

    importance = float(row.get("importance", 0.0))

    created_at = row.get("created_at", "")
    try:
        dt = datetime.fromisoformat(created_at)
        days_elapsed = max(0, (now - dt).days)
    except Exception:
        days_elapsed = 0
    recency = 1.0 / (1.0 + days_elapsed)

    emotion_intensity = float(row.get("emotion_intensity", 0.0))
    mood_fit = max(0.0, min(1.0, 1.0 - abs(emotion_intensity - stress_level)))

    score = (
        relevance  * weights["relevance"]
        + importance * weights["importance"]
        + recency    * weights["recency"]
        + mood_fit   * weights["mood_fit"]
    )
    return score, days_elapsed


def _llm_rerank(query: str, candidates: list) -> list[str]:
    """decision 模式 LLM 二次精排，返回 event_id 列表。"""
    parts = []
    for i, item in enumerate(candidates):
        row = item["row"]
        parts.append(
            f"{i+1}. event_id={row.get('event_id', '')}\n"
            f"   内容：{row.get('action', '')} | {row.get('context', '')}\n"
            f"   重要性：{row.get('importance', 0):.2f} | 情绪：{row.get('emotion', '')}"
        )
    candidates_text = "\n".join(parts)

    user = _RERANK_USR.format(query=query, candidates_text=candidates_text)
    try:
        raw = chat_completion(
            [{"role": "system", "content": _RERANK_SYS},
             {"role": "user",   "content": user}],
            max_tokens=256,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if m:
            raw = m.group(1)
        ids = json.loads(raw)
        if isinstance(ids, list) and ids:
            logger.info(f"_llm_rerank selected {len(ids)} events")
            return [str(x) for x in ids]
    except Exception as e:
        logger.warning(f"_llm_rerank failed, fallback to score order: {e}")

    return [item["row"].get("event_id", "") for item in candidates]


# ── 主入口 ────────────────────────────────────────────────────────────────────

def retrieve(agent_id: str, query: str, mode: str = "dialogue",
             already_surfaced: set = None) -> dict:
    """
    已推送事件去重检索，组装完整 context。

    already_surfaced: set[str]，本次会话已推送的 event_id，传 None 时视为空集合
    mode: "dialogue" | "decision" | "reflection"
    """
    if already_surfaced is None:
        already_surfaced = set()

    # 1. Soul anchor
    try:
        soul_anchor = get_soul_anchor(agent_id)
    except Exception as e:
        logger.warning(f"retrieve get_soul_anchor failed: {e}")
        soul_anchor = ""

    # 2. Global state
    state          = read_global_state(agent_id)
    current_state  = state.get("current_state", {})
    stress_level   = float(current_state.get("stress_level", 0.3))
    current_state_text = (
        f"情绪：{current_state.get('mood', '')} | "
        f"能量：{current_state.get('energy', '')} | "
        f"压力：{stress_level:.1f}"
    )

    # 3. L0 buffer → working_context
    buffer          = _load_l0_buffer(agent_id)
    working_context = _format_working_context(buffer)

    # 4. L2 patterns
    from core.memory_l2 import get_patterns_for_retrieval
    l2_pattern_list = get_patterns_for_retrieval(agent_id, query_topics=[])
    l2_patterns = "；".join(p["abstract_conclusion"] for p in l2_pattern_list) if l2_pattern_list else ""

    # 5. Query embedding
    _t0 = time.monotonic()
    query_embedding = get_embedding(query)
    trace.event("embedding_stage", dim=len(query_embedding), elapsed_ms=int((time.monotonic()-_t0)*1000))

    # 6. LanceDB 向量检索
    tbl = _get_table(agent_id)
    try:
        raw_results = (
            tbl.search(query_embedding)
            .where("status = 'active' OR status = 'dormant' OR status = 'revived'")
            .limit(_RETRIEVAL_TOP_K)
            .to_list()
        )
    except Exception as e:
        logger.warning(f"retrieve vector search failed: {e}")
        raw_results = []

    # 排除会话内已推送事件
    vector_results = [r for r in raw_results if r.get("event_id") not in already_surfaced]
    trace.event(
        "vector_search",
        raw_hits=len(raw_results),
        after_dedup=len(vector_results),
        limit=_RETRIEVAL_TOP_K,
        already_surfaced=len(already_surfaced),
    )
    logger.debug(f"retrieve vector_hits={len(raw_results)} after_dedup={len(vector_results)}")

    # 7. 图扩展：对 top5 调用 get_neighbors，补充候选池
    graph = MemoryGraph()
    candidate_map: dict = {}   # event_id -> {"row": dict, "source": str}

    for row in vector_results:
        eid = row.get("event_id")
        if eid:
            candidate_map[eid] = {"row": row, "source": "vector_search"}

    top5_ids = [
        r.get("event_id")
        for r in vector_results[:_GRAPH_EXPAND_TOP_N]
        if r.get("event_id")
    ]
    for eid in top5_ids:
        try:
            neighbors = graph.get_neighbors(agent_id, eid)
            for n in neighbors:
                nid = n["event_id"]
                if nid in candidate_map or nid in already_surfaced:
                    continue
                nrow = get_event(agent_id, nid)
                if nrow and nrow.get("status") in ("active", "dormant", "revived"):
                    candidate_map[nid] = {"row": nrow, "source": "graph_expand"}
        except Exception as e:
            logger.warning(f"retrieve graph expand failed for {eid[:8]}: {e}")

    neighbors_added = len(candidate_map) - len(vector_results)
    trace.event(
        "graph_expand",
        top5_ids=top5_ids,
        neighbors_added=neighbors_added,
    )
    logger.debug(
        f"retrieve candidate_pool={len(candidate_map)} "
        f"(vector={len(vector_results)} + graph_expand={neighbors_added})"
    )

    # 8. 按 mode 权重评分，取 top 8
    weights = _MODE_WEIGHTS.get(mode, _MODE_WEIGHTS["dialogue"])
    now     = datetime.now()

    scored = []
    for eid, item in candidate_map.items():
        score, days_elapsed = _score_candidate(
            item["row"], query_embedding, stress_level, weights, now
        )
        scored.append({
            "event_id":    eid,
            "row":         item["row"],
            "source":      item["source"],
            "score":       score,
            "days_elapsed": days_elapsed,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = scored[:_FINAL_TOP_K]
    trace.event(
        "score_rerank",
        weights=dict(weights),
        candidate_pool=len(scored),
        top_k_returned=len(top_candidates),
        top_scored=[
            {
                "event_id": s["event_id"],
                "score": round(s["score"], 3),
                "source": s["source"],
            }
            for s in top_candidates
        ],
    )

    # 9. decision 模式 LLM 精排
    if mode == "decision" and top_candidates:
        logger.debug(f"retrieve decision mode: calling LLM rerank on {len(top_candidates)} candidates")
        reranked_ids = _llm_rerank(query, top_candidates)
        id_to_item   = {c["event_id"]: c for c in top_candidates}
        reranked = [id_to_item[rid] for rid in reranked_ids if rid in id_to_item]
        if reranked:
            top_candidates = reranked
            trace.event("llm_rerank", selected=len(reranked))

    # 10. 构建输出（含老化文本）
    relevant_memories = []
    surfaced_ids      = []

    for item in top_candidates:
        row          = item["row"]
        eid          = row.get("event_id", "")
        days_elapsed = item["days_elapsed"]
        status       = row.get("status", "active")

        freshness_text = _freshness_text(days_elapsed, status)

        content = " | ".join(filter(None, [
            row.get("actor",   ""),
            row.get("action",  ""),
            row.get("context", ""),
            row.get("outcome", ""),
        ]))
        scene = " · ".join(filter(None, [
            row.get("scene_location",   ""),
            row.get("scene_atmosphere", ""),
        ]))

        relevant_memories.append({
            "event_id":      eid,
            "content":       content,
            "scene":         scene,
            "time":          row.get("tags_time_period_label", ""),
            "importance":    float(row.get("importance", 0.0)),
            "emotion":       row.get("emotion", ""),
            "freshness_text": freshness_text,
            "source":        item["source"],
        })
        surfaced_ids.append(eid)

    # 11. 更新 access_count
    for eid in surfaced_ids:
        try:
            increment_access_count(agent_id, eid)
        except Exception as e:
            logger.warning(f"retrieve increment_access_count failed {eid[:8]}: {e}")

    # 12. 加强图中共现边
    if len(surfaced_ids) >= 2:
        try:
            graph.strengthen_links_on_retrieval(agent_id, surfaced_ids)
        except Exception as e:
            logger.warning(f"retrieve strengthen_links failed: {e}")

    logger.debug(f"retrieve done agent_id={agent_id} mode={mode} "
                 f"returned={len(relevant_memories)} surfaced={len(surfaced_ids)}")

    return {
        "soul_anchor":       soul_anchor,
        "current_state":     current_state_text,
        "working_context":   working_context,
        "l2_patterns":       l2_patterns,
        "relevant_memories": relevant_memories,
        "surfaced_ids":      surfaced_ids,
    }
