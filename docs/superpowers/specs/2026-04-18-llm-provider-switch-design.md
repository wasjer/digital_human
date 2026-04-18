# LLM Provider 切换 —— 设计方案

日期：2026-04-18
范围：支持在 **deepseek / minimax / kimi / glm** 四家 OpenAI 兼容 provider 之间通过 `LLM_PROVIDER` 一键切换。不包含 Claude / Gemini（未来需求）。

## 1. 问题与目标

### 真实痛点
前两次切换尝试回滚的直接原因不是架构问题，而是：
- **触点分散**：`_strip_json` 在 `core/` 下的 8 个文件里各自重写了一份，任一 provider 带来的新文本包裹规则（例如 `<think>` 思考块）都要改 8 处，改不干净。
- **没有验证矩阵**：切完以后没有一个"每个调用点 × 每个 provider"的冒烟脚本，只能靠运行中踩到哪算哪、回滚就白改。

### 目标（必须达成）
1. 切换 provider 的改动面收敛到**一个代码位置**（`core/llm_client.py`）与**一处配置**（`config.py`）。
2. `chat_completion()` 对下游透明地返回"已清洗的 JSON 可解析字符串"；17 个调用点的 `json.loads(...)` 契约不变。
3. 每次切 provider 都能在合并前跑一个冒烟脚本，覆盖所有 `chat_completion` 调用点，定位到 `(provider, 调用点)` 级别。

### 非目标（明确不做）
- 不支持 Claude / Gemini 等非 OpenAI 协议 provider。
- 不做自动 fallback 降级（同一调用点在 provider A 坏了不自动切 B）。
- 不做 per-task provider 路由（同次运行里所有 `chat_completion` 调用用同一家）。
- 不动 17 个调用方的代码（除了第 3.3 节允许的"去掉各自的 `_strip_json` 副本"）。

## 2. 架构

三层分工，每层只解决它该解决的事：

