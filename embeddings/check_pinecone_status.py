
from dotenv import load_dotenv
import os
from pinecone import Pinecone as pc

load_dotenv()
pc_client = pc(api_key=os.getenv("PINECONE_API_KEY"))
indexes = pc_client.list_indexes()
print(indexes)

for index in indexes.names():
    print(f'Index found: {index}')
    # print(index.describe_index_stats())

