# Investor Intelligence — engineering journal

A RAG system over SEC annual filings: chatbot plus KPI dashboard, with an upload
path that ingests a new filing end to end.

This document records decisions and the reasoning behind them, including the ones
that turned out wrong. Constraint throughout: free-tier tooling wherever possible.

---

## 1. Scope and setup

- RAG chatbot over a company's 10-K, plus a KPI dashboard. Single-filing upload
  for v1; multi-company comparison deferred.
- Initial stack carried over from an earlier project: FastAPI, ChromaDB, Groq for
  the LLM, local embeddings.
- A 10-K is a company's mandatory annual filing to the SEC, standardised in
  structure across all public companies and freely available on EDGAR. It is
  distinct from the glossy "annual report", which is a marketing document and is
  not standardised. That distinction mattered later — see section 16.
- Built against Apple's 2024 filing first, then Microsoft and Tesla.

## 2. PDF to markdown

`pymupdf4llm` was chosen over `pdfplumber`, `Camelot` and `unstructured`: it
handles prose and tables in one pass with no system dependencies, emitting
markdown pipe tables.

Output was verified against a real Apple income statement — net sales, cost of
sales, net income and EPS all matched across three years.

Bugs fixed during this phase: Windows `cp1252` encoding crashing on `☒`, resolved
by making `encoding="utf-8"` explicit on every file write; a missing `Path`
import; a `str`/`Path` direction mix-up in batch processing.

## 3. Chunking, first version

10-K prose and tables need different treatment. A fixed-size splitter can cut a
table in half, separating a row's label from its numbers — unacceptable for a
tool whose value is precise figures.

First version: split blocks into two groups upfront — tables (any block with a
line starting or ending with `|`) and prose. Tables kept atomic; prose through
`RecursiveCharacterTextSplitter` at 500 characters with 50 overlap. Produced 507
chunks from Apple's filing, 48 of them tables.

`SemanticChunker` was considered and rejected: it required a paid embedding API,
and more importantly it fed raw markdown to the splitter with no table/prose
separation at all — exactly the failure this design existed to avoid.

## 4. Embedding and storage

- `all-MiniLM-L6-v2` via `sentence-transformers`: local, free, 384 dimensions.
- ChromaDB with a persistent client.
- **One shared collection**, not one per company. Each chunk carries
  `source_company` and `filing_year` metadata and retrieval filters on them.
  Chosen because multi-company comparison will need the data to coexist;
  per-company collections would have forced a migration later.

`retrieve_chunks()` queries with a metadata filter. `build_context()` formats
results, prefixing `[TABLE DATA]` or `[DOCUMENT TEXT]` per chunk so the model
knows what it is reading.

## 5. The retrieval bug

**Symptom.** "What was Apple's net sales in 2024?" returned "the provided context
does not include that information", despite the data being present in the store.

**Two independent causes.**

*Tables lack matching words.* A chunk reading
`|Total net sales|391,035|383,285|394,328|` has almost no lexical overlap with
the question. The caption describing it ranked well but contained no numbers. The
words and the numbers were in separate chunks — the table ranked 47th of 507.

*Silent token truncation.* `all-MiniLM-L6-v2` drops input beyond 256 tokens with
no error. The income statement chunk was 496 tokens, so the "Net income" row was
never embedded at all and was invisible to any query.

**Research before fixing.** This is a documented problem, not a local one. An
arXiv paper on "Evidence Units" — grouping tables with their captions before
chunking — reported Recall@1 rising from 15% to 51%, confirming the caption
intuition. Alternatives surveyed: hybrid search, table-to-text rewriting,
reranking, contextual retrieval, small-to-large retrieval, late chunking.

XBRL was considered for the KPI dashboard and rejected: it would mean a second
pipeline disconnected from the uploaded PDF, giving two sources of truth.

**Fix.** Rewrote chunking to walk blocks in document order with look-behind-only
caption pairing: a table absorbs the immediately preceding prose block if it is
not already consumed by another table. A `consumed` set prevents reuse.

Look-ahead was implemented and then deliberately removed. It could misattach one
table's introduction to an adjacent unrelated table — a Products table absorbing
the Services table's intro. 10-K captions consistently precede their tables, so
the ambiguity was not worth managing.

A synthetic header `"{company} {year} 10-K"` was prepended to every chunk to give
retrieval literal company and year tokens. This was a mistake, removed in
section 10.

**Oversized chunks.** A token audit found 8 of 507 chunks exceeding even 512
tokens after caption pairing lengthened them. Two options: a local model with a
larger window plus row-splitting of big tables, or a hosted model with a large
window.

Row-splitting was initially preferred, then rejected. Splitting tables correctly
across filings not yet seen — multi-row headers, varying structures — is fragile
parsing work, and the project needs to generalise to unseen documents.

**Decision: `nvidia/nemotron-3-embed-1b:free` via OpenRouter** — 32,768-token
context, 2048 dimensions. A small external dependency accepted in exchange for
removing a category of parsing bugs.

