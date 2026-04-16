"""
nuwa_seed_builder.py

从 nuwa-skill 产出的 examples/{person_slug}-perspective/ 目录一次性创建
完整的 digital_human agent（seed + soul + L1 记忆）。

与 seed_memory_loader.py 并行存在，两者互不干扰。

直接运行：
  python core/nuwa_seed_builder.py steve-jobs jobs_v1
  python core/nuwa_seed_builder.py steve-jobs jobs_v1 --force
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import logging
import re
import shutil
import copy
from datetime import datetime

import config
from core.llm_client import chat_completion
from core.soul import (
    _build_empty_soul,
    _write_soul,
    _CORE_FIELDS,
    CORES,
)
from core.seed_memory_loader import (
    _setup_agent_dirs,
    _write_events_to_l1,
    _build_graph,
    _update_statuses,
)
from core.memory_l2 import check_and_generate_patterns, contribute_to_soul

logger = logging.getLogger("nuwa_seed_builder")

_PROJECT_ROOT = Path(__file__).parent.parent
_EXAMPLES_DIR = _PROJECT_ROOT / "examples"
_AGENTS_DIR   = _PROJECT_ROOT / "data" / "agents"
_SEEDS_DIR    = _PROJECT_ROOT / "data" / "seeds"
_PROMPTS_DIR  = _PROJECT_ROOT / "prompts"

_INIT_MAX_TOKENS  = 8192
_BATCH_MAX_TOKENS = 8192

_CURRENT_YEAR = 2026   # nuwa agent 的"现在"锚点，spec §2.5


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _load_prompt(filename: str) -> str:
    """读取单一 prompt（nuwa 两份都没有 system/user 分隔）。"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _read_source(person_slug: str) -> dict:
    """读取 examples/{slug}-perspective/ 下全部可用文件，返回 dict。"""
    src_dir = _EXAMPLES_DIR / f"{person_slug}-perspective"
    if not src_dir.exists():
        raise FileNotFoundError(f"nuwa 源目录不存在：{src_dir}")

    def _read(relpath: str) -> str:
        p = src_dir / relpath
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return {
        "src_dir":           src_dir,
        "skill_md":          _read("SKILL.md"),
        "writings_md":       _read("references/research/01-writings.md"),
        "conversations_md":  _read("references/research/02-conversations.md"),
        "expression_dna_md": _read("references/research/03-expression-dna.md"),
        "external_views_md": _read("references/research/04-external-views.md"),
        "decisions_md":      _read("references/research/05-decisions.md"),
        "timeline_md":       _read("references/research/06-timeline.md"),
    }


def _extract_seed(agent_id: str, src: dict) -> dict:
    template = _load_prompt("nuwa_skill_to_seed.txt")
    user = template.format(
        agent_id=agent_id,
        current_year=_CURRENT_YEAR,
        skill_md=src["skill_md"],
        expression_dna_md=src["expression_dna_md"] or "（无）",
        external_views_md=src["external_views_md"] or "（无）",
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=_INIT_MAX_TOKENS, temperature=0.2,
    )
    try:
        seed = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_extract_seed json parse error agent_id={agent_id} e={e} raw={raw[:400]}")
        raise
    seed["agent_id"] = agent_id
    return seed


def _extract_timeline_table(skill_md: str) -> str:
    """从 SKILL.md 里抠出 '## 人物时间线' 节的 markdown 表格。"""
    m = re.search(
        r"##\s*人物时间线[\s\S]+?(?=\n##\s|\Z)",
        skill_md,
    )
    return m.group(0) if m else ""


def _extract_l1_events(agent_name: str, src: dict) -> list[dict]:
    template = _load_prompt("nuwa_research_to_l1.txt")
    timeline_table = _extract_timeline_table(src["skill_md"])

    user = template.format(
        agent_name=agent_name,
        current_year=_CURRENT_YEAR,
        timeline_table=timeline_table or "（无）",
        decisions_md=src["decisions_md"]           or "（无）",
        writings_md=src["writings_md"]             or "（无）",
        conversations_md=src["conversations_md"]   or "（无）",
        timeline_md=src["timeline_md"]             or "（无）",
    )
    raw = chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=_BATCH_MAX_TOKENS, temperature=0.2,
    )
    try:
        events = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        logger.error(f"_extract_l1_events json parse error e={e} raw={raw[:400]}")
        raise
    if not isinstance(events, list):
        raise ValueError(f"_extract_l1_events expected list, got {type(events)}")
    logger.info(f"_extract_l1_events extracted={len(events)} events")
    return events


def _build_soul_direct(agent_id: str, seed: dict) -> dict:
    """
    不调 LLM，直接从 seed.json 构造 soul.json。
    映射规则：
      seed.{core}.{field} → soul.{core}.{constitutional|slow_change|elastic}.{field}
      根据 _CORE_FIELDS 自动判断归属区
    """
    soul = _build_empty_soul(agent_id)

    # 4 主核心：按 _CORE_FIELDS 分区归置
    for core in ["emotion_core", "value_core", "goal_core", "relation_core"]:
        seed_core = seed.get(core, {})
        fields = _CORE_FIELDS[core]
        for f in fields["constitutional"]:
            if f in seed_core and seed_core[f] is not None:
                soul[core]["constitutional"][f] = seed_core[f]
        for f in fields["slow_change"]:
            if f in seed_core and seed_core[f] is not None:
                soul[core]["slow_change"][f]["value"] = seed_core[f]
        for f in fields["elastic"]:
            if f in seed_core and seed_core[f] is not None:
                soul[core]["elastic"][f] = seed_core[f]
        soul[core]["constitutional"]["confidence"] = 0.9
        soul[core]["constitutional"]["source"] = "nuwa"

    # cognitive_core：全字段复制到 constitutional
    cog = seed.get("cognitive_core", {})
    for f in _CORE_FIELDS["cognitive_core"]["constitutional"]:
        if f in cog:
            soul["cognitive_core"]["constitutional"][f] = cog[f]
    soul["cognitive_core"]["constitutional"]["source"] = "nuwa"
    soul["cognitive_core"]["constitutional"]["confidence"] = None
    soul["cognitive_core"]["constitutional"]["locked"] = True

    _write_soul(agent_id, soul)
    logger.info(f"_build_soul_direct agent_id={agent_id} soul written (no LLM)")
    return soul


