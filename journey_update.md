# Journey — Rate limits, heading detection, and a bug found by following evidence

## Rate limit handling: two errors wearing the same costume

A Microsoft ingestion run produced 72 raw fallbacks in 30 minutes and converted
nothing. The handler caught `RateLimitError`, slept 5s, retried three times,
gave up, and moved to the next table — 72 times.

The error message had said `try again in 12m`.

Groq sends two different failures under one exception class:

- **TPM (tokens per minute)** — the pool refills every 60 seconds. Waiting and
  retrying is correct.
- **TPD (tokens per day)** — the daily pool is empty. Retrying is pointless, and
  it is pointless for *every remaining table*, not just this one.

The wait time is not only how long to sleep. It is the signal for which failure
this is.

### Two fixes, at two different levels

The distinction that took longest to see: these are separate mechanisms because
they live in different scopes.

**Inside `table_to_text`** — parse the server's own wait time out of the error
text and sleep for that duration. Above a 90-second threshold (the TPM window is
60s, so anything longer cannot be a per-minute refill), stop retrying and raise
`QuotaExhausted`.

**Inside `convert_table_chunks`** — catch `QuotaExhausted` and `break`. A
per-table handler can only fail one table; the daily quota is a property of the
*run*, so the signal has to escape the loop. Nothing inside `table_to_text` could
ever tell table 41 what table 40 had already learned.

### The caching danger this exposed

The original `__main__` wrote the cache and called `embed_and_store`
unconditionally. After an abort that would mean: cache written with 52
unconverted tables, ChromaDB filled with raw table syntax, and — worst — the next
run sees `cache_file.exists()` and skips conversion entirely. Broken data,
cached forever, silently.

Fix: pre-fill `conversion_status = "pending"`, write partial work to a
`.partial.json` under a *different* filename so `cache_file.exists()` stays
False, and `raise SystemExit` before embedding.

The separate filename matters more than the save. A partial cache can be deleted.
A partial ChromaDB collection looks fine and answers with wrong data.

**Proven live.** Microsoft table 21 hit TPM: `Limit 8000, Used 5431, Requested
4344 ... try again in 13.3125s`. The handler slept once for 14.3s and table 22
converted. Under the old code that would have been three failed backoffs and a
`raw_fallback`.

Note `Requested 4344` — that is the `max_tokens` reservation, the same squeeze
that caused the earlier empty conversions on Apple's wide tables.

**Still missing:** resume logic. The partial file is written but nothing reads
it. Deferred until just before a large multi-filing run.

---

## Heading detection: measured before building, twice

### The problem

pymupdf4llm identifies headings by **font size**. Microsoft marks its note
headings by *underlining* them at body text size. The signal pymupdf4llm looks
for is genuinely absent, so no amount of re-running or re-loading changes the
output — the conversion is deterministic.

Confirmed empirically: re-ran the loader (identical output), and tried
`hdr_info=TocHeaders(doc)` (errored — the PDF has no bookmarks). Both routes
ruled out by test, not by argument.

Missed headings do not vanish. The carry-forward logic hands the *previous*
section's heading to everything that follows, so content gets a wrong label.

### Measuring the blast radius before deciding

Wrote `heading_audit.py`: for each undetected heading, count how many following
chunks carry the now-stale label.

| Filing | Undetected headings | Chunks mislabeled | Tables affected |
|---|---|---|---|
| Apple | 0 | 0 | 0 |
| Tesla | 0 | 0 | 0 |
| Microsoft | 9 | 16 / 582 (2.7%) | 0 |

**2.7%, zero tables.** Much smaller than it felt while reading examples.

The damage is self-limiting: each miss corrupts only 1–3 chunks, because the next
correctly-detected heading resets the carried context. The blast radius of a
detection failure is bounded by the detection rate — containment that fell out of
the carry-forward design without being designed for.

### Two failure shapes, not one

- **Lost parent** — `## Effective Tax Rate` with no `INCOME TAXES` above it.
  Missing context. Mild.
- **Wrong parent** — Note 18's stock-compensation body inheriting
  `NOTE 17 — ACCUMULATED OTHER COMPREHENSIVE INCOME`. **False** context.

The second is the dangerous one, and the danger runs backwards from intuition.
Retrieval still works: query "stock compensation" and the body still matches. The
harm is at *generation* time, and on the *opposite* query — ask about accumulated
other comprehensive income and the LLM receives stock compensation text under
that heading, and will attribute it accordingly.

