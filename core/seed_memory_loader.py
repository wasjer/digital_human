"""
seed_memory_loader.py

新 agent 完整初始化入口，专为种子数据加载设计的特殊通道：
  1. parse_seed()         → seed.json
  2. 目录骨架初始化       → l0/l2/global_state
  3. Soul 全量初始化      → soul.json（允许推断，不留 null）
  4. 过滤节点
  5. 批量 L1 事件提取     → LLM 一次或分批输出结构化事件
  6. 写入 LanceDB         → 先全 active，建立记忆图边
  7. 按时间更新 status    → archived / dormant / active
  8. L2 生成 + Soul 积分  → l2_patterns.json + Soul 缓变区更新

直接运行：
  python core/seed_memory_loader.py nodes.json 01
  python core/seed_memory_loader.py nodes.json joon_v2 --threshold 50 --force
"""

import sys
from pathlib import Path

# 直接运行时确保项目根目录在 sys.path 中（必须在其他 import 之前）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import logging
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import lancedb
import pyarrow as pa

import config
from core.llm_client import chat_completion, get_embedding
from core.seed_parser import parse_seed
from core.global_state import init_global_state
from core.soul import (
    _build_empty_soul,
    _merge_llm_into_soul,
    _write_soul,
    check_slow_change,
    apply_slow_change,
)
from core.memory_l1 import _get_table
from core.memory_l2 import check_and_generate_patterns, contribute_to_soul

logger = logging.getLogger("seed_memory_loader")

_PROJECT_ROOT = Path(__file__).parent.parent
_AGENTS_DIR   = _PROJECT_ROOT / "data" / "agents"
_SEEDS_DIR    = _PROJECT_ROOT / "data" / "seeds"
_PROMPTS_DIR  = _PROJECT_ROOT / "prompts"

# 初始化特殊通道：不限 token
_INIT_MAX_TOKENS  = 8192
_BATCH_MAX_TOKENS = 8192
_BATCH_NODE_SIZE  = 30   # 单次 LLM 调用最多处理的节点数

# 状态分配阈值（距今天数）
_ARCHIVED_DAYS = 365 * 2   # > 2年 → archived
_DORMANT_DAYS  = 365 * 1   # 1~2年 → dormant
                            # < 1年 → active


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _now() -> str:
    return datetime.now().isoformat()


def _load_prompt(filename: str) -> tuple[str, str]:
    """读取 prompts/ 文件，按 \\n---\\n 分割为 (system, user) 两部分。"""
    text = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()