def build_from_nuwa(person_slug: str, agent_id: str, force: bool = False) -> dict:
    """
    输入：
      person_slug: examples/{slug}-perspective/ 目录前缀（如 "steve-jobs"）
      agent_id:    新 agent 的 ID
      force:       已存在时删除重建
    """
    agent_dir = _AGENTS_DIR / agent_id
    seed_dir  = _SEEDS_DIR / agent_id

    if agent_dir.exists() or seed_dir.exists():
        if not force:
            raise RuntimeError(
                f"agent_id='{agent_id}' 已存在。如需重建请加 --force"
            )
        logger.warning(f"build_from_nuwa force=True 删除旧数据 agent_id={agent_id}")
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        if seed_dir.exists():
            shutil.rmtree(seed_dir)

    logger.info(f"build_from_nuwa START person={person_slug} agent_id={agent_id}")
    start_time = datetime.now()

    # Step 1: 读源
    logger.info("Step 1/10: read nuwa source files")
    src = _read_source(person_slug)

    # Step 2: LLM pass 1 → seed.json
    logger.info("Step 2/10: LLM pass 1 — SKILL.md → seed.json")
    seed = _extract_seed(agent_id, src)
    seed_dir.mkdir(parents=True, exist_ok=True)
    with open(seed_dir / "seed.json", "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)
    # 单独存一份 cognitive_profile.json，便于 traceability
    with open(seed_dir / "cognitive_profile.json", "w", encoding="utf-8") as f:
        json.dump(seed.get("cognitive_core", {}), f, ensure_ascii=False, indent=2)
    agent_name = seed.get("name") or agent_id

    # Step 3: 存档源文件
    logger.info("Step 3/10: archive source files to data/seeds/.../nuwa_source/")
    archive_dir = seed_dir / "nuwa_source"
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    shutil.copytree(src["src_dir"], archive_dir)

    # Step 4: 初始化 agent 目录（复用）
    logger.info("Step 4/10: setup agent dirs (reuse)")
    _setup_agent_dirs(agent_id)

    # Step 5: 直接构造 soul.json（不走 LLM）
    logger.info("Step 5/10: build soul.json directly from seed")
    _build_soul_direct(agent_id, seed)

    # Step 6: LLM pass 2 → L1 events
    logger.info("Step 6/10: LLM pass 2 — research → L1 events")
    events = _extract_l1_events(agent_name, src)

    # Step 7: 写 LanceDB（复用）
    logger.info(f"Step 7/10: write {len(events)} events to LanceDB")
    written = _write_events_to_l1(agent_id, agent_name, events)

    # Step 8: 建记忆图边（复用）
    logger.info("Step 8/10: build memory graph")
    _build_graph(agent_id, written)

    # Step 9: 分配状态（复用，current_year=2026）
    logger.info("Step 9/10: assign L1 statuses")
    status_dist = _update_statuses(agent_id, written)

    # Step 10: L2 + Soul 积分（cognitive_core 无 slow_change，自然跳过）
    logger.info("Step 10/10: L2 patterns + Soul evidence contribution")
    l2_updated = check_and_generate_patterns(agent_id)
    soul_contribs = contribute_to_soul(agent_id)

    elapsed = (datetime.now() - start_time).seconds
    summary = {
        "agent_id":           agent_id,
        "agent_name":         agent_name,
        "person_slug":        person_slug,
        "l1_events_written":  len(written),
        "l1_status_dist":     status_dist,
        "l2_patterns":        len(l2_updated),
        "soul_contributions": len(soul_contribs),
        "elapsed_seconds":    elapsed,
    }
    logger.info(f"build_from_nuwa DONE summary={summary}")
    print("\n=== nuwa agent 构建完成 ===")
    print(f"  Agent:        {agent_id} ({agent_name})")
    print(f"  来源:         {person_slug}")
    print(f"  L1 事件:      {len(written)} 条  {status_dist}")
    print(f"  L2 patterns:  {len(l2_updated)}")
    print(f"  耗时:         {elapsed}s")
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="从 nuwa-skill 产出一键构建 digital_human agent",
    )
    parser.add_argument("person_slug", help="examples/{slug}-perspective/ 的 slug")
    parser.add_argument("agent_id",    help="新 agent 的 ID")
    parser.add_argument("--force", "-f", action="store_true", help="覆盖重建")
    args = parser.parse_args()

    src_dir = _EXAMPLES_DIR / f"{args.person_slug}-perspective"
    if not src_dir.exists():
        print(f"错误：找不到源目录 {src_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        build_from_nuwa(args.person_slug, args.agent_id, force=args.force)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
