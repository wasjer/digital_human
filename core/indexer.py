import logging
from pathlib import Path

import lancedb

import config
from core.memory_l1 import _get_table

logger = logging.getLogger("indexer")


def query(
    agent_id: str,
    people: str | None = None,
    time_year: int | None = None,
    time_month: int | None = None,
    topic: str | None = None,
    emotion_valence: str | None = None,
    min_importance: float | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    LanceDB metadata filter 查询封装。

    - people  : 匹配 tags_people（JSON 字符串包含匹配）
    - topic   : 匹配 tags_topic（JSON 字符串包含匹配）
    - 其余字段: 精确或范围匹配
    返回事件 dict 列表。
    """
    tbl = _get_table(agent_id)

    conditions: list[str] = []

    if people is not None:
        escaped = people.replace("'", "''")
        conditions.append(f"tags_people LIKE '%{escaped}%'")

    if topic is not None:
        escaped = topic.replace("'", "''")
        conditions.append(f"tags_topic LIKE '%{escaped}%'")

    if time_year is not None:
        conditions.append(f"tags_time_year = {int(time_year)}")

    if time_month is not None:
        conditions.append(f"tags_time_month = {int(time_month)}")

    if emotion_valence is not None:
        escaped = emotion_valence.replace("'", "''")
        conditions.append(f"tags_emotion_valence = '{escaped}'")

    if min_importance is not None:
        conditions.append(f"importance >= {float(min_importance)}")

    if status is not None:
        escaped = status.replace("'", "''")
        conditions.append(f"status = '{escaped}'")

    where_clause = " AND ".join(conditions) if conditions else None

    try:
        q = tbl.search()
        if where_clause:
            q = q.where(where_clause)
        rows = q.limit(limit).to_list()
        logger.info(
            f"indexer.query agent_id={agent_id} filters={len(conditions)} "
            f"where={where_clause!r} results={len(rows)}"
        )
        return rows
    except Exception as e:
        logger.error(f"indexer.query agent_id={agent_id} error={e}")
        return []
