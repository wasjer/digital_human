import json
import logging
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

import config
from core.llm_client import chat_completion
from core.soul import (
    get_soul_anchor, read_soul,
    update_elastic, add_evidence, check_slow_change, apply_slow_change,
)
from core.global_state import read_global_state
from core.memory_l1 import write_event
from core.retrieval import retrieve
from core import trace

logger = logging.getLogger("dialogue")

_AGENTS_DIR  = Path(__file__).parent.parent / "data" / "agents"
_SEEDS_DIR   = Path(__file__).parent.parent / "data" / "seeds"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ── Prompt 加载 ───────────────────────────────────────────────────────────────

def _load_prompt(filename: str) -> tuple[str, str]:
    text = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()

_EMOTION_SYS,  _EMOTION_USR  = _load_prompt("detect_emotion.txt")
_EVIDENCE_SYS, _EVIDENCE_USR = _load_prompt("soul_evidence_check.txt")
_DIALOGUE_TPL                = (_PROMPTS_DIR / "dialogue_system.txt").read_text(encoding="utf-8")
_DECISION_TPL                = (_PROMPTS_DIR / "decision_system.txt").read_text(encoding="utf-8")
_SMALLTALK_SYS, _SMALLTALK_USR = _load_prompt("smalltalk_detect.txt")

# ── L0 buffer 工具 ────────────────────────────────────────────────────────────

def _l0_path(agent_id: str) -> Path:
    return _AGENTS_DIR / agent_id / "l0_buffer.json"

def _load_l0(agent_id: str) -> dict:
    p = _l0_path(agent_id)
    if not p.exists():
        return _empty_l0(agent_id)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_l0(agent_id: str, buf: dict) -> None:
    with open(_l0_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(buf, f, ensure_ascii=False, indent=2)

def _empty_l0(agent_id: str) -> dict:
    return {
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

# ── 基本信息 ──────────────────────────────────────────────────────────────────

def _get_agent_info(agent_id: str) -> dict:
    """优先从 seed.json 读取 name/age/occupation/location，失败则返回默认值。"""
    seed_path = _SEEDS_DIR / agent_id / "seed.json"
    if seed_path.exists():
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "name":       str(data.get("name", agent_id)),
                "age":        str(data.get("age", "")),
                "occupation": str(data.get("occupation", "")),
                "location":   str(data.get("location", "")),
            }
        except Exception:
            pass
    return {"name": agent_id, "age": "", "occupation": "", "location": ""}

# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return m.group(1) if m else text

def _detect_emotion(user_message: str) -> float:
    """调用 LLM 检测 user_message 的 emotion_intensity（0-1）。"""
    user = _EMOTION_USR.format(user_message=user_message)
    try:
        raw = chat_completion(
            [{"role": "system", "content": _EMOTION_SYS},
             {"role": "user",   "content": user}],
            max_tokens=16,
            temperature=0.0,
        )
        return max(0.0, min(1.0, float(raw.strip())))
    except Exception as e:
        logger.warning(f"_detect_emotion failed: {e}")
        return 0.0

def _format_memories_for_prompt(memories: list) -> str:
    if not memories:
        return "（暂无相关记忆）"
    lines = []
    for i, m in enumerate(memories, 1):
        content    = m.get("content", "")[:80]
        importance = m.get("importance", 0.0)
        emotion    = m.get("emotion", "")
        freshness  = m.get("freshness_text", "")
        scene      = m.get("scene", "")[:30]
        line = f"{i}. [重要度:{importance:.2f}] [情绪:{emotion}] {content}"
        if scene:
            line += f" | {scene}"
        if freshness:
            line += f" {freshness}"
        lines.append(line)
    return "\n".join(lines)

def _now() -> str:
    return datetime.now().isoformat()

_SMALLTALK_KEYWORDS = {"你好", "您好", "早", "早上好", "晚安", "嗨", "hi", "hello"}
_FAREWELL_KEYWORDS  = {"再见", "拜拜", "下次", "先这样", "bye", "goodbye"}


def _classify_smalltalk(user_message: str) -> str:
    """返回 'smalltalk' / 'farewell' / 'substantive'。
    硬编码关键词优先；否则 1 次 LLM 快判。"""
    msg = user_message.strip().lower()
    if not msg:
        return "substantive"
    if len(msg) <= 6:
        for kw in _SMALLTALK_KEYWORDS:
            if msg.startswith(kw) or msg == kw:
                return "smalltalk"
        for kw in _FAREWELL_KEYWORDS:
            if msg.startswith(kw) or msg == kw:
                return "farewell"
    try:
        raw = chat_completion(
            [{"role": "system", "content": _SMALLTALK_SYS},
             {"role": "user",   "content": _SMALLTALK_USR.format(user_message=user_message)}],
            max_tokens=4,
            temperature=0.0,
        ).strip().lower()
        if raw in ("smalltalk", "farewell", "substantive"):
            return raw
    except Exception as e:
        logger.warning(f"_classify_smalltalk failed: {e}")
    return "substantive"


def _smalltalk_reply(agent_id: str, user_message: str, kind: str,
                     session_history: list) -> str:
    """不走 retrieve / soul_anchor，直接轻量 prompt 生成。"""
    info = _get_agent_info(agent_id)
    system = (
        f"你是 {info['name']}。用户和你打招呼/告别，简短自然地回一句（1-2 句，口语化）。"
        f"不要展开话题，不要反问太深。"
    )
    messages = [{"role": "system", "content": system}]
    for msg in session_history[-4:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})
    try:
        return chat_completion(messages, max_tokens=80, temperature=0.6)
    except Exception as e:
        logger.warning(f"_smalltalk_reply fallback: {e}")
        return "嗯。" if kind == "smalltalk" else "回头聊。"