def _days_since(timestamp_str: str) -> float:
    """计算 timestamp_str 距今天数，解析失败返回 9999。"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return (datetime.now() - dt).days
    except Exception:
        return 9999.0


def _assign_status(inferred_timestamp: str) -> str:
    """按时间远近决定 L1 事件的初始状态。"""
    days = _days_since(inferred_timestamp)
    if days > _ARCHIVED_DAYS:
        return "archived"
    if days > _DORMANT_DAYS:
        return "dormant"
    return "active"


# ── 目录骨架初始化 ────────────────────────────────────────────────────────────

def _setup_agent_dirs(agent_id: str) -> Path:
    """创建 agent 目录结构和空文件骨架，返回 agent_dir。"""
    agent_dir = _AGENTS_DIR / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "memories").mkdir(exist_ok=True)

    # l0_buffer.json
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
    with open(agent_dir / "l0_buffer.json", "w", encoding="utf-8") as f:
        json.dump(l0, f, ensure_ascii=False, indent=2)

    # l2_patterns.json
    with open(agent_dir / "l2_patterns.json", "w", encoding="utf-8") as f:
        json.dump([], f)

    # global_state.json
    init_global_state(agent_id)

    logger.info(f"_setup_agent_dirs agent_id={agent_id} done")
    return agent_dir


# ── Step 3：Soul 全量初始化 ────────────────────────────────────────────────────

def _init_soul_from_nodes(agent_id: str, seed: dict, nodes: list[dict]) -> dict:
    """
    特殊通道：用完整 nodes + seed 初始化 Soul 所有区域，允许推断，不留 null。
    """
    sys_prompt, usr_template = _load_prompt("seed_soul_init.txt")

    nodes_text = "\n\n".join(
        f"[node_{n.get('node_id', i)}] {n.get('content', '').strip()}"
        for i, n in enumerate(nodes)
        if n.get("content")
    )

    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": usr_template.format(
                seed_json=json.dumps(seed, ensure_ascii=False, indent=2),
                nodes_text=nodes_text,
            ),
        },
    ]

    raw = chat_completion(messages, max_tokens=_INIT_MAX_TOKENS, temperature=0.2)
    try:
        llm_data = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_init_soul_from_nodes parse error agent_id={agent_id} e={e} raw={raw[:300]}")
        llm_data = {}

    soul = _build_empty_soul(agent_id)
    soul = _merge_llm_into_soul(soul, llm_data)
    _write_soul(agent_id, soul)
    logger.info(f"_init_soul_from_nodes agent_id={agent_id} soul written")
    return soul


# ── Step 5：批量 L1 事件提取 ──────────────────────────────────────────────────

def _extract_events_batch(agent_name: str, nodes: list[dict]) -> list[dict]:
    """
    将 nodes 分批发送给 LLM，汇总返回结构化事件列表。
    每批最多 _BATCH_NODE_SIZE 个节点。
    """
    sys_prompt, usr_template = _load_prompt("seed_batch_load.txt")
    current_year = datetime.now().year
    all_events: list[dict] = []

    for batch_start in range(0, len(nodes), _BATCH_NODE_SIZE):
        batch = nodes[batch_start: batch_start + _BATCH_NODE_SIZE]
        nodes_text = "\n\n".join(
            f"[node_{n.get('node_id', batch_start + i)}]\n{n.get('content', '').strip()}"
            for i, n in enumerate(batch)
            if n.get("content")
        )
        if not nodes_text.strip():
            continue

        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": usr_template.format(
                    agent_name=agent_name,
                    current_year=current_year,
                    nodes_text=nodes_text,
                ),
            },
        ]

        raw = chat_completion(messages, max_tokens=_BATCH_MAX_TOKENS, temperature=0.2)
        try:
            batch_events = json.loads(_strip_json(raw))
            if isinstance(batch_events, list):
                all_events.extend(batch_events)
                logger.info(
                    f"_extract_events_batch batch={batch_start//_BATCH_NODE_SIZE + 1} "
                    f"extracted={len(batch_events)} events"
                )
            else:
                logger.warning(f"_extract_events_batch unexpected output type: {type(batch_events)}")
        except json.JSONDecodeError as e:
            logger.error(f"_extract_events_batch parse error batch={batch_start} e={e} raw={raw[:300]}")

    logger.info(f"_extract_events_batch total extracted={len(all_events)}")
    return all_events


# ── Step 6：写入 LanceDB ──────────────────────────────────────────────────────

def _write_events_to_l1(agent_id: str, agent_name: str, events: list[dict]) -> list[tuple[str, str]]:
    """
    写入所有事件到 LanceDB。初始状态全部为 active（Step 7 再更新）。
    返回 [(event_id, inferred_timestamp), ...] 供后续状态更新。
    """
    tbl = _get_table(agent_id)
    now_str = _now()
    written: list[tuple[str, str]] = []

    for ev in events:
        event_id = str(uuid.uuid4())
        inferred_ts = ev.get("inferred_timestamp") or now_str

        # importance 确保是 float
        importance = float(ev.get("importance") or 0.0)
        if importance == 0.0:
            ei = float(ev.get("emotion_intensity_score") or ev.get("emotion_intensity") or 0.0)
            vr = float(ev.get("value_relevance_score") or 0.0)
            nv = float(ev.get("novelty_score") or 0.0)
            ru = float(ev.get("reusability_score") or 0.0)
            importance = ei * 0.3 + vr * 0.3 + nv * 0.2 + ru * 0.2

        tags_people = ev.get("tags_people") or []
        tags_topic  = ev.get("tags_topic")  or []

        try:
            embed_text = f"{ev.get('action', '')} {ev.get('context', '')} {ev.get('outcome', '')}"
            vector = get_embedding(embed_text)

            row = {
                "vector":                       [float(x) for x in vector],
                "event_id":                     event_id,
                "agent_id":                     agent_id,
                "timestamp":                    inferred_ts,
                "created_at":                   now_str,
                "actor":                        str(ev.get("actor") or agent_name),
                "action":                       str(ev.get("action") or ""),
                "context":                      str(ev.get("context") or ""),
                "outcome":                      str(ev.get("outcome") or ""),
                "scene_location":               str(ev.get("scene_location") or ""),
                "scene_atmosphere":             str(ev.get("scene_atmosphere") or ""),
                "scene_sensory_notes":          str(ev.get("scene_sensory_notes") or ""),
                "scene_subjective_experience":  str(ev.get("scene_subjective_experience") or ""),
                "emotion":                      str(ev.get("emotion") or ""),
                "emotion_intensity":            float(ev.get("emotion_intensity") or 0.0),
                "importance":                   float(importance),
                "emotion_intensity_score":      float(ev.get("emotion_intensity_score") or ev.get("emotion_intensity") or 0.0),
                "value_relevance_score":        float(ev.get("value_relevance_score") or 0.0),
                "novelty_score":                float(ev.get("novelty_score") or 0.0),
                "reusability_score":            float(ev.get("reusability_score") or 0.0),
                "is_derivable_score":           0.0,
                "decay_score":                  1.0,
                "access_count":                 0,
                "status":                       "active",   # Step 7 统一更新
                "tags_time_year":               int(ev.get("tags_time_year") or datetime.now().year),
                "tags_time_month":              int(ev.get("tags_time_month") or 0),
                "tags_time_week":               int(ev.get("tags_time_week") or 0),
                "tags_time_period_label":       str(ev.get("tags_time_period_label") or ""),
                "tags_people":                  json.dumps(tags_people, ensure_ascii=False),
                "tags_topic":                   json.dumps(tags_topic,  ensure_ascii=False),
                "tags_emotion_valence":         str(ev.get("tags_emotion_valence") or ""),
                "tags_emotion_label":           str(ev.get("tags_emotion_label") or ""),
                "source":                       "seed",
                "ttl_days":                     365 * 10,   # 种子记忆长期保留
                "raw_quote":                    str(ev.get("raw_quote") or ""),
                "event_kind":                   str(ev.get("event_kind") or "biography"),
            }
            tbl.add([row])
            written.append((event_id, inferred_ts))
            logger.info(f"_write_events_to_l1 event_id={event_id} importance={importance:.3f} ts={inferred_ts}")
        except Exception as e:
            logger.error(f"_write_events_to_l1 skip event={ev.get('action','')[:40]} error={e}")

    logger.info(f"_write_events_to_l1 written={len(written)}/{len(events)}")
    return written


# ── Step 6b：建立记忆图边 ─────────────────────────────────────────────────────

def _build_graph(agent_id: str, written: list[tuple[str, str]]) -> None:
    """对所有已写入的事件逐一建立记忆图关联边。"""
    try:
        from core.memory_graph import MemoryGraph
        from core.memory_l1 import get_event
        graph = MemoryGraph()
        for event_id, _ in written:
            ev = get_event(agent_id, event_id)
            vector = ev.get("vector")
            if not vector:
                continue
            graph.create_links_on_write(agent_id, event_id, vector)
    except Exception as e:
        logger.warning(f"_build_graph agent_id={agent_id} error={e}")


# ── Step 7：按时间更新 status ─────────────────────────────────────────────────

def _update_statuses(agent_id: str, written: list[tuple[str, str]]) -> dict:
    """批量更新 L1 事件状态，返回 status 分布统计。"""
    from core.memory_l1 import update_event_status

    counter = {"active": 0, "dormant": 0, "archived": 0}
    for event_id, inferred_ts in written:
        status = _assign_status(inferred_ts)
        if status != "active":   # active 是写入时的默认值，不需要再更新
            update_event_status(agent_id, event_id, status)
        counter[status] += 1

    logger.info(f"_update_statuses agent_id={agent_id} distribution={counter}")
    return counter


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def load_agent_from_nodes(
    nodes_json_path: str,
    agent_id: str,
    importance_threshold: int = 60,
    force: bool = False,
) -> dict:
    """
    新 agent 完整初始化入口。

    参数：
        nodes_json_path:     nodes.json 文件路径
        agent_id:            agent 唯一标识（如 "01"、"joon_v2"）
        importance_threshold: 过滤节点的 importance 阈值（默认 60）
        force:               True 时删除已有 agent 数据并重建

    返回：
        初始化摘要 dict
    """
    agent_dir   = _AGENTS_DIR / agent_id
    seed_dir    = _SEEDS_DIR / agent_id

    # ── 幂等性检查 ──
    if agent_dir.exists() or seed_dir.exists():
        if not force:
            raise RuntimeError(
                f"agent_id='{agent_id}' 已存在。"
                f"如需重建，请传入 force=True。"
            )
        logger.warning(f"load_agent_from_nodes force=True，删除旧数据 agent_id={agent_id}")
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        if seed_dir.exists():
            shutil.rmtree(seed_dir)

    logger.info(f"load_agent_from_nodes START agent_id={agent_id}")
    start_time = datetime.now()

    # ── Step 1：parse_seed ──
    logger.info("Step 1/8: parse_seed")
    seed = parse_seed(nodes_json_path, agent_id)
    agent_name = seed.get("name") or agent_id

    # ── Step 2：目录骨架 ──
    logger.info("Step 2/8: setup dirs")
    _setup_agent_dirs(agent_id)

    # ── Step 3：Soul 全量初始化 ──
    logger.info("Step 3/8: Soul init from nodes")
    with open(nodes_json_path, "r", encoding="utf-8") as f:
        all_nodes: list[dict] = json.load(f)
    _init_soul_from_nodes(agent_id, seed, all_nodes)

    # ── Step 4：过滤节点 ──
    logger.info(f"Step 4/8: filter nodes importance>={importance_threshold}")
    filtered_nodes = [
        n for n in all_nodes
        if n.get("importance", 0) >= importance_threshold and n.get("content")
    ]
    filtered_nodes.sort(key=lambda n: n.get("node_id", 0))
    logger.info(f"filtered {len(filtered_nodes)}/{len(all_nodes)} nodes")

    # ── Step 5：批量 L1 提取 ──
    logger.info("Step 5/8: batch L1 extract")
    events = _extract_events_batch(agent_name, filtered_nodes)

    # ── Step 6：写入 LanceDB ──
    logger.info(f"Step 6/8: write {len(events)} events to L1")
    written = _write_events_to_l1(agent_id, agent_name, events)

    # ── Step 6b：建立记忆图 ──
    logger.info("Step 6b/8: build memory graph")
    _build_graph(agent_id, written)

    # ── Step 7：更新状态 ──
    logger.info("Step 7/8: update L1 statuses")
    status_dist = _update_statuses(agent_id, written)

    # ── Step 8：L2 生成 + Soul 积分 ──
    logger.info("Step 8/8: L2 patterns + Soul evidence")
    l2_updated = check_and_generate_patterns(agent_id)
    soul_contributions = contribute_to_soul(agent_id)

    # 检查 Soul 缓变区是否触发更新
    triggered = check_slow_change(agent_id)
    for item in triggered:
        apply_slow_change(agent_id, item["core"], item["field"], item["current_value"])
        logger.info(
            f"apply_slow_change core={item['core']} field={item['field']} "
            f"evidence_score={item['evidence_score']:.3f}"
        )

    elapsed = (datetime.now() - start_time).seconds
    summary = {
        "agent_id":           agent_id,
        "agent_name":         agent_name,
        "nodes_total":        len(all_nodes),
        "nodes_filtered":     len(filtered_nodes),
        "l1_events_written":  len(written),
        "l1_status_dist":     status_dist,
        "l2_patterns_created": len(l2_updated),
        "soul_contributions": len(soul_contributions),
        "soul_slow_change_triggered": len(triggered),
        "elapsed_seconds":    elapsed,
    }

    logger.info(f"load_agent_from_nodes DONE agent_id={agent_id} summary={summary}")
    print("\n=== 初始化完成 ===")
    print(f"  Agent:        {agent_id} ({agent_name})")
    print(f"  L1 事件:      {len(written)} 条  {status_dist}")
    print(f"  L2 patterns:  {len(l2_updated)} 条")
    print(f"  Soul 积分贡献: {len(soul_contributions)} 次")
    print(f"  缓变区更新:   {len(triggered)} 个字段")
    print(f"  耗时:         {elapsed}s")

    return summary


# ── 命令行入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="从 nodes.json 创建新的数字人 Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python core/seed_memory_loader.py nodes.json 01
  python core/seed_memory_loader.py nodes.json joon_v2 --threshold 50
  python core/seed_memory_loader.py nodes.json 01 --force
        """,
    )
    parser.add_argument("nodes_json", help="nodes.json 文件路径")
    parser.add_argument("agent_id",   help="新 agent 的唯一标识（如 01、joon_v2）")
    parser.add_argument(
        "--threshold", "-t",
        type=int, default=60,
        help="节点 importance 过滤阈值（默认 60）",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="如果 agent 已存在，强制删除并重建",
    )

    args = parser.parse_args()

    if not os.path.exists(args.nodes_json):
        print(f"错误：找不到文件 {args.nodes_json}", file=sys.stderr)
        sys.exit(1)

    try:
        load_agent_from_nodes(
            nodes_json_path=args.nodes_json,
            agent_id=args.agent_id,
            importance_threshold=args.threshold,
            force=args.force,
        )
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
