# Journey — new sections

Replace the existing sections 6 and 7 with everything below. Section 5 stays as-is.

---

## 6. Boilerplate removal (chunking v3)

**Problem the synthetic header created.** Prepending `"{company} {year} 10-K"` to every chunk had an unintended consequence: page footers already read `Apple Inc. | 2024 Form 10-K | 27`, so after the header they said "Apple 2024" twice, in a chunk containing no information at all. These short, dense, content-free chunks started outranking real financial tables.

**Fix.** `remove_repeating_boilerplate()` — normalize digits to `#` (so "page 27" and "page 28" collapse to the same pattern), count occurrences of each normalized pattern across the document, and drop any block whose pattern repeats 5+ times. The original block is what gets dropped or kept; normalization is only ever used for counting, so real figures are never altered.

Verified by dry-run that no genuine table was caught by the filter. Apple: 507 → 453 chunks, all 48 tables intact.

**Note in hindsight:** this fixed the *victim*, not the *cause*. The cause was the synthetic header itself, removed later in section 10.

---

## 7. The caption-distance gap and table-to-text conversion

**Symptom after v3.** The chatbot still failed on "What was Apple's net sales in 2024?". Raising `RETRIEVAL_TOP_K` to 25 as a diagnostic showed all 25 retrieved chunks were orphaned caption sentences ("The following table(s) show…") — zero real table chunks appeared even at rank 25 of 453. So this was not a "just outside top-5" problem.

**Root cause.** In the Notes to Financial Statements, some tables follow a `caption → subheading → table` pattern. The caption is two blocks back, not one, so look-behind-only never attached it. Those captions stayed as standalone chunks: short, topically dense, and therefore excellent decoys.

**Options considered:**

