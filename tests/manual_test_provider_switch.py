"""跨 provider 冒烟：切 LLM_PROVIDER 环境变量（deepseek/minimax/kimi/glm），
每个 chat_completion 调用点最小化打一次真实 API，验证 provider 兼容性。

运行：
    LLM_PROVIDER=deepseek python tests/manual_test_provider_switch.py
    LLM_PROVIDER=minimax  python tests/manual_test_provider_switch.py
    ...

退出码：0 = 全绿；非 0 = 有 FAIL。
"""
import json
import os
import sys
import traceback
from pathlib import Path

# 允许脚本直接 python 运行（从项目根）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from core.llm_client import chat_completion  # noqa: E402

_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt_pair(filename: str) -> tuple[str, str]:
    """读取 \\n---\\n 分隔的双段 prompt，返回 (system, user)。
    若文件不含 \\n---\\n 分隔符，则回落为 ("", 全文)——调用方需自行判断该回落
    是否合适（例如 `l2_generate_patterns.txt` 用 [SYSTEM]/[USER] 标记，需要特殊处理）。"""
    text = (_PROMPTS / filename).read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", parts[0].strip()


def _load_single_prompt(filename: str) -> str:
    return (_PROMPTS / filename).read_text(encoding="utf-8")


# 共用最小 fixture
SAMPLE_DIALOGUE = "A: 今天工作怎么样？\nB: 写了三段代码，还挺顺的。"
SAMPLE_USER_MSG = "我今天终于把那个 bug 修好了！"


def _expect_json_dict(raw: str) -> bool:
    data = json.loads(raw)
    return isinstance(data, dict)


def _expect_json_list(raw: str) -> bool:
    data = json.loads(raw)
    return isinstance(data, list)


def _expect_non_empty_string(raw: str) -> bool:
    return isinstance(raw, str) and len(raw.strip()) > 0


def _expect_parseable_float(raw: str) -> bool:
    try:
        float(raw.strip())
        return True
    except ValueError:
        return False


def _smoke_detect_emotion():
    # detect_emotion.txt uses \n---\n to split system / user sections;
    # _EMOTION_USR is just "{user_message}" (the placeholder).
    sys_, usr_tpl = _load_prompt_pair("detect_emotion.txt")
    user = usr_tpl.format(user_message=SAMPLE_USER_MSG)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=16, temperature=0.0,
    )


# 2. dialogue 主回合（返回字符串，不是 JSON）
def _smoke_dialogue_reply():
    sys_prompt = "你是一个日常对话助手。请直接回复用户的话，保持自然。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": SAMPLE_USER_MSG}],
        max_tokens=256, temperature=0.7,
    )


# 3. dialogue.make_decision
# decision_system.txt 有大量占位符（name/age/occupation 等），用内联 system prompt 代替
def _smoke_make_decision():
    sys_prompt = "你是一个决策助手。根据用户描述的情况，输出 JSON：{\"decision\": str, \"reasoning\": str}。只输出 JSON，不要任何其他内容。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": "我收到一个创业公司的 offer，待遇比现在好 30%，但要搬到另一个城市。要不要接受？"}],
        max_tokens=256, temperature=0.2,
    )


# 4. dialogue evidence check
# soul_evidence_check.txt 只有 {session_text}，没有 {soul_snapshot}
def _smoke_evidence_check():
    sys_, usr = _load_prompt_pair("soul_evidence_check.txt")
    user = usr.format(session_text=SAMPLE_DIALOGUE)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=512, temperature=0.2,
    )


# 5. dialogue new_val（soul 字段回填，返回字符串）
def _smoke_new_val_fill():
    sys_prompt = "给定字段名与一段证据文本，用一句话写出该字段的新值。直接给值，不要解释。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": "字段=核心价值观，证据=我最在意的是把一件事做对。"}],
        max_tokens=64, temperature=0.3,
    )


# 6. retrieval rerank
# retrieval_rerank.txt 使用 {query} + {candidates_text}，与 plan 一致
def _smoke_rerank():
    sys_, usr = _load_prompt_pair("retrieval_rerank.txt")
    candidates_text = (
        "1. event_id=e1\n   内容：修了一个 bug | 下午\n   重要性：0.60 | 情绪：喜悦\n"
        "2. event_id=e2\n   内容：吃了饭 | 中午\n   重要性：0.20 | 情绪：平静"
    )
    user = usr.format(query="今天的工作亮点", candidates_text=candidates_text)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=128, temperature=0.1,
    )


# 7. memory_l2.check_and_generate_patterns  ← 注意：这个 prompt 用 [SYSTEM]/[USER] 标记，不是 \n---\n
# 实际占位符：{source_topic}, {event_count}, {events_summary}, {existing_pattern}
def _smoke_l2_patterns():
    text = (_PROMPTS / "l2_generate_patterns.txt").read_text(encoding="utf-8")
    # l2 特例：解析 [SYSTEM]…[USER]… 格式
    parts = text.split("[USER]")
    sys_ = parts[0].replace("[SYSTEM]", "").strip()
    usr_tmpl = parts[1].strip() if len(parts) > 1 else ""
    events_block = "e1: 遇到冲突时选择沟通\ne2: 遇到冲突时选择沟通\ne3: 遇到冲突时选择沟通"
    user = usr_tmpl.format(
        source_topic="冲突处理",
        event_count=3,
        events_summary=events_block,
        existing_pattern="无",
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=512, temperature=0.2,
    )


