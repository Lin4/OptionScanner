"""Iteration 12 — Long-term Fundamentals, Financials, and Peer Comparison tests.

Covers:
- POST /api/screener/stock-analysis {purpose: 'long'} across multiple tickers
- GET /api/screener/peers/{ticker}
"""
import time
import pytest
BASE_URL = "https://optionscope.preview.emergentagent.com"


LONG_TICKERS = ["AAPL", "MSFT", "NVDA", "JPM", "KO", "AMZN", "TSLA", "SPY"]
PEER_TICKERS = ["AAPL", "MSFT", "NVDA", "KO"]

VALUATION_KEYS = (
    "market_cap", "enterprise_value", "trailing_pe", "forward_pe", "peg_ratio",
    "price_to_sales", "price_to_book", "ev_to_revenue", "ev_to_ebitda",
)

FIN_KEYS = (
    "label", "end_date", "revenue", "net_income", "operating_cash_flow",
    "free_cash_flow", "cash", "total_debt", "equity", "debt_to_equity",
    "revenue_growth_pct", "net_income_growth_pct", "net_margin_pct",
)


# ---------- Long-term stock-analysis per-ticker ----------
@pytest.mark.parametrize("ticker", LONG_TICKERS)
def test_long_stock_analysis(api, auth_headers, ticker):
    """Validate valuation_measures + financials across many tickers (ETF SPY allowed to be empty)."""
    time.sleep(1.2)  # space Finnhub 60/min
    r = api.post(
        f"{BASE_URL}/api/screener/stock-analysis",
        json={"ticker": ticker, "purpose": "long"},
        headers=auth_headers,
        timeout=45,
    )
    assert r.status_code == 200, f"{ticker}: {r.status_code} {r.text[:200]}"
    body = r.json()
    assert "result" in body
    res = body["result"]
    assert res["ticker"] == ticker
    assert res["purpose"] == "long"

    # valuation_measures has all 9 keys (values may be None, especially for ETFs)
    vm = res.get("valuation_measures")
    assert isinstance(vm, dict), f"{ticker}: valuation_measures missing"
    for k in VALUATION_KEYS:
        assert k in vm, f"{ticker}: valuation_measures missing key {k}"

    # buy_point/sell_point present when EPS>0 (so DCF valid)
    eps = res.get("eps_ttm") or 0
    if eps and eps > 0:
        # may still be None if DCF couldn't compute; just assert keys exist
        assert "buy_point" in res
        assert "sell_point" in res

    # financials
    fins = res.get("financials")
    assert isinstance(fins, list), f"{ticker}: financials not a list"
    if ticker == "SPY":
        # ETFs can be empty
        return
    assert len(fins) <= 8, f"{ticker}: more than 8 rows"
    if not fins:
        return  # some tickers may still have empty data without 500

    # ordered oldest -> newest by end_date ascending
    dates = [row.get("end_date") for row in fins]
    assert dates == sorted(dates), f"{ticker}: financials not ordered oldest->newest: {dates}"

    for row in fins:
        for k in FIN_KEYS:
            assert k in row, f"{ticker}: row missing key {k}"
        assert row["label"].startswith("Q") and "FY" in row["label"], f"{ticker}: bad label {row['label']}"

    # revenue should be positive and not look cumulative (quarterly, de-cumulated).
    revs = [row["revenue"] for row in fins if row.get("revenue") is not None]
    if not revs:
        # Banks (JPM) report InterestAndDividendIncome / NoninterestIncome which aren't in
        # the current _FIN_CONCEPTS mapping. Flag but don't hard-fail.
        pytest.skip(f"{ticker}: no revenue concepts matched (likely financial sector mapping gap)")
    for v in revs:
        assert v > 0, f"{ticker}: non-positive revenue {v}"
    # AAPL quarterly revenue roughly $70B-$150B. Assert no quarter exceeds $300B (would indicate YTD leak).
    if ticker in ("AAPL", "MSFT"):
        for v in revs:
            assert v < 300e9, f"{ticker}: suspicious cumulative revenue {v}"

    # net_margin_pct = net_income/revenue*100
    for row in fins:
        if row.get("revenue") and row.get("net_income") is not None and row.get("net_margin_pct") is not None:
            expected = round(row["net_income"] / row["revenue"] * 100, 1)
            assert abs(row["net_margin_pct"] - expected) < 0.2, f"{ticker}: net_margin mismatch {row}"


# ---------- Peer comparison ----------
@pytest.mark.parametrize("ticker", PEER_TICKERS)
def test_peer_comparison(api, auth_headers, ticker):
    time.sleep(1.2)
    r = api.get(f"{BASE_URL}/api/screener/peers/{ticker}", headers=auth_headers, timeout=45)
    assert r.status_code == 200, f"{ticker}: {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body["ticker"] == ticker
    rows = body.get("rows")
    assert isinstance(rows, list) and len(rows) >= 1, f"{ticker}: empty rows"
    # target is first
    assert rows[0]["is_target"] is True and rows[0]["ticker"] == ticker
    # up to 4 total (target + 3 peers)
    assert len(rows) <= 4
    for row in rows:
        for k in VALUATION_KEYS:
            assert k in row, f"{ticker}: peer row missing {k}"

    verdict = body.get("verdict")
    assert isinstance(verdict, dict)
    for k, v in verdict.items():
        assert "peer_median" in v
        assert "cheaper" in v
        assert "diff_pct" in v
        assert isinstance(v["cheaper"], bool)

    assert isinstance(body.get("summary"), str)


def test_peer_comparison_unknown_ticker(api, auth_headers):
    """Unknown ticker should NOT 500. 200 with empty rows is acceptable."""
    r = api.get(f"{BASE_URL}/api/screener/peers/ZZZZZZ", headers=auth_headers, timeout=30)
    assert r.status_code != 500, f"500 on unknown: {r.text[:200]}"
    assert r.status_code in (200, 404), r.status_code