# ── chat() ────────────────────────────────────────────────────────────────────

def chat(agent_id: str, user_message: str,
         session_history: list) -> dict:
    """
    单轮对话。
    session_history: list[{"role": str, "content": str}]  已有对话历史（不含本轮）
    返回：{"reply": str, "emotion_intensity": float}
    """
    # ── 0. smalltalk 旁路 ──
    kind = _classify_smalltalk(user_message)
    if kind in ("smalltalk", "farewell"):
        trace.mark("smalltalk_bypass", summary=kind)
        buf = _load_l0(agent_id)
        if not buf.get("session_id"):
            buf["session_id"] = str(uuid.uuid4())
            buf["created_at"] = _now()
        buf["raw_dialogue"].append({"role": "user", "content": user_message})
        _save_l0(agent_id, buf)

        reply = _smalltalk_reply(agent_id, user_message, kind, session_history)

        buf = _load_l0(agent_id)
        buf["raw_dialogue"].append({"role": "assistant", "content": reply})
        _save_l0(agent_id, buf)
        return {
            "reply":             reply,
            "emotion_intensity": 0.0,
        }

    # ── 1. 情绪检测 ───────────────────────────────────────────────────────────
    emotion_intensity = _detect_emotion(user_message)
    trace.mark("情绪检测", summary=f"{emotion_intensity:.2f}")

    # ── 2. 情绪峰值快照 ────────────────────────────────────────────────────────
    buf = _load_l0(agent_id)
    if not buf.get("session_id"):
        buf["session_id"] = str(uuid.uuid4())
        buf["created_at"] = _now()

    if emotion_intensity > config.EMOTION_SNAPSHOT_THRESHOLD:
        snapshot = {
            "trigger_message":   user_message,
            "emotion_intensity": emotion_intensity,
            "context":           session_history[-2:],
            "timestamp":         _now(),
        }
        buf["emotion_snapshots"].append(snapshot)
        logger.info(f"chat emotion_snapshot saved intensity={emotion_intensity:.3f}")

    # ── 3. 检索相关记忆 ────────────────────────────────────────────────────────
    retrieval_result = retrieve(agent_id, user_message, mode="dialogue")
    trace.mark("记忆检索")

    # ── 5. 追加 user 消息到 l0_buffer ─────────────────────────────────────────
    buf["raw_dialogue"].append({"role": "user", "content": user_message})
    _save_l0(agent_id, buf)

    # ── 6. 构建 system prompt ──────────────────────────────────────────────────
    info           = _get_agent_info(agent_id)
    memories_block = "【相关记忆】\n" + _format_memories_for_prompt(
        retrieval_result["relevant_memories"]
    )
    l2_block = ""
    if retrieval_result.get("l2_patterns"):
        l2_block = f"【行为模式摘要】\n{retrieval_result['l2_patterns']}"

    system_prompt = _DIALOGUE_TPL.format(
        name=info["name"],
        age=info["age"],
        occupation=info["occupation"],
        location=info["location"],
        soul_anchor=retrieval_result["soul_anchor"],
        current_state=retrieval_result["current_state"],
        l2_patterns_block=l2_block,
        memories_block=memories_block,
        user_message=user_message,
    )
    trace.mark(
        "构造 prompt",
        summary=(
            f"system {len(system_prompt)} 字 / 历史 {min(6, len(session_history))} 轮 / "
            f"记忆 {len(retrieval_result['relevant_memories'])} 条"
        ),
    )

    # ── 7. LLM 生成回答 ────────────────────────────────────────────────────────
    messages = [{"role": "system", "content": system_prompt}]
    for msg in session_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        reply = chat_completion(messages, max_tokens=512, temperature=0.7)
    except Exception as e:
        logger.error(f"chat LLM generation failed: {e}")
        reply = "（系统错误，无法生成回复）"
    trace.mark("对话生成")

    # ── 8. 追加 assistant 消息到 l0_buffer ────────────────────────────────────
    buf = _load_l0(agent_id)
    buf["raw_dialogue"].append({"role": "assistant", "content": reply})
    _save_l0(agent_id, buf)

    return {
        "reply":             reply,
        "emotion_intensity": emotion_intensity,
    }