# 8. memory_l1 extract_events
# l1_extract_events.txt 使用 {value_core}, {recent_summary}, {raw_text}
def _smoke_l1_extract_events():
    sys_, usr = _load_prompt_pair("l1_extract_events.txt")
    user = usr.format(
        value_core="诚实、努力、注重细节",
        recent_summary="近期主要在工作上遇到技术挑战。",
        raw_text=SAMPLE_DIALOGUE,
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=512, temperature=0.2,
    )


# 9. memory_l1 score_event
# l1_score_event.txt 使用 {value_core}, {action}, {context}, {outcome}, {emotion}, {emotion_intensity}
def _smoke_l1_score_event():
    sys_, usr = _load_prompt_pair("l1_score_event.txt")
    user = usr.format(
        value_core="诚实、努力、注重细节",
        action="完成了第一版原型",
        context="项目推进中遇到多个技术障碍",
        outcome="成功交付，获得团队认可",
        emotion="喜悦",
        emotion_intensity=0.8,
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=256, temperature=0.2,
    )


# 10. memory_l1 extract_scene
# l1_extract_scene.txt 使用 {action}, {context}, {outcome}, {raw_text}
def _smoke_l1_scene():
    sys_, usr = _load_prompt_pair("l1_extract_scene.txt")
    user = usr.format(
        action="写了三段代码",
        context="在办公室处理工作任务",
        outcome="顺利完成",
        raw_text=SAMPLE_DIALOGUE,
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=128, temperature=0.2,
    )


# 11. memory_l1 extract_tags
# l1_extract_tags.txt 使用 {action}, {context}, {outcome}, {emotion}, {raw_text}, {current_time}
def _smoke_l1_tags():
    sys_, usr = _load_prompt_pair("l1_extract_tags.txt")
    user = usr.format(
        action="完成了第一版原型",
        context="项目推进中遇到多个技术障碍",
        outcome="成功交付",
        emotion="喜悦",
        raw_text="今天终于完成了第一版原型。",
        current_time="2026-04-18T10:00:00",
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=128, temperature=0.2,
    )


# 12. seed_memory_loader init_soul_from_nodes
# seed_soul_init.txt 使用 \n---\n 分隔 system/user；{seed_json} + {nodes_text}
def _smoke_seed_init_soul():
    sys_, usr_tmpl = _load_prompt_pair("seed_soul_init.txt")
    seed_json = '{"name": "测试用户", "age": 30, "occupation": "工程师", "location": "北京"}'
    nodes_text = "访谈节点1：喜欢独处\n访谈节点2：偏好书写表达\n访谈节点3：工作里追求精确"
    user = usr_tmpl.format(seed_json=seed_json, nodes_text=nodes_text)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=2048, temperature=0.2,
    )


# 13. seed_memory_loader extract_events_batch
# seed_batch_load.txt 使用 \n---\n 分隔 system/user；{agent_name}, {current_year}, {nodes_text}
def _smoke_seed_batch():
    sys_, usr_tmpl = _load_prompt_pair("seed_batch_load.txt")
    user = usr_tmpl.format(
        agent_name="测试用户",
        current_year="2026",
        nodes_text="1. 2019 年搬去北京\n2. 2020 年换了工作\n3. 2022 年结婚",
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=2048, temperature=0.2,
    )


# 14. soul.init_soul
# soul_init.txt 使用 \n---\n 分隔 system/user；{seed_json}
def _smoke_soul_init():
    sys_, usr_tmpl = _load_prompt_pair("soul_init.txt")
    seed_json = '{"name": "测试用户", "age": 30, "occupation": "工程师", "traits": ["喜欢独处", "偏好书写表达", "追求精确"]}'
    user = usr_tmpl.format(seed_json=seed_json)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=1024, temperature=0.2,
    )


# 15. soul.check_constitutional_conflict
# soul_conflict_check.txt 使用 {anchor} + {content}
def _smoke_soul_conflict():
    sys_, usr = _load_prompt_pair("soul_conflict_check.txt")
    user = usr.format(
        anchor="诚实、克制、尊重他人",
        content="为了赶 deadline 撒了个小谎",
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=256, temperature=0.1,
    )


# 16. interview_seed_builder seed
# interview_to_seed.txt 使用 {agent_id}, {interview_date}, {duration_minutes}, {dialogue_text}
def _smoke_interview_seed():
    sys_prompt = _load_single_prompt("interview_to_seed.txt")
    interview_text = "访谈员：请介绍一下你自己。\n受访者：我叫张三，1990 年出生在杭州，大学学了计算机，现在在一家创业公司做产品。"
    user = sys_prompt.format(
        agent_id="test_agent",
        interview_date="2026-04-18",
        duration_minutes=30,
        dialogue_text=interview_text,
    )
    return chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=2048, temperature=0.2,
    )


