import json
import logging
import re
from pathlib import Path

from core.llm_client import chat_completion

logger = logging.getLogger("llm_client")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> tuple[str, str]:
    """读取 prompts/ 文件，按 \\n---\\n 分割为 (system, user) 两部分。"""
    text = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()


_SYSTEM_PROMPT, _USER_PROMPT_TEMPLATE = _load_prompt("seed_extract.txt")

# ── Schema 强制填充 ───────────────────────────────────────────────────────────

_SCHEMA: dict = {
    "name": None,
    "age": None,
    "occupation": None,
    "location": None,
    "emotion_core": {
        "base_emotional_type": None,
        "emotional_regulation_style": None,
        "current_emotional_state": None,
    },
    "value_core": {
        "moral_baseline": None,
        "value_priority_order": None,
        "current_value_focus": None,
    },
    "goal_core": {
        "life_direction": None,
        "mid_term_goals": None,
        "current_phase_goal": None,
    },
    "relation_core": {
        "attachment_style": None,
        "key_relationships": None,
        "current_relation_state": None,
    },
}


def _enforce_schema(data: dict, schema: dict) -> dict:
    """递归确保 data 包含 schema 中所有键，缺失填 null。"""
    result = {}
    for key, default in schema.items():
        value = data.get(key)
        if isinstance(default, dict):
            result[key] = _enforce_schema(value if isinstance(value, dict) else {}, default)
        else:
            result[key] = value if value is not None else default
    return result


def _strip_markdown_json(text: str) -> str:
    """去除 LLM 可能返回的 ```json ... ``` 包裹。"""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1)
    return text


# ── 核心接口 ──────────────────────────────────────────────────────────────────

def parse_seed(nodes_json_path: str, agent_id: str) -> dict:
    """
    读取 nodes.json，提取结构化人物信息，写入 data/seeds/{agent_id}/seed.json。
    返回 seed dict。
    """
    # 1. 读取节点，过滤 importance > 0
    with open(nodes_json_path, "r", encoding="utf-8") as f:
        nodes: list[dict] = json.load(f)

    filtered = [n for n in nodes if n.get("importance", 0) > 0]
    logger.info(f"parse_seed agent_id={agent_id} total={len(nodes)} filtered={len(filtered)}")

    # 2. 拼接对话文本（按 node_id 排序保证顺序）
    filtered.sort(key=lambda n: n.get("node_id", 0))
    dialogue = "\n\n".join(n.get("content", "").strip() for n in filtered if n.get("content"))

    if not dialogue:
        logger.warning(f"parse_seed agent_id={agent_id} no dialogue content after filtering")

    # 3. 调用 LLM 提取
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _USER_PROMPT_TEMPLATE.format(name=agent_id, dialogue=dialogue),
        },
    ]
    raw = chat_completion(messages, max_tokens=1024, temperature=0.2)

    # 4. 解析 JSON
    try:
        extracted = json.loads(_strip_markdown_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"parse_seed agent_id={agent_id} json_parse_error={e} raw={raw[:200]}")
        extracted = {}

    # 5. 强制补全 schema，注入 agent_id
    seed = _enforce_schema(extracted, _SCHEMA)
    seed = {"agent_id": agent_id, **seed}

    # 6. 写入文件
    out_dir = Path(__file__).parent.parent / "data" / "seeds" / agent_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "seed.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)

    logger.info(f"parse_seed agent_id={agent_id} written={out_path}")
    return seed
