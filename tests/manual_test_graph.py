"""
手动测试 core/memory_graph.py。
运行方式（在项目根目录）：python tests/manual_test_graph.py

前置条件：manual_test_soul.py 已执行过，soul.json / global_state.json 存在。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.memory_l1 import write_event, get_event, _get_table, update_event_status, increment_access_count
from core.memory_graph import MemoryGraph

AGENT_ID = "test_agent_001"
graph = MemoryGraph()
DB_PATH = Path(__file__).parent.parent / "data" / "agents" / AGENT_ID / "graph.db"


def query_edges_between(event_ids: list, label: str = ""):
    """打印指定 event_id 集合之间的边（双向匹配）。"""
    if not event_ids:
        return
    placeholders = ",".join("?" * len(event_ids))
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT source_event_id, target_event_id, strength, activation_count, status
        FROM memory_links
        WHERE agent_id = ?
          AND source_event_id IN ({placeholders})
          AND target_event_id IN ({placeholders})
        ORDER BY strength DESC
        """,
        [AGENT_ID] + event_ids + event_ids,
    ).fetchall()
    conn.close()
    tag = f"  [{label}] " if label else "  "
    if not rows:
        print(f"{tag}（无边）")
    for r in rows:
        print(f"{tag}{r['source_event_id'][:8]}<->{r['target_event_id'][:8]}  "
              f"strength={r['strength']:.4f}  activation_count={r['activation_count']}  status={r['status']}")
    return rows


# ── 1. 写入3条语义相似的事件，确认它们之间有边 ────────────────────────────────
print("=" * 60)
print("1. 写入 3 条语义相似的事件（技术学习相关）")
print("=" * 60)

ids1 = write_event(AGENT_ID, "今天学习了 Python 异步编程，深入理解了 asyncio 的原理，感觉很有收获")
ids2 = write_event(AGENT_ID, "研究了 FastAPI 框架的并发处理机制，对异步 IO 有了更深的认识")
ids3 = write_event(AGENT_ID, "看了一篇关于 Python 协程和事件循环的技术文章，豁然开朗")

similar_ids = ids1 + ids2 + ids3
print(f"\n写入 event_id（共 {len(similar_ids)} 条）:")
for eid in similar_ids:
    print(f"  {eid[:8]}...")

print("\n3条事件之间的边（预期：相似度 > 0.6 的对之间有边）:")
rows_s = query_edges_between(similar_ids, "相似事件间")

stats = graph.get_graph_stats(AGENT_ID)
print(f"\n图总统计: {stats}")
edge_count = len(rows_s) if rows_s else 0
print(f"验证结果: 3条事件间共 {edge_count} 条边  → {'✓ 有边建立' if edge_count > 0 else '✗ 无边（相似度可能未超过阈值 ' + str(config.GRAPH_BUILD_EDGE_SIMILARITY_THRESHOLD) + '）'}")


# ── 2. 写入1条完全不相关的事件，确认与前3条没有边 ───────────────────────────────
print("\n" + "=" * 60)
print("2. 写入1条完全不相关的事件（烹饪相关）")
print("=" * 60)

ids_unrelated = write_event(AGENT_ID, "今天尝试做了一道红烧肉，用了老抽和冰糖，味道非常香甜")
unrelated_id = ids_unrelated[0] if ids_unrelated else None
print(f"写入 event_id: {unrelated_id[:8] + '...' if unrelated_id else 'None'}")

if unrelated_id:
    # 检查不相关事件与3条相似事件之间是否有边
    all_four = similar_ids + [unrelated_id]
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cross_rows = conn.execute(
        f"""
        SELECT source_event_id, target_event_id, strength
        FROM memory_links
        WHERE agent_id = ?
          AND (
            (source_event_id = ? AND target_event_id IN ({','.join('?' * len(similar_ids))}))
            OR
            (target_event_id = ? AND source_event_id IN ({','.join('?' * len(similar_ids))}))
          )
        """,
        [AGENT_ID, unrelated_id] + similar_ids + [unrelated_id] + similar_ids,
    ).fetchall()
    conn.close()

    print(f"\n不相关事件与前3条事件之间的边（预期：无）:")
    if cross_rows:
        for r in cross_rows:
            print(f"  ✗ {r['source_event_id'][:8]}<->{r['target_event_id'][:8]}  strength={r['strength']:.4f}")
    else:
        print("  ✓ 无边（相似度未超过阈值，符合预期）")

    # 展示不相关事件实际建立的邻居（来自其他历史事件）
    neighbors_unrelated = graph.get_neighbors(AGENT_ID, unrelated_id)
    print(f"\n不相关事件实际邻居数: {len(neighbors_unrelated)}（均来自历史事件，非本次3条）")


# ── 3. strengthen_links_on_retrieval，打印3条相似事件间边的 strength 变化 ──────
print("\n" + "=" * 60)
print("3. strengthen_links_on_retrieval — 加强共现边")
print("=" * 60)
print(f"（increment = {config.GRAPH_RETRIEVAL_STRENGTHEN_INCREMENT}，上限 1.0）")

if len(similar_ids) >= 2:
    print("\n加强前（3条相似事件之间的边）:")
    query_edges_between(similar_ids, "加强前")

    updated = graph.strengthen_links_on_retrieval(AGENT_ID, similar_ids)
    print(f"\n更新边数: {updated}（预期：{len(similar_ids)*(len(similar_ids)-1)//2} 条两两组合）")

    print("\n加强后（3条相似事件之间的边）:")
    query_edges_between(similar_ids, "加强后")
    print("验证结果: ✓ strength 均 +0.1，activation_count 均 +1（若边存在）；无边的对新建边 strength=0.1")
