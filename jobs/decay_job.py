import logging
from datetime import datetime, timezone

import config
from core.global_state import read_global_state
from core.memory_l1 import _get_table
from core.weight_engine import WeightEngine

logger = logging.getLogger("decay_job")

_engine = WeightEngine()


def run_decay_job(agent_id: str) -> dict:
    """
    每日执行的 L1 事件衰减任务。

    执行顺序：
    1. 读取 global_state 获取 decay_config
    2. 从 LanceDB 取所有 status=active 或 status=dormant 的事件
    3. 对每条事件计算 days_elapsed（now - created_at）
    4. 调用 weight_engine.compute_decay 更新 decay_score
    5. decay_score < DORMANT_THRESHOLD → status 改为 dormant
    6. decay_score < ARCHIVE_THRESHOLD → status 改为 archived
    7. 逐条更新 LanceDB 中的 decay_score 和 status 字段
    8. TODO: memory_graph.decay_edges(agent_id)（Step 6 实现后补充）
    9. TODO: memory_graph.check_dormant_revival(agent_id)（Step 6 实现后补充）

    返回：{"active": int, "newly_dormant": int, "newly_archived": int, "total_processed": int}
    """
    # 1. 获取 decay_config 和阈值
    state = read_global_state(agent_id)
    decay_config = state.get("decay_config", {})

    dormant_threshold = float(getattr(config, "DORMANT_THRESHOLD", 0.3))
    archive_threshold = float(getattr(config, "ARCHIVE_THRESHOLD", 0.1))

    # 2. 查询 active / dormant 事件
    tbl = _get_table(agent_id)
    rows = (
        tbl.search()
        .where("status = 'active' OR status = 'dormant'")
        .limit(config.L1_MAX_ACTIVE)
        .to_list()
    )

    logger.info(f"run_decay_job agent_id={agent_id} candidates={len(rows)}")

    now = datetime.now()
    stats = {"active": 0, "newly_dormant": 0, "newly_archived": 0, "total_processed": 0}

    for row in rows:
        event_id    = row.get("event_id", "")
        old_status  = row.get("status", "active")
        created_at  = row.get("created_at", "")

        # 3. 计算 days_elapsed
        try:
            dt = datetime.fromisoformat(created_at)
            days_elapsed = max(0, (now - dt).days)
        except Exception:
            days_elapsed = 0

        # 4. 计算新 decay_score
        row["_days_elapsed"] = days_elapsed
        new_decay = _engine.compute_decay(row, days_elapsed, decay_config)

        # 5-6. 判断新 status
        if new_decay < archive_threshold:
            new_status = "archived"
        elif new_decay < dormant_threshold:
            new_status = "dormant"
        else:
            new_status = "active" if old_status == "active" else "dormant"

        # 7. 更新 LanceDB
        tbl.update(
            where=f"event_id = '{event_id}'",
            values={"decay_score": float(new_decay), "status": new_status},
        )

        # 统计
        stats["total_processed"] += 1
        if new_status == "active":
            stats["active"] += 1
        elif new_status == "dormant" and old_status == "active":
            stats["newly_dormant"] += 1
        elif new_status == "archived":
            stats["newly_archived"] += 1

        logger.debug(
            f"decay_job event_id={event_id[:8]} days={days_elapsed} "
            f"decay={new_decay:.4f} {old_status}->{new_status}"
        )

    logger.info(f"run_decay_job agent_id={agent_id} stats={stats}")

    # 8-9. 记忆图：边衰减、检查 dormant 事件复活（边不再有状态）
    try:
        from core.memory_graph import MemoryGraph
        graph = MemoryGraph()
        graph.decay_edges(agent_id)
        revived = graph.check_dormant_revival(agent_id)
        if revived:
            logger.info(f"run_decay_job revived dormant events agent_id={agent_id} count={len(revived)}")
    except Exception as e:
        logger.warning(f"run_decay_job memory_graph steps failed agent_id={agent_id} error={e}")

    return stats
