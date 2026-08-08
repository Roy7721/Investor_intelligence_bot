
"""
Derived financial ratios.

Pure arithmetic over the six extracted figures — no LLM, no retrieval, no I/O.
Deliberately separate from the web layer so it can be checked against a known
filing without starting a server.

Every ratio returns None when an input is missing rather than raising. A filing
may legitimately lack a metric, and a missing ratio should render as a blank
card, not a 500.
"""


def _value(metrics: dict, key: str) -> float | None:
    """Pull the numeric value out of a metric entry, or None if there isn't one.

    Guards against three cases at once: the key is absent, the entry exists but
    value is null (SECTION-ABSENT), or value is a list (risk_factors).
    """
    v = (metrics.get(key) or {}).get("value")
    return float(v) if isinstance(v, (int, float)) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def derive(metrics: dict) -> dict:
    revenue     = _value(metrics, "revenue")
    net_income  = _value(metrics, "net_income")
    op_income   = _value(metrics, "operating_income")
    op_cash     = _value(metrics, "operating_cash_flow")
    assets      = _value(metrics, "total_assets")
    liabilities = _value(metrics, "total_liabilities")

    equity = assets - liabilities if assets is not None and liabilities is not None else None

    return {
        "operating_margin": _ratio(op_income, revenue),
        "net_margin":       _ratio(net_income, revenue),
        "implied_equity":   equity,
        "return_on_equity": _ratio(net_income, equity),
        "return_on_assets": _ratio(net_income, assets),
        "cash_conversion":  _ratio(op_cash, net_income),
    }


if __name__ == "__main__":
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / "data" / "kpi").glob("*.json")):
        filing = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n{filing['company']} {filing['year']}")
        for name, value in derive(filing["metrics"]).items():
            if value is None:
                print(f"  {name:<18} —")
            elif name == "implied_equity":
                print(f"  {name:<18} {value:>12,.0f}")
            else:
                print(f"  {name:<18} {value:>12.4f}")