# LLM Provider 切换工作日志

## 2026-04-19 当前状态：可用，但需继续观察

已落地 3 个 provider（deepseek / glm / minimax），kimi 跳过。切换方式：改 `config.py` 的 `LLM_PROVIDER`（一处），embedding 走 SiliconFlow，独立于 provider。

## 本轮提交

- `0bb05c7 docs(llm): provider compat baseline (deepseek)` — 18 调用点冒烟矩阵基线
- `ef5de3c feat(llm): enable glm provider with thinking disabled` — GLM-5.1 通过 `extra_body={"thinking":{"type":"disabled"}}` 关推理
- `0b61447 feat(llm): enable minimax provider with max_tokens multiplier` — MiniMax 官方无关推理参数，走 `token_multiplier=16` + timeout=180s

## 冒烟结果（18 调用点 × 3 轮）

| Provider | 通过率 | 备注 |
|---|---|---|
| deepseek | 18/18 | 非推理模型，延迟 1–3s |
| glm-5.1 | 18/18 | 关推理后稳定 |
| minimax-m2.7-highspeed | ~51/54 ≈ 94% | 推理 JSON 服从度不稳定 |

## 已知不稳定点（需多测）

- **MiniMax `memory_l1.extract_tags`**：3 轮中 2 轮失败（JSON 截断 / `Unterminated string`）
- **MiniMax `memory_l2.generate_patterns`**：3 轮中 1 轮失败
- **MiniMax 延迟**：单次 10–30s（含 1–2K reasoning_tokens），对话串联体感慢
- **外部瞬时抖动**：曾遇 GLM 400 `未正常接收到prompt参数` + SiliconFlow embedding 400 同时出现一次，复测通过；非配置 / 切换相关，属 provider 侧瞬时问题

## 设计要点（便于回看）

- **不影响 deepseek / glm**：`_get_chat_client` 返回 `token_multiplier`，非推理 provider 恒为 1，`chat_completion` 路径与旧实现字节一致
- **推理模型两条路径**：GLM 有官方关推理字段；MiniMax 无——实测 `enable_thinking` / `reasoning_effort` / `thinking.type=disabled` / `no_think` / `chat_template_kwargs.enable_thinking` 均无效，改走预算放大
- **`_sanitize` 保留**：MiniMax 的 `<think>…</think>` 内联在 content 里，仍需剥

## 继续测试建议

1. 长对话跑 main_chat（dialogue.reply + _detect_emotion 串联），观察 MiniMax 体感
2. 批量建库场景跑 seed_memory_loader，观察 MiniMax 在 extract_tags 上的失败是否可容忍
3. 若 MiniMax 要上生产，`extract_tags` / `generate_patterns` 考虑 pin 在 deepseek/glm，或 caller 层加 JSONDecodeError 重试
4. 观察是否再现 embedding 瞬时 400；若频繁，给 embedding 路径加 try/except 兜底，避免整段对话崩
