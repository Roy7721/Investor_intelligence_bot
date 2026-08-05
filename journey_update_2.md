# Journey — Changing the extractor, and rebuilding the chunker

Continues from `journey_update.md`, which ended with PIPELINE_VERSION 7 and a
units-fold fix planned for pymupdf4llm output. That fix was never written. This
is why.

---

## 12. The extractor trial

### The observation that started it

Reading back the open issues list, a pattern was visible: nearly every chunking
bug was a repair for damage done *upstream*.

- Rule B (the `<u>` heading fallback) existed because pymupdf4llm detects
  headings by font size, and Microsoft underlines its note headings at body
  text size.
- `re.sub("<br>", "", b)` existed because the converter leaked HTML.
- The planned units fold existed because `(In millions)` was being stranded on
  its own line and then eaten by boilerplate removal.
- Joined words — `Diluted earnings pershare`, `Operatinglease liabilities` —
  were text-extraction artifacts.

None of those are chunking problems. They are one tool's output being repaired
by rules written specifically for it. Worth testing whether a better extractor
removes the need for any of them.

### Trial design

Change exactly **one** variable: same `chunk_markdown()`, same audit scripts,
different markdown. Never call `convert_table_chunks()`, so the entire trial
costs **zero LLM quota** — the right shape of work while rationing a daily
free-tier limit.

### docling: three environment walls

1. `InvalidCxxCompiler: cl is not found` — `torch.compile` JITs the layout
   model to C++ and needs MSVC, which isn't on this machine. Fixed with
   `TORCHDYNAMO_DISABLE=1`, set before torch is imported.
2. `std::bad_alloc` on pages 13-61 — the default pipeline runs RapidOCR, which
   renders every page to a bitmap. These 10-Ks have a real text layer, so OCR
   was recovering text that was already there. `do_ocr = False`.
3. The parser itself could not read a 61-page filing.

The third was the interesting one:

| run | OCR | page_batch_size | pages asked | failed from |
|---|---|---|---|---|
| 1 | on | 4 | all 61 | page **13** |
| 2 | off | 1 | 1-15 | page **13** |

Between runs, OCR was removed and pages-in-flight cut 4 → 1. The failure
boundary moved **zero pages**. Page 13 itself is unremarkable — 2,879
characters, no images, no vector drawings.

A boundary indifferent to available memory is not exhaustion; it is a bound
inside the C++ parser, unreachable and unconfigurable from Python. Diagnosing
further would have been curiosity, not engineering — leak, fixed arena, or
internal limit all have the same remedy. Switched to `PyPdfiumDocumentBackend`
and the full document converted in 850s.

**Lesson: diagnose to the depth that changes what you do next, then stop.**

### docling won every count and failed the actual test

| | pymupdf4llm | docling |
|---|---|---|
| undetected headings (Rule A only) | **9** | **0** |
| `<u>` tags | 49 | 0 |
| `<br>` tags | 752 | 0 |
| units deleted by boilerplate | 14 | **0** |
| tables carrying their units | 54/72 | **64/72** |
| joined words | 2 | 0 |
| tables detected | 72 | 72 |
| characters | 184,491 | 226,263 |

On those numbers, Rule B, the `<br>` strip and the units fold all become
unnecessary. It looked settled.

Then a manual page-by-page audit against the PDF found **~19 defects**:

- **Missing column headers** in ~10 tables. A financial table without its year
  header is worse than useless — the bot cannot tell 2024 from 2023 and will
  answer confidently either way.
- **Content in the wrong section**: note 7 after note 8, note 11's debt tables
  inside note 10, all of note 15 absorbed into note 13.
- **Values displaced**: note 5's last table shifted upward.

**Every metric in that table counts artefacts, not correctness.** Tidy markdown
is not accurate markdown. No count could see a missing header row or a table
absorbed into its neighbour. This is the single most useful thing learned in
the trial.

### Testing the confound, and finding one in the incumbent

The backend swap was forced, and `docling-parse` exposes richer cell geometry
that TableFormer uses for cell matching — so the missing headers might have
been the handicap, not docling. Re-ran pages 37-43 (under the 12-page ceiling)
with `parsev4`:

```
pypdfium   | (In millions) |   | 2023 | 2022 |     <- 2024 header missing
parsev4    | (In millions) |   | 2023 | 2022 |     <- still missing
```

Hypothesis disproved for header rows. It *was* right about cell boundaries:

```
pypdfium   | Total | $  (1,646) $ | 788 | $  333 |   <- $ drifted one cell right
parsev4    | Total | $ (1,646)    | $ 788 | $ 333 |   <- correct
```

Then, checking the same table in the incumbent, PDF page 37 reads
`Year Ended June 30, 2024 2023 2022`, and pymupdf4llm produced:

