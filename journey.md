# AI-Powered Investor Intelligence Platform — Project Journey

**Status as of this document:** Ingestion pipeline (PDF → markdown → chunking → embedding → storage) is built and being actively debugged/upgraded. Retrieval and chatbot layers are built. Metric extraction dashboard and deployment are not yet started.

**Author's background:** Fresher building a portfolio. This is the second of three planned portfolio projects (after a YouTube sentiment analysis + MLOps project, before a hybrid recommender system). Prefers slow, step-by-step, analogy-driven explanations, writes most code themselves with guidance rather than receiving finished code, and wants every design decision understood well enough to explain in an interview — not just working code.

**Constraint:** local and free-tier tools as much as possible, end-to-end through deployment.

---

## 1. Project scope and setup

- **Goal:** RAG chatbot over a company's 10-K filing, plus a KPI dashboard, single-company upload for v1 (multi-company comparison deferred to v2).
- **Stack carried over from an earlier practice project ("AskTheVid" — RAG over YouTube transcripts):** FastAPI backend, Streamlit frontend, ChromaDB vector store, Groq for the LLM, local embeddings.
- **What a 10-K is:** a company's mandatory annual filing to the SEC (the US securities regulator), standardized in structure across all public companies, freely available on SEC EDGAR (the SEC's public filing database). Distinct from the glossy "annual report" companies also produce for shareholders (marketing document, not standardized).
- Downloaded 2024 10-Ks for Apple, Microsoft, and Tesla. Built the pipeline against Apple's first (~120+ pages; financial statements section around page 30).

## 2. PDF → Markdown (Phase 1)

- **Tool chosen:** `pymupdf4llm` — converts PDF pages directly to markdown, auto-detecting tables and converting them to markdown table syntax (`|` pipe syntax). Chosen over `pdfplumber`/`Camelot`/`unstructured` because it does prose + tables in one pass with no extra system dependencies.
- Verified output against a real Apple income statement screenshot — numbers matched correctly (net sales, cost of sales, net income, EPS all correct across three years).
- Built `pdf_to_markdown.py` with `convert_pdf()` (single file) and `convert_directory()` (batch), plus a `if __name__ == "__main__":` guard so importing the module elsewhere doesn't trigger unwanted execution.
- **Bugs hit and fixed along the way:** Windows default file encoding (`cp1252`) crashing on special characters like "☒" — fixed with explicit `encoding="utf-8"` on every file write. Missing `Path` import. A `str(input_dir)`/`Path(input_dir)` direction mix-up in batch processing.

## 3. Chunking (Phase 2) — first version, later found to be broken

- **Design goal:** 10-K prose and tables need different chunking treatment. A naive fixed-size splitter could slice a financial table in half, separating a row's label from its numbers — unacceptable for an investor-facing tool where wrong numbers are worse than no answer.
- **First version:** split all blocks into two upfront groups — `table_blocks` (any block where a line starts/ends with `|`) and `prose_blocks` — tables kept atomic (never split), prose run through `RecursiveCharacterTextSplitter` (chunk_size=500, overlap=50).
- Verified working: 507 chunks total (48 table, 459 prose) from the Apple PDF, structure looked correct on inspection.
- Considered and rejected `SemanticChunker` (used by a reference tutorial repo) — it required a paid Azure OpenAI embedding API to function, breaking the free-tier constraint, and more importantly it fed the raw markdown straight to the chunker with **no table/prose separation at all**, exposing exactly the table-splitting risk this project was trying to avoid.

## 4. Embedding + storage (Phase 2 continued)