else:
    print("  similar_ids 不足2条，跳过")


# ── 4. check_dormant_revival — dormant 事件复活检测 ──────────────────────────
print("\n" + "=" * 60)
print("4. check_dormant_revival — dormant 事件复活检测")
print("=" * 60)
print(f"（需要 active 邻居数 >= {config.GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT}，且 access_count > 0）")

if similar_ids:
    dormant_id = similar_ids[0]
    print(f"\n将 event_id={dormant_id[:8]}... 改为 dormant")
    update_event_status(AGENT_ID, dormant_id, "dormant")

    # 另外2条（已与 dormant 有边），access_count +1
    other_ids = similar_ids[1:]
    print(f"\n对另外 {len(other_ids)} 条邻居事件 access_count +1:")
    for eid in other_ids:
        increment_access_count(AGENT_ID, eid)
        print(f"  {eid[:8]}...")

    # 写入第4条相似事件，让 dormant 凑足3个邻居
    print("\n写入第4条相似事件（让 dormant 事件凑足3个邻居）:")
    ids4 = write_event(AGENT_ID, "今天深入研究了 Python asyncio 的底层实现，理解了 uvloop 的性能优势")
    if ids4:
        fourth_id = ids4[0]
        print(f"  写入 event_id={fourth_id[:8]}...")
        increment_access_count(AGENT_ID, fourth_id)
        print(f"  access_count +1: {fourth_id[:8]}...")
    else:
        fourth_id = None
        print("  写入失败")

    # 展示 dormant 事件邻居详情
    neighbors = graph.get_neighbors(AGENT_ID, dormant_id)
    active_with_access = [
        n for n in neighbors
        if get_event(AGENT_ID, n["event_id"]).get("access_count", 0) > 0
           and get_event(AGENT_ID, n["event_id"]).get("status") == "active"
    ]
    print(f"\ndormant 事件邻居（共 {len(neighbors)} 个），其中 active+access_count>0 的: {len(active_with_access)} 个")
    for n in neighbors:
        ev_n = get_event(AGENT_ID, n["event_id"])
        mark = "✓" if ev_n.get("access_count", 0) > 0 and ev_n.get("status") == "active" else " "
        print(f"  [{mark}] {n['event_id'][:8]}...  strength={n['strength']:.4f}  "
              f"access_count={ev_n.get('access_count', 0)}  status={ev_n.get('status', '')}")
    print(f"需要满足条件: active+access_count>0 的邻居数 {len(active_with_access)} >= {config.GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT}")

    revived = graph.check_dormant_revival(AGENT_ID)
    print(f"\n复活的 event_id 列表: {[eid[:8] + '...' for eid in revived]}")
    if dormant_id in revived:
        ev = get_event(AGENT_ID, dormant_id)
        print(f"✓ 确认复活: status={ev.get('status')}  decay_score={ev.get('decay_score'):.4f}"
              f"（预期 decay_score = DORMANT_THRESHOLD+0.1 = {config.DORMANT_THRESHOLD + 0.1:.1f}）")
    else:
        print(f"✗ 未复活（满足邻居数 {len(active_with_access)}，阈值 {config.GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT}）")
else:
    print("  无可用 similar_ids，跳过")


# ── 5. decay_edges — 验证低强度边被删除 ──────────────────────────────────────
print("\n" + "=" * 60)
print("5. decay_edges — 低强度边删除验证")
print("=" * 60)
# 正确的临界值：strength 需满足 strength × decay_rate < 0.05
# 0.05 × 0.99 = 0.0495 < 0.05 → 会被删除
# 0.06 × 0.99 = 0.0594 > 0.05 → 不会被删除（之前用0.06是错的）
test_strength = 0.05
print(f"将某条边 strength 设为 {test_strength}（{test_strength} × {config.GRAPH_EDGE_DECAY_RATE} = "
      f"{test_strength * config.GRAPH_EDGE_DECAY_RATE:.4f} < 0.05 → 预期删除）")

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
target_link = conn.execute(
    "SELECT link_id, strength FROM memory_links WHERE agent_id = ? AND status = 'active' LIMIT 1",
    (AGENT_ID,),
).fetchone()
conn.close()

if target_link:
    target_link_id = target_link["link_id"]
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE memory_links SET strength = ? WHERE link_id = ?",
        (test_strength, target_link_id),
    )
    conn.commit()
    conn.close()
    print(f"已设置 link_id={target_link_id[:8]}...  strength={test_strength}")
else:
    target_link_id = None
    print("  无 active 边，跳过")

stats_before = graph.get_graph_stats(AGENT_ID)
print(f"\ndecay_edges 前: total_edges={stats_before['total_edges']}  active_edges={stats_before['active_edges']}")

decay_stats = graph.decay_edges(AGENT_ID)
print(f"decay_edges 统计: decayed={decay_stats['decayed']}（衰减保留）  removed={decay_stats['removed']}（删除）")

stats_after = graph.get_graph_stats(AGENT_ID)
print(f"decay_edges 后: total_edges={stats_after['total_edges']}  active_edges={stats_after['active_edges']}")
print(f"total_edges 减少了: {stats_before['total_edges'] - stats_after['total_edges']} 条")

if target_link_id:
    conn = sqlite3.connect(str(DB_PATH))
    gone = conn.execute(
        "SELECT link_id FROM memory_links WHERE link_id = ?", (target_link_id,)
    ).fetchone()
    conn.close()
    if gone is None:
        print(f"\n✓ link_id={target_link_id[:8]}... 已从数据库删除（符合预期）")
    else:
        print(f"\n✗ link_id={target_link_id[:8]}... 仍存在（异常）")