# ── end_session() ─────────────────────────────────────────────────────────────

def _end_session_sync(agent_id: str, session_history: list):
    """
    同步部分：把本次会话写入 L1，清空 l0_buffer。
    返回 (session_text, session_id, emotion_snaps) 供异步使用。
    """
    buf           = _load_l0(agent_id)
    raw_dialogue  = buf.get("raw_dialogue", [])
    emotion_snaps = buf.get("emotion_snapshots", [])
    session_id    = buf.get("session_id") or str(uuid.uuid4())

    # 拼接完整会话文本（emotion_snapshots 优先放前面）
    lines = []
    if emotion_snaps:
        lines.append("【情绪峰值时刻】")
        for snap in emotion_snaps:
            lines.append(
                f"情绪强度{snap.get('emotion_intensity', 0):.2f}："
                f"{snap.get('trigger_message', '')}"
            )

    source = raw_dialogue if raw_dialogue else session_history
    if source:
        lines.append("【完整对话】")
        for msg in source:
            lines.append(f"{msg.get('role', '')}: {msg.get('content', '')}")

    session_text = "\n".join(lines)

    if session_text.strip():
        try:
            write_event(agent_id, session_text, source="session")
            logger.info(f"_end_session_sync write_event done agent_id={agent_id}")
        except Exception as e:
            logger.error(f"_end_session_sync write_event failed: {e}")

    _save_l0(agent_id, _empty_l0(agent_id))
    logger.info(f"_end_session_sync l0_buffer cleared agent_id={agent_id}")

    return session_text, session_id, emotion_snaps


def _end_session_async(agent_id: str, session_text: str,
                       session_id: str, emotion_snaps: list):
    """
    异步后台部分：更新 soul 弹性区、证据检查、缓变区更新、L2。
    内部任何异常均不向上抛出（含 import 失败）。
    """
    try:
        _end_session_async_body(agent_id, session_text, session_id, emotion_snaps)
    except Exception as e:
        logger.error(f"_end_session_async top-level guard caught: {e}")


