"""Iteration 17 tests: Tradier live option chain integration, new OptiIQ Value formula,
and AlertAddReq validation. Uses the production trader@optiscreen.app seed account.
"""
import os
import time
import requests
import pytest

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "https://optionscope.preview.emergentagent.com").rstrip("/")
EMAIL = "trader@optiscreen.app"
PASS = "TestPass123!"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASS}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Tradier live option chain ----------
class TestTradierLive:
    def test_ticker_options_aapl_live(self, auth):
        r = requests.post(f"{BASE}/api/screener/ticker-options",
                          json={"ticker": "AAPL", "expiration_range": "month"},
                          headers=auth, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert res["live_quotes"] is True, f"live_quotes should be True, got {res.get('live_quotes')}, quote_source={res.get('quote_source')}"
        assert res["quote_source"] == "Tradier", res.get("quote_source")
        # legs: option legs must have bid/ask + live True
        opt_legs = [l for l in res["legs"] if l["type"].lower() in ("call", "put")]
        assert opt_legs, "No option legs returned"
        for l in opt_legs:
            assert l.get("live") is True, f"leg not live: {l}"
            assert "bid" in l and "ask" in l, f"leg missing bid/ask: {l}"
            assert l["ask"] > 0, f"leg ask<=0: {l}"
        # liquidity.estimated false
        liq = res.get("liquidity", {})
        assert liq.get("estimated") is False, f"liquidity still estimated: {liq}"
        # data_source.options_live true
        ds = res.get("data_source", {})
        assert ds.get("options_live") is True, ds
        # expiration is a real listed date (YYYY-MM-DD)
        assert len(res["expiration"]) == 10 and res["expiration"][4] == "-"

    def test_best_options_carries_live(self, auth):
        t0 = time.time()
        r = requests.post(f"{BASE}/api/screener/best-options",
                          json={"period": "week", "limit": 3},
                          headers=auth, timeout=120)
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        body = r.json()
        assert dt < 90, f"scan too slow: {dt:.1f}s"
        if body["results"]:
            # at least one carries live_quotes true for high-liquidity universe
            live_flags = [bool(r.get("live_quotes")) for r in body["results"]]
            assert any(live_flags), f"no result carried live quotes: {live_flags}"

    def test_find_stocks_still_works(self, auth):
        r = requests.post(f"{BASE}/api/screener/find-stocks",
                          json={"expiration": "week", "limit": 3},
                          headers=auth, timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "results" in body


# ---------- OptiIQ new formula ----------
class TestOptiIQNewFormula:
    def test_optiiq_aapl_available_formula_matches(self, auth):
        r = requests.post(f"{BASE}/api/screener/stock-analysis",
                          json={"ticker": "AAPL", "purpose": "long"},
                          headers=auth, timeout=120)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        o = res["optiiq"]
        assert o["available"] is True, o
        # New schema: no 'methods' key
        assert "methods" not in o, f"old 'methods' key still present: {list(o.keys())}"
        # Formula sanity: value ≈ (pv_cash_flows + net_assets)/shares
        f = o["formula"]
        pv = f["pv_cash_flows"]
        na = f["net_assets"]
        sh = f["shares"]
        expected = (pv + na) / sh
        assert abs(o["value"] - expected) / max(abs(expected), 0.01) < 0.02, \
            f"value {o['value']} != formula ({pv}+{na})/{sh}={expected}"
        # projection has 10 years
        proj = o["projection"]
        assert len(proj) == 10, f"projection years={len(proj)}"
        years = [p["year"] for p in proj]
        assert years == list(range(1, 11))
        for p in proj:
            assert "cash_flow" in p and "pv" in p
        # stress low <= value <= high
        s = o["stress"]
        assert s["low"] <= o["value"] <= s["high"], f"stress {s['low']}..{s['high']} does not bracket {o['value']}"
        # assumptions present
        a = o["assumptions"]
        for k in ("years", "discount_rate_pct", "growth_y1_5_pct", "growth_y6_10_pct", "cfo_ttm"):
            assert k in a, f"missing assumption key: {k}"
        assert a["years"] == 10

    def test_optiiq_bank_or_biotech_unavailable_with_reason(self, auth):
        # JPM (bank, negative/erratic operating cash flow) OR MRNA (biotech burning cash)
        unavailable = []
        for tk in ("JPM", "MRNA"):
            r = requests.post(f"{BASE}/api/screener/stock-analysis",
                              json={"ticker": tk, "purpose": "long"},
                              headers=auth, timeout=120)
            assert r.status_code == 200, r.text
            o = r.json()["result"]["optiiq"]
            if o.get("available") is False:
                assert isinstance(o.get("reason"), str) and len(o["reason"]) > 10, o
                unavailable.append(tk)
            time.sleep(1.3)
        assert unavailable, "expected JPM or MRNA to be unavailable; both came back available"


# ---------- Alerts validation ----------
class TestAlertValidation:
    created_ids = []

    def test_valid_price_alert(self, auth):
        r = requests.post(f"{BASE}/api/alerts/add",
                          json={"ticker": "AAPL", "kind": "price_above", "threshold": 250.0, "note": "TEST_"},
                          headers=auth, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ticker"] == "AAPL"
        assert body["kind"] == "price_above"
        assert body["threshold"] == 250.0
        TestAlertValidation.created_ids.append(body["alert_id"])

    def test_valid_earnings_alert_no_threshold(self, auth):
        r = requests.post(f"{BASE}/api/alerts/add",
                          json={"ticker": "AAPL", "kind": "earnings"},
                          headers=auth, timeout=30)
        assert r.status_code == 200, r.text
        TestAlertValidation.created_ids.append(r.json()["alert_id"])

    @pytest.mark.parametrize("payload", [
        {"ticker": "AAPL", "kind": "price_above", "threshold": -5},     # negative
        {"ticker": "AAPL", "kind": "price_below", "threshold": 0},      # zero
        {"ticker": "AAPL", "kind": "price_above", "threshold": "abc"},  # non-numeric
        {"ticker": "AAPL", "kind": "price_above"},                      # missing threshold for price alert
        {"ticker": "AAPL", "kind": "bogus_kind", "threshold": 10},      # bad literal
    ])
    def test_invalid_payloads_return_422(self, auth, payload):
        r = requests.post(f"{BASE}/api/alerts/add", json=payload, headers=auth, timeout=30)
        assert r.status_code == 422, f"expected 422 for {payload} got {r.status_code}: {r.text}"

    def test_cleanup(self, auth):
        for aid in TestAlertValidation.created_ids:
            requests.delete(f"{BASE}/api/alerts/{aid}", headers=auth, timeout=15)
