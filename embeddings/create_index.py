
from langchain_core.documents import Document
from pinecone import Pinecone as pc, ServerlessSpec
import os
from dotenv import load_dotenv
load_dotenv()

pine_client= pc(
    api_key = os.getenv("PINECONE_API_KEY"),  # API key from app.pinecone.io
    )
index_name = os.getenv("PINECONE_INDEX_NAME", "ut-multi-campus-v1")

# First, check if the index already exists. If it doesn't, create a new one.
if index_name not in pine_client.list_indexes().names():
    # Create a new index.
    # https://docs.pinecone.io/docs/new-api#creating-a-starter-index
    print(f'Creating index: {index_name}')
    pine_client.create_index(name=index_name,
                      # `cosine` distance metric compares different documents
                      # for similarity.
                      # Read more about different distance metrics from
                      # https://docs.pinecone.io/docs/indexes#distance-metrics.
                      metric="cosine",
                      # The Gemini embedding model `gemini-embedding-001` uses
                      # 3072 dimensions.
                      dimension=3072,
                      # The `pod_type` is the type of pod to use.
                      # Read more about different pod types from
                      # https://docs.pinecone.io/docs/pod-types.
                      # Specify the pod details.
                      spec=ServerlessSpec(
                        cloud="aws",
                        region="us-east-1"
                        ),
    )
