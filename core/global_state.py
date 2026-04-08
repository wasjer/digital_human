import json
import logging
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger("llm_client")

_AGENTS_DIR = Path(__file__).parent.parent / "data" / "agents"


def _agent_dir(agent_id: str) -> Path:
    d = _AGENTS_DIR / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / "global_state.json"


def _write(agent_id: str, state: dict) -> None:
    with open(_state_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _collect_config(prefix: str) -> dict:
    """从 config 收集所有以 prefix 开头的配置项。"""
    return {k: getattr(config, k) for k in dir(config) if k.startswith(prefix)}


def init_global_state(agent_id: str, personality_params: dict | None = None) -> dict:
    """初始化并写入 global_state.json，返回 state dict。"""
    state = {
        "agent_id": agent_id,
        "updated_at": datetime.now().isoformat(),
        "current_state": {
            "mood": "平稳",        # 当前情绪：平稳 / 轻微波动 / 情绪波动
            "energy": "正常",      # 精力状态：正常 / 低迷 / 充沛
            "stress_level": 0.3,   # 压力水平 0-1，影响记忆检索的 mood_fit 权重
        },
        "personality_params": personality_params or {
            "introversion": 0.7,   # 内向程度 0-1，1 为极度内向
            "risk_aversion": 0.8,  # 风险规避倾向 0-1，1 为极度保守
            "curiosity": 0.5,      # 好奇心强度 0-1
            "empathy": 0.6,        # 共情能力 0-1
        },
        "decay_config": _collect_config("DECAY_"),   # 从 config 同步的衰减参数
        "graph_config": _collect_config("GRAPH_"),   # 从 config 同步的记忆图参数
    }
    _write(agent_id, state)
    logger.info(f"init_global_state agent_id={agent_id}")
    return state


def read_global_state(agent_id: str) -> dict:
    """读取 global_state.json，文件不存在则自动初始化。"""
    path = _state_path(agent_id)
    if not path.exists():
        return init_global_state(agent_id)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_global_state(agent_id: str, field: str, value) -> None:
    """
    更新指定字段，支持点路径（如 "current_state.mood"）。
    路径中间节点不存在时抛出 KeyError。
    """
    state = read_global_state(agent_id)
    parts = field.split(".")
    obj = state
    for part in parts[:-1]:
        if part not in obj:
            raise KeyError(f"global_state: invalid field path segment '{part}' in '{field}'")
        obj = obj[part]
    obj[parts[-1]] = value
    state["updated_at"] = datetime.now().isoformat()
    _write(agent_id, state)
    logger.info(f"update_global_state agent_id={agent_id} field={field}")