```
|**Year Ended June 30,**|**2024**|**2023**|
|Interest and dividends income|**$**<br>**3,157**|$    2,994|
```

**The entire 2022 column was missing — data, not a label.** It had been in the
pipeline for weeks, in the cache, unnoticed.

docling had been audited page by page. pymupdf4llm never had. Comparing an
audited challenger against an unaudited incumbent always favours the incumbent,
because only one side's defects have been counted.

### LlamaParse: rejected

Headers all present. Rows not aligned to them, and **not aligned to each
other**:

```
|                               |         | 2024    |         | 2023    |   | 2022    |
| Interest and dividends income | $ 3,157 | $ 2,994 | $ 2,094 |         |   |         |
| Interest expense              |         | (2,935) |         | (1,968) |   | (2,063) |
```

`Interest expense` matches the header. The row above it doesn't. Read
positionally, interest and dividends income for 2024 comes out as **$2,994**;
the true figure is $3,157. Note 6 had three rows with three different offsets.

A missing header is uniformly missing — you know you don't know. Per-row
offsets are silently wrong for *some* rows with nothing in the output to say
which. No downstream rule can repair it.

### Datalab (Marker API): selected

Full 61-page filing in **22.4 seconds**, against docling's 850.

```
| Year Ended June 30,                          | 2024     | 2023     | 2022     |
| Interest and dividends income                | $ 3,157  | $ 2,994  | $ 2,094  |
```

Header present, all three year columns, rows aligned, digits exact. First
extractor to get this table completely right.

### The deciding argument was recoverability, not score

| extractor | defect | recoverable? |
|---|---|---|
| **Datalab** | units detached above table | **yes — fixable downstream** |
| docling | `2024` header label missing | by inference (statements run newest-first) |
| pymupdf4llm | entire 2022 column dropped | **no** — the data isn't in the file |
| LlamaParse | inconsistent per-row column offsets | **no** — silently wrong, undetectable |

Not "which scores best" but "whose failures can I engineer around". Datalab's
one structural defect had a fix already designed for a different tool.

Regression check on the other two filings: Apple and Tesla both converted in
~22s. Apple needed 54 boilerplate blocks removed under pymupdf4llm and only 5
under Datalab — the extractor strips page furniture itself. Apple folds units
*into* the heading (`#### CONSOLIDATED STATEMENTS OF CASH FLOWS (In millions)`),
which the heading carry-forward then propagates for free. Tesla has zero
standalone units blocks. The units problem turned out to be Microsoft-specific,
not a general behaviour.

### The cost, recorded deliberately

Datalab is a cloud API. Ingestion now needs a key, a network call and a
per-page cost, and the PDF is uploaded to a third party. Acceptable for public
SEC filings, but it breaks the "local and free-tier" half of the original
constraint, and that is an architectural commitment worth stating rather than
drifting into.

Offsetting it: 22 seconds per filing means re-ingesting after a chunker change
stops being a coffee break, which changes how freely the pipeline can be
iterated.

---

## 13. Chunking v5 — rebuild

### Heading context became hierarchical

v4 kept a flat context: every new heading replaced the previous one wholesale,
regardless of level. A `####` obliterated the `##` above it. That is why
`NOTE 6 — INVENTORIES` chunks were labelled `Fair Values of Derivative
Instruments`.

Datalab's headings go six levels deep with the mass at 3-5, and the levels are
derived from layout analysis rather than font-size guessing — trustworthy
enough to build on. Replaced the flat model with a level stack: a heading at
level N clears every deeper slot and occupies slot N; context is the slots
joined in order.

```
# PART II
## Item 8. Financial Statements and Supplementary Data
### Notes to Consolidated Financial Statements
#### Note 4 — Financial Instruments
##### **Accounts Receivable**
###### *Trade Receivables*
```

Under the flat model that chunk carried only `###### *Trade Receivables*`.

Measured before deciding whether to cap the depth: median context 118-142
characters against 500-character chunks, max 264. About a quarter overhead —
no cap needed. The `previous_was_heading` accumulation flag disappeared
entirely; the stack handles consecutive headings for free.

### table-to-text was dropped

The step existed for **retrieval**, not generation — a bare grid of numbers
embeds poorly against a natural-language question. Two things changed that:

1. Table chunks now carry 118-264 characters of heading path plus a caption
   sentence. The pipes no longer dominate the embedding.
2. `retrieve_chunks()` already runs a second table-filtered query and merges
   it, guaranteeing tables reach the LLM regardless of rank. That is a
   retrieval-side fix for the same problem — keeping both solves it twice.

What dropping it buys:

- **Iteration becomes free.** Chunking is pure text processing; change the
  chunker, re-run, instant, zero quota. Previously every tweak cost ~100 LLM
  calls per filing.
- **One less lossy step over financial data.** `raw_fallback` existed as a
  status *because* the rewrite could fail. Raw tables preserve digits exactly.
