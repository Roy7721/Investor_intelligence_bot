import json
import hashlib
from pathlib import Path

from ingestion.chunking_v4 import chunk_markdown, convert_table_chunks
import chromadb
from confiq.confiq import (
    CHROMA_PERSIST_DIR, EMBEDDING_MODEL,
    OpenRouterEmbeddingFunction, OPENROUTER_API_KEY,
)

_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_embedder = OpenRouterEmbeddingFunction(api_key=OPENROUTER_API_KEY, model=EMBEDDING_MODEL)

# Bump this whenever chunking or table_to_text logic changes.
PIPELINE_VERSION = 5




def cache_path_for(root: Path, md_path: Path, company: str, year: int) -> Path:
    md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()[:16]
    return root / "data" / "cache" / f"{company}_{year}_{md_hash}_v{PIPELINE_VERSION}.json"


def embed_and_store(chunks: list[dict], name: str):
    """Replace this filing's data in the collection. Idempotent."""
    if not chunks:
        raise ValueError("embed_and_store received no chunks")

    company = chunks[0]["source_company"]
    year = chunks[0]["filing_year"]

    collection = _client.get_or_create_collection(
        name=name,
        embedding_function=_embedder,
    )

    scope = {"$and": [
        {"source_company": {"$eq": company}},
        {"filing_year": {"$eq": year}},
    ]}

    collection.delete(where=scope)

    collection.add(
        documents=[c["text"] for c in chunks],
        metadatas=[{
            "content_type": c["content_type"],
            "source_company": c["source_company"],
            "filing_year": c["filing_year"],
            "conversion_status": c["conversion_status"],
        } for c in chunks],
        ids=[f"{c['source_company']}_{c['filing_year']}_chunk_{i}"
             for i, c in enumerate(chunks)],
    )
    print(f"Stored {len(chunks)} chunks for {company} {year}.")


if __name__ == "__main__":
    root_path = Path(__file__).resolve().parents[1]

    source_company = "Tesla"
    filing_year = 2024

    pdf_path = root_path / "data" / "raw_pdfs" / "2024_Tesla.pdf"
    md_path = root_path / "data" / "markdown" / "2024_Tesla.md"

    cache_file = cache_path_for(root_path, md_path, source_company, filing_year)

    if cache_file.exists():
        print(f"IMPORTED FROM CACHE: {cache_file.name}")
        chunks = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        print("No cache hit — running full pipeline.")
        chunks = chunk_markdown(
            markdown_file=str(md_path),
            source_company=source_company,
            filing_year=filing_year,
        )
        print("Converting table chunks to natural language...")
        chunks = convert_table_chunks(chunks)
        print("Done.")

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(chunks), encoding="utf-8")
        print(f"Saved cache: {cache_file.name}")

    # Debug — outside the if/else, runs on both paths
    for i, chunk in enumerate(chunks):
        if not chunk["text"].strip():
            print(f"EMPTY CHUNK at index {i} — content_type={chunk['content_type']}")

    embed_and_store(chunks=chunks, name="investor_intelligence")