Body-driven queries are safe. Label-driven queries are not.

### The rule (PIPELINE_VERSION 6)

Accept `<u>...</u>` as a fallback heading marker. Reject `**...**` — bold
produced 17 false positives across Apple and Tesla, all cover-page form fields.
Require 3+ consecutive letters (kills bolded figures like `**$22,529**`) and no
trailing punctuation.

**9 true positives on Microsoft, 0 false positives across all three filings.**

Also added `clean_heading()`: strips the `<u>` tags so markup is not embedded as
tokens, and prefixes promoted headings with `##` so all heading context has one
shape regardless of which rule caught it.

### Result

Microsoft: 582 → 573 chunks (exactly the 9 promoted headings). Audit reports zero
undetected headings. Apple and Tesla unchanged at 316 and 343 — the rule provably
cannot affect them, so they were **not** re-ingested. The collection holds
Microsoft at v6 and Apple/Tesla at v5, with identical content.

In retrieval, the content-free `<u>NOTE 11 — DEBT</u>` chunk that had ranked
*first* is gone, and the stock-compensation chunk now correctly carries
`## NOTE 18 — EMPLOYEE STOCK AND SAVINGS PLANS`.

### Rejected: demoting units captions

pymupdf4llm marked `### **<u>(In millions, except lease term and discount
rate)</u>**` as a heading. It is a units note belonging to the table below it.

Measured: **1 chunk out of 582.**

Rejected. And demotion is a riskier operation than promotion — the `<u>` rule
only *adds* structure, while a demotion rule *removes* it. A false positive there
would delete a real section heading and create exactly the bug being fixed. Not
worth it for one chunk.

---

## The real bug, found by following evidence

The heading fix worked, and the query that motivated it still failed.

Asking "what does Note 10 cover" returned three chunks: a caption ("The
components of intangible assets... were as follows:"), a second caption, and a
footnote about Activision Blizzard. **The tables themselves never surfaced.** The
three tables that did arrive — 5-year return, segment revenue, server products —
were unrelated.

An answer built from that reads fluently and contains no data. That is the worst
failure mode for this project: a wrong number is obvious, a missing number is not.

### Two hypotheses, one script

Either the tables were missing from the collection, or they were present but
ranked too low. Completely different fixes, so worth ten minutes to find out
rather than guessing.

`find_table.py` searched the cache for "intangible" and printed each hit's
neighbours in document order:

```
[437] (prose)  ## NOTE 10 — INTANGIBLE ASSETS  The components of intangible assets...
[438] (table)  For the marketing-related intangible assets, the gross carrying
               amount was $16,500 million...
```

The tables are present, converted, and sitting correctly beside their captions.
So: a ranking problem, not a data problem.

### What the diagnostic actually revealed

The prose chunk carries `## NOTE 10 — INTANGIBLE ASSETS`. The table chunk carries
nothing. And every other table in the file starts the same way — straight into
converted sentences, no heading.

The cause is two lines in `convert_table_chunks`:

```python
text, status = table_to_text(chunk["text"])
chunk["text"] = text          # the whole chunk is replaced
```

`chunk_markdown` prepends heading context to tables as well as prose. The LLM
receives it, is instructed to rewrite the table's rows, and returns only that.
Overwriting `chunk["text"]` with the response **discards the heading**.

So the words "Note 10" exist in the prose chunks and nowhere in the table chunks.
The search found the prose and missed the tables, exactly as observed.

This affects **every table in all three filings** — roughly 190 chunks. Tables can
be found by their own wording, but never by section name.

### Fix (PIPELINE_VERSION 7)

Do not trust the LLM to preserve structural context. Keep it separately:

```python
"heading_context": context,        # stored at chunking time
...
chunk["text"] = "\n".join(p for p in (chunk["heading_context"], text) if p)
```

Worth a full three-filing re-ingestion, unlike the heading rule — this is every
table, and tables are where the financial figures live.

### The lesson

The heading work was a 2.7% problem that *felt* large because the examples were
vivid. The real defect was found only by writing a diagnostic to answer a
question the examples had raised, and reading its output carefully.

Measure before building. Then read the measurement for what it actually says,
not for what confirms the hypothesis you started with.
