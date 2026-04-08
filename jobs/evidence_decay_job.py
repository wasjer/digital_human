import logging

from core.soul import decay_evidence, read_soul, CORES, _CORE_FIELDS

logger = logging.getLogger("evidence_decay_job")


def run_evidence_decay_job(agent_id: str) -> dict:
    """
    对 soul.json 所有缓变区执行 evidence_score 每日衰减。
    调用 soul.decay_evidence(agent_id)。

    返回：{"cores_processed": int, "fields_decayed": int}
    """
    decay_evidence(agent_id)

    # 统计处理的核心数和字段数
    soul = read_soul(agent_id)
    fields_decayed = sum(
        len(_CORE_FIELDS[core]["slow_change"]) for core in CORES
    )
    stats = {
        "cores_processed": len(CORES),
        "fields_decayed": fields_decayed,
    }
    logger.info(f"run_evidence_decay_job agent_id={agent_id} stats={stats}")
    return stats
