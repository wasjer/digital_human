# Provider 兼容性矩阵

跨 provider 冒烟结果。每次切 `LLM_PROVIDER` 后运行：

```bash
LLM_PROVIDER=<provider> python tests/manual_test_provider_switch.py
```

## 2026-04-18 基线

| 调用点 | deepseek | minimax | kimi | glm |
|---|:-:|:-:|:-:|:-:|
| dialogue._detect_emotion | ✅ | ? | ? | ✅ |
| dialogue.reply | ✅ | ? | ? | ✅ |
| dialogue.make_decision | ✅ | ? | ? | ✅ |
| dialogue.evidence_check | ✅ | ? | ? | ✅ |
| dialogue.new_val_fill | ✅ | ? | ? | ✅ |
| retrieval.rerank | ✅ | ? | ? | ✅ |
| memory_l2.generate_patterns | ✅ | ? | ? | ✅ |
| memory_l1.extract_events | ✅ | ? | ? | ✅ |
| memory_l1.score_event | ✅ | ? | ? | ✅ |
| memory_l1.extract_scene | ✅ | ? | ? | ✅ |
| memory_l1.extract_tags | ✅ | ? | ? | ✅ |
| seed_memory_loader.init_soul | ✅ | ? | ? | ✅ |
| seed_memory_loader.extract_batch | ✅ | ? | ? | ✅ |
| soul.init_soul | ✅ | ? | ? | ✅ |
| soul.check_conflict | ✅ | ? | ? | ✅ |
| interview_seed_builder.seed | ✅ | ? | ? | ✅ |
| interview_seed_builder.l1_events | ✅ | ? | ? | ✅ |
| seed_parser.parse_seed | ✅ | ? | ? | ✅ |

## 已知兼容性问题

- **推理模型需关闭 thinking**：GLM-5.1 / MiniMax-M2.7-highspeed 等推理模型默认会消耗 `max_tokens` 做推理，而生产调用点按非推理模型预算 (64–1024) 写；若不关推理，小输出调用点（情绪打分、tag 抽取等）的 `max_tokens` 会被推理吃光，返回空 content。
  - GLM：`chat.completions.create(extra_body={"thinking":{"type":"disabled"}})` 关闭，已在 `core/llm_client._get_chat_client()` 注入。实测 18/18 ✅。
  - MiniMax：关推理的官方参数待确认。