- **Contextual retrieval** (Anthropic's technique — an LLM reads the whole document and writes a short context blurb for each chunk, prepended before embedding). Would solve the positional-distance problem, but costs one LLM call per chunk (453 calls), and its published cost savings depend on prompt caching, which was uncertain on Groq's free tier.
- **Table-to-text conversion** — an LLM rewrites each table's rows into natural-language sentences before embedding. Only touches the 48 table chunks rather than all 453, and sidesteps the distance problem entirely: a converted table is self-describing regardless of how far away its caption sits.

**Decision: table-to-text.** Roughly one-tenth the LLM calls for the same effect on the chunks that actually mattered.

**Bug found during Tesla ingestion.** 34 of Tesla's tables came back empty (vs 2 for Apple), crashing `embed_and_store`. Root cause: `gpt-oss-120b` is a *reasoning* model — it spends `max_tokens` on internal reasoning before emitting an answer. With `LLM_MAX_TOKENS=1024`, complex tables exhausted the budget mid-reasoning and returned empty content with `finish_reason="length"`.

Fixes: raised the token budget; added retry-with-backoff for rate limits; added a raw-text fallback so one bad table degrades gracefully instead of crashing the run. Tried `llama-3.3-70b-versatile` (non-reasoning) which resolved the empty conversions, but it draws on a separate 100K-tokens-per-day quota that heavy same-day re-ingestion exhausted. Kept `openai/gpt-oss-120b` available as a fallback since it draws from a different quota pool.

**Cache staleness gotcha.** The JSON cache built to avoid re-paying the 10–15 minute conversion cost served the *old broken* conversions after `table_to_text()` was fixed — the fix silently never took effect. First appearance of a pattern that recurred twice more: **state that must be manually invalidated will eventually be forgotten.** Addressed properly in section 9.

---

## 8. Table-guaranteed retrieval merge

Rather than fight the ranking directly, `retrieve_chunks()` now runs **two** queries: the normal one, plus a second filtered to `content_type: "table"`. Results are merged and deduplicated by chunk ID.

This guarantees table content reaches the LLM regardless of how it ranks in plain similarity search.

**Result — the core bug fixed end-to-end.** The chatbot returned Apple's total net sales for 2024 as $391,035 million, correctly, from the converted income-statement chunk.

**Milestone.** The full pipeline was then verified on Tesla's 10-K as well (automotive sales $72,480M, 2024). Two filings from two companies with materially different formatting — evidence the pipeline generalizes rather than being fitted to one document.

**Acknowledged as a workaround, not a cure.** The merge compensates for bad ranking instead of fixing it. The general half of the results was still dominated by orphaned captions. Addressed in section 10.

---

## 9. Storage correctness

**Bug 1 — collection-wide deletion.** Ingestion called `_client.delete_collection("investor_intelligence")` before each run. That deletes the *entire collection*, every company in it. So Apple and Tesla were never actually coexisting: each was verified immediately after its own ingestion, having silently destroyed the other. The shared-collection design chosen back in section 4 had never once been exercised.

**Fix.** A scoped delete moved *inside* `embed_and_store()`:

```python
collection.delete(where={"$and": [
    {"source_company": {"$eq": company}},
    {"filing_year":    {"$eq": year}},
]})
```

Two things matter here. Scoping on company **and year** — a filing is identified by both, and company alone would wipe 2024 when re-ingesting 2025. And placing it *inside* the function rather than in `__main__`: a cleanup step that depends on a human remembering to run it isn't correctness, it's luck. When a FastAPI upload endpoint calls this later, there is no `__main__` to remember.

**Why delete before insert rather than overwrite.** Chunk IDs are positional (`chunk_0`, `chunk_1`, …). Any change to chunking shifts every subsequent ID, so overwriting is accidental rather than meaningful — and if a run produces fewer chunks than the last, the surplus old chunks survive as orphans, competing in every future retrieval. Delete-then-insert makes ingestion **idempotent**: running it once or five times leaves identical state.

**Bug 2 — cache invalidation by hand.** The converted-chunks cache was a single hardcoded filename, checked only with `.exists()`. Changing the chunker didn't change the filename, so stale chunks were served silently — the same failure as in section 7.

**Fix — put the identity in the filename:**

```
data/cache/Tesla_2024_<content-hash>_v5.json
```

`.exists()` now *is* the validation. If the file is there, it is by construction the right chunks for that company, that year, that exact source content, that pipeline version. A `PIPELINE_VERSION` constant is bumped whenever chunking logic changes, which renames the file and orphans the old cache automatically. No manual deletion step to forget.

A content hash was chosen over company+year alone because company+year identifies a filing *period*, not a *file* — an amended filing would match the cache key and silently serve superseded figures.

---

## 10. Chunking v4 — fixing the ranking at its source

With the merge guaranteeing correctness, the remaining problem was quality: retrieval was still full of junk. This section is deliberately measurement-led — a diagnostic script was written first, and one planned fix was dropped as a result.

### Diagnostic findings (Tesla, 443 chunks)

- ~40 short chunks were stranded markdown section headings (`#### **Revenues**`, `#### Income Taxes`). **Not junk — orphaned.** Structurally the same bug as the orphaned captions: a label separated from the content it labels.
- Only 8 exact duplicate texts in 443 — and two of them were legitimately different sections that share a title (Tesla has an "Automotive Segment" subsection under both *Revenue Recognition* and *Cost of Revenues*).
- 4 of 74 tables had silently fallen back to raw table syntax during conversion, with no way to identify which.

### Decision: deduplication measured and NOT built

The planned dedup pass was dropped. 8 duplicates in 443 is not worth the code, and the implementation would have been actively harmful — deleting one of two same-titled sections destroys real information. Recorded here deliberately: the useful outcome of measuring was deciding *not* to build something.

### Decision: heading detection by markup, not by length

Two candidate rules for identifying a label block:

- **Structural** — the block starts with a markdown `#`
- **Length** — the block is under N characters

Chose structural. It reads the document's own markup rather than inferring from a proxy, consistent with the existing `|` pipe-detection for tables.

The deciding argument was the *shape* of each failure mode. The structural rule inherits `pymupdf4llm`'s heading detection, so it may **miss** a heading — leaving an orphan, which is the status quo. The length rule fails in both directions: it also **merges real content**, since `None.` (Tesla's actual answer to a 10-K item) is short but is not a heading. Merging it into the next section attaches an answer to the wrong question. **A rule that only leaves work undone beats one that can fabricate.**

Confirmed by the results: `#### **ITEM 16. FORM 10-K SUMMARY** / None.` survived as a correctly labelled chunk. A length filter would have deleted it.

### Decision: carry-forward heading context

A heading is attached to *every* block until the next heading replaces it, not just the first. 10-K sections run for several paragraphs and the answer is as likely to be in the fourth as the first.