Implementation bugs: base64 was the default `encoding_format` and unsupported by
the model (fixed with `encoding_format="float"`); the API caps batches at 256
texts while 507 were being sent in one call (fixed with internal batching).

---

## 6. Boilerplate removal

The synthetic header created a problem. Page footers already read
`Apple Inc. | 2024 Form 10-K | 27`, so after the header they said "Apple 2024"
twice inside a chunk containing no information. These short, dense, content-free
chunks began outranking real tables.

`remove_repeating_boilerplate()` normalises digits to `#` so "page 27" and
"page 28" collapse to one pattern, counts occurrences, and drops any block
repeating five or more times. Normalisation is used only for counting; the
original block is what is kept or dropped, so figures are never altered.

Apple: 507 → 453 chunks, all 48 tables intact.

This fixed the victim, not the cause. The cause was the synthetic header, removed
in section 10.

## 7. The caption-distance gap, and table-to-text

**Symptom after boilerplate removal.** The same query still failed. Raising
`RETRIEVAL_TOP_K` to 25 as a diagnostic showed all 25 results were orphaned
caption sentences — zero table chunks at rank 25 of 453. Not a near-miss.

**Cause.** In the Notes, some tables follow `caption → subheading → table`. The
caption is two blocks back, so look-behind-only never attached it. Those captions
survived as standalone chunks: short, topically dense, and excellent decoys.

**Options.** Contextual retrieval (an LLM writes a context blurb per chunk) would
solve it but costs one call per chunk — 453 calls. Table-to-text conversion
rewrites each table's rows as sentences before embedding, touching only 48
chunks, and sidesteps distance entirely because a converted table describes
itself.

**Chose table-to-text.** A tenth of the calls for the same effect where it
mattered.

**Bug during Tesla ingestion.** 34 tables came back empty. `gpt-oss-120b` is a
reasoning model: it spends `max_tokens` on internal reasoning before emitting an
answer. At 1024 tokens, complex tables exhausted the budget mid-reasoning and
returned empty content with `finish_reason="length"`.

Fixes: raised the budget, added retry-with-backoff, added a raw-text fallback so
one bad table degrades rather than crashing the run.

**Cache staleness.** The JSON cache built to avoid re-paying the 10–15 minute
conversion cost served the *old broken* conversions after `table_to_text()` was
fixed, so the fix silently never took effect. First instance of a pattern that
recurred twice more: **state requiring manual invalidation will eventually be
forgotten.** Addressed in section 9.

## 8. Table-guaranteed retrieval merge

Rather than fight the ranking, `retrieve_chunks()` runs two queries: the normal
one, and a second filtered to `content_type: "table"`. Results are merged and
deduplicated by chunk id.

This guarantees table content reaches the model regardless of how it ranks.

**Result.** The chatbot returned Apple's total net sales for 2024 as $391,035
million, correctly, from the converted income-statement chunk. Verified again on
Tesla's filing — two companies with materially different formatting.

Acknowledged as a workaround. It compensates for bad ranking rather than fixing
it; the general half of the results was still dominated by orphaned captions.
Addressed in section 10.

## 9. Storage correctness

**Collection-wide deletion.** Ingestion called
`_client.delete_collection("investor_intelligence")` before each run — deleting
every company in it. Apple and Tesla were never coexisting: each was verified
immediately after its own ingestion, having silently destroyed the other. The
shared-collection design from section 4 had never once been exercised.

Fixed with a scoped delete moved *inside* `embed_and_store()`:

```python
collection.delete(where={"$and": [
    {"source_company": {"$eq": company}},
    {"filing_year":    {"$eq": year}},
]})
```

Two things matter. Scoping on company **and** year, because a filing is
identified by both and company alone would wipe 2024 when re-ingesting 2025. And
placing it inside the function rather than in `__main__`: a cleanup step that
depends on someone remembering to run it is not correctness. When an upload
endpoint calls this later there is no `__main__` to remember.

Delete-then-insert rather than overwrite, because chunk ids are positional. Any
chunking change shifts every subsequent id, so overwriting is accidental; and a
run producing fewer chunks leaves the surplus as orphans competing in every
future retrieval. Delete-then-insert makes ingestion idempotent.

**Cache invalidation by hand.** The converted-chunks cache used a hardcoded
filename checked with `.exists()`. Changing the chunker did not change the
filename, so stale chunks were served silently — the same failure as section 7.

Fixed by putting the identity in the filename:

```
data/cache/Tesla_2024_<content-hash>_v5.json
```

`.exists()` now *is* the validation. A `PIPELINE_VERSION` constant is bumped when
chunking changes, which renames the file and orphans the old cache automatically.

A content hash was chosen over company-and-year because company-and-year
identifies a filing *period*, not a *file* — an amended filing would match the
key and serve superseded figures.

## 10. Chunking v4 — fixing ranking at the source

