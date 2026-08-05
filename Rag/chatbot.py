from config.config import LLM_MODEL
from Rag.retrieval import retrieve_chunks, build_context
import time


# The last line was commented out while retrieval was being debugged: it made
# "the context doesn't contain that" indistinguishable from a retrieval failure.
# That reason expired once retrieval was fixed. Without it the prompt says to
# use only the context but never says what to do when the context lacks the
# answer — which is exactly the gap where a model invents a plausible figure.
SYSTEM_PROMPT = """You are a financial analyst assistant helping investors understand a company's 10-K filing.
Answer questions using only the provided context. If the context includes table data, use it for precise figures.
If the answer isn't in the context, say so clearly instead of guessing.
Answer in one short sentence. Give the figure and its units, nothing else.
"""


def ask(question: str, source_company: str, debug: bool = False) -> str:
    retrieved = retrieve_chunks(question=question, source_company=source_company)

    if not retrieved:
        return f"No data found for '{source_company}'. Please upload its 10-K first."

    # Was an unconditional "TEMPORARY DEBUG" block. Kept behind a flag rather
    # than deleted: retrieve_chunks() returns `distance` specifically so ranking
    # can be inspected, and this has been needed more than once.
    if debug:
        print(f"\n--- Retrieved {len(retrieved)} chunks ---")
        for i, chunk in enumerate(retrieved):
            print(f"[{i}] {chunk['distance']:.4f} type={chunk['content_type']} | {chunk['text']}")
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

    
    chunks = retrieve_chunks(question="What does Note 10 of Microsoft's 10-K cover?", source_company="Microsoft")
    eval_questions = [
    # "Total revenue in FY2024?",
    # "Net income in FY2024?",
    # "Intelligent Cloud revenue 2024?",
    # "R&D spend 2024?",
    #"Diluted EPS 2024?",
    "Server products and cloud services revenue 2024?",
    "Gross carrying amount of marketing-related intangible assets?",
    "Intangible assets from Activision Blizzard?",
    "Shares repurchased in FY2024? State units.",
    "Total stockholders' equity at 30 June 2024? State units.",
    "What does Note 10 cover?",
    "What does Note 13 cover?",
    "Which note covers unearned revenue?",
    "Summarise the debt note.",
    "What is in the employee stock and savings plans note?",
    "Who is the auditor?",
    "What AI-related risks are listed?",
    "What is said about cloud competition?",
    "Revenue recognition policy for software licences?",
    "Do the three segments sum to total revenue?",
    "Intelligent Cloud growth 2023 to 2024, dollars and percent?",
    "More Personal Computing share of total revenue?",
    "Which segment grew fastest in 2024?",
    "Productivity and Business Processes revenue: 2023 vs 2024?",
    "Did operating expenses rise or fall vs 2023?",
    "What were Apple's net sales in 2024?",
    "Compare Microsoft's revenue with Tesla's.",
    "Revenue forecast for 2026?",
    "How many people work in Azure?",
    "Share price in August 2026?",
    "What was announced at Build 2025?",
    "Why did revenue fall in 2024?",
    "How much was paid to acquire OpenAI?",
    "Gaming Cloud segment revenue?",
]
    for q in eval_questions:

        print(f"\n=== {q}")
        print(ask(question=q, source_company="Microsoft"))
        time.sleep(3)