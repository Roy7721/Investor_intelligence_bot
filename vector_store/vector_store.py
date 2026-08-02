from ingestion.chunking_v3 import chunk_markdown, convert_table_chunks
import  chromadb
from chromadb.utils import embedding_functions
from confiq.confiq import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, OpenRouterEmbeddingFunction, OPENROUTER_API_KEY

_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_embedder = OpenRouterEmbeddingFunction(api_key=OPENROUTER_API_KEY, model=EMBEDDING_MODEL)


def embed_and_store(chunks: list[dict],name: str):
    texts = []
    for chunk in chunks:
        texts.append(chunk["text"])


    collection = _client.get_or_create_collection(
            name= name,
            embedding_function=_embedder
        )
    collection.add(
            documents=texts,
            metadatas=[{
                "content_type": c["content_type"],
                "source_company": c["source_company"],
                "filing_year": c["filing_year"],
            } for c in chunks],             
            ids=[f"chunk_{i}" for i in range(len(chunks))],
    )


import json
from pathlib import Path

CONVERTED_CHUNKS_CACHE = Path("./data/tesla_converted_chunks.json")

if __name__ == "__main__":
    if CONVERTED_CHUNKS_CACHE.exists():
        print("Loading previously converted chunks from cache...")
        chunks = json.loads(CONVERTED_CHUNKS_CACHE.read_text(encoding="utf-8"))
    else:
        chunks = chunk_markdown(
            markdown_file="./data/markdown/2024_Tesla.md",
            source_company="Tesla",
            filing_year=2024,
        )

        print("Converting table chunks to natural language...")
        chunks = convert_table_chunks(chunks)
        print("Done.")

        CONVERTED_CHUNKS_CACHE.write_text(json.dumps(chunks), encoding="utf-8")
        print("Saved converted chunks to cache.")

    # TEMPORARY DEBUG — find empty chunks
    for i, chunk in enumerate(chunks):
        if not chunk["text"].strip():
            print(f"EMPTY CHUNK at index {i} — content_type={chunk['content_type']}")

    try:
        _client.delete_collection(name="investor_intelligence")
    except Exception:
        pass

    embed_and_store(chunks=chunks, name="investor_intelligence")







