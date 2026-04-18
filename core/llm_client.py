import os
import json
import time
import logging
import urllib.request
import urllib.error

from openai import OpenAI

import config

# ── 日志配置 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s llm_client %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("llm_client")

# ── Provider 路由 ────────────────────────────────────────────────────────────

_PROVIDER_ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "minimax":  "MINIMAX_API_KEY",
    "kimi":     "KIMI_API_KEY",
    "glm":      "GLM_API_KEY",
}


def _get_chat_client() -> tuple[OpenAI, str]:
    """根据 LLM_PROVIDER 返回 (OpenAI client, model_name)。"""
    provider = getattr(config, "LLM_PROVIDER", "deepseek")

    if provider == "deepseek":
        api_key = config.DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置（config.py 或环境变量）")
        return OpenAI(api_key=api_key, base_url=config.DEEPSEEK_BASE_URL), config.DEEPSEEK_MODEL

    if provider == "minimax":
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        return OpenAI(api_key=api_key, base_url=config.MINIMAX_BASE_URL), config.MINIMAX_MODEL

    if provider == "kimi":
        api_key = os.environ.get("KIMI_API_KEY", "")
        return OpenAI(api_key=api_key, base_url=config.KIMI_BASE_URL), config.KIMI_MODEL

    if provider == "glm":
        api_key = os.environ.get("GLM_API_KEY", "")
        return OpenAI(api_key=api_key, base_url=config.GLM_BASE_URL), config.GLM_MODEL

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
        client, model = _get_chat_client()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content

    result = _retry(_call, operation="chat_completion")
    logger.info(f"chat_completion result_len={len(result)}")
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

    result = _retry(_call, operation="get_embedding")
    logger.info(f"get_embedding dim={len(result)}")
    return result
