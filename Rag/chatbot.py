from config.config import LLM_MODEL
from Rag.retrieval import retrieve_chunks, build_context
import time


# The last line was commented out while retrieval was being debugged: it made
# "the context doesn't contain that" indistinguishable from a retrieval failure.
# That reason expired once retrieval was fixed. Without it the prompt says to
# use only the context but never says what to do when the context lacks the
# answer — which is exactly the gap where a model invents a plausible figure.
SYSTEM_PROMPT = """You are a financial analyst assistant helping investors understand a company's annual filing.
Answer using only the provided context. If the context includes table data, use it for precise figures.
If the answer isn't in the context, say so clearly instead of guessing.
If the question names a company, segment, note, or metric that does not appear in the context, say that it does not appear. Do not answer with a similarly named item instead.
If the question assumes something the context contradicts or does not support, say so rather than accepting the assumption.
Answer in one short sentence. Give the figure and its units, nothing else. If you show a calculation, your verdict must follow from it. Do not state a conclusion your own figures contradict.
"""


def ask(question: str, source_company: str,
        filing_year: int | None = None, debug: bool = False) -> str:
    retrieved = retrieve_chunks(
        question=question, source_company=source_company, filing_year=filing_year
    )

    if not retrieved:
        return f"No data found for '{source_company}'. Please ingest its filing first."

    if debug:
        print(f"\n--- Retrieved {len(retrieved)} chunks ---")
        for i, chunk in enumerate(retrieved):
            print(f"[{i}] {chunk['distance']:.4f} type={chunk['content_type']} | {chunk['text']}")
        print("--- end retrieved chunks ---\n")

    context = build_context(retrieved)

    # Retrieval is scoped by a metadata filter, but nothing in the chunk TEXT
    # says whose filing it is — v4 removed the synthetic "{company} {year}"
    # header because it added no ranking signal. Correct for retrieval, but it
    # left the generator blind: asked about Apple, it answered with Microsoft's
    # revenue and had no way to notice. The scope has to be stated here.
    scope = f"{source_company}'s {filing_year}" if filing_year else f"{source_company}'s"
    user_prompt = (
        f"The context below is from {scope} annual filing, and contains data for "
        f"no other company.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    #return LLM_MODEL.invoke(messages).content

    response = LLM_MODEL.invoke(messages)

    # answer = (response.content or "").strip()

    # if not answer:
    #     meta = getattr(response, "response_metadata", {})
    #     return f"[empty response — finish_reason={meta.get('finish_reason')}]"

    

    # approx_tokens = len(SYSTEM_PROMPT + user_prompt) // 4
    # if debug or approx_tokens > 4000:
    #     print(f"[~{approx_tokens} prompt tokens, {len(retrieved)} chunks]")

    return response.text

if __name__ == "__main__":

    
        # response = ask(question="Do the three segments(Productivity and Business Processes,Intelligent Cloud,More Personal Computing) sum to total revenue?", source_company="Apple",filing_year=2024,debug= False)
        # print(response)
#     #eval_questions = [
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
#     "Do the three segments(Productivity and Business Processes,Intelligent Cloud,More Personal Computing) sum to total revenue?",
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

    apple_eval = [
    # --- paired: bare then hinted ---
    "Do the segments sum to total net sales?",
    "Do Americas, Europe, Greater China, Japan and Rest of Asia Pacific sum to total net sales in fiscal 2024?",
    "What were the product category sales?",
    "What were net sales for iPhone, Mac, iPad, Wearables Home and Accessories, and Services in fiscal 2024?",
    "What is in the financial instruments note?",
    "In Note 4, Financial Instruments, what were cash, cash equivalents and marketable securities by investment category as of September 28, 2024?",

    # --- income statement, specific line labels ---
    "What were total net sales for fiscal 2024?",
    "What were Products net sales and Services net sales in fiscal 2024?",
    "What was gross margin in fiscal 2024?",
    "What was research and development expense in fiscal 2024?",
    "What was selling, general and administrative expense in fiscal 2024?",
    "What was operating income in fiscal 2024?",
    "What was net income in fiscal 2024?",
    "What was diluted earnings per share in fiscal 2024?",

    # --- geographic segment table (Note 13) ---
    "What were Greater China net sales in fiscal 2024?",
    "Which reportable segment had the highest net sales in fiscal 2024?",
    "What is Apple's smallest reportable segment by net sales?",

    # --- table found by section name (the v7 before/after test) ---
    "According to Note 13, Segment Information and Geographic Data, what were Europe net sales?",
    "According to Note 10, Shareholders' Equity, how much common stock was repurchased in fiscal 2024?",

    # --- shareholders' equity statement ---
    "What was total shareholders' equity at September 28, 2024?",
    "How much was declared in dividends and dividend equivalents per share in fiscal 2024?",

    # --- prose (Apple's 10-K does have these sections) ---
    "Who is Apple's independent registered public accounting firm?",
    "What one-time income tax charge did Apple record from the European Commission State Aid decision?",
    "What does Item 1A, Risk Factors, say about supplier concentration?",
    "On what date did Apple's 2024 fiscal year end?",

    # --- entity-name traps (the Gaming Cloud failure class) ---
    "What was iPhone segment revenue in fiscal 2024?",

    "What were Intelligent Cloud net sales?",
    "What was the Apple Vision Pro segment's revenue?",
    "What were Microsoft's total revenues in 2024?",

    # --- must refuse ---
    "What is Apple's revenue guidance for fiscal 2026?",
    "How many employees work on Apple Silicon?",

    # --- false premise ---
    "Why did Apple's net income rise in fiscal 2024?",
]

    recheck_apple = [
    "Which reportable segment had the highest net sales in 2024?",
    "What was iPhone segment revenue in 2024?",
    "Do Apple's reportable segments sum to total net sales in 2024? Show the calculation.",
    "What is in the financial instruments note?",
    "What are Apple's cash and marketable securities by investment category?",
    "Who is Apple's independent registered public accounting firm?"
]

    questions = [
    "What were total revenues in 2024?",
    "What were automotive revenues in 2024?",
    "What was energy generation and storage revenue in 2024?",
    "What was services and other revenue in 2024?",
    "What was gross profit in 2024?",
    "What was research and development expense in 2024?",
    "What was diluted EPS in 2024?",
    "How much revenue came from automotive regulatory credits in 2024?",
    
    "What is in the note on digital assets?",
    "Which note covers commitments and contingencies?",
    "Who is Tesla's independent registered public accounting firm?",
    "On what date did Tesla's 2024 fiscal year end?",
    
    "Do automotive, energy generation and storage, and services and other sum to total revenues in 2024? Show the calculation.",
    "Did net income rise or fall from 2023 to 2024?",
    "What was total revenue growth from 2023 to 2024, in dollars and percent?",
    
    "What were vehicle production and delivery volumes by model in 2024?",
    "What were revenues by geography in 2024?",
    
    "What was Cybertruck segment revenue in 2024?",
    "Which of Tesla's three reportable segments was largest?",
    "Why did Tesla's revenue decline in 2024?",
    "What were Apple's net sales in 2024?",
    "How many Roadsters were delivered in 2024?",
    "What is Tesla's revenue forecast for 2026?"
]
    for q in questions:

        print(f"\n=== {q}")
        print(ask(question=q, source_company="Tesla",filing_year=2024))
        time.sleep(3)

    #print(ask(question="Who is Apple's independent registered public accounting firm?", source_company="Apple",filing_year=2024, debug=False))