With correctness guaranteed by the merge, the remaining problem was quality. This
section is measurement-led: a diagnostic ran first, and one planned fix was
dropped as a result.

**Findings (Tesla, 443 chunks).** ~40 short chunks were stranded markdown
headings — not junk, orphaned, structurally the same bug as the orphaned
captions. Only 8 exact duplicates in 443, two of which were legitimately
different sections sharing a title. 4 of 74 tables had silently fallen back to
raw syntax with no way to tell which.

**Deduplication measured and not built.** 8 duplicates in 443 is not worth the
code, and deleting one of two same-titled sections destroys real information.
Recorded deliberately: the useful outcome of measuring was deciding not to build.

**Heading detection by markup, not length.** Two candidate rules: the block
starts with `#`, or the block is under N characters. Chose structural.

The deciding argument was the shape of each failure. The structural rule inherits
the converter's heading detection, so it may *miss* a heading — leaving an
orphan, which is the status quo. The length rule fails in both directions: it
also *merges real content*, because `None.` is Tesla's actual answer to a 10-K
item and is short. **A rule that only leaves work undone beats one that can
fabricate.**

Confirmed: `#### **ITEM 16. FORM 10-K SUMMARY** / None.` survived as a correctly
labelled chunk. A length filter would have deleted it.

**Carry-forward heading context.** A heading attaches to every following block
until replaced, not just the first — 10-K sections run for several paragraphs and
the answer is as likely to be in the fourth as the first.

An ancestor trail (`Apple / Notes / Note 1 / Revenue`) was rejected: the
converter flattens Apple's Notes headings to one level, so there was no hierarchy
to reconstruct, and a 110-character trail on every chunk reintroduces the problem
solved immediately below. This decision was revisited in section 15.

**Synthetic header removed.** The `"{company} {year} 10-K"` prefix was deleted.

*Why it could not help.* Vector ranking depends on *relative* difference. A
string present in all 443 chunks shifts all 443 embeddings equally and changes no
ordering — the equivalent of adding ten marks to every exam paper.

*Why it actively hurt.* An embedding is a fixed-size summary, so a constant
prefix consumes budget in proportion to how much of the chunk it is. On a
900-character paragraph it is noise. On `Tesla 2024 10-K\nx` — a cover-page
checkbox — it is 16 of 17 characters, making that chunk's embedding essentially
just the header, parked exactly where every company-and-year query lands.

*Why removal rather than filtering.* Filtering is a blocklist: it handles only
failure shapes already seen. Apple's victim was doubled footer text, Tesla's was
cover-page marks, a third filer would produce a third shape. Removing the cause
covers documents not yet seen.

Company and year remain in metadata, where they can be filtered exactly.

**Regression caught before shipping.** Pulling headings out of the block stream
removed them as *section boundaries* as well as noise, so look-behind reached
across a section break. In Apple's filing the value-at-risk paragraph closes Item
7A, `#### Item 8` follows, then the financial-statements index table — which
absorbed the VAR paragraph as its caption, mislabelling the table and deleting a
real paragraph. Caught by tracing document text, not by running the pipeline.

Fixed by pairing only when both blocks share the same heading context. Same
context means no boundary was crossed. Purely structural, nothing to tune.

Known cost: a caption separated from its table by a subheading stays an orphan.
Accepted, because the table carries its heading, table-to-text makes it
self-describing, and the merge surfaces it regardless of rank.

**Conversion status made visible.** `table_to_text()` returns a status stored as
`conversion_status` metadata. Previously a degraded table was indistinguishable
from a good one after ingestion — silent degradation in exactly the place the
conversion step exists to prevent.

Results (Tesla): 443 → 343 chunks, 74 tables unchanged, chunks under 60
characters from ~59 to 10 — all of which now carry a heading and are meaningful.

---

## 11. Rate limits: two errors wearing one costume

A Microsoft run produced 72 raw fallbacks in 30 minutes and converted nothing.
The handler caught `RateLimitError`, slept 5s, retried three times, gave up, and
moved on — 72 times. The error had said `try again in 12m`.

Groq sends two different failures under one exception class:

- **TPM** — the per-minute pool refills in 60 seconds. Waiting is correct.
- **TPD** — the daily pool is empty. Retrying is pointless, and it is pointless
  for *every remaining table*, not just this one.

The wait time is not only how long to sleep. It is the signal for which failure
this is.

**Two fixes at two scopes.** Inside `table_to_text`, parse the server's wait time
from the error text and sleep for it; above a 90-second threshold (the TPM window
is 60s, so anything longer cannot be a per-minute refill) raise `QuotaExhausted`.
Inside `convert_table_chunks`, catch that and `break`. A per-table handler can
only fail one table; the daily quota is a property of the *run*, so the signal
has to escape the loop.

**The caching danger this exposed.** The original code wrote the cache and
embedded unconditionally. After an abort that meant: cache written with 52
unconverted tables, ChromaDB filled with raw table syntax, and the next run
seeing `cache_file.exists()` and skipping conversion entirely. Broken data,
cached forever, silently.

