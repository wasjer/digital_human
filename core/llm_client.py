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

# ── 日志配置 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s llm_client %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
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


def _get_chat_client() -> tuple[OpenAI, str, dict]:
    """根据 LLM_PROVIDER 返回 (OpenAI client, model_name, extra_body)。
    extra_body 透传到 chat.completions.create；对推理模型用它关掉 thinking，
    让生产调用点的 max_tokens 预算不被推理吃掉。"""
    provider = getattr(config, "LLM_PROVIDER", "deepseek")

    if provider == "deepseek":
        api_key = config.DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置（config.py 或环境变量）")
        return OpenAI(api_key=api_key, base_url=config.DEEPSEEK_BASE_URL), config.DEEPSEEK_MODEL, {}

    if provider == "minimax":
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY 未配置（环境变量）")
        # TODO(minimax): 关推理的官方参数待确认。试过 enable_thinking / reasoning_effort /
        # thinking.type=disabled / no_think / chat_template_kwargs.enable_thinking 等均无效，
        # reasoning_tokens 仍 >0。暂为空，依赖 _sanitize 剥 <think> 并搭配生产侧 max_tokens。
        return OpenAI(api_key=api_key, base_url=config.MINIMAX_BASE_URL), config.MINIMAX_MODEL, {}

    if provider == "kimi":
        api_key = os.environ.get("KIMI_API_KEY", "")
        if not api_key:
            raise RuntimeError("KIMI_API_KEY 未配置（环境变量）")
        return OpenAI(api_key=api_key, base_url=config.KIMI_BASE_URL), config.KIMI_MODEL, {}

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
        )

    raise RuntimeError(f"未知 LLM_PROVIDER: {provider!r}，可选: deepseek | minimax | kimi | glm")


def _retry(fn, operation: str, max_retries: int = 3, base_delay: float = 2.0):
    """最多重试 max_retries 次，指数退避。"""
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            logger.info(f"{operation} success attempt={attempt}")
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

    def _call():
        client, model, extra_body = _get_chat_client()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body or None,
        )
        return resp.choices[0].message.content

    result_raw = _retry(_call, operation="chat_completion")
    result = _sanitize(result_raw)
    trimmed = (len(result_raw) if result_raw else 0) - len(result)
    logger.info(f"chat_completion result_len={len(result)} sanitize_trimmed={trimmed}")
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
    logger.info(f"get_embedding dim={len(result)}")
    return result