Accepted tradeoff: chunks within a section share their heading prefix, so their embeddings sit closer together and a query tends to surface several of them at once. Acceptable — and arguably useful — for financial questions that need surrounding context.

Also decided **not** to build an ancestor trail (`Apple / Notes / Note 1 / Revenue`). `pymupdf4llm` flattens all headings in Apple's Notes section to `####`, so there is no hierarchy to reconstruct; and a ~110-character trail repeated across every chunk in the largest section of the document reintroduces exactly the problem solved immediately below.

### Decision: synthetic header removed

The `"{company} {year} 10-K"` prefix on every chunk was deleted.

**Why it could not help.** Vector ranking depends on *relative* difference. A string present in all 443 chunks shifts all 443 embeddings equally and changes no ordering — the equivalent of adding ten marks to every exam paper.

**Why it actively hurt.** An embedding is a fixed-size summary, so a constant prefix consumes budget in proportion to how much of the chunk it is. On a 900-character paragraph it is noise. On `Tesla 2024 10-K\nx` — a cover-page checkbox mark — it is 16 of 17 characters, making that chunk's embedding essentially *just the header*, parked exactly where every company-and-year query lands. The Apple footer decoys in section 6 were the same mechanism via a different trigger.

**Why removal rather than filtering.** Filtering is a blocklist: it only handles failure shapes already observed. Apple's victim was doubled footer text; Tesla's was cover-page marks; a third filer would produce a third shape. Removing the cause covers documents not yet seen. (The same generalization argument used in section 5 when choosing a hosted large-context embedding model over local row-splitting.)

Company and year remain in metadata, where they can be filtered *exactly* — the right tool for a fact you either want or don't.

### Regression found and fixed before shipping

Pulling headings out of the block stream removed them as **section boundaries** as well as noise. Look-behind then reached across a section break.

Concretely, in Apple's filing: the value-at-risk paragraph closes Item 7A; `#### Item 8` follows; then the financial-statements index table. With the heading removed from the stream, the index table absorbed the VAR paragraph as its caption — mislabelling the table *and* deleting a real paragraph from the store. v3 had handled this case correctly, so this was a genuine regression, caught by tracing real document text rather than by running the pipeline.

**Fix — pair only when both blocks share the same heading context.** Same context means no section boundary was crossed. Purely structural; no heuristic to tune.

**Known cost.** A caption separated from its own table by a subheading now stays an orphan. Accepted, because the table still carries its heading, table-to-text makes it self-describing, and the guaranteed merge surfaces it regardless of rank — the combination that already produced the correct Apple and Tesla figures. The alternative was inferring intent from phrasing ("does this sentence announce a table?"), which is precisely the kind of heuristic rejected earlier in this section.

### Conversion status made visible

`table_to_text()` now returns a status alongside its text, stored as `conversion_status` metadata (`converted` / `raw_fallback`), with a per-table log line and a summary warning. Previously a degraded table was indistinguishable from a good one after ingestion — silent degradation in the exact place the conversion step exists to prevent.

### Results (Tesla, dry run)

| | v3 | v4 |
|---|---|---|
| chunks | 443 | 343 |
| tables | 74 | 74 |
| chunks under 60 chars | ~59 | 10 |

All 10 remaining short chunks now carry a heading and are meaningful. No table was lost.

---

## 11. Where things stand

**Working:** PDF → markdown → chunking (boilerplate removal, heading carry-forward, section-scoped caption pairing, degenerate filtering) → table-to-text conversion → OpenRouter nemotron embeddings → ChromaDB (scoped idempotent writes) → retrieval with table-guaranteed merge → chatbot. Verified on Apple and Tesla 2024 10-Ks.

**Known issues, not blocking:**

- `retrieval.py` uses `get_or_create_collection()`, which silently creates an empty collection and returns zero results if the store is missing — should be `get_collection()` so a missing store fails loudly
- `retrieval.py` filters on `source_company` but not `filing_year`; harmless today, will mix years once a second year is ingested
- `RETRIEVAL_TOP_K = 25` is a leftover from the orphaned-caption era and likely wastes tokens now
- Seven Tesla cover-page chunks share an identical heading context, producing near-identical embeddings; cosmetic
- Ingestion takes 10–15 minutes because table conversion is one LLM call per table with rate-limit spacing; could batch or run async

**Not started:** KPI/metric extraction, dashboard, deployment.
