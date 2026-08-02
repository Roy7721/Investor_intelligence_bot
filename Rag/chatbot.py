import os
from confiq.confiq import LLM_MODEL
from Rag.retrieval import retrieve_chunks, build_context



SYSTEM_PROMPT = """You are a financial analyst assistant helping investors understand a company's 10-K filing.
Answer questions using only the provided context. If the context includes table data, use it for precise figures.
"""
#If the answer isn't in the context, say so clearly instead of guessing.


def ask(question: str, source_company: str) -> str:
    retrieved = retrieve_chunks(question=question, source_company=source_company)

    if not retrieved:
        return f"No data found for '{source_company}'. Please upload its 10-K first."

    # TEMPORARY DEBUG — remove once diagnosed
    print(f"\n--- Retrieved {len(retrieved)} chunks ---")
    for i, chunk in enumerate(retrieved):
        print(f"[{i}] type={chunk['content_type']} | {chunk['text']}")
    print("--- end retrieved chunks ---\n")

    context = build_context(retrieved)

    user_prompt = f"Context:\n{context}\n\nQuestion: {question}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
    ]
    response = LLM_MODEL.invoke(messages)

    return response.content

if __name__ == "__main__":

    response = ask(
        question= "what was the tesla's Automotive sales in 2024", 
        source_company= "Tesla")

    print(response)