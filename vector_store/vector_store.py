from ingestion.chunking import chunk_markdown
import  chromadb
from chromadb.utils import embedding_functions
from confiq.confiq import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, RETRIEVAL_TOP_K

_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_embedder = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)

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


if __name__ == "__main__":
        chunks = chunk_markdown(
            markdown_file="./apple_full.md",
            source_company="Apple",
            filing_year=2024,
        )

        embed_and_store(chunks=chunks, name="investor_intelligence")








