# 🤖 UT ChatBot — Backend

A Retrieval-Augmented Generation (RAG) chatbot API built specifically for the University of Texas system. Users can ask questions about any of the 14 UT campuses and receive grounded, context-aware answers powered by Google Gemini, LangGraph, and a Pinecone vector database populated with UT-specific documents.

## How It Works

Each user message is processed through a **LangGraph state machine** with six sequential nodes:

1. **`checking_query`** — Validates and extracts the user's message from the conversation state
2. **`specific_school`** — Uses Gemini to identify which UT campus(es) the query refers to (or defaults to `All`)
3. **`vectorize_query`** — Embeds the query using `gemini-embedding-001`
4. **`retrive_documents`** — Queries Pinecone with the embedding, filtered by campus metadata; fetches top-K matching documents
5. **`prepare_docs`** — Formats retrieved chunks into a context string
6. **`chatbot`** — Feeds context + conversation history into Gemini to produce a grounded response

**Conversation memory** is automatically persisted in DynamoDB via `langgraph-dynamodb-checkpoint`, enabling multi-turn threads across sessions.

## Key Features

- **14-campus coverage** — UT Arlington, Austin, Dallas, El Paso, MD Anderson, and more
- **RAG pipeline** — All responses are grounded in Pinecone-indexed UT documents; Gemini only supplements when context is insufficient
- **Persistent multi-turn memory** — LangGraph checkpoints stored in DynamoDB; threads survive server restarts
- **Embeddings ingestion scripts** — `embeddings/` directory contains scripts to scrape, chunk, and push documents to Pinecone
- **Full auth system** — Email/password registration + login with httpOnly JWT cookies and Google OAuth
- **Per-user chat history** — Each user has a personal thread history list (max 20 threads) in DynamoDB
- **Thread ownership enforcement** — Users can only access their own chat threads
- **Dockerized** with a GitHub Actions deployment pipeline

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.x |
| Framework | FastAPI + Uvicorn |
| LLM & Embeddings | Google Gemini via `langchain-google-genai` |
| Workflow Orchestration | LangGraph |
| Vector Database | Pinecone (`pinecone-client`) |
| Conversation Memory | `langgraph-dynamodb-checkpoint` |
| Database | AWS DynamoDB (boto3) |
| Auth | JWT (`python-jose`) + Google OAuth (Authlib) |
| Web Scraping | BeautifulSoup4 + requests |
| Container | Docker |
| CI/CD | GitHub Actions |

## Project Structure

```
├── App/                      # FastAPI application
│   ├── app.py                # All API endpoints (chat, auth, history)
│   ├── api/routes/           # Google OAuth route
│   ├── core/config.py        # Settings from environment
│   ├── models/               # Pydantic request/response models
│   ├── services/auth_service.py  # Registration, login, JWT logic
│   └── utils/                # Validators and serializers
├── ChatBot/
│   └── LangGraph_workflow.py # 6-node RAG state machine (compiled LangGraph app)
├── embeddings/               # Scripts for document ingestion into Pinecone
│   ├── create_documents.py
│   ├── create_embeddings_pinecone.py
│   └── create_index.py
├── Scraper/scraper.py        # Web scraper for UT website content
├── DynamoDB_Table/           # DynamoDB table provisioning scripts
└── Tests/                    # Integration and unit tests
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Register a new user |
| `POST` | `/auth/login` | Login and receive session cookie |
| `POST` | `/auth/logout` | Clear session cookie |
| `GET` | `/auth/me` | Get current user info |
| `POST` | `/chats/{thread_id}` | Send a message to a conversation thread |
| `GET` | `/chats/specific/{thread_id}` | Get full message history for a thread |
| `GET` | `/chats/personal-history` | List all threads for the current user |
| `DELETE` | `/chats/delete/{thread_id}` | Delete a thread from personal history |
| `GET` | `/health` | DynamoDB health check |

## Setup & Installation

**Prerequisites**: Python 3.10+, AWS account (DynamoDB), Pinecone account, Google Cloud project (Gemini API + OAuth).

1. **Clone the repository**
   ```bash
   git clone https://github.com/moksh555/UT-ChatBot-Backend.git
   cd UT-ChatBot-Backend
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment** — create a `.env` file:
   ```env
   GOOGLE_API_KEY=your_gemini_api_key
   PINECONE_API_KEY=your_pinecone_key
   PINECONE_INDEX_NAME=ut-multi-campus-v1
   AWS_REGION=us-east-1
   CHECKPOINTER_TABLE=langgraph-checkpoints
   USER_PERSONAL_HISTORY=user-personal-history
   SECRET_KEY=your_jwt_secret
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```

4. **Ingest documents into Pinecone** (one-time setup)
   ```bash
   python embeddings/create_index.py
   python embeddings/create_embeddings_pinecone.py
   ```

5. **Run the server**
   ```bash
   uvicorn App.app:app --reload --host 0.0.0.0 --port 8000
   ```

## Usage

Create a conversation thread and start chatting:

```bash
# Start or continue a conversation
curl -X POST http://localhost:8000/chats/my-thread-001 \
  -H "Content-Type: application/json" \
  -b "access_token=<your_cookie>" \
  -d '{"user_message": "What graduate programs does UT Dallas offer?"}'

# Returns: thread_id, user_message, model_response
```
