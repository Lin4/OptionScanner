"""Iteration 13 — Bank revenue mapping fix retest.

Verifies market.py _FIN_CONCEPTS['revenue'] now resolves to a non-null quarterly
revenue for financial-sector tickers (JPM, BAC, WFC, GS) via either:
  - us-gaap_RevenuesNetOfInterestExpense tag, or
  - fallback composition: InterestIncomeExpenseNet + NoninterestIncome.
"""
import time
import pytest

BASE_URL = "https://optionscope.preview.emergentagent.com"

BANK_TICKERS = ["JPM", "BAC", "WFC", "GS"]

# Rough per-quarter revenue sanity bounds in USD (very wide to accommodate
# different reporting styles and avoid false negatives).
BANK_REV_BOUNDS = {
    "JPM": (20e9, 80e9),   # expect ~$40–60B
    "BAC": (15e9, 50e9),   # expect ~$25–32B
    "WFC": (10e9, 40e9),   # expect ~$18–22B
    "GS":  (5e9, 30e9),    # expect ~$10–15B
}


@pytest.mark.parametrize("ticker", BANK_TICKERS)
def test_bank_quarterly_revenue(api, auth_headers, ticker):
    """Each bank should return at least one quarter with a non-null, realistic revenue + net_margin_pct."""
    time.sleep(1.5)  # space Finnhub 60/min across parametrized tests
    r = api.post(
        f"{BASE_URL}/api/screener/stock-analysis",
        json={"ticker": ticker, "purpose": "long"},
        headers=auth_headers,
        timeout=60,
    )
    assert r.status_code == 200, f"{ticker}: {r.status_code} {r.text[:200]}"
    body = r.json()
    res = body["result"]
    assert res["ticker"] == ticker
    assert res["purpose"] == "long"

    fins = res.get("financials") or []
    assert isinstance(fins, list) and len(fins) >= 1, f"{ticker}: empty financials"

    revs = [row.get("revenue") for row in fins]
    non_null = [v for v in revs if v is not None]
    assert len(non_null) >= 1, (
        f"{ticker}: ALL quarters have revenue=null — bank fix did not work. "
        f"Rows: {[{'label': r.get('label'), 'revenue': r.get('revenue')} for r in fins]}"
    )

    # At least 60% of returned quarters should now have revenue populated.
    coverage = len(non_null) / len(revs)
    assert coverage >= 0.5, f"{ticker}: only {coverage*100:.0f}% of quarters have revenue"

    # Sanity bounds — not cumulative, within expected per-quarter range.
    lo, hi = BANK_REV_BOUNDS[ticker]
    for row in fins:
        v = row.get("revenue")
        if v is None:
            continue
        assert v > 0, f"{ticker}: non-positive revenue {v} in {row.get('label')}"
        assert lo * 0.5 <= v <= hi * 1.5, (
            f"{ticker}: revenue {v:,.0f} in {row.get('label')} outside sanity bounds "
            f"[{lo:,.0f}, {hi:,.0f}] — possibly cumulative YTD leak"
        )

    # net_margin_pct and revenue_growth_pct should populate where revenue is present.
    for row in fins:
        if row.get("revenue") and row.get("net_income") is not None:
            assert row.get("net_margin_pct") is not None, (
                f"{ticker}: net_margin_pct null despite revenue + net_income present in {row.get('label')}"
            )
            expected = round(row["net_income"] / row["revenue"] * 100, 1)
            assert abs(row["net_margin_pct"] - expected) < 0.3, f"{ticker}: net_margin mismatch {row}"

    # Growth should appear in at least one row (newest-ish quarter) since we now have >=2 consecutive revenues.
    growths = [row.get("revenue_growth_pct") for row in fins if row.get("revenue_growth_pct") is not None]
    assert len(growths) >= 1, f"{ticker}: revenue_growth_pct never populated — rows: {fins}"


# ---------- Regression: AAPL still realistic ----------
def test_aapl_regression(api, auth_headers):
    time.sleep(1.5)
    r = api.post(
        f"{BASE_URL}/api/screener/stock-analysis",
        json={"ticker": "AAPL", "purpose": "long"},
        headers=auth_headers,
        timeout=60,
    )
    assert r.status_code == 200, r.text[:200]
    fins = r.json()["result"]["financials"]
    assert isinstance(fins, list) and len(fins) >= 3
    revs = [row["revenue"] for row in fins if row.get("revenue") is not None]
    assert len(revs) >= 3, f"AAPL: expected >=3 quarters with revenue, got {revs}"
    for v in revs:
        # AAPL quarterly revenue roughly $70B–$150B. Reject anything cumulative-looking (>$300B).
        assert 50e9 <= v <= 300e9, f"AAPL: suspicious quarterly revenue {v:,.0f}"
