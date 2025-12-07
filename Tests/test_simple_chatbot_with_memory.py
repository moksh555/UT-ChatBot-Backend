from typing import TypedDict, Annotated, List
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
import os

# --- setup ---

load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")

chat_model = ChatGoogleGenerativeAI(
    model="gemini-3-pro-preview",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)

# --- STATE ---

class State(TypedDict):
    # messages history, LangGraph will append automatically
    messages: Annotated[List[BaseMessage], add_messages]

# --- NODE ---

def chatbot_node(state: State) -> State:
    messages = state["messages"]
    ai_msg = chat_model.invoke(messages)
    return {"messages": [ai_msg]}

# --- GRAPH ---

builder = StateGraph(State)
builder.add_node("chatbot", chatbot_node)
builder.add_edge(START, "chatbot")
builder.add_edge("chatbot", END)

checkpointer = MemorySaver()
app = builder.compile(checkpointer=checkpointer)

# --- LIVE CHAT LOOP ---

if __name__ == "__main__":
    # one thread_id = one conversation with memory
    thread_config = {"configurable": {"thread_id": "cli-user-1"}}

    state = None

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Bot: Bye 👋")
            break

        # send only the new user message; memory is handled by checkpointer + thread_id
        state = app.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=thread_config,
        )

        bot_reply = state["messages"][-1].content[0]['text']
        print("Bot:", bot_reply)
