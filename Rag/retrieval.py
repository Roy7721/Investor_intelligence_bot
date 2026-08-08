from vector_store.client import _client, _embedder
from config.config import COLLECTION_NAME, RETRIEVAL_TOP_K


def retrieve_chunks(
    question: str,
    source_company: str,
    filing_year: int | None = None,
    top_k: int = RETRIEVAL_TOP_K,
    table_top_k: int = 5,
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
            })

    return chunks


def build_context(retrieved_chunks: list[dict]) -> str:
    context_parts = []
    for chunk in retrieved_chunks:
        label = "[TABLE DATA]" if chunk["content_type"] == "table" else "[DOCUMENT TEXT]"
        context_parts.append(f"{label}\n{chunk['text']}\n")
    return "\n---\n".join(context_parts)



# if __name__ == "__main__":

#     chunks = retrieve_chunks(question="What does Note 10 of Microsoft's 10-K cover?", source_company="Microsoft")
#     eval_questions = [
#     "Total revenue in FY2024?",
#     "Net income in FY2024?",
#     "Intelligent Cloud revenue 2024?",
#     "R&D spend 2024?",
#     "Diluted EPS 2024?",
#     "Server products and cloud services revenue 2024?",
#     "Gross carrying amount of marketing-related intangible assets?",
#     "Intangible assets from Activision Blizzard?",
#     "Shares repurchased in FY2024? State units.",
#     "Total stockholders' equity at 30 June 2024? State units.",
#     "What does Note 10 cover?",
#     "What does Note 13 cover?",
#     "Which note covers unearned revenue?",
#     "Summarise the debt note.",
#     "What is in the employee stock and savings plans note?",
#     "Who is the auditor?",
#     "What AI-related risks are listed?",
#     "What is said about cloud competition?",
#     "Revenue recognition policy for software licences?",
#     "Do the three segments sum to total revenue?",
#     "Intelligent Cloud growth 2023 to 2024, dollars and percent?",
#     "More Personal Computing share of total revenue?",
#     "Which segment grew fastest in 2024?",
#     "Productivity and Business Processes revenue: 2023 vs 2024?",
#     "Did operating expenses rise or fall vs 2023?",
#     "What were Apple's net sales in 2024?",
#     "Compare Microsoft's revenue with Tesla's.",
#     "Revenue forecast for 2026?",
#     "How many people work in Azure?",
#     "Share price in August 2026?",
#     "What was announced at Build 2025?",
#     "Why did revenue fall in 2024?",
#     "How much was paid to acquire OpenAI?",
#     "Gaming Cloud segment revenue?",
# ]
#     for i in eval_questions:
#         chunks = retrieve_chunks(question=str(i), source_company="Microsoft")
#         print(build_context(chunks))


    # tables = sum(1 for c in chunks if c["content_type"] == "table")
    # degraded = sum(1 for c in chunks if c["conversion_status"] == "raw_fallback")
    # print(f"Retrieved {len(chunks)} chunks ({tables} tables, {degraded} raw_fallback)")
    
    # if not chunks:
    #     raise SystemExit("No chunks retrieved.")

    # print("\nRanking:")
    # for c in chunks:
    #         preview = c["text"].replace("\n", " ")[:70]
    #         print(f"  {c['distance']:.4f}  {c['content_type']:<5}  {preview}")
    
    # print("\nContext preview:")
    
   # print(build_context(chunks)[:1000])