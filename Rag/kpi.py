from config.config import LLM_MODEL, COLLECTION_NAME, ROOT
from Rag.retrieval import retrieve_chunks, build_context,_client, _embedder
import re, json






KPIS = [
    {"key": "revenue",            "kind": "money", "label": "Total revenues", "question": "What were total revenues in {year}?"},
    {"key": "net_income",         "kind": "money", "label": "   ", "question": "What was net income in {year}?"},
    {"key": "operating_income",   "kind": "money",  "label": "Income from operations (operating income)","question": "What was operating income in {year}?"},
    {"key": "operating_cash_flow","kind": "money",  "label": "Net cash provided by operating activities","question": "What was net cash provided by operating activities in {year}?"},
    {"key": "total_assets",       "kind": "money",  "label": "Total assets","question": "What were total assets at the end of {year}?"},
    {"key": "total_liabilities",  "kind": "money",  "label": "Total liabilities","question": "What were total liabilities at the end of {year}?"},
    # requires_section is "Item 1A", NOT "Risk Factors". The phrase "Risk Factors"
    # appears in Microsoft's annual report three times — all cross-references
    # ("refer to Risk Factors in our fiscal year 2024 Form 10-K"). Matching on it
    # would report the section present and let the model substitute market-risk
    # categories, which is the exact failure this check exists to stop. "Item 1A"
    # is a structural identifier; "Risk Factors" is a phrase that occurs in prose.
    {"key": "risk_factors",       "kind": "list",   "label": "Principal risk factors from Item 1A",
     "requires_section": "Item 1A",
     "guidance": "Return individual risk factors, each a full sentence describing one specific "
                 "risk. Do NOT return section or category headings such as 'Business Risks' or "
                 "'Macroeconomic and Industry Risks' — return the risks listed under them.",
     "question": "What are the principal risk factors described in Item 1A?"},
    {"key": "growth_drivers",     "kind": "list",   "label": "Stated drivers of revenue growth",
     "guidance": "Return specific named drivers — products, segments or services the filing "
                 "credits for growth. Do not return strategic intentions.",
     "question": "What drove revenue growth in {year}?"},
]



EXTRACTION_PROMPT = """You are a financial analyst extracting one value from a filing.

Company: {company}
Fiscal year: {year}
Metric: {label}
Expected value type: {kind}
{guidance}

Context:
{context}

Return JSON only, exactly these keys:
{{"value": <number or list of strings or null>,
  "units": "<e.g. millions USD, or null>",
  "source_quote": "<the sentence or table row the value came from, verbatim>"}}

Rules:
- Use only the context above. If the metric is not present, set value to null.
- Numbers must match the filing exactly. Do not convert or round.
- "units" must be exactly one of: "millions USD", "billions USD", "USD", or null.
  Do not invent other wordings — these values are compared across companies.
- source_quote must be copied verbatim, never paraphrased.
- Output JSON and nothing else.
"""

RESULT_SCHEMA = {"value": None, "units": None, "source_quote": None,
                 "error": None, "absent": None}


def _parse_json(text: str) -> dict:
    """
    Parse the model's reply into the fixed RESULT_SCHEMA shape.

    Two things go wrong without normalising here. Models wrap JSON in ``` fences.
    And source_quote is copied verbatim as instructed, so it can carry markdown
    escapes like \\$ — not a valid JSON escape, which threw away an otherwise
    perfect extraction of net_income (7153, correct units, correct quote).

    Returning a fixed shape also means every cached metric has identical keys,
    so the dashboard never has to guess which branch produced a dict.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    cleaned = re.sub(r'\\(?!["\\/bfnrtu])', "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {**RESULT_SCHEMA, "error": f"unparseable JSON: {e}", "raw": text[:200]}
    if not isinstance(parsed, dict):
        return {**RESULT_SCHEMA, "error": f"expected object, got {type(parsed).__name__}",
                "raw": text[:200]}
    return {**RESULT_SCHEMA,
            **{k: parsed.get(k) for k in ("value", "units", "source_quote")}}

def section_present(company: str, year: int, marker: str) -> bool:
    """Does this filing contain the section at all? Deterministic — no model,
    no threshold. A filing either has 'Item 1A' in its text or it doesn't."""

    collection = _client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=_embedder,
        )
    
    got = collection.get(
        where={"$and": [{"source_company": {"$eq": company}},
                        {"filing_year": {"$eq": year}}]},
        include=["documents"],
    )
    return any(marker.lower() in d.lower() for d in got["documents"])


def extract_kpi(company: str, year: int, spec: dict, debug: bool = False) -> dict:
    
    marker = spec.get("requires_section")
    if marker and not section_present(company, year, marker):
        if debug:
            print(f"  [{spec['key']}] skipped — {marker} not in filing")
        return {**RESULT_SCHEMA, "absent": f"{marker} not present in this filing"}
    
    question = spec["question"].format(year=year)
    retrieved = retrieve_chunks(question=question, source_company=company, filing_year=year)
    if not retrieved:
        return {**RESULT_SCHEMA, "error": f"no chunks for {company} {year}"}

    if debug:
        print(f"  [{spec['key']}] {len(retrieved)} chunks, best {retrieved[0]['distance']:.4f}")

    prompt = EXTRACTION_PROMPT.format(
        company=company, year=year, label=spec["label"],
        context=build_context(retrieved), kind=spec["kind"],
        guidance=spec.get("guidance", ""),
    )


    return _parse_json(LLM_MODEL.invoke([{"role": "user", "content": prompt}]).text)


def extract_kpis(company: str, year: int, debug: bool = False, refresh: bool = False) -> dict:
    cache = ROOT / "data" / "kpi" / f"{company}_{year}.json"
    if cache.exists() and not refresh:
        print(f"cached: {cache.name}")
        return json.loads(cache.read_text(encoding="utf-8"))

    result = {
        "company": company,
        "year": year,
        "metrics": {s["key"]: extract_kpi(company, year, s, debug) for s in KPIS}}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

def looks_wrong(m):
    v, q = m.get("value"), m.get("source_quote") or ""
    v = int(v) if isinstance(v, float) and v.is_integer() else v
    return v is not None and isinstance(v, (int, float)) and f"{v:,}" not in q

def check_balance_sheet(metrics: dict) -> str | None:
    """assets - liabilities should be a plausible equity figure. Cheap arithmetic
    catches what no single-value check can: two figures that are individually
    believable but inconsistent with each other."""
    a = (metrics.get("total_assets") or {}).get("value")
    l = (metrics.get("total_liabilities") or {}).get("value")
    if not isinstance(a, (int, float)) or not isinstance(l, (int, float)):
        return None
    equity = a - l
    if equity <= 0:
        return f"implied equity {equity:,.0f} is not positive"
    if equity > a:
        return f"implied equity {equity:,.0f} exceeds total assets"
    return None

if __name__ == "__main__":
    for company in ("Tesla", "Microsoft", "Apple"):
        result = extract_kpis(company, 2024, debug=True, refresh=True)
        print(f"\n=== {company} 2024")
        for key, m in result["metrics"].items():
            flags = []
            if looks_wrong(m):   flags.append("QUOTE-MISMATCH")
            if m.get("absent"):  flags.append("SECTION-ABSENT")
            if m.get("error"):   flags.append("PARSE-ERROR")
            print(f"  {key:<22} {str(m.get('value'))[:40]:<42} "
                  f"{m.get('units') or '':<14} {' '.join(flags)}")
        print(f"  balance check: {check_balance_sheet(result['metrics']) or 'OK'}")