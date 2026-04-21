import argparse
import json
import signal
import sys
from pathlib import Path

from core import trace
from core.dialogue import chat, end_session

_AGENTS_DIR = Path(__file__).parent / "data" / "agents"


def _recover_stale_buffer_if_any(agent_id: str) -> None:
    """启动时若 l0_buffer 有残留，自动 end_session 把它清进 L1。"""
    buf_path = _AGENTS_DIR / agent_id / "l0_buffer.json"
    if not buf_path.exists():
        return
    try:
        buf = json.loads(buf_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not buf.get("session_id") or not buf.get("raw_dialogue"):
        return

    stale_history = list(buf.get("raw_dialogue", []))
    print(f"[recover] 检测到上次会话残留（{len(stale_history)} 条），正在写入 L1...")
    try:
        end_session(agent_id, stale_history)
        print("[recover] 残留会话已写入 L1。")
    except Exception as e:
        print(f"[recover] 恢复失败（非致命）：{e}")


def main():
    parser = argparse.ArgumentParser(description="和数字人对话（main_chat）")
    parser.add_argument("agent_id", nargs="?", default="test_agent_001",
                        help="agent 目录名（data/agents/<agent_id>）")
    parser.add_argument("--debug", action="store_true",
                        help="开启 debug 模式：控制台展开子项 + 落盘 logs/sessions/<session_id>.md")
    args = parser.parse_args()

    _recover_stale_buffer_if_any(args.agent_id)

    session_history = []

    def _on_sigint(signum, frame):
        print("\n[SIGINT] 收到中断，正在保存记忆...")
        try:
            end_session(args.agent_id, session_history)
            print("[SIGINT] 完成。")
        except Exception as e:
            print(f"[SIGINT] end_session 失败：{e}")
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_sigint)

    print(f"开始和数字人对话（agent: {args.agent_id}，输入 quit 结束会话）\n")
    if args.debug:
        print("[debug] 本次会话的完整链路会写入 logs/sessions/<session_id>.md\n")

    while True:
        user_input = input("你：").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("\n会话结束，正在保存记忆...")
            end_session(args.agent_id, session_history)
            print("完成。")
            break

        try:
            with trace.turn(args.agent_id, user_input, debug=args.debug):
                result = chat(args.agent_id, user_input, session_history)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n出错了：{e}，请继续输入或输入 quit 退出\n")
            continue

        reply = result["reply"]

        session_history.append({"role": "user", "content": user_input})
        session_history.append({"role": "assistant", "content": reply})

        print(f"\n数字人：{reply}\n")


if __name__ == "__main__":
    main()
