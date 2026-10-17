"""Iteration 18 tests:
   (1) Chain feature endpoints: templates, expirations, chain rows, template, analyze.
   (2) OptiIQ new shape (available/value/price/upside_pct) + screener regression.
"""
import time
import pytest
import requests

BASE = "https://optionscope.preview.emergentagent.com"


# -------- helpers --------
def _get(path, token, params=None):
    return requests.get(f"{BASE}{path}", params=params,
                        headers={"Authorization": f"Bearer {token}"}, timeout=30)


def _post(path, token, body):
    return requests.post(f"{BASE}{path}", json=body,
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"}, timeout=45)


# =============== Chain templates ===============
class TestChainTemplates:
    def test_templates_returns_12(self, seed_token):
        r = _get("/api/chain/templates", seed_token)
        assert r.status_code == 200, r.text
        tpls = r.json()["templates"]
        assert len(tpls) == 12
        names = [t["name"] for t in tpls]
        for req in ["Iron Condor", "Long Call", "Covered Call", "Long Straddle", "Bull Call Spread"]:
            assert req in names
        for t in tpls:
            assert "bias" in t and t["bias"]


# =============== Expirations ===============
class TestExpirations:
    def test_aapl_expirations(self, seed_token):
        r = _get("/api/chain/AAPL/expirations", seed_token)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ticker"] == "AAPL"
        assert isinstance(d["price"], (int, float)) and d["price"] > 0
        exps = d["expirations"]
        assert len(exps) >= 1
        for e in exps:
            assert "date" in e and "dte" in e
            assert e["dte"] >= 0
        pytest.exp_cache = exps  # share across tests

    def test_invalid_ticker_400(self, seed_token):
        r = _get("/api/chain/123$/expirations", seed_token)
        assert r.status_code == 400, r.text

    def test_unknown_ticker_404(self, seed_token):
        r = _get("/api/chain/ZZZZZZ/expirations", seed_token)
        assert r.status_code == 404, r.text


# =============== Chain rows ===============
class TestChainRows:
    @pytest.fixture(scope="class")
    def exp_date(self, seed_token):
        r = _get("/api/chain/AAPL/expirations", seed_token)
        exps = r.json()["expirations"]
        pick = next((e for e in exps if e["dte"] >= 7), exps[0])
        return pick["date"]

    def test_chain_rows(self, seed_token, exp_date):
        r = _get(f"/api/chain/AAPL", seed_token, params={"expiration": exp_date})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ticker"] == "AAPL"
        assert d["expiration"] == exp_date
        assert "atm_iv" in d
        rows = d["rows"]
        assert len(rows) > 5
        for row in rows[:5]:
            assert "strike" in row
            assert "call" in row and "put" in row
        # Find a row with both call and put filled
        populated = [r for r in rows if r.get("call") and r.get("put")]
        assert populated, "No row with both call & put quotes"
        r0 = populated[0]
        for side in (r0["call"], r0["put"]):
            assert "bid" in side and "ask" in side
            assert "iv" in side and "oi" in side

    def test_bad_date_400(self, seed_token):
        r = _get("/api/chain/AAPL", seed_token, params={"expiration": "not-a-date"})
        assert r.status_code == 400, r.text


# =============== Template builder ===============
class TestTemplateBuilder:
    @pytest.fixture(scope="class")
    def exp_date(self, seed_token):
        r = _get("/api/chain/AAPL/expirations", seed_token)
        exps = r.json()["expirations"]
        return next((e for e in exps if e["dte"] >= 20), exps[-1])["date"]

    def test_iron_condor_4_legs(self, seed_token, exp_date):
        r = _post("/api/chain/template", seed_token,
                  {"ticker": "AAPL", "expiration": exp_date, "template": "Iron Condor"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["template"] == "Iron Condor"
        legs = d["legs"]
        assert len(legs) == 4
        actions = sorted([(l["action"], l["type"]) for l in legs])
        # 2 sells, 2 buys, 2 calls, 2 puts
        assert sum(1 for a, _ in actions if a == "Sell") == 2
        assert sum(1 for a, _ in actions if a == "Buy") == 2
        assert sum(1 for _, t in actions if t == "Call") == 2
        assert sum(1 for _, t in actions if t == "Put") == 2
        for l in legs:
            assert l["strike"] > 0
            assert l["price"] >= 0

    def test_unknown_template_400(self, seed_token, exp_date):
        r = _post("/api/chain/template", seed_token,
                  {"ticker": "AAPL", "expiration": exp_date, "template": "Super Spread"})
        assert r.status_code == 400, r.text


# =============== Analyze ===============
class TestAnalyze:
    @pytest.fixture(scope="class")
    def ctx(self, seed_token):
        exps = _get("/api/chain/AAPL/expirations", seed_token).json()
        price = exps["price"]
        exp = next((e for e in exps["expirations"] if e["dte"] >= 20), exps["expirations"][-1])
        chain = _get("/api/chain/AAPL", seed_token, params={"expiration": exp["date"]}).json()
        # Find an ATM call with a real ask
        atm_row = min((r for r in chain["rows"] if r.get("call") and (r["call"].get("ask") or 0) > 0),
                      key=lambda r: abs(r["strike"] - price))
        return {"exp": exp["date"], "dte": exp["dte"], "price": price,
                "strike": atm_row["strike"], "ask": atm_row["call"]["ask"],
                "iv": atm_row["call"].get("iv")}

    def test_single_long_call(self, seed_token, ctx):
        body = {"ticker": "AAPL", "expiration": ctx["exp"], "legs": [
            {"action": "Buy", "type": "Call", "strike": ctx["strike"], "qty": 1,
             "price": ctx["ask"], "iv": ctx["iv"]}
        ]}
        r = _post("/api/chain/analyze", seed_token, body)
        assert r.status_code == 200, r.text
        a = r.json()
        # structure
        assert len(a["curve"]) == 61
        for p in a["curve"][:3]:
            assert "expiry" in p and "today" in p
        heatmap = a["heatmap"]
        assert len(heatmap["columns"]) <= 6
        assert heatmap["columns"][-1]["days_left"] == 0
        assert len(heatmap["rows"]) == 9
        # greeks keys
        for k in ("delta", "gamma", "theta", "vega"):
            assert k in a["greeks"]
        # single long call max_loss ≈ -(ask*100 + 0.65)
        expected = -(ctx["ask"] * 100 + 0.65)
        assert a["max_loss"] is not None
        assert abs(a["max_loss"] - expected) < 0.5, f"max_loss={a['max_loss']} expected={expected}"
        # breakevens list exists
        assert isinstance(a["breakevens"], list)

    def test_empty_legs_422(self, seed_token, ctx):
        body = {"ticker": "AAPL", "expiration": ctx["exp"], "legs": []}
        r = _post("/api/chain/analyze", seed_token, body)
        assert r.status_code == 422, r.text

    def test_negative_strike_422(self, seed_token, ctx):
        body = {"ticker": "AAPL", "expiration": ctx["exp"], "legs": [
            {"action": "Buy", "type": "Call", "strike": -5, "qty": 1, "price": 1.0}
        ]}
        r = _post("/api/chain/analyze", seed_token, body)
        assert r.status_code == 422, r.text

    def test_only_stock_legs_400(self, seed_token, ctx):
        body = {"ticker": "AAPL", "expiration": ctx["exp"], "legs": [
            {"action": "Buy", "type": "Stock", "strike": ctx["price"], "qty": 1, "price": ctx["price"]}
        ]}
        r = _post("/api/chain/analyze", seed_token, body)
        assert r.status_code == 400, r.text


# =============== OptiIQ via stock-analysis ===============
class TestOptiIQ:
    def _call(self, token, ticker, retries=3):
        for i in range(retries + 1):
            r = _post("/api/screener/stock-analysis", token,
                      {"ticker": ticker, "purpose": "long"})
            if r.status_code != 404 or i == retries:
                return r
            time.sleep(8)
        return r

    def _optiiq(self, r):
        d = r.json()
        return (d.get("result") or d).get("optiiq")

    def test_aapl_available(self, seed_token):
        time.sleep(2)
        r = self._call(seed_token, "AAPL")
        assert r.status_code == 200, r.text
        o = self._optiiq(r)
        assert o is not None, "optiiq missing"
        # Shape: only {available, value, price, upside_pct}
        assert set(o.keys()) <= {"available", "value", "price", "upside_pct", "reason"}
        assert o["available"] is True
        assert o["value"] > 0 and o["price"] > 0
        assert isinstance(o["upside_pct"], (int, float))

    def test_msft_available(self, seed_token):
        time.sleep(3)
        r = self._call(seed_token, "MSFT")
        assert r.status_code == 200, r.text
        o = self._optiiq(r)
        assert o["available"] is True
        assert o["value"] > 0

    def test_ko_available(self, seed_token):
        time.sleep(3)
        r = self._call(seed_token, "KO")
        assert r.status_code == 200, r.text
        o = self._optiiq(r)
        assert o["available"] is True, o

    def test_jpm_bank_available(self, seed_token):
        time.sleep(3)
        r = self._call(seed_token, "JPM")
        assert r.status_code == 200, r.text
        o = self._optiiq(r)
        assert o["available"] is True, f"JPM should use excess-return model: {o}"
        assert o["value"] > 0

    def test_mrna_unavailable(self, seed_token):
        time.sleep(3)
        r = self._call(seed_token, "MRNA")
        assert r.status_code == 200, r.text
        o = self._optiiq(r)
        assert o["available"] is False, f"MRNA expected unavailable: {o}"

    def test_screener_ticker_options_live(self, seed_token):
        time.sleep(3)
        r = _post("/api/screener/ticker-options", seed_token,
                  {"ticker": "AAPL", "account_size": 25000, "risk_pct": 2,
                   "profile": "low_low", "purpose": "long"})
        assert r.status_code == 200, r.text
        d = r.json()
        payload = d.get("result") or d
        ideas = payload.get("ideas") or payload.get("results") or []
        if ideas:
            assert any(i.get("live_quotes") is True for i in ideas), "Expected at least one live_quotes idea"