- **Model:** `all-MiniLM-L6-v2` via `sentence-transformers` (same as AskTheVid) — local, free, 384-dim vectors.
- **Storage:** ChromaDB, persistent client.
- **Key architecture decision:** one shared ChromaDB collection (`"investor_intelligence"`), not one collection per company. Each chunk carries `source_company` and `filing_year` metadata; retrieval filters with `where={"source_company": ...}`. Chosen specifically because v2 (multi-company comparison) will need company data to coexist in one place — per-company collections would require a painful migration later.
- Built `retrieval.py`: `retrieve_chunks()` (query + metadata filter) and `build_context()` (formats retrieved chunks into a labeled prompt string, prefixing `[TABLE DATA]` or `[DOCUMENT TEXT]` per chunk so the LLM knows what it's reading).
- Built `chatbot.py`: `ask()` — retrieves context, builds a prompt with a system instruction to answer only from context and admit when the answer isn't there (to prevent hallucination), calls the LLM (Groq via LangChain's `ChatOpenAI` pointed at Groq's OpenAI-compatible endpoint).

## 5. The retrieval bug — the central debugging arc of this project

**Symptom:** asked the chatbot "What was Apple's net sales/net income in 2024?" — got "the provided context does not include that information," despite the data being definitely ingested (verified in the actual PDF, and confirmed present in the ChromaDB store).

**Diagnosis (two separate root causes):**

1. **Tables lack matching words.** A bare table chunk like `|Total net sales|391,035|383,285|394,328|` has almost no natural-language overlap with a question like "what was Apple's net sales in 2024?" Meanwhile, the *caption* describing that table ("Net sales disaggregated by significant products...") ranked well in similarity search but had no numbers. The words and the numbers were stored in separate, disconnected chunks — the caption chunk ranked in the top few results, the actual table chunk ranked 47th out of 507, well outside the top-5 retrieved.

2. **Embedding model token truncation.** `all-MiniLM-L6-v2` silently truncates input beyond 256 tokens — no error, just silently drops the rest. The income statement table chunk was 496 tokens; everything past the truncation point (including the "Net income" row) was never actually embedded, making it permanently invisible to search regardless of query wording.

**Research done before fixing (not just patched blindly):**
- Found this is a well-documented, named problem in the RAG field, not a bug unique to this project.
- Read an arXiv paper on "Evidence Units" — a formal method for grouping tables with their captions/headers before chunking, empirically shown to raise Recall@1 from 15% to 51% on a benchmark. Confirmed the caption-pairing intuition was sound, not overengineering.
- Surveyed the broader landscape of alternative approaches: hybrid search (BM25 + vector), table-to-natural-language rewriting via LLM, reranking, multimodal/vision chunking, "contextual retrieval" (prepending a synthetic header/summary to each chunk — a named, currently-recommended 2026 technique), small-to-large (ParentDocumentRetriever) retrieval, late chunking.
- Also researched KPI/metric extraction approaches for the future dashboard phase separately: XBRL (SEC's structured, pre-tagged financial data format) vs. direct table parsing vs. LLM structured generation. Decided **against** XBRL for v1 specifically because it would mean a second, disconnected data pipeline separate from the uploaded PDF (inconsistent source of truth) — chose to stick with parsing the same PDF the user uploads, for both the chatbot and the dashboard.

**Fix implemented — chunking.py rewritten:**
- Single pass over blocks in **document order** (not split into two groups upfront).
- **Look-behind-only caption pairing**: when a table block is found, check if the immediately preceding block is prose and not already used as another table's caption; if so, attach it. A `consumed_indices` set (tracked by block index) prevents the same caption being reused by two different tables.
- **Look-ahead was tried and deliberately rejected**: found a real failure case where an unconditional look-ahead could misattach a table's own trailing caption to a different, unrelated adjacent table (e.g., a Products table's chunk wrongly absorbing the intro sentence for the following Services table). Decided the cost of this misattribution (mild noise in the context) was still much smaller than the original bug (data completely missing from retrieval), but chose to drop look-ahead entirely rather than manage the ambiguity, since 10-K captions consistently precede their tables in practice.
- **Synthetic header** (`"{company} {year} 10-K\n"`) prepended to every chunk (table and prose), giving retrieval literal company/year words to match against even inside otherwise bare tables.
- Old broken chunking.py and its ChromaDB data were deliberately kept (not deleted) for a possible before/after comparison — decided as optional/deprioritized for now.
- Re-ran ingestion: same 507 chunks, table chunks now visibly include header + caption text on inspection.

**Second issue found after the first fix — oversized chunks:**
- A token-count audit (using the actual target tokenizer) found 8 of 507 chunks still exceed even a 512-token budget after caption-pairing made table chunks longer. Of these, 5 are real financial tables (balance sheet, income statement, cash flow, segment breakdowns) and 3 are boilerplate exhibit/signature-page tables (lower priority, unlikely to be asked about).
- **Debated two fixes:** (a) swap to a local embedding model with a bigger limit (`bge-small-en-v1.5`, 512 tokens) plus manually split oversized tables by row (repeating the header row on each split piece), vs. (b) switch to a hosted embedding model with a much larger context window.
- **Initial recommendation was (a)**, reasoning "stay local, avoid external dependency." **Reconsidered after pushback**: row-splitting correctly and generically — handling 10-K tables with multi-row headers, varying structures across different companies' filings not yet seen — is real, nontrivial, fragile parsing work, and this project explicitly needs to generalize to future/unseen client documents, not just Apple's filing. A hosted model with a large context window sidesteps this whole category of problem with much less fragile code.
- **Decision: switched to `nvidia/nemotron-3-embed-1b:free` via OpenRouter** — free, 32,768 token context window (vs 256/512), 2048-dimension vectors. Explicitly logged as a deliberate tradeoff (small external dependency accepted in exchange for correctness/generality that would otherwise require fragile custom parsing) — worth stating this reasoning explicitly in an interview, not hiding it as a compromise.

**Implementation work for the embedding swap (in progress):**
- Got an OpenRouter API key, added `OPENROUTER_API_KEY` to `.env`, wired into `config.py`.
- Built a custom `OpenRouterEmbeddingFunction` class (ChromaDB doesn't have this built in) implementing `__call__` (makes ChromaDB able to treat the object like a function — Python's `__call__` dunder method makes any object callable) and `name()` (ChromaDB requires this to detect embedding-function mismatches between what's stored in a collection and what's currently being used).
- Bugs hit and fixed during this: default `encoding_format` (base64) not supported by this model — fixed with explicit `encoding_format="float"`. API caps input batches at 256 texts per request, but 507 chunks were being sent in one call — fixed by adding internal batching inside `__call__` (loops in steps of `batch_size`, one API call per batch, results flattened into one list via `.extend()`).
- New embedding dimension (2048) is incompatible with the old collection's stored dimension (384) — needs a distinct/fresh ChromaDB collection going forward (old collection can't be reused, though the decision was made not to prioritize a formal before/after comparison for now).