Fixed by pre-filling `conversion_status = "pending"`, writing partial work under
a *different* filename so `cache_file.exists()` stays false, and exiting before
embedding. The separate filename matters more than the save: a partial cache can
be deleted, while a partial collection looks fine and answers with wrong data.

Proven live — Microsoft table 21 hit TPM with `try again in 13.3125s`, the
handler slept once and table 22 converted.

## 12. Heading detection, measured twice

`pymupdf4llm` identifies headings by **font size**. Microsoft marks its note
headings by underlining them at body size, so the signal is genuinely absent and
the conversion is deterministic — re-running changes nothing. Confirmed by test,
not argument: re-ran the loader (identical output) and tried
`hdr_info=TocHeaders(doc)` (the PDF has no bookmarks).

Missed headings do not vanish. Carry-forward hands the *previous* section's
heading to everything following, so content gets a wrong label.

**Blast radius measured before deciding.**

| Filing | Undetected headings | Chunks mislabelled | Tables affected |
|---|---|---|---|
| Apple | 0 | 0 | 0 |
| Tesla | 0 | 0 | 0 |
| Microsoft | 9 | 16 / 582 (2.7%) | 0 |

2.7%, zero tables — much smaller than it felt while reading examples. The damage
is self-limiting: each miss corrupts 1–3 chunks because the next detected heading
resets the context. The blast radius of a detection failure is bounded by the
detection rate, which fell out of the carry-forward design without being designed
for.

**Two failure shapes.** *Lost parent* — a subheading with its parent missing;
mild. *Wrong parent* — Note 18's stock-compensation body inheriting
`NOTE 17 — ACCUMULATED OTHER COMPREHENSIVE INCOME`; false context.

The second is dangerous in a counterintuitive direction. Retrieval still works:
query "stock compensation" and the body matches. The harm is at *generation*
time, on the *opposite* query — ask about accumulated other comprehensive income
and the model receives stock compensation text under that heading and attributes
it accordingly. Body-driven queries are safe; label-driven queries are not.

**The rule.** Accept `<u>...</u>` as a fallback heading marker. Reject `**...**`
— bold produced 17 false positives across Apple and Tesla, all cover-page form
fields. Require three consecutive letters and no trailing punctuation.

9 true positives on Microsoft, 0 false positives across all three filings.

**Rejected: demoting units captions.** The converter marked
`### **<u>(In millions, ...)</u>**` as a heading; it is a units note belonging to
the table below. Measured at 1 chunk of 582 and rejected. Demotion is riskier
than promotion: the `<u>` rule only *adds* structure, while a demotion rule
*removes* it, and a false positive would delete a real heading and create exactly
the bug being fixed.

## 13. A bug found by following evidence

The heading fix worked and the query that motivated it still failed. "What does
Note 10 cover" returned two captions and a footnote. **The tables never
surfaced.** An answer built from that reads fluently and contains no data — the
worst failure mode here, because a wrong number is obvious and a missing one is
not.

Two hypotheses: the tables were absent from the collection, or present and
ranked too low. Completely different fixes, so worth ten minutes to find out.

A diagnostic searched the cache for "intangible" and printed each hit's
neighbours in document order:

```
[437] (prose)  ## NOTE 10 — INTANGIBLE ASSETS  The components of intangible assets...
[438] (table)  For the marketing-related intangible assets, the gross carrying
               amount was $16,500 million...
```

Present, converted, correctly positioned. A ranking problem, not a data problem.

The prose chunk carries `## NOTE 10 — INTANGIBLE ASSETS`. The table chunk carries
nothing — and every other table in the file starts the same way. The cause was
two lines:

```python
text, status = table_to_text(chunk["text"])
chunk["text"] = text          # the whole chunk is replaced
```

Chunking prepends heading context to tables as well as prose. The model receives
it, is instructed to rewrite the table's rows, and returns only that. Overwriting
`chunk["text"]` with the response **discards the heading**. So the words "Note
10" existed in prose chunks and nowhere in table chunks — roughly 190 chunks
across three filings, findable by their own wording but never by section name.

Fixed by storing `heading_context` separately at chunking time and recombining
after conversion, rather than trusting the model to preserve structural context.

**The lesson.** The heading work was a 2.7% problem that felt large because the
examples were vivid. The real defect was found only by writing a diagnostic to
answer a question the examples had raised, and reading its output for what it
said rather than for what confirmed the starting hypothesis.

---

## 14. Changing the extractor

Reading back the open issues, a pattern was visible: nearly every chunking rule
was repairing damage done *upstream*. The `<u>` heading fallback existed because
the converter detects headings by font size. The `<br>` strip existed because it
leaked HTML. A planned units fold existed because `(In millions)` was stranded on
its own line. Joined words like `Diluted earnings pershare` were extraction
artifacts.

None of those are chunking problems.

