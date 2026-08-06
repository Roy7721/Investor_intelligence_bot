import json
import hashlib
from pathlib import Path

from ingestion.chunking_v5 import chunk_markdown
import chromadb
from config.config import (
    CHROMA_PERSIST_DIR, COLLECTION_NAME, EMBEDDING_MODEL,
     OpenRouterEmbeddingFunction, OPENROUTER_API_KEY,ROOT)

PIPELINE_VERSION = 7


_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_embedder = OpenRouterEmbeddingFunction(api_key=OPENROUTER_API_KEY, model=EMBEDDING_MODEL)



def cache_path_for(root: Path, md_path: Path, company: str, year: int) -> Path:
    md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()[:16]
    return root / "data" / "cache" / f"{company}_{year}_{md_hash}_v{PIPELINE_VERSION}.json"


def embed_and_store(chunks: list[dict], name: str = COLLECTION_NAME):
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
        } for c in chunks],
        ids=[f"{c['source_company']}_{c['filing_year']}_chunk_{i}"
             for i, c in enumerate(chunks)],
    )
    print(f"Stored {len(chunks)} chunks for {company} {year}.")



if __name__ == "__main__":
    import re
    import sys

    MD_DIR = ROOT / "data" / "markdown_datalab"

    def ingest(md_path: Path) -> None:
        # Company and year are DERIVED, never typed separately. They used to be
        # two independent literals and they drifted: md_path pointed at Apple
        # while source_company still said "Microsoft". Apple's filing went in
        # under Microsoft's label, and because embed_and_store deletes by
        # (company, year) first, the real Microsoft chunks were wiped.
        year, company = md_path.stem.split("_", 1)
        print(f"\n=== {company} {year}  <-  {md_path.name}")
        chunks = chunk_markdown(
            markdown_file=str(md_path),
            source_company=company,
            filing_year=int(year),
        )
        embed_and_store(chunks=chunks)

    # Only "{year}_{Company}.md" — excludes page-range test files like
    # 2024_Microsoft_p37-43.md, which would otherwise be ingested as a company
    # called "Microsoft_p37-43".
    targets = sorted(
        p for p in MD_DIR.glob("*.md")
        if re.fullmatch(r"\d{4}_[A-Za-z]+", p.stem)
    )
    if not targets:
        raise SystemExit(f"No filings found in {MD_DIR}")
    for p in targets:
        ingest(p)

# if __name__ == "__main__":
    # source_company = "Microsoft"
    # filing_year = 2024

    # md_path  = ROOT / "data" / "markdown_datalab" / "2024_Apple.md"

    # chunks = chunk_markdown(
    #             markdown_file=str(md_path),
    #             source_company=source_company,
    #             filing_year=filing_year,
    #         )

    # embed_and_store(chunks=chunks)