- **Two open issues close for free** — resume-from-partial and the mass-
  `raw_fallback` guard existed only to survive the conversion loop.

To be validated by measurement, not assumed: build the store with raw tables
and check whether the correct table is retrieved for known questions.

### The units fix turned out to be a guard, not a new stage

Datalab strands `(In millions)` as its own block above 33 Microsoft tables. 29
of them are identical, so `remove_repeating_boilerplate` deleted them — the
same factor-of-10⁶ bug as before, triggered harder than by pymupdf4llm.

First attempt was positional: don't drop a repeated block if a table follows
within N blocks. It has no workable setting. At N=1 it missed units separated
from their table by a period label (`Year Ended June 30, 2024`). At N=3 it
spared **every** footer in the financial statements and disabled the function
entirely — 0 blocks dropped across all three filings.

Replaced with an explicit exemption: a repeated block matching `UNITS_RE` is
never dropped. Precise instead of positional. Result: 5 genuine footers dropped
per filing, zero units lines lost.

No separate fold stage was needed. Caption pairing already absorbs the block
before a table; the units line only failed to reach it because boilerplate
removal deleted it first.

### Two bugs that looked correct on the page

**`for j in range(i-1, i-3):`** — ranges count upward, so this is always empty.
The caption loop never executed and no table got a caption at all. Verified
by measurement: `with caption 0` on all three filings, units coverage collapsed
from 67/73 to 34/73.

**The `consumed` set had never prevented anything** — and this one was
inherited from v4, so it had been in the pipeline for weeks.

The loop iterated forward. A caption sits at index `i-1`, its table at `i`. So
`i-1` was reached first, wasn't in `consumed` yet, and was emitted as a prose
chunk. The table then added it to `consumed` — too late.

```
Apple: captions ALSO emitted as a standalone prose chunk: 37/37
MSFT : captions ALSO emitted as a standalone prose chunk: 66/66
       -> consumed set prevented emission in 0 cases
```

Every caption was stored twice. v4's comment read
`# prose blocks already used as a table's caption`, describing an intent the
code never carried out.

Fix: split decision from emission. Pass 1 assigns captions and fills
`consumed` with no output; pass 2 emits. Chunk counts fell from 319/346/592 to
**252/268/462** — that drop is the duplicates disappearing.

### Validation became a permanent harness

Both of those bugs produced *plausible* output and were caught only by
measuring. The checks that found them belong in the code, not in scratch
scripts:

| invariant | why it exists |
|---|---|
| chunk schemas uniform | caught a `{...}` placeholder that made table chunks `set` objects, and a missing `conversion_status` |
| no block emitted twice | caught the `consumed` no-op |
| no block lost | the baseline safety property |
| table rows in == out | proves no table was split or truncated |

Final state across all three filings: zero leaked duplicates, zero lost blocks,
table rows preserved exactly (624→624, 920→920, 792→792), one chunk schema,
no empty-body chunks.

**A validation that only checks for loss is half a validation.** The first pass
reported `content lost: 0` and was read as "the pipeline is fine" — while every
caption was being duplicated. Both directions need a test.

---

## 14. Where things stand

**Done**
- Extractor decided and documented: Datalab, with the reasoning and the
  rejected alternatives recorded
- All three filings converted (~22s each)
- `chunking_v5` — hierarchical headings, units-safe boilerplate removal,
  two-pass caption assignment, no LLM dependency, validated
- `config/` replaces `confiq/`; `PIPELINE_VERSION` and `COLLECTION_NAME` each
  declared once
- Five extractor-independent bugs fixed (commit `0a240a2`)

**Immediately next**
- `Rag/retrieval.py` still imports `vector_store.vector_store` (v1), which
  imports the deleted `confiq` — nothing in the RAG path runs until that points
  at `vector_store_v2`
- Retire `vector_store.py` and `chunking_v4.py`; both are unrunnable and only
  serve to drag the dead chain back in
- Wipe the collection and re-ingest all three filings — it still holds 659
  chunks built from pymupdf4llm markdown by the v1 pipeline
- `pip install -r requirements.lock.txt` — the docling trial left torch and
  transformers in the venv, and `langchain_text_splitters` now takes 97 seconds
  to import

**Then**
- Retrieval evaluation on known-answer questions, to decide empirically whether
  dropping table-to-text hurt
- Not started: KPI extraction, dashboard, FastAPI layer, deployment

**Open, non-blocking**
- Cover-page junk (`Yes ☐ No ☒`, `(Zip Code)`) becomes content-free chunks
- `config.py` builds `ChatOpenAI` and `OpenAI` clients at import, so pure-text
  scripts need a network stack
- Three journey supplements now exist unmerged: `journey_sections_6_to_11.md`,
  `journey_update.md`, and this file
