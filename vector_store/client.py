import chromadb

from config.config import (
    CHROMA_PERSIST_DIR, EMBEDDING_MODEL, OPENROUTER_API_KEY,
    OpenRouterEmbeddingFunction,
)

_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_embedder = OpenRouterEmbeddingFunction(api_key=OPENROUTER_API_KEY, model=EMBEDDING_MODEL)