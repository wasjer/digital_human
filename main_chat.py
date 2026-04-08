import sys
from core.dialogue import chat, end_session

agent_id = sys.argv[1] if len(sys.argv) > 1 else "test_agent_001"
session_history = []
session_surfaced = set()

print(f"开始和数字人对话（agent: {agent_id}，输入 quit 结束会话）\n")

while True:
    user_input = input("你：").strip()
    if user_input.lower() == "quit":
        print("\n会话结束，正在保存记忆...")
        end_session(agent_id, session_history)
        print("完成。")
        break

    try:
        result = chat(agent_id, user_input, session_history, session_surfaced)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n出错了：{e}，请继续输入或输入 quit 退出\n")
        continue

    reply = result["reply"]
    session_surfaced = result["session_surfaced"]

    session_history.append({"role": "user", "content": user_input})
    session_history.append({"role": "assistant", "content": reply})

    print(f"\n数字人：{reply}\n")
