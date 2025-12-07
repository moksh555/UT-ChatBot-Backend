import json
import glob
import langchain_core.documents as Documents

def load_chunks_to_documents(pattern: str="../scraped_data/embeddings_ready/*_chunks.json"):

    docs = []

    for path in glob.glob(pattern):
        print(f'Loading chunks from: {path}')
        with open(path, 'r', encoding='utf-8') as f:
            file_chunks = json.load(f)

        for chunk in file_chunks:
            metadata = chunk.get('metadata', {}).copy()
            metadata['chunk_id'] = chunk.get('chunk_id')

            doc = Documents.Document(
                page_content=chunk.get('text'),
                metadata=metadata
            )
            docs.append(doc)
    print(f'Total documents loaded: {len(docs)}')
    return docs