# LLM Provider 切换 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持通过 `LLM_PROVIDER` 在 deepseek / minimax / kimi / glm 四家 OpenAI 兼容 provider 之间一键切换，所有调用点自动适配。

**Architecture:** 在 `chat_completion()` 内部新增集中式文本清洗层，去掉 provider 特有的 `<think>…</think>` / ```` ```json ``` ```` / 空串等包裹；调用方 `json.loads` 契约不变。配置层补齐 3 家 provider 的 base_url/model；新增真实 API 冒烟矩阵，验收标准为"(provider × 调用点)"级别全绿/已记录。

**Tech Stack:** Python 3, openai SDK, pytest（单元）, standalone script + env var（冒烟）。

对应 spec：`docs/superpowers/specs/2026-04-18-llm-provider-switch-design.md`

---

## 文件结构

**新增：**
- `tests/test_llm_sanitize.py` — `_sanitize` / `EmptyResponseError` 的纯函数单元测试（不打 API）
- `tests/manual_test_provider_switch.py` — 跨 provider 冒烟脚本，读 `LLM_PROVIDER` 环境变量
- `docs/provider_compat.md` — 冒烟矩阵结果与兼容性备忘

**修改：**
- `core/llm_client.py` — 新增 `_sanitize`、`EmptyResponseError`；在 `chat_completion` 调用清洗；补 api_key 校验
- `config.py` — 填 MINIMAX/KIMI/GLM 的 model + base_url
- `.env.example` — 追加 3 个 key 的占位

**可选清理（Task 9）：** 删除 `core/` 下 8 个文件里 `_strip_json` / `_strip_markdown_json` 的私有副本。

---

## Task 1: 为 `_sanitize` 写失败测试 + 定义 `EmptyResponseError`

**Files:**
- Create: `tests/test_llm_sanitize.py`
- Modify: `core/llm_client.py`（仅新增空的异常类和空的 `_sanitize` 占位，尚未实现）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_sanitize.py
import pytest
from core.llm_client import _sanitize, EmptyResponseError