**Trial design.** Change exactly one variable: same `chunk_markdown()`, same
audit scripts, different markdown. Never call `convert_table_chunks()`, so the
whole trial cost zero LLM quota.

### docling

Three environment walls. `torch.compile` needed an MSVC toolchain that was not
installed. The default pipeline ran OCR, rendering every page to a bitmap, which
produced `std::bad_alloc` on a machine with 7.9 GB — and these filings have a
real text layer, so OCR was recovering text that was already there.

The third was more interesting:

| run | OCR | page_batch_size | pages asked | failed from |
|---|---|---|---|---|
| 1 | on | 4 | all 61 | page **13** |
| 2 | off | 1 | 1–15 | page **13** |

OCR was removed and pages-in-flight cut from 4 to 1. The failure boundary moved
**zero pages**. Page 13 itself is unremarkable — 2,879 characters, no images, no
drawings.

A boundary indifferent to available memory is not exhaustion; it is a bound
inside the C++ parser, unreachable from Python. Diagnosing further would have
been curiosity rather than engineering — leak, fixed arena or internal limit all
have the same remedy. Switched backend, and the full document converted.

**docling won every count and failed the actual test.**

| | pymupdf4llm | docling |
|---|---|---|
| undetected headings | **9** | **0** |
| `<u>` tags | 49 | 0 |
| `<br>` tags | 752 | 0 |
| units deleted by boilerplate | 14 | **0** |
| tables carrying units | 54/72 | **64/72** |
| characters | 184,491 | 226,263 |

