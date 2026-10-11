"""Tests for OptiScreen pivot: watchlist, alerts, learn cards, options Greeks/payoff/scenarios."""
import uuid
import pytest


# ========== Watchlist ==========
class TestWatchlist:
    def test_requires_auth_add(self, api, base_url):
        r = api.post(f"{base_url}/api/watchlist/add", json={"ticker": "AAPL"}, timeout=10)
        assert r.status_code == 401

    def test_requires_auth_list(self, api, base_url):
        r = api.get(f"{base_url}/api/watchlist", timeout=10)
        assert r.status_code == 401

    def test_requires_auth_delete(self, api, base_url):
        r = api.delete(f"{base_url}/api/watchlist/AAPL", timeout=10)
        assert r.status_code == 401

    def test_add_normalizes_and_is_idempotent(self, api, base_url, auth_headers):
        # cleanup first
        api.delete(f"{base_url}/api/watchlist/AAPL", headers=auth_headers, timeout=10)
        r1 = api.post(f"{base_url}/api/watchlist/add", json={"ticker": "aapl"}, headers=auth_headers, timeout=15)
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1.get("ok") is True
        assert body1.get("ticker") == "AAPL"  # normalized to uppercase

        r2 = api.post(f"{base_url}/api/watchlist/add", json={"ticker": "AAPL"}, headers=auth_headers, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("ok") is True  # idempotent

    def test_list_returns_quote_and_metadata(self, api, base_url, auth_headers):
        # ensure AAPL in watchlist
        api.post(f"{base_url}/api/watchlist/add", json={"ticker": "AAPL"}, headers=auth_headers, timeout=15)
        r = api.get(f"{base_url}/api/watchlist", headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)
        assert "fetched_at" in body
        aapl = next((x for x in body["items"] if x["ticker"] == "AAPL"), None)
        assert aapl is not None
        assert "added_at" in aapl
        assert "name" in aapl
        assert "sector" in aapl
        assert "quote" in aapl
        assert aapl["quote"] is not None
        assert aapl["quote"]["price"] > 0
        # no field-level leaks
        for item in body["items"]:
            assert "_id" not in item
            assert "user_id" not in item

    def test_delete_then_absent(self, api, base_url, auth_headers):
        api.post(f"{base_url}/api/watchlist/add", json={"ticker": "AAPL"}, headers=auth_headers, timeout=15)
        r = api.delete(f"{base_url}/api/watchlist/AAPL", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        r2 = api.get(f"{base_url}/api/watchlist", headers=auth_headers, timeout=30)
        tickers = [x["ticker"] for x in r2.json()["items"]]
        assert "AAPL" not in tickers


# ========== Alerts ==========
class TestAlerts:
    def test_requires_auth_add(self, api, base_url):
        r = api.post(f"{base_url}/api/alerts/add", json={"ticker": "TSLA", "kind": "price_above", "threshold": 400}, timeout=10)
        assert r.status_code == 401

    def test_requires_auth_list(self, api, base_url):
        r = api.get(f"{base_url}/api/alerts", timeout=10)
        assert r.status_code == 401

    def test_requires_auth_delete(self, api, base_url):
        r = api.delete(f"{base_url}/api/alerts/alert_fake", timeout=10)
        assert r.status_code == 401

    def test_add_invalid_kind(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/alerts/add",
                     json={"ticker": "TSLA", "kind": "bogus", "threshold": 100},
                     headers=auth_headers, timeout=10)
        assert r.status_code == 400

    def test_add_price_above(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/alerts/add",
                     json={"ticker": "TSLA", "kind": "price_above", "threshold": 400},
                     headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["alert_id"].startswith("alert_")
        assert body["ticker"] == "TSLA"
        assert body["kind"] == "price_above"
        assert body["threshold"] == 400
        assert body["active"] is True
        assert "created_at" in body
        assert "user_id" not in body
        assert "_id" not in body

    def test_list_and_delete(self, api, base_url, auth_headers):
        r_add = api.post(f"{base_url}/api/alerts/add",
                         json={"ticker": "NVDA", "kind": "price_below", "threshold": 300},
                         headers=auth_headers, timeout=10)
        assert r_add.status_code == 200
        alert_id = r_add.json()["alert_id"]

        r_list = api.get(f"{base_url}/api/alerts", headers=auth_headers, timeout=10)
        assert r_list.status_code == 200
        body = r_list.json()
        assert "items" in body
        ids = [a["alert_id"] for a in body["items"]]
        assert alert_id in ids
        for a in body["items"]:
            assert "user_id" not in a
            assert "_id" not in a

        r_del = api.delete(f"{base_url}/api/alerts/{alert_id}", headers=auth_headers, timeout=10)
        assert r_del.status_code == 200
        assert r_del.json().get("ok") is True

        r_list2 = api.get(f"{base_url}/api/alerts", headers=auth_headers, timeout=10)
        ids2 = [a["alert_id"] for a in r_list2.json()["items"]]
        assert alert_id not in ids2

    def test_add_earnings_alert(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/alerts/add",
                     json={"ticker": "MSFT", "kind": "earnings"},
                     headers=auth_headers, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "earnings"


# ========== Learn ==========
class TestLearn:
    def test_cards_public(self, api, base_url):
        r = api.get(f"{base_url}/api/learn/cards", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "cards" in body
        assert isinstance(body["cards"], list)
        assert len(body["cards"]) >= 6
        for c in body["cards"]:
            for k in ("id", "category", "title", "summary"):
                assert k in c, f"missing {k} in card"


# ========== Ticker Options with Greeks + Payoff + Scenario ==========
class TestTickerOptionsEnriched:
    def test_full_shape(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/ticker-options",
                     json={"ticker": "AAPL", "expiration_range": "month"},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        # top-level keys
        for k in ["strategy", "legs", "premium_net", "breakevens", "max_profit", "max_loss",
                  "greeks", "iv_assumed", "scenario_matrix", "assumptions", "data_source"]:
            assert k in res, f"missing {k}"
        # legs enriched with greeks
        assert isinstance(res["legs"], list) and len(res["legs"]) >= 1
        for leg in res["legs"]:
            for g in ("theo_price", "delta", "gamma", "theta", "vega"):
                assert g in leg, f"leg missing {g}: {leg}"
                assert isinstance(leg[g], (int, float))
        # breakevens list
        assert isinstance(res["breakevens"], list)
        # max_profit numeric
        assert isinstance(res["max_profit"], (int, float))
        # max_loss can be None (Short Strangle) OR number
        assert res["max_loss"] is None or isinstance(res["max_loss"], (int, float))
        # Aggregate greeks
        g = res["greeks"]
        for k in ("delta", "gamma", "theta", "vega"):
            assert k in g
            assert isinstance(g[k], (int, float))
        assert -2 <= g["delta"] <= 2, f"unrealistic delta {g['delta']}"
        # IV
        assert isinstance(res["iv_assumed"], (int, float))
        # scenario matrix: list of {days_elapsed, pnl}
        sm = res["scenario_matrix"]
        assert isinstance(sm, list) and len(sm) >= 1
        for row in sm:
            assert "days_elapsed" in row
            assert "pnl" in row
            assert isinstance(row["pnl"], dict)
        # data_source
        ds = res["data_source"]
        assert "quote" in ds and "fetched_at" in ds
        # assumptions is object
        assert isinstance(res["assumptions"], dict)


# ========== Best Options with Greeks + Payoff ==========
class TestBestOptionsEnriched:
    def test_best_options_shape(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/best-options",
                     json={"period": "week", "limit": 3},
                     headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "results" in body
        assert len(body["results"]) >= 1
        for item in body["results"]:
            for k in ("max_profit", "max_loss", "breakevens", "greeks", "scenario_matrix"):
                assert k in item, f"missing {k} in best-options result"
            for g in ("delta", "gamma", "theta", "vega"):
                assert g in item["greeks"]
                assert isinstance(item["greeks"][g], (int, float))
            assert -2 <= item["greeks"]["delta"] <= 2


# ========== Live Quote ==========
class TestLiveQuote:
    def test_quote_shape(self, api, base_url, auth_headers):
        r = api.get(f"{base_url}/api/screener/quote/AAPL", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["price"] > 0
        assert body["source"] == "Finnhub"
        assert "fetched_at" in body

    def test_quote_requires_auth(self, api, base_url):
        r = api.get(f"{base_url}/api/screener/quote/AAPL", timeout=10)
        assert r.status_code == 401


# ========== Regression ==========
class TestRegression:
    def test_login_still_works(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login",
                     json={"email": "trader@optiscreen.app", "password": "TestPass123!"},
                     timeout=15)
        assert r.status_code == 200
        assert "session_token" in r.json()

    def test_questionnaire_still_works(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/user/questionnaire",
                     json={"answers": {"experience": "Intermediate", "max_loss": 500}},
                     headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_stock_analysis_still_works(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/stock-analysis",
                     json={"ticker": "AAPL", "purpose": "swing"},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert res["ticker"] == "AAPL"
        assert "verdict" in res
