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
PIPELINE_VERSION = 6




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

    source_company = "Microsoft"
    filing_year = 2024
    pdf_path = root_path / "data" / "raw_pdfs" / "2024_Microsoft.pdf"
    md_path  = root_path / "data" / "markdown" / "2024_Microsoft.md"

    from confiq.confiq import LLM_MODEL, LLM_MAX_TOKENS
    print(f"MODEL: {LLM_MODEL.model_name}  MAX_TOKENS: {LLM_MAX_TOKENS}")

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

        pending = [c for c in chunks if c.get("conversion_status") == "pending"]

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        if pending:
            partial_file = cache_file.with_suffix(".partial.json")
            partial_file.write_text(json.dumps(chunks), encoding="utf-8")
            print(f"Saved PARTIAL cache: {partial_file.name}")
            raise SystemExit(
                f"Aborted: {len(pending)} tables unconverted. "
                f"Nothing embedded. Resume when quota resets."
            )

        cache_file.write_text(json.dumps(chunks), encoding="utf-8")
        print(f"Saved cache: {cache_file.name}")

    embed_and_store(chunks, name="investor_intelligence")