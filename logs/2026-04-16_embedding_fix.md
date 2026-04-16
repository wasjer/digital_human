# 修复日志：embedding 从 Ollama 切换至 SiliconFlow

**日期**：2026-04-16  
**分支**：data_source/nuwa  
**涉及文件**：`.env` / `config.py` / `core/llm_client.py` / `tests/verify_env.py`

---

## 问题描述

运行 `main_chat.py` 时，chat_completion 正常，但 `get_embedding` 调用本地 Ollama 持续返回 HTTP 500：

```
llama runner process has terminated: %!w(<nil>)
ggml_metal_init: error: failed to initialize the Metal library
static_assert failed: "Input types must match cooperative tensor types" (bfloat vs half)
```

**根因**：macOS 升级至 26.3.1 (Tahoe) 后，系统 `MetalPerformancePrimitives.framework` 的 API 发生 breaking change，Ollama 0.20.5 的 Metal GPU backend 初始化崩溃，所有模型均受影响。`OLLAMA_NO_METAL=1` 亦无效。

---

## 解决方案

放弃本地 Ollama，改用 **SiliconFlow** 在线 bge-m3 embedding API：
- 模型：`BAAI/bge-m3`，向量维度 1024（与原 Ollama bge-m3 完全一致，已有数据无需重新 embed）
- API 格式：OpenAI 兼容，Bearer 认证

---

## 还原方法

如需回退到 Ollama 本地 embedding，执行：

```bash
git checkout HEAD -- config.py core/llm_client.py tests/verify_env.py
```

同时手动删除 `.env` 中的 `SILICONFLOW_API_KEY` 行，并确保 Ollama 正常运行。

---

## 各文件修改对照

### `.env`
```diff
+ SILICONFLOW_API_KEY=sk-frlgeoeoyfdobkzpmhzvcqnppdiujiualhsspmmczafhhmxa
```

---

### `config.py`
```diff
-EMBEDDING_MODEL = "bge-m3"
-EMBEDDING_BASE_URL = "http://localhost:11434"
+EMBEDDING_MODEL = "BAAI/bge-m3"
+EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
+SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
```

---

### `core/llm_client.py` — `get_embedding()` 函数

**修改前（Ollama 格式）：**
```python
def get_embedding(text: str) -> list[float]:
    """调用本地 Ollama 生成 embedding，返回 float 列表。不随 LLM_PROVIDER 切换。"""

    def _call():
        payload = json.dumps({"model": config.EMBEDDING_MODEL, "prompt": text}).encode()
        req = urllib.request.Request(
            f"{config.EMBEDDING_BASE_URL}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["embedding"]

    result = _retry(_call, operation="get_embedding")
    logger.info(f"get_embedding dim={len(result)}")
    return result
```

**修改后（SiliconFlow 格式）：**
```python
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
```

---

### `tests/verify_env.py`

**修改前：**
```python
import sys
import os
import json
import urllib.request
from config import EMBEDDING_MODEL, EMBEDDING_BASE_URL, EMBEDDING_DIM, CHAT_MODEL, CHAT_BASE_URL

def post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())

def verify_embedding():
    print("=== 验证 Embedding ===")
    try:
        result = post(f"{EMBEDDING_BASE_URL}/api/embeddings", {
            "model": EMBEDDING_MODEL,
            "prompt": "你好世界"
        })
        embedding = result["embedding"]
```

**修改后：**
```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json
import urllib.request
from config import EMBEDDING_MODEL, EMBEDDING_BASE_URL, EMBEDDING_DIM, CHAT_MODEL, CHAT_BASE_URL, SILICONFLOW_API_KEY

def post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())

def verify_embedding():
    print("=== 验证 Embedding ===")
    try:
        api_key = SILICONFLOW_API_KEY or os.environ.get("SILICONFLOW_API_KEY", "")
        result = post(
            f"{EMBEDDING_BASE_URL}/embeddings",
            {"model": EMBEDDING_MODEL, "input": "你好世界"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        embedding = result["data"][0]["embedding"]
```

---

## 验证结果

```
=== 验证 Embedding ===
Embedding 维度: 1024
✓ 维度验证通过 (期望 1024)

=== 验证 Chat 模型 ===
模型回复: 好的，收到指令。
```
