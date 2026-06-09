"""
终端交互式聊天测试

用法:
  python chat.py            # 使用默认租户 demo_001
  python chat.py --tenant demo_002   # 指定租户

输入消息后回车发送，输入 quit 退出
"""
import sys
import os
import asyncio
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_core.messages import HumanMessage
from backend.agent.graph import get_agent


async def chat_loop(tenant_id: str = "demo_001"):
    print("\n" + "=" * 50)
    print(f"  聚宝赞AI客服 - 交互测试")
    print(f"  租户: {tenant_id}")
    print(f"  输入消息后回车，quit 退出")
    print("=" * 50 + "\n")

    agent = await get_agent()
    thread_id = str(uuid.uuid4())[:8]
    print(f"  会话ID: {thread_id}")

    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("退出")
            break

        input_state = {
            "messages": [HumanMessage(content=user_input)],
            "tenant_id": tenant_id,
            "tenant_name": f"测试租户_{tenant_id}",
        }

        try:
            result = await agent.ainvoke(input_state, config=config)
            intent = result.get("intent", "unknown")
            intent_sub = result.get("intent_sub_type", "")
            answer = result.get("final_answer", "")

            intent_label = f"{intent}/{intent_sub}" if intent_sub else intent
            print(f"意图: [{intent_label}]")
            print(f"客服: {answer}")

        except Exception as e:
            print(f"错误: {e}")


if __name__ == "__main__":
    tenant = "demo_001"
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--tenant" and i + 1 < len(args):
            tenant = args[i + 1]
    asyncio.run(chat_loop(tenant))