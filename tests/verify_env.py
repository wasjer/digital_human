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
        dim = len(embedding)
        print(f"Embedding 维度: {dim}")
        if dim == EMBEDDING_DIM:
            print(f"✓ 维度验证通过 (期望 {EMBEDDING_DIM})")
        else:
            print(f"✗ 维度不匹配: 期望 {EMBEDDING_DIM}, 实际 {dim}")
        return True
    except Exception as e:
        print(f"✗ Embedding 失败: {e}")
        return False

def verify_chat():
    print("\n=== 验证 Chat 模型 ===")
    try:
        from openai import OpenAI
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("✗ 环境变量 DEEPSEEK_API_KEY 未设置")
            return False
        client = OpenAI(api_key=api_key, base_url=CHAT_BASE_URL)
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": "你好，回复五个字"}]
        )
        reply = response.choices[0].message.content
        print(f"模型回复: {reply}")
        return True
    except Exception as e:
        print(f"✗ Chat 失败: {e}")
        return False

if __name__ == "__main__":
    ok1 = verify_embedding()
    ok2 = verify_chat()
    if not (ok1 and ok2):
        sys.exit(1)
