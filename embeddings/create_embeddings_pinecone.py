import os
from langchain_core.documents import Document
from dotenv import load_dotenv
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone as pc, ServerlessSpec
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
from create_documents import load_chunks_to_documents
import time


load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
os.environ["PINECONE_API_KEY"] = os.getenv("PINECONE_API_KEY")
index_name = os.getenv("PINECONE_INDEX_NAME", "ut-multi-campus-v1")



# Eoor Raise if there are no API KEYS set   
if not os.environ.get("PINECONE_API_KEY"):
    raise RuntimeError("PINECONE_API_KEY is not set in environment")

if not os.environ.get("GOOGLE_API_KEY"):
    raise RuntimeError("GOOGLE_API_KEY is not set in environment")

# embeddings model
gemini_embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
pine_client = pc(api_key=os.environ["PINECONE_API_KEY"])


# sanity check that index exists
if index_name not in pine_client.list_indexes().names():
    raise RuntimeError(
        f"Index '{index_name}' does not exist. "
        "Run create_index.py first to create it."
    )

index = pine_client.Index(index_name)
stats = index.describe_index_stats()
already_vectors = stats.get("total_vector_count", 0)

print("Loading UT chunks into Documents...")
docs = load_chunks_to_documents(
    pattern="../scraped_data/embeddings_ready/*_chunks.json"
)
print(f"Total Documents to embed: {len(docs)}")

start_offset = already_vectors
if start_offset >= len(docs):
    print("All docs appear to be embedded already.")
    raise SystemExit

# sanity check that we have documents
if not docs:
    raise RuntimeError("No documents loaded. Check your chunks path and files.")

vectorstore = PineconeVectorStore(
    index_name=index_name,
    embedding=gemini_embeddings,
)

BATCH_SIZE = 100  # tune this depending on size / rate limits
MAX_DOCS_PER_WINDOW = 500        # 3 batches * 100 docs
WINDOW_SECONDS = 60              # 1 minute
MAX_RETRIES_PER_BATCH = 5     # retry on 429 a few times

window_start = time.time()
docs_in_window = 0

for i in range(start_offset, len(docs), BATCH_SIZE):
    # Throttle: if we've hit the per-minute doc limit, wait for the window to reset
    if docs_in_window >= MAX_DOCS_PER_WINDOW:
        elapsed = time.time() - window_start
        if elapsed < WINDOW_SECONDS:
            sleep_for = WINDOW_SECONDS - elapsed
            print(f"\nReached {MAX_DOCS_PER_WINDOW} docs in this minute. "
                  f"Sleeping {sleep_for:.1f}s to reset window...")
            time.sleep(sleep_for)
        # reset window
        window_start = time.time()
        docs_in_window = 0

    batch = docs[i:i + BATCH_SIZE]
    print(f"\nUpserting batch {i}–{i + len(batch) - 1} (size={len(batch)})...")

    # Basic retry loop for 429s
    for attempt in range(1, MAX_RETRIES_PER_BATCH + 1):
        try:
            vectorstore.add_documents(batch)
            print(f" Batch {i}–{i + len(batch) - 1} succeeded (attempt {attempt})")
            docs_in_window += len(batch)
            break
        except GoogleGenerativeAIError as e:
            msg = str(e)
            if "429" in msg:
                backoff = 30 * attempt  # 30s, 60s, 90s
                print(f"  429 on batch starting at {i}, attempt {attempt}/{MAX_RETRIES_PER_BATCH}")
                print(f"  Message: {msg}")
                print(f"  Sleeping {backoff}s before retry...")
                time.sleep(backoff)
                continue
            else:
                print(f" Non-429 error on batch starting at {i}: {msg}")
                raise

    else:
        # All retries exhausted
        print(f"\nGiving up on batch starting at {i} after {MAX_RETRIES_PER_BATCH} attempts.")
        print("   Likely you hit a daily/project-level quota. "
              "Let quota reset or increase limits, then rerun this script; "
              "it will resume from the current vector_count.")
        break

print("Finished adding all UT documents to Pinecone")
print(f"Index name: {index_name}")