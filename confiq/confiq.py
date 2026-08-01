from pathlib import Path


EMBEDDING_MODEL = "all-MiniLM-L6-v2"


root_path = Path(__file__).resolve().parents[1]

CHROMA_PERSIST_DIR = root_path / "CHROMA_PERSIST_DIR" / "chroma_store"

RETRIEVAL_TOP_K = 5