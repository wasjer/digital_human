import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import config
from core.global_state import read_global_state
from core.memory_l1 import _get_table, get_event, update_event_status

logger = logging.getLogger("memory_graph")

_AGENTS_DIR = Path(__file__).parent.parent / "data" / "agents"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_links (
    link_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    activation_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_activated TEXT,
    status TEXT DEFAULT 'active',
    UNIQUE(agent_id, source_event_id, target_event_id)
);
CREATE INDEX IF NOT EXISTS idx_links_source
    ON memory_links(agent_id, source_event_id, status);
CREATE INDEX IF NOT EXISTS idx_links_target
    ON memory_links(agent_id, target_event_id, status);
"""


def _db_path(agent_id: str) -> Path:
    d = _AGENTS_DIR / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "graph.db"


def _get_conn(agent_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(agent_id)))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLE_SQL)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now().isoformat()


def _cosine_sim(a, b) -> float:
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class MemoryGraph:

    def create_links_on_write(self, agent_id: str, new_event_id: str, new_embedding) -> int:
        """
        写入时建边。
        取最近 GRAPH_BUILD_EDGE_TOP_N 条 active 事件的 embedding，
        计算余弦相似度，> GRAPH_BUILD_EDGE_SIMILARITY_THRESHOLD 则建边。
        strength = 相似度值。
        返回新建边数。
        """
        top_n = config.GRAPH_BUILD_EDGE_TOP_N
        threshold = config.GRAPH_BUILD_EDGE_SIMILARITY_THRESHOLD

        # 取最近 top_n 条 active 事件（排除刚写入的自身）
        tbl = _get_table(agent_id)
        try:
            rows = (
                tbl.search()
                .where(f"status = 'active' AND event_id != '{new_event_id}'")
                .limit(top_n * 4)
                .to_list()
            )
        except Exception as e:
            logger.warning(f"create_links_on_write fetch failed agent_id={agent_id} error={e}")
            return 0

        # 按 created_at 倒序取最近 top_n 条
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        rows = rows[:top_n]

        if not rows:
            return 0

        created = 0
        now_str = _now()
        conn = _get_conn(agent_id)
        try:
            for row in rows:
                existing_id = row.get("event_id", "")
                vector = row.get("vector")
                if not vector or not existing_id:
                    continue
                sim = _cosine_sim(new_embedding, vector)
                if sim <= threshold:
                    continue
                link_id = str(uuid.uuid4())
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO memory_links
                        (link_id, agent_id, source_event_id, target_event_id,
                         strength, activation_count, created_at, last_activated, status)
                        VALUES (?, ?, ?, ?, ?, 0, ?, NULL, 'active')
                        """,
                        (link_id, agent_id, new_event_id, existing_id, sim, now_str),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] > 0:
                        created += 1
                        logger.debug(
                            f"create_links_on_write link {new_event_id[:8]}<->{existing_id[:8]} sim={sim:.3f}"
                        )
                except sqlite3.Error as e:
                    logger.warning(f"create_links_on_write insert error: {e}")
            conn.commit()
        finally:
            conn.close()

        logger.info(f"create_links_on_write agent_id={agent_id} new_event={new_event_id[:8]} created={created}")
        return created

    def strengthen_links_on_retrieval(self, agent_id: str, retrieved_event_ids: list) -> int:
        """
        检索时加强共现边。
        retrieved_event_ids 两两之间：
          已有边 → strength += increment，activation_count += 1
          无边   → 建新边，strength = increment
        strength 上限 1.0。
        返回更新边数。
        """
        increment = config.GRAPH_RETRIEVAL_STRENGTHEN_INCREMENT
        ids = list(retrieved_event_ids)
        if len(ids) < 2:
            return 0

        updated = 0
        now_str = _now()
        conn = _get_conn(agent_id)
        try:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    src, tgt = ids[i], ids[j]
                    # Check both directions
                    row = conn.execute(
                        """
                        SELECT link_id, strength, activation_count FROM memory_links
                        WHERE agent_id = ?
                          AND ((source_event_id = ? AND target_event_id = ?)
                            OR (source_event_id = ? AND target_event_id = ?))
                        LIMIT 1
                        """,
                        (agent_id, src, tgt, tgt, src),
                    ).fetchone()

                    if row:
                        new_strength = min(1.0, row["strength"] + increment)
                        conn.execute(
                            """
                            UPDATE memory_links
                            SET strength = ?, activation_count = activation_count + 1,
                                last_activated = ?
                            WHERE link_id = ?
                            """,
                            (new_strength, now_str, row["link_id"]),
                        )
                        updated += 1
                    else:
                        link_id = str(uuid.uuid4())
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO memory_links
                            (link_id, agent_id, source_event_id, target_event_id,
                             strength, activation_count, created_at, last_activated, status)
                            VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'active')
                            """,
                            (link_id, agent_id, src, tgt, min(1.0, increment), now_str, now_str),
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            updated += 1

            conn.commit()
        finally:
            conn.close()

        logger.info(f"strengthen_links_on_retrieval agent_id={agent_id} updated={updated}")
        return updated

    def get_neighbors(self, agent_id: str, event_id: str, min_strength: float = None) -> list[dict]:
        """
        获取某事件的关联邻居。
        min_strength 默认读 GRAPH_RETRIEVAL_EXPAND_MIN_STRENGTH。
        min_strength 受 introversion 调制：
          introversion > 0.6 → min_strength × 0.6（联想更远）
          introversion < 0.4 → min_strength × 1.4（只要强关联）
        只返回 status=active 的边对应的邻居。
        返回：[{"event_id": str, "strength": float}, ...]
        """
        if min_strength is None:
            min_strength = config.GRAPH_RETRIEVAL_EXPAND_MIN_STRENGTH

        # introversion 调制
        try:
            state = read_global_state(agent_id)
            introversion = float(state.get("personality_params", {}).get("introversion", 0.5))
            if introversion > 0.6:
                min_strength = min_strength * 0.6
            elif introversion < 0.4:
                min_strength = min_strength * 1.4
        except Exception as e:
            logger.warning(f"get_neighbors read introversion failed: {e}")

        conn = _get_conn(agent_id)
        try:
            rows = conn.execute(
                """
                SELECT
                    CASE WHEN source_event_id = ? THEN target_event_id
                         ELSE source_event_id END AS neighbor_id,
                    strength
                FROM memory_links
                WHERE agent_id = ?
                  AND status = 'active'
                  AND (source_event_id = ? OR target_event_id = ?)
                  AND strength >= ?
                """,
                (event_id, agent_id, event_id, event_id, min_strength),
            ).fetchall()
        finally:
            conn.close()

        return [{"event_id": r["neighbor_id"], "strength": r["strength"]} for r in rows]

    def check_dormant_revival(self, agent_id: str) -> list[str]:
        """
        检查 dormant 事件是否满足复活条件：
          active 邻居数 >= GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT
          且这些邻居的 access_count > 0
        满足条件：
          → 调用 memory_l1.update_event_status 改为 revived
          → 调用 memory_l1 更新 decay_score 为 DORMANT_THRESHOLD + 0.1
        返回复活的 event_id 列表。
        """
        neighbor_count_required = config.GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT
        recent_days = config.GRAPH_DORMANT_REVIVAL_RECENT_DAYS
        revive_decay = config.DORMANT_THRESHOLD + 0.1

        # 获取所有 dormant 事件
        tbl = _get_table(agent_id)
        try:
            dormant_rows = (
                tbl.search()
                .where("status = 'dormant'")
                .limit(500)
                .to_list()
            )
        except Exception as e:
            logger.warning(f"check_dormant_revival fetch dormant failed: {e}")
            return []

        if not dormant_rows:
            return []

        # cutoff for "recent"
        cutoff = (datetime.now() - timedelta(days=recent_days)).isoformat()

        revived = []
        conn = _get_conn(agent_id)
        try:
            for row in dormant_rows:
                event_id = row.get("event_id", "")
                if not event_id:
                    continue

                # 找该事件的 active 邻居
                neighbor_rows = conn.execute(
                    """
                    SELECT
                        CASE WHEN source_event_id = ? THEN target_event_id
                             ELSE source_event_id END AS neighbor_id
                    FROM memory_links
                    WHERE agent_id = ?
                      AND status = 'active'
                      AND (source_event_id = ? OR target_event_id = ?)
                    """,
                    (event_id, agent_id, event_id, event_id),
                ).fetchall()

                if not neighbor_rows:
                    continue

                neighbor_ids = [r["neighbor_id"] for r in neighbor_rows]

                # 从 LanceDB 查这些邻居，筛选 active 且 access_count > 0 且 created_at >= cutoff
                qualifying = 0
                for nid in neighbor_ids:
                    try:
                        nev = tbl.search().where(
                            f"event_id = '{nid}' AND status = 'active' AND access_count > 0"
                            f" AND created_at >= '{cutoff}'"
                        ).limit(1).to_list()
                        if nev:
                            qualifying += 1
                    except Exception:
                        pass

                if qualifying >= neighbor_count_required:
                    try:
                        update_event_status(agent_id, event_id, "revived")
                        tbl.update(
                            where=f"event_id = '{event_id}'",
                            values={"decay_score": float(revive_decay)},
                        )
                        revived.append(event_id)
                        logger.info(
                            f"check_dormant_revival revived event_id={event_id[:8]} "
                            f"qualifying_neighbors={qualifying}"
                        )
                    except Exception as e:
                        logger.warning(f"check_dormant_revival update failed event_id={event_id}: {e}")
        finally:
            conn.close()

        logger.info(f"check_dormant_revival agent_id={agent_id} revived={len(revived)}")
        return revived

    def decay_edges(self, agent_id: str) -> dict:
        """
        边的 strength 每日衰减：
          strength = strength × GRAPH_EDGE_DECAY_RATE
          strength < 0.05 → 改为 dormant（保留边，不删除）
        返回：{"decayed": int, "dormanted": int}
        """
        decay_rate = config.GRAPH_EDGE_DECAY_RATE
        dormant_threshold = 0.05

        conn = _get_conn(agent_id)
        try:
            rows = conn.execute(
                "SELECT link_id, strength FROM memory_links "
                "WHERE agent_id = ? AND status = 'active'",
                (agent_id,),
            ).fetchall()

            decayed = 0
            dormanted = 0
            for row in rows:
                new_strength = row["strength"] * decay_rate
                if new_strength < dormant_threshold:
                    conn.execute(
                        "UPDATE memory_links SET strength = ?, status = 'dormant' "
                        "WHERE link_id = ?",
                        (new_strength, row["link_id"]),
                    )
                    dormanted += 1
                else:
                    conn.execute(
                        "UPDATE memory_links SET strength = ? WHERE link_id = ?",
                        (new_strength, row["link_id"]),
                    )
                    decayed += 1
            conn.commit()
        finally:
            conn.close()

        logger.info(f"decay_edges agent_id={agent_id} decayed={decayed} dormanted={dormanted}")
        return {"decayed": decayed, "dormanted": dormanted}

    def update_frozen_edges(self, agent_id: str) -> int:
        """
        检查所有 active 边，若两端事件都是 archived 状态
        → 边的 status 改为 frozen。
        返回冻结边数。
        """
        tbl = _get_table(agent_id)
        conn = _get_conn(agent_id)
        frozen = 0
        try:
            rows = conn.execute(
                "SELECT link_id, source_event_id, target_event_id FROM memory_links "
                "WHERE agent_id = ? AND status = 'active'",
                (agent_id,),
            ).fetchall()

            for row in rows:
                try:
                    src_rows = tbl.search().where(
                        f"event_id = '{row['source_event_id']}'"
                    ).limit(1).to_list()
                    tgt_rows = tbl.search().where(
                        f"event_id = '{row['target_event_id']}'"
                    ).limit(1).to_list()
                except Exception:
                    continue

                src_status = src_rows[0].get("status", "") if src_rows else ""
                tgt_status = tgt_rows[0].get("status", "") if tgt_rows else ""

                if src_status == "archived" and tgt_status == "archived":
                    conn.execute(
                        "UPDATE memory_links SET status = 'frozen' WHERE link_id = ?",
                        (row["link_id"],),
                    )
                    frozen += 1

            conn.commit()
        finally:
            conn.close()

        logger.info(f"update_frozen_edges agent_id={agent_id} frozen={frozen}")
        return frozen

    def get_graph_stats(self, agent_id: str) -> dict:
        """
        返回图统计：
        {"total_edges": int, "active_edges": int,
         "frozen_edges": int, "avg_strength": float}
        """
        conn = _get_conn(agent_id)
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_edges,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_edges,
                    SUM(CASE WHEN status = 'frozen' THEN 1 ELSE 0 END) AS frozen_edges,
                    AVG(CASE WHEN status = 'active' THEN strength ELSE NULL END) AS avg_strength
                FROM memory_links
                WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchone()
        finally:
            conn.close()

        return {
            "total_edges": row["total_edges"] or 0,
            "active_edges": row["active_edges"] or 0,
            "frozen_edges": row["frozen_edges"] or 0,
            "avg_strength": round(row["avg_strength"] or 0.0, 4),
        }
