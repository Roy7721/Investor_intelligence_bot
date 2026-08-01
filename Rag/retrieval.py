from vector_store.vector_store import _client, _embedder
from confiq.confiq import RETRIEVAL_TOP_K

COLLECTION_NAME = "investor_intelligence"

def retrieve_chunks(question: str, source_company: str,top_k:int = RETRIEVAL_TOP_K) -> list[dict] :
    """
    Retrieve the top-k most relevant chunks for a given question.
    Returns a list of dicts with text, content_type, and metadata.
    """

    collection = _client.get_or_create_collection(
        name = COLLECTION_NAME,
        embedding_function=_embedder
    )

    result = collection.query(
        query_texts = [question],
        n_results = top_k,
        where={"source_company": source_company}
    )

    chunks = []

    for text, metadata in zip(result["documents"][0], result["metadatas"][0]):
        chunks.append(
            {
            "text": text,
            "content_type": metadata["content_type"],
            "source_company": metadata["source_company"],
            "filing_year": metadata["filing_year"],
            }
        )

    return chunks

def build_context(retrieved_chunks: list[dict]) -> str:
    context_parts = []

    for chunks in retrieved_chunks:
        if chunks["content_type"] == 'table':
            label = "[TABLE DATA]"
        else:
            label = "[Document Text]"

        context_parts.append(f"{label}\n{chunks['text']}\n")
    return "\n---\n".join(context_parts)

if __name__ == "__main__":

    chunks = retrieve_chunks(
        question= "what was the apple's net income in 2024", 
        source_company= "apple")

    build_context(chunks)

    print("file is working fine")