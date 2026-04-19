# Provider 兼容性矩阵

跨 provider 冒烟结果。每次切 `LLM_PROVIDER` 后运行：

```bash
LLM_PROVIDER=<provider> python tests/manual_test_provider_switch.py
```

## 2026-04-18 基线

| 调用点 | deepseek | minimax | kimi | glm |
|---|:-:|:-:|:-:|:-:|
| dialogue._detect_emotion | ✅ | ✅ | ? | ✅ |
| dialogue.reply | ✅ | ✅ | ? | ✅ |
| dialogue.make_decision | ✅ | ✅ | ? | ✅ |
| dialogue.evidence_check | ✅ | ✅ | ? | ✅ |
| dialogue.new_val_fill | ✅ | ✅ | ? | ✅ |
| retrieval.rerank | ✅ | ✅ | ? | ✅ |
| memory_l2.generate_patterns | ✅ | ⚠️ | ? | ✅ |
| memory_l1.extract_events | ✅ | ✅ | ? | ✅ |
| memory_l1.score_event | ✅ | ✅ | ? | ✅ |
| memory_l1.extract_scene | ✅ | ✅ | ? | ✅ |
| memory_l1.extract_tags | ✅ | ⚠️ | ? | ✅ |
| seed_memory_loader.init_soul | ✅ | ✅ | ? | ✅ |
| seed_memory_loader.extract_batch | ✅ | ✅ | ? | ✅ |
| soul.init_soul | ✅ | ✅ | ? | ✅ |
| soul.check_conflict | ✅ | ✅ | ? | ✅ |
| interview_seed_builder.seed | ✅ | ✅ | ? | ✅ |
| interview_seed_builder.l1_events | ✅ | ✅ | ? | ✅ |
| seed_parser.parse_seed | ✅ | ✅ | ? | ✅ |

图例：✅ 稳定通过；⚠️ 偶发失败（≥1 轮未过）；❌ 稳定失败；？ 未测。

## 已知兼容性问题

- **推理模型需关闭 thinking（或抬高 max_tokens）**：GLM-5.1 / MiniMax-M2.7-highspeed 默认做推理，reasoning_tokens 会占生产调用点 `max_tokens` 预算（64–1024），小输出调用点会被推理吃光，返回空或截断。
  - **GLM-5.1**：`extra_body={"thinking":{"type":"disabled"}}` 关推理（官方字段），已在 `core/llm_client._get_chat_client()` 注入。实测 18/18 稳定 ✅。
  - **MiniMax-M2.7-highspeed**：官方 API **不提供**关推理参数（实测 `enable_thinking` / `reasoning_effort` / `thinking.type=disabled` / `no_think` / `chat_template_kwargs.enable_thinking` 等均无效）。折中方案：在 `_get_chat_client` 给 minimax 返回 `token_multiplier=16`，`chat_completion` 把 `max_tokens × 16` 再 clamp 到 `LLM_MAX_OUTPUT_TOKENS`，给推理 + 答案都留空间；同时 client timeout 抬到 180s（推理 p99 墙时 >60s）。

- **MiniMax 脆性调用点**：跨 3 轮冒烟，`memory_l1.extract_tags` 2/3 轮未过、`memory_l2.generate_patterns` 1/3 轮未过——推理模型 JSON 格式服从度不稳定（曾出 `Unterminated string` / `Expecting property name`）。整体通过率 51/54 ≈ **94%**。这两个点建议：若要用 minimax 跑生产，caller 侧对 JSONDecodeError 加重试；或把这两个点 pin 在 deepseek/glm。

- **延迟**：MiniMax-M2.7-highspeed 单次推理调用典型 10–30s（含 1–2K reasoning_tokens），比 DeepSeek-chat（1–3s）慢 5–10 倍；交互对话场景（dialogue.reply + _detect_emotion 串联）体感明显下降。适合时间计费套餐下的批量建库。
