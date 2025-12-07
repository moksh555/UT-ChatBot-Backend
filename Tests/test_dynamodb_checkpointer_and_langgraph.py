# Tests/manual_chat_with_langgraph.py

import os
import sys
from langchain_core.messages import HumanMessage

# --- Make sure we can import ChatBot.LangGraph_workflow ---
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from ChatBot.LangGraph_workflow import app  # your compiled graph


def chat_with_thread(thread_id: str):
    """
    Simple REPL-style chat with your LangGraph workflow,
    using the given thread_id for memory.
    """
    print(f"\n🧠 Using thread_id = {thread_id}")
    print("Type 'exit' or 'quit' to stop.\n")

    config = {"configurable": {"thread_id": thread_id}}

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Bye! 👋")
            break

        if not user_input:
            continue

        # Call your LangGraph app
        state = app.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )

        # Get the latest assistant message
        messages = state["messages"]
        last_msg = messages[-1]
        print(f"Bot: {last_msg.content}\n")


if __name__ == "__main__":
    print("=== LangGraph Chatbot Manual Test ===")
    default_thread = "test-student-1"
    thread_id = input(f"Enter thread_id (default: {default_thread}): ").strip()
    if not thread_id:
        thread_id = default_thread

    chat_with_thread(thread_id)
