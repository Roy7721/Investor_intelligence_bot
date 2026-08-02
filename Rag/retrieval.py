from vector_store.vector_store import _client, _embedder
from confiq.confiq import RETRIEVAL_TOP_K

COLLECTION_NAME = "investor_intelligence"

def retrieve_chunks(question: str, source_company: str, top_k: int = RETRIEVAL_TOP_K, table_top_k: int = 3) -> list[dict]:
    """
    Retrieves the top-k most relevant chunks generally, PLUS a guaranteed
    top table_top_k table-only results — merged, deduplicated by chunk id.
    This ensures table content always gets a chance to reach the LLM, even
    if prose captions currently rank higher in plain similarity search.
    """
    collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedder
    )

    general_result = collection.query(
        query_texts=[question],
        n_results=top_k,
        where={"source_company": source_company}
    )

    table_result = collection.query(
        query_texts=[question],
        n_results=table_top_k,
        where={"$and": [{"source_company": source_company}, {"content_type": "table"}]}
    )

    seen_ids = set()
    chunks = []

    for result in (general_result, table_result):
        for id_, text, metadata in zip(result["ids"][0], result["documents"][0], result["metadatas"][0]):
            if id_ in seen_ids:
                continue
            seen_ids.add(id_)
            chunks.append({
                "text": text,
                "content_type": metadata["content_type"],
                "source_company": metadata["source_company"],
                "filing_year": metadata["filing_year"],
            })

    return chunks


def build_context(retrieved_chunks: list[dict]) -> str:
    context_parts = []
    for chunk in retrieved_chunks:
        label = "[TABLE DATA]" if chunk["content_type"] == "table" else "[Document Text]"
        context_parts.append(f"{label}\n{chunk['text']}\n")
    return "\n---\n".join(context_parts)

if __name__ == "__main__":

    chunks = retrieve_chunks(
        question= "what was the apple's net income in 2024", 
        source_company= "Apple")

    build_context(chunks)

    print("file is working fine")