def _end_session_async_body(agent_id: str, session_text: str,
                            session_id: str, emotion_snaps: list):
    # ── 1. update_elastic：根据情绪快照推断当前情绪状态 ──────────────────────
    try:
        if emotion_snaps:
            max_intensity = max(s.get("emotion_intensity", 0) for s in emotion_snaps)
            state = "情绪波动" if max_intensity > 0.6 else "轻微波动"
        else:
            state = "平稳"
        update_elastic(agent_id, "emotion_core", "current_emotional_state", state)
        logger.info(f"_end_session_async update_elastic state={state}")
    except Exception as e:
        logger.warning(f"_end_session_async update_elastic failed: {e}")

    # ── 2. soul_evidence_check ────────────────────────────────────────────────
    try:
        evidence_user = _EVIDENCE_USR.format(session_text=session_text)
        raw = chat_completion(
            [{"role": "system", "content": _EVIDENCE_SYS},
             {"role": "user",   "content": evidence_user}],
            max_tokens=256,
            temperature=0.1,
        )
        ev = json.loads(_strip_json(raw))
        logger.info(
            f"_end_session_async evidence is_evidence={ev.get('is_evidence')} "
            f"core={ev.get('core')} field={ev.get('field')} score={ev.get('score')}"
        )

        # ── 3. add_evidence ───────────────────────────────────────────────────
        if ev.get("is_evidence") and ev.get("core") and ev.get("field"):
            add_evidence(
                agent_id,
                core=ev["core"],
                field=ev["field"],
                score=float(ev.get("score", 0.1)),
                reason=ev.get("reason", ""),
                session_id=session_id,
            )
    except Exception as e:
        logger.warning(f"_end_session_async evidence_check failed: {e}")

    # ── 4. check_slow_change → generate new value → apply_slow_change ────────
    try:
        triggered = check_slow_change(agent_id)
        for item in triggered:
            try:
                new_val = chat_completion(
                    [
                        {"role": "system", "content":
                            "根据对话证据，为人格缓变字段生成一个新的描述值。"
                            "只输出新值文本，20字以内，不含任何其他内容。"},
                        {"role": "user", "content":
                            f"字段：{item['core']}.{item['field']}\n"
                            f"当前值：{item['current_value']}\n"
                            f"累积证据分：{item['evidence_score']:.2f}\n"
                            f"相关对话（节选）：{session_text[:400]}\n"
                            f"新值："},
                    ],
                    max_tokens=64,
                    temperature=0.3,
                ).strip()
                apply_slow_change(agent_id, item["core"], item["field"], new_val)
                logger.info(
                    f"_end_session_async slow_change "
                    f"{item['core']}.{item['field']} -> {new_val!r}"
                )
            except Exception as e:
                logger.warning(
                    f"_end_session_async apply_slow_change failed "
                    f"{item['core']}.{item['field']}: {e}"
                )
    except Exception as e:
        logger.warning(f"_end_session_async check_slow_change failed: {e}")

    # ── 5. memory_l2 ─────────────────────────────────────────────────────────
    try:
        from core.memory_l2 import check_and_generate_patterns, contribute_to_soul
        check_and_generate_patterns(agent_id)
        contribute_to_soul(agent_id)
    except Exception as e:
        logger.warning(f"_end_session_async memory_l2 failed: {e}")


def end_session(agent_id: str, session_history: list, wait_async: bool = False) -> None:
    """
    结束会话：同步写入 L1 + 清空 l0_buffer，后台异步更新 soul。
    默认立即返回，不等待异步完成。wait_async=True 时阻塞到异步完成
    （benchmark/离线任务用，避免主进程退出时 daemon 线程被 kill）。
    """
    session_text, session_id, emotion_snaps = _end_session_sync(agent_id, session_history)

    t = threading.Thread(
        target=_end_session_async,
        args=(agent_id, session_text, session_id, emotion_snaps),
        daemon=True,
    )
    t.start()
    logger.info(f"end_session async thread started agent_id={agent_id}")

    if wait_async:
        t.join()
        logger.info(f"end_session async thread joined agent_id={agent_id}")


# ── make_decision() ───────────────────────────────────────────────────────────

def make_decision(agent_id: str, scenario: str) -> dict:
    """
    decision 模式检索 + LLM 生成决策和推理。
    返回：{"decision": str, "reasoning": str, "relevant_memories_used": list[str]}
    """
    # 1. decision 模式检索
    result = retrieve(agent_id, scenario, mode="decision")

    # 2. 构建决策 prompt
    info           = _get_agent_info(agent_id)
    memories_block = "【参考记忆】\n" + _format_memories_for_prompt(result["relevant_memories"])

    decision_prompt = _DECISION_TPL.format(
        name=info["name"],
        age=info["age"],
        occupation=info["occupation"],
        location=info["location"],
        soul_anchor=result["soul_anchor"],
        current_state=result["current_state"],
        memories_block=memories_block,
        scenario=scenario,
    )

    # 3. LLM 生成决策
    try:
        raw = chat_completion(
            [{"role": "system", "content": decision_prompt},
             {"role": "user",   "content": scenario}],
            max_tokens=512,
            temperature=0.4,
        )
        parsed    = json.loads(_strip_json(raw))
        decision  = parsed.get("decision", "")
        reasoning = parsed.get("reasoning", "")
    except Exception:
        decision  = raw.strip() if "raw" in dir() else "无法生成决策"
        reasoning = ""

    logger.info(f"make_decision done agent_id={agent_id} "
                f"memories_used={len(result['surfaced_ids'])}")

    return {
        "decision":               decision,
        "reasoning":              reasoning,
        "relevant_memories_used": result["surfaced_ids"],
    }