# 17. interview_seed_builder l1_events
# interview_to_l1.txt 使用 {agent_name}, {interview_date}, {current_age}, {dialogue_text}
def _smoke_interview_l1():
    sys_prompt = _load_single_prompt("interview_to_l1.txt")
    interview_text = "访谈员：请介绍一下你自己。\n受访者：我叫张三，1990 年出生在杭州，大学学了计算机，现在在一家创业公司做产品。"
    user = sys_prompt.format(
        agent_name="张三",
        interview_date="2026-04-18",
        current_age=36,
        dialogue_text=interview_text,
    )
    return chat_completion(
        [{"role": "user", "content": user}],
        max_tokens=2048, temperature=0.2,
    )


# 18. seed_parser.parse_seed
# seed_extract.txt 无 \n---\n 分隔符；_load_prompt_pair 回落为 ("", 全文)，
# 与 seed_parser.py 中 _load_prompt() 的行为一致（_SYSTEM_PROMPT=""）。
# 占位符：{name}, {dialogue}
def _smoke_seed_parse():
    sys_, usr_tmpl = _load_prompt_pair("seed_extract.txt")
    user = usr_tmpl.format(
        name="测试用户",
        dialogue="A: 今天怎么样？\nB: 还不错，完成了一个项目。",
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=1024, temperature=0.2,
    )


# 覆盖说明：
# - 下面 18 条覆盖 core/ 下所有 chat_completion 调用点（含 seed_parser.parse_seed）。
# - nuwa_seed_builder 的两个调用点（_extract_seed / _extract_events_of_kind）
#   依赖完整的 SKILL.md 作为 fixture，冒烟不构造；由 interview_seed_builder 的
#   两个 smoke 作为代理验证 prompt 风格与 JSON 服从度。
CALL_SITES = [
    {"name": "dialogue._detect_emotion",          "invoke": _smoke_detect_emotion,   "expect": _expect_parseable_float},
    {"name": "dialogue.reply",                    "invoke": _smoke_dialogue_reply,   "expect": _expect_non_empty_string},
    {"name": "dialogue.make_decision",            "invoke": _smoke_make_decision,    "expect": _expect_json_dict},
    {"name": "dialogue.evidence_check",           "invoke": _smoke_evidence_check,   "expect": _expect_json_dict},
    {"name": "dialogue.new_val_fill",             "invoke": _smoke_new_val_fill,     "expect": _expect_non_empty_string},
    {"name": "retrieval.rerank",                  "invoke": _smoke_rerank,           "expect": _expect_json_list},
    {"name": "memory_l2.generate_patterns",       "invoke": _smoke_l2_patterns,      "expect": _expect_json_dict},
    {"name": "memory_l1.extract_events",          "invoke": _smoke_l1_extract_events,"expect": _expect_json_list},
    {"name": "memory_l1.score_event",             "invoke": _smoke_l1_score_event,   "expect": _expect_json_dict},
    {"name": "memory_l1.extract_scene",           "invoke": _smoke_l1_scene,         "expect": _expect_json_dict},
    {"name": "memory_l1.extract_tags",            "invoke": _smoke_l1_tags,          "expect": _expect_json_dict},
    {"name": "seed_memory_loader.init_soul",      "invoke": _smoke_seed_init_soul,   "expect": _expect_json_dict},
    {"name": "seed_memory_loader.extract_batch",  "invoke": _smoke_seed_batch,       "expect": _expect_json_list},
    {"name": "soul.init_soul",                    "invoke": _smoke_soul_init,        "expect": _expect_json_dict},
    {"name": "soul.check_conflict",               "invoke": _smoke_soul_conflict,    "expect": _expect_json_dict},
    {"name": "interview_seed_builder.seed",       "invoke": _smoke_interview_seed,   "expect": _expect_json_dict},
    {"name": "interview_seed_builder.l1_events",  "invoke": _smoke_interview_l1,     "expect": _expect_json_list},
    {"name": "seed_parser.parse_seed",            "invoke": _smoke_seed_parse,       "expect": _expect_json_dict},
]


def main() -> int:
    provider = os.environ.get("LLM_PROVIDER") or config.LLM_PROVIDER
    config.LLM_PROVIDER = provider

    print(f"\n=== provider={provider} ===")
    fail = 0
    for cs in CALL_SITES:
        name = cs["name"]
        # expect() returning False → wrong shape (FAIL(schema), raw_head printed);
        # raising → parse/network failure (FAIL(exception), traceback printed).
        try:
            raw = cs["invoke"]()
            ok = cs["expect"](raw)
            status = "OK" if ok else "FAIL(schema)"
        except Exception:
            status = "FAIL(exception)"
            print(f"[{provider}] {name}: {status}")
            traceback.print_exc()
            fail += 1
            continue
        print(f"[{provider}] {name}: {status}  raw_head={raw[:60]!r}")
        if status != "OK":
            fail += 1
    print(f"\n=== summary: {len(CALL_SITES) - fail}/{len(CALL_SITES)} OK ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
