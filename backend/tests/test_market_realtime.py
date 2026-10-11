"""Tests for real-time market data integration (Finnhub + Polygon + Alpha Vantage).

Covers screener endpoints that must now return LIVE prices (no mock constants).
"""
import time
import pytest

# ------- MOCK CONSTANTS we must NOT see (old stale values from mock mode) -------
STALE_MOCK_PRICES = {232.14, 428.90}


# =====================================================================
# /api/screener/quote/{ticker}
# =====================================================================
class TestLiveQuote:
    def test_quote_requires_auth(self, api, base_url):
        r = api.get(f"{base_url}/api/screener/quote/AAPL", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"

    def test_quote_aapl_shape(self, api, base_url, auth_headers):
        r = api.get(f"{base_url}/api/screener/quote/AAPL", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("price", "change", "change_pct", "high", "low", "open", "prev_close"):
            assert k in d, f"missing key {k} in {d}"
        assert d["price"] > 0, f"price must be > 0, got {d['price']}"
        assert d["price"] not in STALE_MOCK_PRICES, f"stale mock price returned: {d['price']}"
        assert d["ticker"] == "AAPL"
        assert "_id" not in d

    def test_quote_404_for_unknown_ticker(self, api, base_url, auth_headers):
        r = api.get(f"{base_url}/api/screener/quote/ZZZZZZZZ", headers=auth_headers, timeout=20)
        assert r.status_code == 404, f"expected 404 for unknown ticker, got {r.status_code} / {r.text[:200]}"

    def test_quote_caching_same_price(self, api, base_url, auth_headers):
        r1 = api.get(f"{base_url}/api/screener/quote/AAPL", headers=auth_headers, timeout=20)
        r2 = api.get(f"{base_url}/api/screener/quote/AAPL", headers=auth_headers, timeout=20)
        assert r1.status_code == 200 and r2.status_code == 200
        # TTL cache 30s -> same price
        assert r1.json()["price"] == r2.json()["price"], "cache not working: prices differ"


# =====================================================================
# /api/screener/best-options
# =====================================================================
class TestBestOptions:
    def test_requires_auth(self, api, base_url):
        r = api.post(f"{base_url}/api/screener/best-options", json={"period": "week", "limit": 3}, timeout=15)
        assert r.status_code == 401

    def test_best_options_real_prices(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/best-options",
            json={"period": "week", "limit": 3},
            headers=auth_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "results" in body
        results = body["results"]
        assert len(results) <= 3
        assert len(results) >= 1, "no results returned"
        for item in results:
            assert item["price"] > 0
            assert item["price"] not in STALE_MOCK_PRICES, f"stale mock price in result: {item['ticker']}={item['price']}"
            for k in ("ticker", "strategy", "legs", "premium", "pop", "annual_pct_no_margin", "sparkline"):
                assert k in item, f"missing key {k}"
            assert isinstance(item["legs"], list) and len(item["legs"]) >= 1
            assert isinstance(item["sparkline"], list)
            if item["sparkline"]:
                # sparkline values should be roughly in the price ballpark (within 50%)
                price = item["price"]
                for v in item["sparkline"]:
                    assert 0.3 * price <= v <= 3.0 * price, f"sparkline value {v} far from price {price}"
            assert "_id" not in item


# =====================================================================
# /api/screener/find-stocks
# =====================================================================
class TestFindStocks:
    def test_find_stocks_tech_sector(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/find-stocks",
            json={"risk": "high", "reward": "high", "expiration": "week", "sectors": ["Tech"], "limit": 3},
            headers=auth_headers,
            timeout=90,
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert len(results) >= 1
        tech_tickers = {"AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMD"}
        for item in results:
            assert item["ticker"] in tech_tickers, f"non-tech ticker in Tech-filtered result: {item['ticker']}"
            assert item["price"] > 0
            assert item["price"] not in STALE_MOCK_PRICES
            assert "bias" in item
            assert "rationale" in item
            assert isinstance(item["rationale"], str) and len(item["rationale"]) > 0


# =====================================================================
# /api/screener/ticker-options
# =====================================================================
class TestTickerOptions:
    def test_ticker_options_aapl(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/ticker-options",
            json={"ticker": "AAPL", "expiration_range": "month"},
            headers=auth_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert res["price"] > 0
        assert res["price"] not in STALE_MOCK_PRICES
        assert res["strategy"] in {"Cash Secured Put", "Covered Call", "Bull Put Spread", "Iron Condor", "Bear Call Spread", "Short Strangle"}
        for k in ("ai_summary", "risk_note", "entry_tip"):
            assert k in res and isinstance(res[k], str) and len(res[k]) > 0

    def test_ticker_options_unknown_ticker_404(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/ticker-options",
            json={"ticker": "ZZZZZZZZ", "expiration_range": "month"},
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} / {r.text[:200]}"


# =====================================================================
# /api/screener/stock-analysis — swing (TSLA)
# =====================================================================
class TestStockAnalysisSwing:
    def test_swing_tsla(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/stock-analysis",
            json={"ticker": "TSLA", "purpose": "swing"},
            headers=auth_headers,
            timeout=90,
        )
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        price = res["price"]
        assert price > 0
        assert price not in STALE_MOCK_PRICES
        # candles 30-60
        candles = res["candles"]
        assert isinstance(candles, list)
        assert 25 <= len(candles) <= 70, f"candles length {len(candles)} outside expected 30-60"
        for c in candles[:3]:
            for k in ("o", "h", "l", "c"):
                assert k in c
        # anchored near real price (within ~50%)
        for pt_key in ("buy_point", "sell_point", "stop_loss"):
            v = res[pt_key]
            assert 0.5 * price <= v <= 1.5 * price, f"{pt_key}={v} not anchored near price {price}"
        # tech indicators present
        assert res["sma_20"] is not None and res["sma_20"] > 0
        assert res["sma_50"] is not None and res["sma_50"] > 0
        assert res["rsi"] is not None and 0 <= res["rsi"] <= 100
        assert isinstance(res["market_sentiment"], str) and res["market_sentiment"] in {"Bullish", "Bearish", "Neutral"}
        assert res["verdict"] in {"BUY", "SELL", "HOLD"}


# =====================================================================
# /api/screener/stock-analysis — long (MSFT)
# =====================================================================
class TestStockAnalysisLong:
    def test_long_msft(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/stock-analysis",
            json={"ticker": "MSFT", "purpose": "long"},
            headers=auth_headers,
            timeout=90,
        )
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        price = res["price"]
        assert price > 0
        assert price not in STALE_MOCK_PRICES
        # real financials
        assert res["pe_ratio"] is not None and res["pe_ratio"] > 0, f"pe_ratio must be real>0, got {res['pe_ratio']}"
        assert res["eps_ttm"] is not None and res["eps_ttm"] > 0, f"eps_ttm must be real>0, got {res['eps_ttm']}"
        # competitors - real peers from Finnhub (should include known MSFT peers)
        comps = res["competitors"]
        assert isinstance(comps, list) and len(comps) >= 1
        # MSFT's Finnhub peers typically include big tech like GOOGL, AAPL, AMZN, ORCL, CRM, IBM
        known_msft_peers = {"GOOGL", "AAPL", "AMZN", "ORCL", "CRM", "IBM", "GOOG", "META", "SAP", "ADBE"}
        assert any(c in known_msft_peers for c in comps), f"competitors look random, not real peers: {comps}"
        # analyst_ratings with integers
        ar = res["analyst_ratings"]
        for k in ("buy", "hold", "sell"):
            assert k in ar
            assert isinstance(ar[k], int)
        assert (ar["buy"] + ar["hold"] + ar["sell"]) > 0, f"analyst ratings all zero: {ar}"
        # earnings_date either None or ISO string
        ed = res.get("earnings_date")
        assert ed is None or (isinstance(ed, str) and len(ed) >= 8)
        assert res["verdict"] in {"BUY", "SELL", "HOLD"}

    def test_stock_analysis_unknown_404(self, api, base_url, auth_headers):
        r = api.post(
            f"{base_url}/api/screener/stock-analysis",
            json={"ticker": "ZZZZZZZZ", "purpose": "swing"},
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 404, f"expected 404 for unknown ticker, got {r.status_code}"


# =====================================================================
# AUTH guards on all screener endpoints
# =====================================================================
class TestAuthGuards:
    @pytest.mark.parametrize("method,path,body", [
        ("GET", "/api/screener/quote/AAPL", None),
        ("POST", "/api/screener/best-options", {"period": "week", "limit": 2}),
        ("POST", "/api/screener/find-stocks", {"risk": "high", "reward": "high", "expiration": "week", "sectors": [], "limit": 2}),
        ("POST", "/api/screener/ticker-options", {"ticker": "AAPL", "expiration_range": "week"}),
        ("POST", "/api/screener/stock-analysis", {"ticker": "AAPL", "purpose": "swing"}),
    ])
    def test_requires_auth(self, api, base_url, method, path, body):
        if method == "GET":
            r = api.get(f"{base_url}{path}", timeout=15)
        else:
            r = api.post(f"{base_url}{path}", json=body, timeout=15)
        assert r.status_code == 401, f"{path} should require auth, got {r.status_code}"


# =====================================================================
# REGRESSION: existing endpoints
# =====================================================================
class TestRegression:
    def test_login_still_works(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login", json={"email": "trader@optiscreen.app", "password": "TestPass123!"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "session_token" in d
        assert "_id" not in d.get("user", {})

    def test_user_plan(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/user/plan", json={"plan": "advance"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("plan") == "advance"

    def test_tts_generate(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/tts/generate", json={"text": "hello world"}, headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "audio_url" in d or "audio" in d or "audio_base64" in d, f"TTS response missing audio: keys={list(d.keys())}"
        if "audio_url" in d:
            assert d["audio_url"].startswith("data:audio"), f"audio_url not data URI"

    def test_paypal_create_order(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/paypal/create-order", json={"plan": "simple"}, headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "order_id" in d or "id" in d or "approve_url" in d
