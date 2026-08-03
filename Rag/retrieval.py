from vector_store.vector_store import _client, _embedder
from confiq.confiq import RETRIEVAL_TOP_K

COLLECTION_NAME = "investor_intelligence"


def retrieve_chunks(
    question: str,
    source_company: str,
    filing_year: int | None = None,
    top_k: int = RETRIEVAL_TOP_K,
    table_top_k: int = 3,
) -> list[dict]:
    """
    Retrieve the top-k most relevant chunks generally, PLUS a guaranteed
    top table_top_k table-only results — merged, deduplicated by chunk id.

    The second, table-filtered query exists because bare table content can
    rank poorly against a natural-language question even after table-to-text
    conversion. Guaranteeing a few table chunks reach the LLM is cheaper and
    more reliable than trying to make plain similarity search rank them well.

    filing_year is optional so existing single-year callers keep working,
    but it should be passed once a second year of any company is ingested —
    otherwise a question about 2024 can silently mix in 2025 figures.

    Returns chunks in merge order (general results first, then any table
    results not already present), each carrying its distance so ranking
    problems can be diagnosed without a separate debug script.
    """
    collection = _client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedder,
    )

    scope = [{"source_company": {"$eq": source_company}}]
    if filing_year is not None:
        scope.append({"filing_year": {"$eq": filing_year}})

    general_where = scope[0] if len(scope) == 1 else {"$and": scope}
    table_where = {"$and": scope + [{"content_type": {"$eq": "table"}}]}

    general_result = collection.query(
        query_texts=[question],
        n_results=top_k,
        where=general_where,
    )

    table_result = collection.query(
        query_texts=[question],
        n_results=table_top_k,
        where=table_where,
    )

    seen_ids = set()
    chunks = []

    for result in (general_result, table_result):
        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]

        for id_, text, metadata, distance in zip(ids, documents, metadatas, distances):
            if id_ in seen_ids:
                continue
            seen_ids.add(id_)
            chunks.append({
                "id": id_,
                "text": text,
                "distance": distance,
                "content_type": metadata["content_type"],
                "source_company": metadata["source_company"],
                "filing_year": metadata["filing_year"],
                # Older chunks predate this field — default rather than KeyError.
                "conversion_status": metadata.get("conversion_status", "unknown"),
            })

    return chunks


def build_context(retrieved_chunks: list[dict]) -> str:
    context_parts = []
    for chunk in retrieved_chunks:
        label = "[TABLE DATA]" if chunk["content_type"] == "table" else "[DOCUMENT TEXT]"
        context_parts.append(f"{label}\n{chunk['text']}\n")
    return "\n---\n".join(context_parts)



if __name__ == "__main__":

    chunks = retrieve_chunks(question="What was Microsoft's total Revenue in 2024?", source_company="Microsoft")

    

    tables = sum(1 for c in chunks if c["content_type"] == "table")
    degraded = sum(1 for c in chunks if c["conversion_status"] == "raw_fallback")
    print(f"Retrieved {len(chunks)} chunks ({tables} tables, {degraded} raw_fallback)")
    
    if not chunks:
        raise SystemExit("No chunks retrieved.")

    print("\nRanking:")
    for c in chunks:
            preview = c["text"].replace("\n", " ")[:70]
            print(f"  {c['distance']:.4f}  {c['content_type']:<5}  {preview}")
    
    print("\nContext preview:")
    
    print(build_context(chunks)[:1000])