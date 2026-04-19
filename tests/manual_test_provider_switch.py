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


CALL_SITES = [
    {
        "name": "dialogue._detect_emotion",
        "invoke": _smoke_detect_emotion,
        "expect": _expect_parseable_float,
    },
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