On those numbers, three planned fixes became unnecessary. Then a page-by-page
audit against the PDF found ~19 defects: missing column headers in ~10 tables,
content filed under the wrong note (note 15's content inside note 13), values
shifted upward.

**Every metric in that table counts artefacts, not correctness.** Tidy markdown
is not accurate markdown. No count could see a missing header row or a table
absorbed into its neighbour.

A financial table without its year header is worse than useless: the system
cannot tell 2024 from 2023 and will answer confidently either way.

### The incumbent had never been audited

The degraded-backend hypothesis was tested by re-running a page range with the
richer parser. The `2024` header was still missing, so it was docling's table
model, not the handicap. It *was* right about cell boundaries — `$` signs drifted
one cell right under the fallback backend and were correct under the other.

Then, checking the same table in pymupdf4llm:

```
PDF:          Year Ended June 30,  2024  2023  2022
pymupdf4llm:  |**Year Ended June 30,**|**2024**|**2023**|
```

**The entire 2022 column was missing — data, not a label.** It had been in the
pipeline for weeks.

docling had been audited page by page. pymupdf4llm never had. Comparing an
audited challenger against an unaudited incumbent always favours the incumbent,
because only one side's defects have been counted.

### LlamaParse, rejected

Headers all present. Rows not aligned to them, and not aligned to each other:

```
|                               |         | 2024    |         | 2023    |   | 2022    |
| Interest and dividends income | $ 3,157 | $ 2,994 | $ 2,094 |         |   |         |
| Interest expense              |         | (2,935) |         | (1,968) |   | (2,063) |
```

Read positionally, interest and dividends income for 2024 comes out as $2,994;
the true figure is $3,157. The row below it reads correctly.

A missing header is uniformly missing — you know you do not know. Per-row offsets
are silently wrong for *some* rows with nothing to indicate which.

### Datalab, selected

The full 61-page filing in **22.4 seconds**, against docling's 850.

| | pymupdf4llm | docling | LlamaParse | **Datalab** |
|---|---|---|---|---|
| `2024` header label | yes | **no** | yes | yes |
| 2022 column data | **no** | yes | yes | yes |
| rows aligned to header | yes | yes | **no** | yes |
| full-document time | seconds | 850s | — | **22s** |

**The deciding argument was recoverability, not score:**

| extractor | defect | recoverable? |
|---|---|---|
| Datalab | units detached above the table | **yes** |
| docling | `2024` label missing | by inference — statements run newest-first |
| pymupdf4llm | whole 2022 column dropped | **no** — the data is not in the file |
| LlamaParse | inconsistent per-row offsets | **no** — silently wrong, undetectable |

Not which scores best, but whose failures can be engineered around.

**Cost recorded deliberately.** Datalab is a cloud API. Ingestion now needs a
key, a network call and a per-page cost, and the PDF is uploaded to a third
party. Acceptable for public SEC filings. It does break the "local" half of the
original constraint, which is an architectural commitment worth stating rather
than drifting into.

## 15. Chunking v5

**Heading context became hierarchical.** v4 kept a flat context: every heading
replaced the previous one regardless of level, so a `####` obliterated the `##`
above it. That is why `NOTE 6 — INVENTORIES` chunks were labelled `Fair Values of
Derivative Instruments`.

Datalab's headings go six levels deep with the mass at 3–5, derived from layout
analysis rather than font-size guessing. The flat model was replaced with a level
stack: a heading at level N clears deeper slots and occupies slot N; context is
the slots joined in order.

```
# PART II
## Item 8. Financial Statements and Supplementary Data
### Notes to Consolidated Financial Statements
#### Note 4 — Financial Instruments
##### **Accounts Receivable**
###### *Trade Receivables*
```

Under the flat model that chunk carried only `###### *Trade Receivables*`.

Measured before deciding whether to cap depth: median context 118–142 characters
against 500-character chunks, maximum 264. No cap needed. The
`previous_was_heading` accumulation flag disappeared — a stack handles
consecutive headings without it.

**table-to-text was dropped.** The step existed for *retrieval*, not generation:
a bare grid of numbers embeds poorly against a natural-language question. Two
things changed that. Table chunks now carry 118–264 characters of heading path
plus a caption sentence. And `retrieve_chunks()` already runs a table-filtered
second query, which is a retrieval-side fix for the same problem.

What dropping it bought: chunking became pure text processing, so iteration costs
nothing — previously every chunker change cost ~100 LLM calls per filing. It
removed a lossy step over financial data, where `raw_fallback` existed as a
status precisely because the rewrite could fail. And two open issues closed for
free, since resume-from-partial and the mass-fallback guard existed only to
survive the conversion loop.

**The units fix turned out to be a guard, not a stage.** Datalab strands
`(In millions)` as its own block above 33 Microsoft tables, 29 of them identical
— so boilerplate removal deleted them, the same factor-of-10⁶ bug as before.

The first attempt was positional: do not drop a repeated block if a table follows
within N blocks. It has no workable setting. At N=1 it missed units separated
from their table by a period label. At N=3 it spared *every* footer in the
financial statements and disabled the function entirely — 0 blocks dropped across
three filings.

Replaced with an explicit exemption: a repeated block matching a units pattern is
never dropped. Precise instead of positional. Five genuine footers dropped per
filing, zero units lines lost.

**Two bugs that looked correct on the page.**

`for j in range(i-1, i-3):` — ranges count upward, so this is always empty. The
caption loop never executed and no table got a caption. Verified by measurement:
`with caption 0` on all three filings, units coverage collapsing from 67/73 to
34/73.

And **the `consumed` set had never prevented anything**, inherited from v4. The
loop iterates forward. A caption sits at index `i-1`, its table at `i`, so `i-1`
is reached first, is not yet in `consumed`, and is emitted as a prose chunk. The
table then adds it — too late.

```
Apple: captions ALSO emitted as a standalone prose chunk: 37/37
MSFT : captions ALSO emitted as a standalone prose chunk: 66/66
```

Every caption was stored twice. The v4 comment read `# prose blocks already used
as a table's caption`, describing an intent the code never carried out.

Fixed by splitting decision from emission: pass 1 assigns captions and fills
`consumed` with no output; pass 2 emits. Chunk counts fell from 319/346/592 to
252/268/462 — that drop is the duplicates disappearing.

**Validation became a permanent harness.** Both bugs produced plausible output
and were caught only by measuring:

| invariant | what it caught |
|---|---|
| chunk schemas uniform | a `{...}` placeholder that made table chunks `set` objects |
| no block emitted twice | the `consumed` no-op |
| no block lost | baseline safety |
| table rows in == out | proves no table was split or truncated |

Final state: zero leaked duplicates, zero lost blocks, table rows preserved
exactly (624→624, 920→920, 792→792).

**A validation that only checks for loss is half a validation.** The first pass
reported `content lost: 0` and was read as "the pipeline is fine" — while every
caption was being duplicated.

## 16. The inputs were excerpts

Adding `"Answer in one short sentence. Give the figure and its units, nothing
else."` broke four question types at once: yes/no questions answered with a bare
number, a request for five product categories answered with one aggregate,
a descriptive question answered with a figure, a breakdown answered with a total.

A formatting constraint does not only change formatting — it **competes with the
reasoning instructions already in the prompt**. The fix was to make the format
conditional on question type.

The change was also confounded: the model had been switched in the same edit, so
the regression could not be attributed. The extractor trial's discipline — change
one thing — applies to prompts too, and was not applied.

**Then chasing a failed auditor query surfaced the real problem.**

| | PDF used | actual filing |
|---|---|---|
| Apple | 39 pages | 121 |
| Microsoft | 61 pages, "Annual Report 2024" | ~100 |
| Tesla | excerpt | 144 |

Microsoft's had **zero** occurrences of Item 1A, Item 7 or Item 8. Apple's had no
audit report.

Which retroactively vindicated a class of results treated as failures — the
AI-risks refusal, the cloud-competition refusal, the Item 1A refusal. The
pipeline was right every time; the content was never there.

**The weakest link was data acquisition, not engineering.** Days were spent
tuning extraction and chunking against documents missing the sections being
queried.

**The auditor question, diagnosed properly.** With Apple's full 121-page filing
ingested (1,218 chunks, up from 252), the query still failed — now a genuine miss
with an obvious gold chunk containing both the query phrase and the answer in one
sentence. It ranked **11**, outside top-10.

```
[1] 0.7677  ... / Report of Independent Re...  "To the Shareholders and the Board"
[2] 0.7677  ... / Report of Independent Re...  "To the Shareholders and the Board"   <- identical
[3] 0.9575  ... / Consent of Independent Registered P...
```

Retrieval found the right *region* and returned the chunks without the name. The
heading `Report of Independent Registered Public Accounting Firm` matches the
query almost perfectly and is carried by **every chunk in that section**, so the
salutation at the start ranks equal to the signature at the end.

The same intra-section collapse had been measured on a segment-revenue query.
Two independent confirmations of one mechanism: heading context makes chunks
self-describing and simultaneously makes chunks within a section hard to tell
apart.

Fixed by widening `RETRIEVAL_TOP_K` from 10 to 15, which then worked first time
on Tesla — the fix generalised rather than being fitted to one query.

**The free tier kept shaping the architecture.** A third time, after the
256-token embedding window and the daily quota:

```
413 — Request too large. Limit 8000, Requested 8395
```

Not a rate problem — a single request over the per-minute ceiling. Groq counts
`prompt_tokens + max_tokens`, so `LLM_MAX_TOKENS = 4000` reserved half the budget
before any context. This also argues against reasoning models on a constrained
tier: they need a large reservation *and* spend most of it invisibly.

Groq's daily quota then failed to reset for several days, forcing a move to
Gemini.

**An accidental architectural property.** Three model families — `gpt-oss-120b`,
`llama-3.3-70b-versatile`, `gemini-3.1-flash-lite` — have run through the same
`ask()` with no changes to retrieval or chunking. The pipeline is model-agnostic
in practice. Not designed; forced by quota.

One seam it exposed: Gemini returns `response.content` as a list of content
blocks rather than a string. `response.text` flattens both forms.

## 17. KPI extraction

The evaluation question set turned out to be the extraction spec. *"What was
research and development expense in 2024?"* already returned $4,540M correctly —
that question **is** the R&D extractor. The harness that proved the system worked
became the thing that produces the product's data.

**One call per KPI, not one for eight.** A single retrieval biases the whole
context toward whatever was asked, so total assets would be extracted from chunks
selected for revenue. Merging eight retrievals blows the token budget. One
focused retrieval and one small call per metric keeps each context small and
makes a failure traceable to its own retrieval.

**Provenance.** Every extraction returns `source_quote` — the verbatim table row:

```
revenue   97,690   "Total revenues | $ 97,690 | $ 96,773 | $ 81,462 | $ 917 | 1 %"
```

Two returns. A free non-LLM correctness check — if the quote does not contain the
number, the extraction is wrong. And it made the next two bugs diagnosable.

**Two failures that looked identical and were not.**

`operating_cash_flow` returned null with a retrieval distance of 0.7722, the
*best* of all eight, and the answer at ranks 1 and 2. Perfect retrieval, failed
generation. The cause was in the prompt:

```
Metric: operating_cash_flow
```

A JSON key, not a financial term. Fixed with a separate `label` field carrying
the filing's own wording. **The identifier a data structure needs and the name a
model needs are different things.**

`net_income` returned null for an entirely different reason, visible only because
the error branch kept the raw response:

```json
"raw": "{\"value\": 7153, \"units\": \"millions USD\",
         \"source_quote\": \"Net income ... | \\$ 7,..."
"error": "unparseable JSON: Invalid \\escape"
```

The model extracted 7153 correctly with a verbatim quote. The quote contained
`\$` — Datalab escapes dollar signs — which is not a valid JSON escape, so
`json.loads` rejected the whole object. Correct retrieval, correct extraction,
correct instruction-following, discarded by the parser. The instruction to copy
verbatim is what carried the escape in.

**Rejecting a threshold.** Microsoft's `risk_factors` returned four *market risk*
categories because its filing has no Item 1A and retrieval returned the nearest
thing. Its distance was 1.4103, worst of all 24 by a clear margin.

The tempting fix was `DISTANCE_THRESHOLD = 1.30`. That is overfitting: one
observation, one constant, and distances shift with embedding model, query
phrasing and corpus size. Rejected in favour of a deterministic precondition —
does the filing contain the section at all. Free, exact, and it skips the call
entirely.

**Prefer checks that are true by definition over checks fitted to observations.**
The three that survived — the accounting identity (assets − liabilities =
equity), the section marker, and quote-contains-number — all hold on documents
not yet seen.

One subtlety: the marker is `"Item 1A"`, deliberately not `"Risk Factors"`.
Microsoft's report contains that phrase three times, all cross-references to a
10-K not in the document. A structural identifier and a phrase that occurs in
prose are not interchangeable.

**Result.** 18 of 18 numeric KPIs correct across three companies, units
normalised, balance sheet identity holding on all three, and `risk_factors`
correctly reporting absent where the section is not there.

## 18. The application layer

Built in an order deliberately opposite to how a user meets it: results page
first, then chat, then upload. Building upload first risks having nothing to
show; building results first always leaves something demonstrable.

**Client-side rendering.** `index.html` arrives with empty slots and JavaScript
fills them from `/api/*`. Forced by the chat panel, which must update without a
page reload — a server-rendered dashboard beside a client-rendered chat would
mean two mental models in one page.

**Derived metrics are pure arithmetic.** `app/metrics.py` takes a metrics dict
and returns ratios, with no web framework and no I/O, so it can be checked
against a known filing without starting a server. Same discipline that made the
chunker's bugs findable.

**Three frontend bugs worth recording.** Peer bars were invisible because the
track colour differed from the page by 1.16:1 and the fill was an accent at
`opacity: .32` — an accent blended into a pale ground reads as nothing. Darkening
the peer tone enough to clear the track pushed it to 1.02:1 against the accent,
identical in lightness, so value alone could not separate three things. Solved
with texture: peers hatched, the selected filing solid.

Risk factors rendered at double height because each `<li>` had a `::before`
bullet *and* an empty `<span>`, making three items in a two-column grid.

And the bars did not fill at all, because `.bar-fill` is a `<span>` — an inline
element, which ignores `width` and `height`. The track escaped this only by being
a grid item, which blockifies automatically.

**Import cost.** Before wiring the chat endpoint, importing `Rag.chatbot` was
measured at **231 seconds** — which would have been the server's startup time on
every reload. `langchain_openai` pulled in torch and transformers (58s) for a
Groq path that was already commented out, and `Rag.retrieval` reached the Chroma
client through `vector_store_v2`, which imports the chunker, which imports
`langchain_text_splitters`, which imports transformers again (101s).

Splitting the client handles into their own module and deleting one unused import
took it to **20.5 seconds**. Most of the cost was in something that was not being
used.

**Upload.** `POST /api/upload` starts a background thread and returns a job id;
`GET /api/progress/{id}` streams Server-Sent Events. Every stage already reports
something true — page counts, chunk counts, table counts — so nothing is
invented.

The pipeline hashes the PDF first, so re-uploading an ingested filing returns in
milliseconds. Identification runs immediately after conversion and gates
everything expensive: a document with no financial statements stops there, before
~1,200 embeddings and 8 LLM calls.

**Identification is deterministic.** Every SEC annual filing carries the same
cover-page markers, and the registrant's legal name is the last non-empty line
before `(Exact name of Registrant as specified in its charter)`. No model
involved.

But two signals are kept apart. A cover page allows automatic identification;
financial-statement markers say whether there is anything worth extracting.
Microsoft's annual report has the second and not the first — no cover page, yet
six of six financial metrics. Treating "not a 10-K" as "reject" would have
discarded a document that works, so a missing cover page asks who the filer is
rather than refusing.

That rule proved brittle once: a second conversion of the same PDF left a
dangling `**` on its own line above the marker, which stripped to an empty
string. Datalab is not byte-deterministic — the same filing converted to 487,751
characters once and 483,495 another time. Fixed by walking back to the first line
with real content.

**Containerisation.** The vector store is built during the image build, not
copied from the host and not built at container start. Building at start would
repeat ~25 minutes on every restart, and free hosts restart whenever they wake —
and it would need a persistent volume, which is the part of most free tiers that
costs money.

Build-time secrets are mounted per-step so no credential enters a layer. Only the
three keys the application uses are passed, out of eight in the local
environment.

Measured: 989 MB image, 455 MB resident at idle.

**Deployment is unresolved.** 455 MB does not fit the 512 MB free tiers that do
not require a credit card, and every option that does fit requires one. The image
is the deployment artefact and every host takes it unchanged, so this is a
blocked step rather than an unfinished one.

## 19. Where things stand

**Working end to end.** PDF → Datalab conversion → deterministic identification →
chunking with hierarchical headings and section-scoped caption pairing →
OpenRouter embeddings → ChromaDB with scoped idempotent writes → retrieval with
a table-guaranteed merge → Gemini. Plus KPI extraction with provenance, a
dashboard, a scoped chatbot, and an upload path with streamed progress. Packaged
as a single container that needs no external state.

**Verified.** 18/18 numeric KPIs correct across Apple, Microsoft and Tesla, each
traceable to a table row. Chunker invariants: zero content loss, zero
duplication, exact table preservation. The upload path proven on filings not in
the reference set.

**Open.**

- No public URL. Free tiers without a credit card cap at 512 MB; the container
  needs more.
- Microsoft's source document is an annual report, not a 10-K, so its Item 1A
  panel is correctly empty.
- The `operating_income` retrieval query was tuned on Tesla and verified on Apple
  and Microsoft. It has not met a filing outside that family.
- No test suite. The chunker invariants exist as a dry run rather than as
  `pytest` cases.
