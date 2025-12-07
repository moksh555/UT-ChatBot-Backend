from datetime import datetime
from typing import Annotated, List, TypedDict
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, MessagesState, START, END, add_messages
from langchain_core.messages import HumanMessage, BaseMessage, SystemMessage
from dotenv import load_dotenv
import os
import ast
from pinecone import Pinecone as pc
from langgraph_dynamodb_checkpoint import DynamoDBSaver

load_dotenv()

os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
CHECKPOINTER_TABLE = os.getenv("CHECKPOINTER_TABLE", "langgraph-checkpoints")

# models used in answering
school_model = ChatGoogleGenerativeAI(
    model="gemini-3-pro-preview",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)
embeddings_model = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
chat_model = ChatGoogleGenerativeAI(
    model="gemini-3-pro-preview",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)

# pinecone setup would go here if needed
pc_client = pc(api_key=os.getenv("PINECONE_API_KEY"))
pincecone_index_name = os.getenv("PINECONE_INDEX_NAME", "ut-multi-campus-v1")
index = pc_client.Index(pincecone_index_name)



# Nodes and State Definitions 
class State(TypedDict, total=False):
    query: str
    campus_list: List[str]
    query_embedding: List[float]
    retrieved_docs: List[dict]
    full_context_documents: str
    messages: Annotated[List[BaseMessage], add_messages]


def checking_query(state: State) -> State:
    try:
        messages = state.get("messages", [])
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        if not last_human_message or not str(last_human_message.content).split():
            print(f'LOG: No query provided : FUNCTION -> saving_query : time -> {datetime.now().isoformat(timespec="seconds")}')
            return SystemError("Please provide a valid query.")
        query = last_human_message.content.strip()
        print(f'LOG: Received query -> "{query}" : FUNCTION -> checking_query : time -> {datetime.now().isoformat(timespec="seconds")}')
        return {"query": query}
    except Exception as e:
        print(f'LOG: Error in checking_query -> {str(e)} : FUNCTION -> checking_query : time -> {datetime.now().isoformat(timespec="seconds")}')
        return SystemError("An error occurred while processing the query.")



def specific_school(state: State) -> State:
    query = state.get("query")
    messages = state.get("messages", [])

    system_prompt = "You are an assistant that identifies which UT campuses a query refers to based on the provided context. The full list of valid campuses is: ['UT_Arlington','UT_Austin','UT_Dallas','UT_El_Paso','UT_Health_Houston','UT_Health_San_Antonio','UT_Health_Science_Center_Tyler','UT_MD_Anderson','UT_Medical_Branch_Galveston','UT_Permian_Basin','UT_Rio_Grande_Valley','UT_San_Antonio','UT_Southwestern','UT_Tyler']. Analyze the human query and return ONLY a Python list of all campuses explicitly or implicitly mentioned. If no specific campus is mentioned, return ['All']."

    full_context = []
    
    for messsage in messages:
        if isinstance(messsage, HumanMessage):
            full_context.append(f"User: {messsage.content}")
        elif isinstance(messsage, SystemMessage):
            full_context.append(f"System: {messsage.content}")
    full_context = "\n".join(full_context)

    lc_messages: List[BaseMessage] = [
        SystemMessage(content=system_prompt),
        SystemMessage(content=f"Context Documents:\n{full_context}"),
        HumanMessage(content=query),
    ]

    ai_msg = school_model.invoke(lc_messages)
    raw_text = ai_msg.content[0]["text"]  
    campuses = ast.literal_eval(raw_text) 

    if not campuses:
        print(f'LOG: No campuses identified from query -> "{query}" : FUNCTION -> specific_school : time -> {datetime.now().isoformat(timespec="seconds")}')
        return SystemError("Please mentioned which UT campus you are interested in.")
    
    print(f'LOG: Returning campuses -> {campuses} from query -> "{query}" : FUNCTION -> specific_school : time -> {datetime.now().isoformat(timespec="seconds")}')
    return {"campus_list": campuses}


def vectorize_query(state: State) -> State:
    query = state.get("query")
    vectorize_query = embeddings_model.embed_query(query)

    if not vectorize_query:
        print(f'LOG: Failed to vectorize query -> "{query}" : FUNCTION -> vectorize_query : time -> {datetime.now().isoformat(timespec="seconds")}')
        return SystemError("Failed to vectorize the query.")
    
    print(f'LOG: Returning vectorized query  ->  from query -> "{query}" : FUNCTION -> vectorize_query : time -> {datetime.now().isoformat(timespec="seconds")}')
    return {"query_embedding" : vectorize_query} 