| 层 | 范围 A (4 家) 下是否有差异 | 谁来统一 |
|---|---|---|
| 1. HTTP/SDK 传输 | 无差异，都走 OpenAI chat API | `openai` SDK |
| 2. 文本包裹（```json 围栏、`<think>` 块、空串/截断） | **有差异**——真正的 provider 变量 | **`chat_completion()` 内部集中后处理**（本次新增） |
| 3. JSON schema（字段名、结构） | 无差异——由你的 prompt 规定 | prompt 本身；跨 provider 服从度差异靠冒烟测试暴露 |

### 数据流

```
调用方                              llm_client.chat_completion()
──────                              ──────────────────────────────
messages  ─────────────────────▶   _get_chat_client()          ← 按 LLM_PROVIDER 路由
                                    client.chat.completions.create()
                                      │
                                      ▼
                                    resp.choices[0].message.content  (可能含 ```json 围栏 / <think>…</think> / 空串)
                                      │
                                      ▼
                                    _sanitize(raw)                    ← 本次新增的"统一清洗工具"
                                      │                                   1. 去 ```json ``` 围栏
                                      │                                   2. 去 <think>…</think>（及 DeepSeek-R1 的 reasoning_content 合并异常）
                                      │                                   3. 去常见前言包裹（"以下是 JSON："之类）
                                      │                                   4. 空串/纯空白抛 EmptyResponseError
                                      ▼
                    ◀─────────────   str（可直接 json.loads 的文本；原本就是裸 JSON 则原样透传）

调用方继续：json.loads(raw) → 业务逻辑
```

## 3. 组件变更

### 3.1 `core/llm_client.py`（核心改动）

**新增模块级函数** `_sanitize(raw: str) -> str`：
- 输入 `chat_completion` 的原始返回文本。
- 按以下顺序处理：
  1. `str.strip()`
  2. 若整体为空或仅有空白/换行 → `raise EmptyResponseError(provider, model)`
  3. 若匹配 `<think>...</think>`（DOTALL），去掉整个块；若首尾不配对（只有 `<think>` 没有 `</think>`，常见于截断），去掉从 `<think>` 到首个 `{` 或 `[` 之前的全部内容。
  4. 若匹配 ```` ```(?:json)?\s*([\s\S]+?)\s*``` ````，取捕获组内容。
  5. 再 `strip()` 一次。返回。
- 不捕获 `json.JSONDecodeError`——调用方原有的 try/except 已覆盖。

**新增自定义异常** `class EmptyResponseError(RuntimeError)`。

**修改** `chat_completion()`：
- 在 `_retry` 返回后、`return result` 前，插入 `result = _sanitize(result)`。
- 日志保持 `result_len=len(result)`，但额外记录 `sanitize_trimmed=<原长度 - 清洗后长度>` 以便诊断。

**修改** `_get_chat_client()`：
- minimax / kimi / glm 分支里，api_key 缺失时也要抛 `RuntimeError(f"{provider}_API_KEY 未配置")`（当前 deepseek 有，其他三家没有，是 bug 也是本次必补）。

### 3.2 `config.py`（填值）

把以下字段从空串填满：

```python
MINIMAX_MODEL    = "MiniMax-M2"            # 用户已确认：coding plan 下的高速端点
MINIMAX_BASE_URL = "<impl 时查 minimax 官方文档确认 openai 兼容端点>"

KIMI_MODEL       = "<impl 时确认，例如 kimi-k2-0905-preview>"
KIMI_BASE_URL    = "https://api.moonshot.cn/v1"

GLM_MODEL        = "<impl 时确认，例如 glm-4.6>"
GLM_BASE_URL     = "https://open.bigmodel.cn/api/paas/v4"
```

> 模型名与 base_url 的具体字面值在实施（提交 3）时以官网为准。`MINIMAX_MODEL=MiniMax-M2` 已由用户确认。

`.env.example` 追加 `MINIMAX_API_KEY=`、`KIMI_API_KEY=`、`GLM_API_KEY=`。

### 3.3 调用方（`core/` 下 8 个文件）

**强烈推荐但可选**：删除各文件里的 `_strip_json` / `_strip_markdown_json` 私有副本与其调用，改为直接 `json.loads(raw)`。

受影响文件：`core/dialogue.py`, `core/memory_l1.py`, `core/memory_l2.py`, `core/nuwa_seed_builder.py`, `core/interview_seed_builder.py`, `core/seed_memory_loader.py`, `core/seed_parser.py`, `core/soul.py`（共 8 个，定义点见第 6 节附录）。

这一步属于"顺手清理"，失败可回滚，不影响切 provider 功能。推荐做是因为：保留私有副本时，一旦清洗规则在 `llm_client` 内部升级（例如以后要加新规则），调用方私有副本仍是旧规则，会造成行为分叉。

### 3.4 `tests/test_provider_switch.py`（新增冒烟测试）

> 参考现有约定：`tests/test_*.py` 走 pytest；`manual_test_*.py` 是可能要真实 API 的手动脚本。本次冒烟测试走 `manual_test_provider_switch.py` 的形态，因为它**必须打真实 API**。

结构：
```
manual_test_provider_switch.py
├── CALL_SITES = [
│     {
│       "name": "memory_l1._llm_json",
│       "invoke": lambda: 准备最小 fixture + 真的走一遍 chat_completion,
│       "expect": lambda out: isinstance(out, dict) and "events" in out,
│     },
│     ... 每个 chat_completion 调用点一条
│   ]
└── main():
      provider = os.environ["TARGET_PROVIDER"]   # 由外部 shell 循环设置
      for cs in CALL_SITES:
          try: out = cs["invoke"](); ok = cs["expect"](out)
          except Exception as e: ok = False; err = e
          print(f"[{provider}] {cs['name']}: {'OK' if ok else 'FAIL'} {err or ''}")
      sys.exit(0 if all_ok else 1)
```

外层 shell 用 `for p in deepseek minimax kimi glm; do LLM_PROVIDER=$p python manual_test_provider_switch.py; done` 得到 4×N 的结果矩阵。

**每个调用点的 fixture 必须"最小但合法"**：不得依赖真实持久化数据，方便在 CI 或本地一键跑。

调用点清单（参见第 6 节附录完整映射）共 17 个：
1. `core/seed_parser.py::parse_seed` (L105)
2. `core/dialogue.py::_detect_emotion` (L102)
3. `core/dialogue.py:: dialogue 主回合` (L210)
4. `core/dialogue.py::_end_session_async evidence` (L291)
5. `core/dialogue.py::_end_session_async new_val` (L321)
6. `core/dialogue.py::make_decision` (L398)
7. `core/retrieval.py::rerank` (L143)
8. `core/memory_l2.py::check_and_generate_patterns` (L197)
9. `core/memory_l1.py::_llm_json` (L98)
10. `core/seed_memory_loader.py::_init_soul_from_nodes` (L173)
11. `core/seed_memory_loader.py::_extract_events_batch` (L220)
12. `core/soul.py::init_soul` (L189)
13. `core/soul.py::check_constitutional_conflict` (L320)
14. `core/interview_seed_builder.py::_call_llm_for_seed` (L271)
15. `core/interview_seed_builder.py::_call_llm_for_l1_events` (L295)
16. `core/nuwa_seed_builder.py::_extract_seed` (L100)
17. `core/nuwa_seed_builder.py::_extract_events_of_kind` (L169)

实际以 Agent-A（见第 5 节）清查为准。

## 4. 错误处理

| 故障模式 | 谁处理 | 怎么处理 |
|---|---|---|
| API 超时 / 网络错误 / 5xx | `_retry`（已存在） | 指数退避最多 3 次 |
| API 返回空 content | `_sanitize` → `EmptyResponseError` | 让 `_retry` 捕获并重试（需在 `_retry` 的 `except Exception` 里命中） |
| `<think>` 未闭合（截断） | `_sanitize` | 尽力剥离；若剥离后仍非合法 JSON，调用方的 `json.JSONDecodeError` 处理 |
| JSON 解析失败 | 调用方自己（现有逻辑） | 保留原有 log + 异常行为 |
| 某 provider 对某 prompt 不服从（schema 不对） | 人工 | 冒烟测试会标红 `(provider, call_site)`；记 `docs/provider_compat.md`，不自动降级 |
| api_key 未配置 | `_get_chat_client` | 抛 `RuntimeError`，不进 `_retry` 重试（当前 deepseek 已有，其余三家本次补齐） |

## 5. 实施流程（双 agent + 3 个可独立回滚的提交）

### 提交 1：冒烟测试骨架 + 调用点清单
- **由 Agent-A 产出**：`manual_test_provider_switch.py` + `docs/provider_compat.md` 初始占位。
- **Agent-A 不改 `core/` 代码**，只读取 + 新增 `tests/`、`docs/`。
- 验收：当前 `LLM_PROVIDER=deepseek` 跑冒烟脚本应全绿（因为代码没变）。
- **失败可独立回滚**：仅删除新文件，不影响生产路径。

### 提交 2：`chat_completion` 集中清洗 + `EmptyResponseError`
- **由主 Claude 改**：`core/llm_client.py` 加 `_sanitize` 与异常，修 api_key 检查。
- 验收：`LLM_PROVIDER=deepseek` 跑冒烟测试仍全绿（行为不变，清洗只是"锦上添花"）。
- **失败可独立回滚**：只退 `core/llm_client.py` 一个文件。

### 提交 3：config 填值 + 跨 provider 冒烟
- **由主 Claude 改**：`config.py` 填 base_url/model，`.env.example` 补 key。
- **由 Agent-B 验证**：在本地循环 `LLM_PROVIDER` ∈ {deepseek, minimax, kimi, glm}，每家跑冒烟测试，汇总矩阵报告。
- 验收标准：deepseek 全绿、其余三家 `≥ 80%` 调用点绿（soul/评分类这种对指令服从要求高的调用点允许个别红，进 `provider_compat.md` 登记即可）。
- **失败可独立回滚**：退 `config.py` 即可回到默认 deepseek。

### 可选提交 4：去除 8 份 `_strip_json` 副本
- 独立提交，让调用方直接 `json.loads(raw)`。
- 本提交失败回滚不影响前 3 个提交带来的 provider 切换能力。

## 6. 附录

### 6.1 `_strip_json` 副本定义位置
- `core/dialogue.py:93`
- `core/interview_seed_builder.py:252`
- `core/memory_l1.py:91`
- `core/memory_l2.py:59`
- `core/nuwa_seed_builder.py:58`
- `core/seed_memory_loader.py:72`
- `core/seed_parser.py:67`（此文件命名为 `_strip_markdown_json`）
- `core/soul.py:95`

全部是同一段正则 `r"```(?:json)?\s*([\s\S]+?)\s*```"`。

### 6.2 决策记录
- **为什么不用 Provider Registry / BaseProvider 抽象类？** scope A 下 4 家都走 OpenAI 协议，用现有 `if/elif` 路由 + 集中清洗已经解决问题；引入类层会让未来加 Claude/Gemini 时反而被既有抽象约束。等真正需要时再做。
- **为什么冒烟测试放 `manual_test_*.py` 而不是 pytest？** 要真实打 API、有成本、不能进 CI 默认流水；手动执行语义更明确，也贴合现有项目约定。
- **为什么保留调用方的 `json.loads` + `_strip_json` 而不是一步到位改成在 `chat_completion` 里直接 `return json.loads(...)`？** 现有部分调用方（如 `core/dialogue.py::make_decision` L404）在 JSON 解析失败时有自己的回落策略（用原文当 decision），由调用方掌握合适。`chat_completion` 始终返回字符串是对 16 处调用契约的最小侵入。
