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
| seed_parser.parse_seed | ✅ | ? | ? | ? |

## 已知兼容性问题

（填空）
