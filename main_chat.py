import argparse
import sys

from core import trace
from core.dialogue import chat, end_session


def main():
    parser = argparse.ArgumentParser(description="和数字人对话（main_chat）")
    parser.add_argument("agent_id", nargs="?", default="test_agent_001",
                        help="agent 目录名（data/agents/<agent_id>）")
    parser.add_argument("--debug", action="store_true",
                        help="开启 debug 模式：控制台展开子项 + 落盘 logs/sessions/<session_id>.md")
    args = parser.parse_args()

    session_history = []
    session_surfaced = set()

    print(f"开始和数字人对话（agent: {args.agent_id}，输入 quit 结束会话）\n")
    if args.debug:
        print("[debug] 本次会话的完整链路会写入 logs/sessions/<session_id>.md\n")

    while True:
        user_input = input("你：").strip()
        if user_input.lower() == "quit":
            print("\n会话结束，正在保存记忆...")
            end_session(args.agent_id, session_history)
            print("完成。")
            break

        try:
            with trace.turn(args.agent_id, user_input, debug=args.debug):
                result = chat(args.agent_id, user_input, session_history, session_surfaced)
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


if __name__ == "__main__":
    main()
