import os
import re
import json
import time
import logging
import urllib.request
import urllib.error
from typing import Optional

from openai import OpenAI

import config
from core import trace

# ── 日志配置 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logger = logging.getLogger("llm_client")


# ── 响应清洗 ────────────────────────────────────────────────────────────────

# Matches bare <think>…</think>. NOTE: GLM-4.5+ may return <think type="...">…</think>
# which will NOT match. If Task 9's smoke run shows unstripped GLM think blocks, broaden
# this regex to r"<think\b[^>]*>[\s\S]*?</think>" and add a corresponding test.
_THINK_CLOSED_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)
# Truncation heuristic: if <think> is opened but never closed, strip from <think>
# up to the first { or [. Known limitation: if the think body itself contains a
# literal { or [, we stop too early — accepted, since real truncation is rare and
# think-containing-brace content is rarer.
_THINK_OPEN_ONLY_RE = re.compile(r"<think>[\s\S]*?(?=[\{\[])", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.DOTALL)


class EmptyResponseError(RuntimeError):
    """LLM 返回空字符串或纯空白。"""


def _sanitize(raw: Optional[str]) -> str:
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


# ── Provider 路由 ────────────────────────────────────────────────────────────

_PROVIDER_ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "minimax":  "MINIMAX_API_KEY",
    "kimi":     "KIMI_API_KEY",
    "glm":      "GLM_API_KEY",
}


def _get_chat_client() -> tuple[OpenAI, str, dict, int]:
    """根据 LLM_PROVIDER 返回 (OpenAI client, model_name, extra_body, token_multiplier)。

    - extra_body：透传到 chat.completions.create。GLM 用它关 thinking。
    - token_multiplier：无法关推理的推理模型（如 MiniMax-M2.x 系列）把 max_tokens
      按调用方写的值直接用，会被推理吃光；此系数在 chat_completion 里把 max_tokens
      乘进去并 clamp 到 LLM_MAX_OUTPUT_TOKENS，给推理+答案都留出预算。非推理 provider
      一律为 1，行为与乘前完全一致。
    """
    provider = getattr(config, "LLM_PROVIDER", "deepseek")

    if provider == "deepseek":
        api_key = config.DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置（config.py 或环境变量）")
        return OpenAI(api_key=api_key, base_url=config.DEEPSEEK_BASE_URL), config.DEEPSEEK_MODEL, {}, 1

    if provider == "minimax":
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY 未配置（环境变量）")
        # MiniMax-M2.x 系列是推理模型，官方 API 不提供关推理参数（实测 enable_thinking /
        # reasoning_effort / thinking.type / no_think / chat_template_kwargs 等均无效）。
        # <think>…</think> 内联在 content 里由 _sanitize 剥；但 reasoning_tokens 会占
        # max_tokens 预算——把 max_tokens 乘 16 给推理 + 答案都留空间（实测 ×8 对 base=128
        # 的结构化 JSON 调用点会截断，~1100 tokens thinking 把 1024 budget 吃光）；
        # clamp 防超 LLM_MAX_OUTPUT_TOKENS 上限。超时也抬到 180s，推理模型 p99 墙时 >60s。
        return (
            OpenAI(api_key=api_key, base_url=config.MINIMAX_BASE_URL, timeout=180.0),
            config.MINIMAX_MODEL,
            {},
            16,
        )

    if provider == "kimi":
        api_key = os.environ.get("KIMI_API_KEY", "")
        if not api_key:
            raise RuntimeError("KIMI_API_KEY 未配置（环境变量）")
        return OpenAI(api_key=api_key, base_url=config.KIMI_BASE_URL), config.KIMI_MODEL, {}, 1

    if provider == "glm":
        api_key = os.environ.get("GLM_API_KEY", "")
        if not api_key:
            raise RuntimeError("GLM_API_KEY 未配置（环境变量）")
        # glm-5.1 默认开 thinking，会把 reasoning_tokens 算进 max_tokens 预算；关掉让
        # content 直接拿到答案。智谱 BigModel OpenAI 兼容口官方支持该字段。
        return (
            OpenAI(api_key=api_key, base_url=config.GLM_BASE_URL),
            config.GLM_MODEL,
            {"thinking": {"type": "disabled"}},
            1,
        )

    raise RuntimeError(f"未知 LLM_PROVIDER: {provider!r}，可选: deepseek | minimax | kimi | glm")


def _retry(fn, operation: str, max_retries: int = 3, base_delay: float = 2.0):
    """最多重试 max_retries 次，指数退避。"""
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            logger.debug(f"{operation} success attempt={attempt}")
            return result
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"{operation} failed after {max_retries} attempts error={e}")
                raise
            delay = base_delay ** attempt
            logger.warning(f"{operation} attempt={attempt} error={e} retry_in={delay}s")
            time.sleep(delay)


# ── 公开接口 ─────────────────────────────────────────────────────────────────

def chat_completion(
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """根据 LLM_PROVIDER 路由调用 chat，返回回复文本。embedding 不受影响。"""
    provider = getattr(config, "LLM_PROVIDER", "deepseek")
    captured: dict = {}

    def _call():
        client, model, extra_body, token_mul = _get_chat_client()
        effective_max = min(max_tokens * token_mul, config.LLM_MAX_OUTPUT_TOKENS)
        if effective_max != max_tokens:
            logger.debug(
                f"chat_completion max_tokens={max_tokens}x{token_mul}->{effective_max} "
                f"(provider reasoning budget)"
            )
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=effective_max,
            temperature=temperature,
            extra_body=extra_body or None,
        )
        captured["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        captured["model"] = model
        captured["effective_max_tokens"] = effective_max
        captured["usage"] = getattr(resp, "usage", None)
        return resp.choices[0].message.content

    result_raw = _retry(_call, operation="chat_completion")
    result = _sanitize(result_raw)
    trimmed = (len(result_raw) if result_raw else 0) - len(result)
    logger.debug(f"chat_completion result_len={len(result)} sanitize_trimmed={trimmed}")

    usage = captured.get("usage")
    trace.event(
        "llm_call",
        provider=provider,
        model=captured.get("model"),
        messages=messages,
        raw=result_raw,
        sanitized=result,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        effective_max_tokens=captured.get("effective_max_tokens"),
        elapsed_ms=captured.get("elapsed_ms", 0),
        attempt=1,
    )
    return result


def get_embedding(text: str) -> list[float]:
    """调用 SiliconFlow bge-m3 生成 embedding，返回 float 列表。不随 LLM_PROVIDER 切换。"""

    def _call():
        api_key = config.SILICONFLOW_API_KEY or os.environ.get("SILICONFLOW_API_KEY", "")
        if not api_key:
            raise RuntimeError("SILICONFLOW_API_KEY 未配置（config.py 或环境变量）")
        payload = json.dumps({"model": config.EMBEDDING_MODEL, "input": text}).encode()
        req = urllib.request.Request(
            f"{config.EMBEDDING_BASE_URL}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["data"][0]["embedding"]

    result = _retry(_call, operation="get_embedding", max_retries=5)
    logger.debug(f"get_embedding dim={len(result)}")
    return result
