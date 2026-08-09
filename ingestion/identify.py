
"""
Read the company and fiscal year off a 10-K cover page.

Every SEC annual filing has the same three markers near the top: a
"For the fiscal year ended ..." line, a Commission File Number, and the
registrant's legal name immediately above "(Exact name of Registrant as
specified in its charter)". That last one is the anchor — the company name is
the last non-empty line before it, on both Apple's and Tesla's filings despite
quite different cover layouts.

Failing to find them is informative rather than an error: a document without
these markers is not an SEC annual filing, so this doubles as the check that
stops a press release or an annual report being ingested as a 10-K.
"""

import re

# Trailing legal suffixes. Stripped so "Apple Inc." keys the same as the
# "Apple" already in the store. Lossy on purpose — the legal name is kept in
# `legal_name` if it is ever needed.
_SUFFIX = r"\s*,?\s*(inc|incorporated|corporation|corp|company|co|ltd|limited|plc|llc|n\.v|s\.a)\.?$"


# Generic line items any set of financial statements carries. Not 10-K
# structural markers — that is what has_cover_page is for.
_FINANCIAL_MARKERS = [
    "total revenue", "net income", "total assets", "total liabilities",
    "cash flow", "gross margin", "operating income", "net sales",
    "shareholders' equity", "stockholders' equity",
]

# Measured: Apple 8, Microsoft 8, Tesla 7; a design-system readme 0, this
# project's README 1. Four sits in a wide gap rather than on a boundary — but
# it is still a threshold fitted to five documents, so log the score alongside
# the verdict instead of only the yes/no.
_FINANCIAL_THRESHOLD = 4


def identify(markdown: str) -> dict:
    head = markdown[:6000]          # cover page; further in invites false hits
    low = markdown.lower()

    score = sum(1 for m in _FINANCIAL_MARKERS if m in low)

    year = None
    m = re.search(r"(?i)for the fiscal year ended[^\n|]*?(\d{4})", head)
    if m:
        year = int(m.group(1))

    company = legal = None
    m = re.search(r"(?i)\(?exact name of\s+registrant", head)
    if m:
        # Walk backwards to the first line that survives markdown stripping.
        # Datalab sometimes leaves a dangling '**' on its own line right above
        # the marker; taking the last line blindly yields "" for that filing.
        for raw in reversed([l.strip() for l in head[:m.start()].split("\n") if l.strip()]):
            candidate = re.sub(r"[*_#]", "", raw).strip()
            if re.search(r"[A-Za-z]{2,}", candidate):
                legal = candidate
                company = re.sub(_SUFFIX, "", legal, flags=re.I).strip().rstrip(",")
                break
    has_cover = bool(company and year)
    is_financial = score >= _FINANCIAL_THRESHOLD

    return {
        "company": company,
        "legal_name": legal,
        "year": year,
        "has_cover_page": has_cover,
        "financial_score": score,
        "is_financial": is_financial,
        "needs_input": is_financial and not has_cover,
    }