def test_strips_json_fence():
    assert _sanitize('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strips_bare_fence():
    assert _sanitize('```\n{"a": 1}\n```') == '{"a": 1}'


def test_passes_through_bare_json():
    assert _sanitize('{"a": 1}') == '{"a": 1}'


def test_strips_think_block_then_fence():
    raw = '<think>reasoning</think>\n```json\n{"a": 1}\n```'
    assert _sanitize(raw) == '{"a": 1}'


def test_strips_multiline_think_block():
    raw = '<think>\nline 1\nline 2\n</think>\n{"a": 1}'
    assert _sanitize(raw) == '{"a": 1}'


def test_strips_unclosed_think_before_json_start():
    # provider 截断：<think> 开了但没闭合，后续直接出 JSON
    raw = '<think>reasoning context...{"a": 1}'
    assert _sanitize(raw) == '{"a": 1}'


def test_strips_unclosed_think_before_array_start():
    raw = '<think>foo...[1, 2, 3]'
    assert _sanitize(raw) == '[1, 2, 3]'


def test_passes_through_plain_string():
    # 不是所有调用方都 json.loads，dialogue.reply / detect_emotion 返回纯字符串
    assert _sanitize('hello world') == 'hello world'


def test_raises_on_empty():
    with pytest.raises(EmptyResponseError):
        _sanitize('')


def test_raises_on_whitespace_only():
    with pytest.raises(EmptyResponseError):
        _sanitize('   \n\t  ')
```

- [ ] **Step 2: 在 `core/llm_client.py` 加占位，确保测试能 import 但会失败**

在 `core/llm_client.py` 的 `# ── Provider 路由 ──` 之前插入：

```python
class EmptyResponseError(RuntimeError):
    """LLM 返回空字符串或纯空白。"""


def _sanitize(raw: str) -> str:
    raise NotImplementedError
```

- [ ] **Step 3: 运行测试，确认全部失败**

Run: `pytest tests/test_llm_sanitize.py -v`
Expected: 10 FAILED with `NotImplementedError` 或 `EmptyResponseError` 没实现导致的错误

- [ ] **Step 4: 提交（红）**

```bash
git add tests/test_llm_sanitize.py core/llm_client.py
git commit -m "test(llm): red — _sanitize spec"
```

---

## Task 2: 实现 `_sanitize`，让测试全绿

**Files:**
- Modify: `core/llm_client.py:20-28`（替换上一步的 `_sanitize` 占位）

- [ ] **Step 1: 替换 `_sanitize` 的最小实现**

删除上一步的 `raise NotImplementedError`，替换为：

```python
import re

_THINK_CLOSED_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)
_THINK_OPEN_ONLY_RE = re.compile(r"<think>[\s\S]*?(?=[\{\[])", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.DOTALL)


def _sanitize(raw: str) -> str:
    """把 LLM 返回内容里 provider 相关的包裹去掉，返回可直接 json.loads 的字符串。
    对非 JSON 的纯文本返回（如情绪打分、对话回复）也安全——只是原样 trim。"""
    if raw is None:
        raise EmptyResponseError("LLM returned None")
    text = raw.strip()
    if not text:
        raise EmptyResponseError("LLM returned empty string")

    # 1. 去闭合的 <think>…</think>
    text = _THINK_CLOSED_RE.sub("", text).strip()

    # 2. 去未闭合 <think>（截断场景）：从 <think> 到首个 { 或 [ 之前删掉
    if text.startswith("<think>") and "</think>" not in text:
        text = _THINK_OPEN_ONLY_RE.sub("", text, count=1).strip()

    # 3. 去 ```json … ``` 围栏
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()

    if not text:
        raise EmptyResponseError("LLM content empty after sanitize")
    return text
```

- [ ] **Step 2: 运行测试，全绿**

Run: `pytest tests/test_llm_sanitize.py -v`
Expected: 10 PASSED

- [ ] **Step 3: 提交（绿）**

```bash
git add core/llm_client.py
git commit -m "feat(llm): add _sanitize + EmptyResponseError"
```

---

## Task 3: 把 `_sanitize` 接入 `chat_completion`，补 api_key 校验

**Files:**
- Modify: `core/llm_client.py:30-52`（`_get_chat_client`）
- Modify: `core/llm_client.py:73-92`（`chat_completion`）

- [ ] **Step 1: 在 `_get_chat_client` 里为 minimax/kimi/glm 补 api_key 校验**

把当前三段

```python
    if provider == "minimax":
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        return OpenAI(api_key=api_key, base_url=config.MINIMAX_BASE_URL), config.MINIMAX_MODEL
```

替换为（同样模式改 kimi / glm）：

```python
    if provider == "minimax":
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY 未配置（环境变量）")
        return OpenAI(api_key=api_key, base_url=config.MINIMAX_BASE_URL), config.MINIMAX_MODEL

    if provider == "kimi":
        api_key = os.environ.get("KIMI_API_KEY", "")
        if not api_key:
            raise RuntimeError("KIMI_API_KEY 未配置（环境变量）")
        return OpenAI(api_key=api_key, base_url=config.KIMI_BASE_URL), config.KIMI_MODEL

    if provider == "glm":
        api_key = os.environ.get("GLM_API_KEY", "")
        if not api_key:
            raise RuntimeError("GLM_API_KEY 未配置（环境变量）")
        return OpenAI(api_key=api_key, base_url=config.GLM_BASE_URL), config.GLM_MODEL
```

- [ ] **Step 2: 在 `chat_completion` 末尾挂上 `_sanitize`**

把：

```python
    result = _retry(_call, operation="chat_completion")
    logger.info(f"chat_completion result_len={len(result)}")
    return result
```

替换为：

```python
    result_raw = _retry(_call, operation="chat_completion")
    result = _sanitize(result_raw)
    trimmed = len(result_raw) - len(result)
    logger.info(f"chat_completion result_len={len(result)} sanitize_trimmed={trimmed}")
    return result
```

- [ ] **Step 3: 跑一遍既有单元测试，确保没回归**

Run: `pytest tests/ -v --ignore=tests/manual_test_dialogue.py --ignore=tests/manual_test_l1.py --ignore=tests/manual_test_l2.py --ignore=tests/manual_test_decay.py --ignore=tests/manual_test_graph.py --ignore=tests/manual_test_retrieval.py --ignore=tests/manual_test_soul.py --ignore=tests/e2e_test.py`
Expected: 所有非 manual 测试 PASS（如果原本就在绿就还绿；`_sanitize` 对现有测试透明，因为 mock 返回的裸字符串不会被围栏正则命中）

- [ ] **Step 4: 提交**

```bash
git add core/llm_client.py
git commit -m "feat(llm): sanitize in chat_completion + api_key checks"
```

---

## Task 4: 搭冒烟脚手架（1 个调用点跑通）

**Files:**
- Create: `tests/manual_test_provider_switch.py`

- [ ] **Step 1: 写脚手架（含 1 个条目做冒烟骨架验证）**

```python
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

import config  # noqa: E402  （必须在 sys.path 修正之后）
from core.llm_client import chat_completion  # noqa: E402

_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt_pair(filename: str) -> tuple[str, str]:
    text = (_PROMPTS / filename).read_text(encoding="utf-8")
    parts = text.split("[USER]")
    sys_part = parts[0].replace("[SYSTEM]", "").strip()
    usr_part = parts[1].strip() if len(parts) > 1 else ""
    return sys_part, usr_part


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
    float(raw.strip())
    return True


def _smoke_detect_emotion():
    sys_, usr = _load_prompt_pair("detect_emotion.txt")
    user = usr.format(user_message=SAMPLE_USER_MSG)
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
    # 让 chat_completion 的 _get_chat_client 读到新 provider
    config.LLM_PROVIDER = provider

    print(f"\n=== provider={provider} ===")
    fail = 0
    for cs in CALL_SITES:
        name = cs["name"]
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
```

- [ ] **Step 2: 用当前 provider（deepseek）跑一次确认脚手架通**

Run: `LLM_PROVIDER=deepseek python tests/manual_test_provider_switch.py`
Expected: 输出 `[deepseek] dialogue._detect_emotion: OK raw_head='...'`，退出码 0

> 如果这一步就 FAIL，先修脚手架（比如 `detect_emotion.txt` 的实际 `[SYSTEM]`/`[USER]` 结构是否跟 `_load_prompt_pair` 的假设一致——如果不一致就按实际结构调整 parse 逻辑）。

- [ ] **Step 3: 提交**

```bash
git add tests/manual_test_provider_switch.py
git commit -m "test(llm): smoke harness skeleton (1 call site)"
```

---

## Task 5: 把剩余 16 个调用点补进冒烟矩阵

**Files:**
- Modify: `tests/manual_test_provider_switch.py`

- [ ] **Step 1: 逐个补 `_smoke_*` 函数并加入 `CALL_SITES`**

在 `CALL_SITES = [...]` 之前追加以下 16 个函数；之后把每个函数追加为一个条目。每个条目结构固定：

```python
{"name": "<module>.<func>", "invoke": _smoke_xxx, "expect": <expect fn>}
```

**补 16 个 `_smoke_*` 函数（在 `_smoke_detect_emotion` 之后）：**

```python
# 2. dialogue 主回合
def _smoke_dialogue_reply():
    sys_prompt = (
        "你是一个日常对话助手。请直接回复用户的话，保持自然。"
    )
    return chat_completion(
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": SAMPLE_USER_MSG}],
        max_tokens=256, temperature=0.7,
    )


# 3. dialogue.make_decision
def _smoke_make_decision():
    sys_prompt = _load_single_prompt("decision_system.txt")
    return chat_completion(
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": "现在要不要接受这份 offer？只返回 JSON：{\"decision\": str, \"reasoning\": str}"}],
        max_tokens=256, temperature=0.2,
    )


# 4. dialogue evidence check
def _smoke_evidence_check():
    sys_, usr = _load_prompt_pair("soul_evidence_check.txt")
    user = usr.format(session_text=SAMPLE_DIALOGUE, soul_snapshot="{}")
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


# 7. memory_l2.check_and_generate_patterns
def _smoke_l2_patterns():
    sys_, usr = _load_prompt_pair("l2_generate_patterns.txt")
    events_block = "e1: 遇到冲突时选择沟通\ne2: 遇到冲突时选择沟通\ne3: 遇到冲突时选择沟通"
    user = usr.format(topic="冲突处理", events_block=events_block)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=512, temperature=0.2,
    )


# 8. memory_l1 extract_events
def _smoke_l1_extract_events():
    sys_, usr = _load_prompt_pair("l1_extract_events.txt")
    user = usr.format(dialogue_text=SAMPLE_DIALOGUE)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=512, temperature=0.2,
    )


# 9. memory_l1 score_event
def _smoke_l1_score_event():
    sys_, usr = _load_prompt_pair("l1_score_event.txt")
    user = usr.format(event_text="今天终于完成了第一版原型。")
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=256, temperature=0.2,
    )


# 10. memory_l1 extract_scene
def _smoke_l1_scene():
    sys_, usr = _load_prompt_pair("l1_extract_scene.txt")
    user = usr.format(dialogue_text=SAMPLE_DIALOGUE)
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=128, temperature=0.2,
    )


# 11. memory_l1 extract_tags
def _smoke_l1_tags():
    sys_, usr = _load_prompt_pair("l1_extract_tags.txt")
    user = usr.format(event_text="今天终于完成了第一版原型。")
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=128, temperature=0.2,
    )


# 12. seed_memory_loader init_soul_from_nodes
def _smoke_seed_init_soul():
    sys_prompt = _load_single_prompt("seed_soul_init.txt")
    user = "节点：1. 喜欢独处；2. 偏好书写表达；3. 工作里追求精确。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
        max_tokens=1024, temperature=0.2,
    )


# 13. seed_memory_loader extract_events_batch
def _smoke_seed_batch():
    sys_prompt = _load_single_prompt("seed_batch_load.txt")
    user = "节点批次：\n1. 2019 年搬去北京\n2. 2020 年换了工作\n3. 2022 年结婚"
    return chat_completion(
        [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
        max_tokens=1024, temperature=0.2,
    )


# 14. soul.init_soul
def _smoke_soul_init():
    sys_prompt = _load_single_prompt("soul_init.txt")
    user = "seed：喜欢独处；偏好书写表达；追求精确。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
        max_tokens=1024, temperature=0.2,
    )


# 15. soul.check_constitutional_conflict
def _smoke_soul_conflict():
    sys_, usr = _load_prompt_pair("soul_conflict_check.txt")
    user = usr.format(
        constitutional="诚实、克制、尊重他人",
        new_event="为了赶 deadline 撒了个小谎",
    )
    return chat_completion(
        [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
        max_tokens=256, temperature=0.1,
    )


# 16. interview_seed_builder seed
def _smoke_interview_seed():
    sys_prompt = _load_single_prompt("interview_to_seed.txt")
    user = "访谈摘录：我 1990 年出生在杭州，大学学了计算机，现在在一家创业公司做产品。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
        max_tokens=2048, temperature=0.2,
    )


# 17. interview_seed_builder l1_events
def _smoke_interview_l1():
    sys_prompt = _load_single_prompt("interview_to_l1.txt")
    user = "访谈摘录：我 1990 年出生在杭州，大学学了计算机，现在在一家创业公司做产品。"
    return chat_completion(
        [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
        max_tokens=2048, temperature=0.2,
    )


# 注：nuwa_seed_builder 的两个调用点（nuwa_skill_to_seed / nuwa_research_to_l1）依赖一份完整 SKILL.md 作为输入，
# 冒烟不方便构造最小 fixture，这里复用 interview 的两个作为代理（同样的 prompt 风格、同样需要 JSON）。
# 如果 nuwa 侧报兼容问题再单独补冒烟。
```

- [ ] **Step 2: 替换 `CALL_SITES`**

把单条目的 `CALL_SITES` 替换为 17 条目（如果某 prompt 文件的 `[SYSTEM]/[USER]` 结构实际不是预期的双段，调整对应 `_load_*` / `.format` 调用到实际结构）：

```python
CALL_SITES = [
    {"name": "dialogue._detect_emotion",          "invoke": _smoke_detect_emotion,  "expect": _expect_parseable_float},
    {"name": "dialogue.reply",                    "invoke": _smoke_dialogue_reply,  "expect": _expect_non_empty_string},
    {"name": "dialogue.make_decision",            "invoke": _smoke_make_decision,   "expect": _expect_json_dict},
    {"name": "dialogue.evidence_check",           "invoke": _smoke_evidence_check,  "expect": _expect_json_dict},
    {"name": "dialogue.new_val_fill",             "invoke": _smoke_new_val_fill,    "expect": _expect_non_empty_string},
    {"name": "retrieval.rerank",                  "invoke": _smoke_rerank,          "expect": _expect_json_list},
    {"name": "memory_l2.generate_patterns",       "invoke": _smoke_l2_patterns,     "expect": _expect_json_dict},
    {"name": "memory_l1.extract_events",          "invoke": _smoke_l1_extract_events,"expect": _expect_json_dict},
    {"name": "memory_l1.score_event",             "invoke": _smoke_l1_score_event,  "expect": _expect_json_dict},
    {"name": "memory_l1.extract_scene",           "invoke": _smoke_l1_scene,        "expect": _expect_json_dict},
    {"name": "memory_l1.extract_tags",            "invoke": _smoke_l1_tags,         "expect": _expect_json_dict},
    {"name": "seed_memory_loader.init_soul",      "invoke": _smoke_seed_init_soul,  "expect": _expect_json_dict},
    {"name": "seed_memory_loader.extract_batch",  "invoke": _smoke_seed_batch,      "expect": _expect_json_list},
    {"name": "soul.init_soul",                    "invoke": _smoke_soul_init,       "expect": _expect_json_dict},
    {"name": "soul.check_conflict",               "invoke": _smoke_soul_conflict,   "expect": _expect_json_dict},
    {"name": "interview_seed_builder.seed",       "invoke": _smoke_interview_seed,  "expect": _expect_json_dict},
    {"name": "interview_seed_builder.l1_events",  "invoke": _smoke_interview_l1,    "expect": _expect_json_list},
]
```

- [ ] **Step 3: 跑 deepseek 基线**

Run: `LLM_PROVIDER=deepseek python tests/manual_test_provider_switch.py`
Expected: 至少 15/17 OK（允许个别 prompt 在 fixture 最小化后返回不完全符合，但 JSON 解析应都过）。若某项 FAIL，看 traceback：
- 若是 `_load_prompt_pair` 把 prompt 解析错了，调整对应 prompt 的 parse。
- 若是 prompt 在最小 fixture 下返回不规范，调整 fixture 或 expect。
- 调通后重跑到绿/可接受。

- [ ] **Step 4: 提交**

```bash
git add tests/manual_test_provider_switch.py
git commit -m "test(llm): full smoke matrix (17 call sites)"
```

---

## Task 6: deepseek 基线进 provider_compat.md

**Files:**
- Create: `docs/provider_compat.md`

- [ ] **Step 1: 建文档并写基线**

```markdown
# Provider 兼容性矩阵

跨 provider 冒烟结果。每次切 `LLM_PROVIDER` 后运行：

```bash
LLM_PROVIDER=<provider> python tests/manual_test_provider_switch.py
```

## 2026-04-18 基线

| 调用点 | deepseek | minimax | kimi | glm |
|---|:-:|:-:|:-:|:-:|
| dialogue._detect_emotion | ✅ | ? | ? | ? |
| dialogue.reply | ✅ | ? | ? | ? |
| dialogue.make_decision | ✅ | ? | ? | ? |
| dialogue.evidence_check | ✅ | ? | ? | ? |
| dialogue.new_val_fill | ✅ | ? | ? | ? |
| retrieval.rerank | ✅ | ? | ? | ? |
| memory_l2.generate_patterns | ✅ | ? | ? | ? |
| memory_l1.extract_events | ✅ | ? | ? | ? |
| memory_l1.score_event | ✅ | ? | ? | ? |
| memory_l1.extract_scene | ✅ | ? | ? | ? |
| memory_l1.extract_tags | ✅ | ? | ? | ? |
| seed_memory_loader.init_soul | ✅ | ? | ? | ? |
| seed_memory_loader.extract_batch | ✅ | ? | ? | ? |
| soul.init_soul | ✅ | ? | ? | ? |
| soul.check_conflict | ✅ | ? | ? | ? |
| interview_seed_builder.seed | ✅ | ? | ? | ? |
| interview_seed_builder.l1_events | ✅ | ? | ? | ? |

## 已知兼容性问题
（填空）
```

（如果基线里某项实际 FAIL，写 ❌ 并在"已知兼容性问题"里记原因）

- [ ] **Step 2: 提交**

```bash
git add docs/provider_compat.md
git commit -m "docs(llm): provider compat baseline (deepseek)"
```

---

## Task 7: 打通 minimax

**Files:**
- Modify: `config.py:13-14`
- Modify: `.env.example`
- Modify: `docs/provider_compat.md`

- [ ] **Step 1: 填 minimax 配置**

打开 `config.py`，把：

```python
MINIMAX_MODEL = ""
MINIMAX_BASE_URL = ""
```

替换为：

```python
MINIMAX_MODEL = "MiniMax-M2"
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
```

> 用户已确认 MiniMax-M2 高速端点。实际 base_url 以 minimax 官方 OpenAI 兼容文档为准（常见形式 `https://api.minimaxi.com/v1` 或 `https://api.minimax.chat/v1`，若第一个跑不通切第二个；两者都不通则查 minimax 控制台的 "OpenAI 兼容 API" 入口）。

- [ ] **Step 2: 加 `.env.example`**

打开 `.env.example` 追加：

```
MINIMAX_API_KEY=
KIMI_API_KEY=
GLM_API_KEY=
```

- [ ] **Step 3: 在本地 `.env` 里写真实 `MINIMAX_API_KEY`**

（由用户/执行者手动填写，plan 不提交 `.env`。）

- [ ] **Step 4: 跑 minimax 冒烟**

Run: `LLM_PROVIDER=minimax python tests/manual_test_provider_switch.py`
Expected: 至少 14/17 OK（80% 阈值）

若 FAIL 了几项：
- `FAIL(exception)` + 401 → api_key 问题，检查 `.env`
- `FAIL(exception)` + 404/DNS → base_url 错，换另一个候选
- `FAIL(exception)` + JSONDecodeError → prompt 服从度问题，记入 compat.md 已知问题，**不改代码**，换下一项
- `FAIL(schema)` → prompt 返回格式不对，记入 compat.md

- [ ] **Step 5: 更新 compat.md**

把 minimax 列的 `?` 按实际结果改成 ✅/❌，把 ❌ 的原因写进"已知兼容性问题"。

- [ ] **Step 6: 提交**

```bash
git add config.py .env.example docs/provider_compat.md
git commit -m "feat(config): enable minimax provider + compat results"
```

---

## Task 8: 打通 kimi

**Files:**
- Modify: `config.py:16-17`
- Modify: `docs/provider_compat.md`

- [ ] **Step 1: 填 kimi 配置**

把：

```python
KIMI_MODEL = ""
KIMI_BASE_URL = ""
```

替换为：

```python
KIMI_MODEL = "kimi-k2-0905-preview"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
```

> base_url 是 moonshot 官方 OpenAI 兼容入口。模型名以 moonshot 控制台可用模型为准，若 `kimi-k2-0905-preview` 不可用可替换为 `moonshot-v1-32k`。

- [ ] **Step 2: 跑 kimi 冒烟**

Run: `LLM_PROVIDER=kimi python tests/manual_test_provider_switch.py`
Expected: 至少 14/17 OK

- [ ] **Step 3: 更新 compat.md**

- [ ] **Step 4: 提交**

```bash
git add config.py docs/provider_compat.md
git commit -m "feat(config): enable kimi provider + compat results"
```

---

## Task 9: 打通 glm

**Files:**
- Modify: `config.py:19-20`
- Modify: `docs/provider_compat.md`

- [ ] **Step 1: 填 glm 配置**

把：

```python
GLM_MODEL = ""
GLM_BASE_URL = ""
```

替换为：

```python
GLM_MODEL = "glm-4.6"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
```

> base_url 是智谱官方 OpenAI 兼容入口。模型名以智谱 BigModel 当前可用模型为准。
> 注意：glm-4.5+ 模型可能会在响应里带 `<think>…</think>` 块——这正是 Task 2 的 `_sanitize` 要清的东西，如果冒烟里看到 `JSONDecodeError` 且 raw_head 带 `<think>`，说明 `_sanitize` 的正则没命中实际返回（比如带属性的 `<think type="...">`），需要回 Task 2 的测试里补 case 再修正则。

- [ ] **Step 2: 跑 glm 冒烟**

Run: `LLM_PROVIDER=glm python tests/manual_test_provider_switch.py`
Expected: 至少 14/17 OK

- [ ] **Step 3: 更新 compat.md**

- [ ] **Step 4: 提交**

```bash
git add config.py docs/provider_compat.md
git commit -m "feat(config): enable glm provider + compat results"
```

---

## Task 10（可选）: 清掉 8 份 `_strip_json` 副本

**Files:**
- Modify: `core/dialogue.py:93-96, 297, 404`（去掉 `_strip_json`，`json.loads(_strip_json(raw))` → `json.loads(raw)`；L150-152 的 retrieval 特例也改掉）
- Modify: `core/retrieval.py:150-153`（同上）
- Modify: `core/interview_seed_builder.py:252-255, 277, 301`
- Modify: `core/memory_l1.py:91-94, 102`
- Modify: `core/memory_l2.py:59-62, 203`
- Modify: `core/nuwa_seed_builder.py:58-61, 105, 174`
- Modify: `core/seed_memory_loader.py:72-75, 175, 222`
- Modify: `core/seed_parser.py:67-73, 109`（函数名是 `_strip_markdown_json`）
- Modify: `core/soul.py:95-98, 192, 323`

- [ ] **Step 1: 逐文件操作**

对每个文件：
- 删除 `def _strip_json(...)` / `def _strip_markdown_json(...)` 整段（约 4 行）。
- 把 `json.loads(_strip_json(raw))` 改为 `json.loads(raw)`。
- 把 `json.loads(_strip_markdown_json(raw))` 改为 `json.loads(raw)`。
- `core/retrieval.py:149-152` 有 4 行独立的 fence 剥离：
  ```python
  raw = raw.strip()
  m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
  if m:
      raw = m.group(1)
  ```
  全部删掉（`chat_completion` 已经做过清洗）。

- [ ] **Step 2: 跑既有单元测试**

Run: `pytest tests/ -v --ignore=tests/manual_test_*.py --ignore=tests/e2e_test.py --ignore=tests/manual_test_provider_switch.py`
Expected: PASS（调用方之前是 `json.loads(_strip_json(raw))`，现在 `chat_completion` 已经返回清洗后的 `raw`，二者行为等价）

- [ ] **Step 3: 跑 deepseek 冒烟**

Run: `LLM_PROVIDER=deepseek python tests/manual_test_provider_switch.py`
Expected: 与 Task 6 基线完全一致（改动是重构不是行为变化）

- [ ] **Step 4: 提交**

```bash
git add core/
git commit -m "refactor(core): remove 8 duplicated _strip_json copies"
```

---

## 双 Agent 协同建议

本 plan 的 10 个 Task 天然分工：

- **Implementer（主执行者）**：Task 1–3（加 `_sanitize`）、Task 7–9（填 config）、Task 10（可选清理）。
- **Verifier（独立 agent，最好另开会话）**：每个涉及冒烟的 Task 结束后，独立跑一遍冒烟、核对 `provider_compat.md` 是否与当前代码一致、是否有 Implementer 漏掉的 FAIL。Verifier 只读不写，或仅改 `provider_compat.md`。

建议用 **subagent-driven-development** 模式：每个 Task 派一个 fresh subagent 执行，主 session 做 review。这样每次上下文干净、失败只影响当前 Task。