## 6. Where things stand right now / immediate next steps

- [ ] Confirm the batched `OpenRouterEmbeddingFunction` successfully completes `embed_and_store()` on all 507 chunks without hitting further API errors
- [ ] Re-test `ask()` with the original failing questions ("What was Apple's net sales in 2024?", "What was Apple's net income in 2024?") to confirm the retrieval bug is actually fixed end-to-end
- [ ] Decide finally on collection naming (old collection is now technically dead weight — different vector dimension, can't be queried by the new embedder)
- [ ] Not yet started: KPI/metric extraction pipeline, dashboard, deployment

## 7. Working style notes for whoever picks this up next

- Explanations should be slow, step-by-step, with concrete traced examples (e.g., "let's trace this loop with i=0, i=1..." rather than describing code abstractly) and a concept check before moving on.
- The user writes code themselves after a design discussion; code is usually reviewed and debugged line-by-line rather than handed over pre-written, except when explicitly asked for a reference/finished version.
- Wants direct, unhedged feedback — has explicitly asked for "kill critic" mode.
- Treats every bug/decision as something to understand and be able to explain later, not just fix and move past — this project is a portfolio/interview talking point as much as it is working software.
- Was explicitly told, and responded well to, a mid-project note about slowing down and not letting new research/complexity cause a rushed pace — worth remembering to keep the pace deliberate, especially when a discussion opens up many possible directions (as the chunking-strategy research did).