def retrive_documents(state: State) -> State:
    # This function would implement retrieval logic from Pinecone using the query_embedding
    query_embedding = state.get("query_embedding")
    campuses = state.get("campus_list")
    # just making sure it does not give issue in development if something bad happens
    if not query_embedding: 
        print(f'LOG: No query embedding found : FUNCTION -> retrive_documents : time -> {datetime.now().isoformat(timespec="seconds")}')
        return SystemError("No query embedding found for document retrieval.")

    if not campuses:
        print(f'LOG: No campuses found : FUNCTION -> retrive_documents : time -> {datetime.now().isoformat(timespec="seconds")}')
        return SystemError("No campuses found for document retrieval.")

    try:
        retrieve_docs = []

        if campuses != ['All']:
            for campus in campuses:
                docs_matched = index.query(
                    vector=query_embedding,
                    top_k=5,
                    include_metadata=True,
                    filter={"university": campus}
                )
                for doc in docs_matched.matches:
                    retrieve_docs.append({
                        "id": doc.id,
                        "score": float(doc.score),
                        "metadata": doc.metadata
                    })
        else:
            ALL_CAMPUSES = [
                "UT_Arlington",
                "UT_Austin",
                "UT_Dallas",
                "UT_El_Paso",
                "UT_Health_Houston",
                "UT_Health_San_Antonio",
                "UT_Health_Science_Center_Tyler",
                "UT_MD_Anderson",
                "UT_Medical_Branch_Galveston",
                "UT_Permian_Basin",
                "UT_Rio_Grande_Valley",
                "UT_San_Antonio",
                "UT_Southwestern",
                "UT_Tyler"
            ]

            for campus in ALL_CAMPUSES:
                docs_matched = index.query(
                    vector=query_embedding,
                    top_k=2,
                    include_metadata=True,
                    filter={"university": campus}
                )
                for doc in docs_matched.matches:
                    retrieve_docs.append({
                        "id": doc.id,
                        "score": doc.score,
                        "metadata": doc.metadata
                    })
        return {"retrieved_docs": retrieve_docs}
    except Exception as e:
        print(f'LOG: Error during document retrieval -> {str(e)} : FUNCTION -> retrive_documents : time -> {datetime.now().isoformat(timespec="seconds")}')
        return SystemError("An error occurred during document retrieval.")

    
def prepare_docs(state: State) -> State:
    retrieved_docs = state.get("retrieved_docs")
    context_documents = []
    for docs in retrieved_docs:
        # print(f'LOG: Retrieved doc -> {docs} : FUNCTION -> prepare_docs : time -> {datetime.now().isoformat(timespec="seconds")}')
        metadata = docs.get('metadata', {})
        text = metadata.get('text', '')
        title = metadata.get('title', 'No Title')
        university = metadata.get('university', 'Unknown University')
        context_documents.append(f"Title: {title}\nUniversity: {university}\nContent: {text}\n")
    
    full_context = "\n---\n".join(context_documents)
    return {"full_context_documents": full_context}

def chatbot_node(state: State) -> State:
    full_context = state["full_context_documents"]
    messages = state.get("messages", [])

    system_prompt = "You are an assistant specializing in questions about the University of Texas system campuses. When context is available and relevant, use it as your primary source. If the context does not include the answer, use your broader knowledge to help, but never contradict the context. Keep responses concise and student-friendly."
    lc_messages: List[BaseMessage] = [
        SystemMessage(content=system_prompt),
        SystemMessage(content=f"Context Documents:\n{full_context}"),
    ]
    lc_messages.extend(messages) 
    ai_msg = chat_model.invoke(lc_messages)
    return {"messages": [ai_msg]}



#---------------------------------------------------------------------------------------------------------
# Building the state graph
builder = StateGraph(State)

# Defining nodes
builder.add_node("checking_query", checking_query)
builder.add_node("specific_school", specific_school)
builder.add_node("vectorize_query", vectorize_query)
builder.add_node("retrive_documents", retrive_documents)
builder.add_node("prepare_docs", prepare_docs)
builder.add_node("chatbot", chatbot_node)

# Defining edges
builder.add_edge(
    START,
    "checking_query",
)
builder.add_edge(
    "checking_query",
    "specific_school",
)
builder.add_edge(
    "specific_school",
    "vectorize_query",
)
builder.add_edge(
    "vectorize_query",
    "retrive_documents",
)
builder.add_edge(
    "retrive_documents",
    "prepare_docs",
)
builder.add_edge(
    "prepare_docs",
    "chatbot", 
)
builder.add_edge(   
    "chatbot",
    END,
)

saver = DynamoDBSaver(
    table_name=CHECKPOINTER_TABLE,
    max_read_request_units=5,  # Optional, default is 100
    max_write_request_units=5,  # Optional, default is 100
)

app = builder.compile(checkpointer=saver)


