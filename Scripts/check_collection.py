"""
Verify both companies coexist in the ChromaDB collection.

This is the check for the delete_collection bug fixed earlier: ingestion
used to wipe the entire collection each run, so Apple and Tesla were never
actually stored at the same time.

Usage (from project root):
    python .\\Scripts\\check_collection.py
"""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vector_store.vector_store import _client, _embedder

COLLECTION_NAME = "investor_intelligence"


def main() -> None:
    collection = _client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedder,
    )

    print(f"Total chunks in collection: {collection.count()}")
    print()

    for company in ("Tesla", "Apple"):
        result = collection.get(
            where={"source_company": {"$eq": company}},
            include=["metadatas"],
        )
        ids = result["ids"]
        metas = result["metadatas"]

        types = Counter(m["content_type"] for m in metas)
        degraded = sum(
            1 for m in metas
            if m.get("conversion_status") == "raw_fallback"
        )

        print(f"{company}: {len(ids)} chunks "
              f"({types['table']} tables, {types['prose']} prose, "
              f"{degraded} raw_fallback)")

    print()
    print("Expected: Tesla 343, Apple 316.")
    print("If either is 0, the scoped delete did not scope correctly.")


if __name__ == "__main__":
    main()
