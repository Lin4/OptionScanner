"""OptiScreen backend API tests - auth, profile, screener."""
import os
import uuid
import requests
import pytest

BASE_URL = "https://optionscope.preview.emergentagent.com"


# ========== HEALTH ==========
class TestHealth:
    def test_root(self, api, base_url):
        r = api.get(f"{base_url}/api/", timeout=10)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ========== AUTH ==========
class TestAuth:
    def test_register_returns_token_and_user(self, api, base_url):
        email = f"TEST_reg_{uuid.uuid4().hex[:8]}@mail.com"
        r = api.post(f"{base_url}/api/auth/register", json={"email": email, "password": "Passw0rd!", "name": "Reg Test"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session_token" in body and isinstance(body["session_token"], str) and len(body["session_token"]) > 20
        assert "user" in body
        user = body["user"]
        assert user["email"] == email.lower()
        assert user["name"] == "Reg Test"
        assert "password" not in user
        assert "_id" not in user
        assert user.get("plan") is None
        assert user.get("questionnaire_complete") is False
        assert user.get("consent_signed") is False

    def test_register_duplicate_rejected(self, api, base_url):
        email = f"TEST_dup_{uuid.uuid4().hex[:8]}@mail.com"
        r1 = api.post(f"{base_url}/api/auth/register", json={"email": email, "password": "Passw0rd!"}, timeout=15)
        assert r1.status_code == 200
        r2 = api.post(f"{base_url}/api/auth/register", json={"email": email, "password": "Passw0rd!"}, timeout=15)
        assert r2.status_code == 400

    def test_login_success(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login", json={"email": "trader@optiscreen.app", "password": "TestPass123!"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session_token" in body
        assert body["user"]["email"] == "trader@optiscreen.app"
        assert "_id" not in body["user"]
        assert "password" not in body["user"]

    def test_login_wrong_password(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login", json={"email": "trader@optiscreen.app", "password": "WrongPass!!"}, timeout=15)
        assert r.status_code == 401

    def test_login_unknown_user(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login", json={"email": f"nope_{uuid.uuid4().hex[:6]}@x.com", "password": "x"}, timeout=15)
        assert r.status_code == 401

    def test_me_with_token(self, api, base_url, auth_headers):
        r = api.get(f"{base_url}/api/auth/me", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "user" in body
        assert body["user"]["email"] == "trader@optiscreen.app"
        assert "_id" not in body["user"]
        assert "password" not in body["user"]

    def test_me_without_token(self, api, base_url):
        r = api.get(f"{base_url}/api/auth/me", timeout=10)
        assert r.status_code == 401

    def test_me_invalid_token(self, api, base_url):
        r = api.get(f"{base_url}/api/auth/me", headers={"Authorization": "Bearer total.garbage.token"}, timeout=10)
        assert r.status_code == 401

    def test_logout_clears_session(self, api, base_url):
        # register fresh so we don't nuke the seed token
        email = f"TEST_lo_{uuid.uuid4().hex[:8]}@mail.com"
        r = api.post(f"{base_url}/api/auth/register", json={"email": email, "password": "Passw0rd!"}, timeout=15)
        token = r.json()["session_token"]
        hdr = {"Authorization": f"Bearer {token}"}
        r2 = api.post(f"{base_url}/api/auth/logout", headers=hdr, timeout=10)
        assert r2.status_code == 200
        assert r2.json().get("ok") is True

    def test_oauth_session_invalid(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/session", json={"session_id": "invalid-xyz-" + uuid.uuid4().hex}, timeout=20)
        assert r.status_code == 401


# ========== PROFILE ==========
class TestProfile:
    def test_set_plan_valid(self, api, base_url, fresh_user):
        hdr = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = api.post(f"{base_url}/api/user/plan", json={"plan": "expert"}, headers=hdr, timeout=10)
        assert r.status_code == 200
        assert r.json()["plan"] == "expert"
        # verify persisted via /me
        me = api.get(f"{base_url}/api/auth/me", headers=hdr, timeout=10).json()
        assert me["user"]["plan"] == "expert"

    def test_set_plan_invalid(self, api, base_url, fresh_user):
        hdr = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = api.post(f"{base_url}/api/user/plan", json={"plan": "diamond"}, headers=hdr, timeout=10)
        assert r.status_code == 400

    def test_set_plan_requires_auth(self, api, base_url):
        r = api.post(f"{base_url}/api/user/plan", json={"plan": "free"}, timeout=10)
        assert r.status_code == 401

    def test_questionnaire_saves_and_flags(self, api, base_url, fresh_user):
        hdr = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = api.post(f"{base_url}/api/user/questionnaire", json={"answers": {"experience": "beginner", "goal": "income"}}, headers=hdr, timeout=10)
        assert r.status_code == 200 and r.json().get("ok") is True
        me = api.get(f"{base_url}/api/auth/me", headers=hdr, timeout=10).json()
        assert me["user"]["questionnaire_complete"] is True

    def test_consent_requires_signature(self, api, base_url, fresh_user):
        hdr = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = api.post(f"{base_url}/api/user/consent", json={"agreed": True, "signature": "   "}, headers=hdr, timeout=10)
        assert r.status_code == 400

    def test_consent_requires_agreed(self, api, base_url, fresh_user):
        hdr = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = api.post(f"{base_url}/api/user/consent", json={"agreed": False, "signature": "John"}, headers=hdr, timeout=10)
        assert r.status_code == 400

    def test_consent_success(self, api, base_url, fresh_user):
        hdr = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = api.post(f"{base_url}/api/user/consent", json={"agreed": True, "signature": "John Doe"}, headers=hdr, timeout=10)
        assert r.status_code == 200
        me = api.get(f"{base_url}/api/auth/me", headers=hdr, timeout=10).json()
        assert me["user"]["consent_signed"] is True


# ========== SCREENER ==========
class TestScreenerStocks:
    def test_list_stocks(self, api, base_url):
        r = api.get(f"{base_url}/api/screener/stocks", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "stocks" in body and len(body["stocks"]) > 5
        s0 = body["stocks"][0]
        assert all(k in s0 for k in ["ticker", "name", "sector", "price"])


class TestFindStocks:
    def test_requires_auth(self, api, base_url):
        r = api.post(f"{base_url}/api/screener/find-stocks",
                     json={"risk": "high", "reward": "high", "expiration": "month", "sectors": [], "limit": 3},
                     timeout=10)
        assert r.status_code == 401

    def test_find_stocks_full(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/find-stocks",
                     json={"risk": "high", "reward": "high", "expiration": "month", "sectors": ["Tech"], "limit": 3},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "results" in body and len(body["results"]) == 3
        for item in body["results"]:
            for k in ["ticker", "strategy", "legs", "premium", "pop", "annual_pct_no_margin", "bias", "rationale", "expiration"]:
                assert k in item, f"missing {k} in {item}"
            assert isinstance(item["legs"], list) and len(item["legs"]) >= 1
            assert "_id" not in item
            # Tech filter honored
            assert item["sector"] == "Tech"


class TestBestOptions:
    def test_requires_auth(self, api, base_url):
        r = api.post(f"{base_url}/api/screener/best-options", json={"period": "week", "limit": 3}, timeout=10)
        assert r.status_code == 401

    @pytest.mark.parametrize("period", ["day", "week", "month", "custom"])
    def test_best_options_periods(self, api, base_url, auth_headers, period):
        payload = {"period": period, "limit": 4}
        if period == "custom":
            payload["custom_days"] = 14
        r = api.post(f"{base_url}/api/screener/best-options", json=payload, headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "results" in body and "ai_summary" in body
        assert len(body["results"]) == 4
        # must be sorted descending by annual_pct_no_margin
        vals = [r["annual_pct_no_margin"] for r in body["results"]]
        assert vals == sorted(vals, reverse=True)
        for item in body["results"]:
            assert "_id" not in item


class TestTickerOptions:
    def test_requires_auth(self, api, base_url):
        r = api.post(f"{base_url}/api/screener/ticker-options", json={"ticker": "AAPL", "expiration_range": "month"}, timeout=10)
        assert r.status_code == 401

    def test_ticker_options_known(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/ticker-options",
                     json={"ticker": "AAPL", "expiration_range": "month"},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "result" in body
        res = body["result"]
        for k in ["ticker", "legs", "premium", "collateral", "annual_pct_no_margin", "ai_summary"]:
            assert k in res
        assert res["ticker"] == "AAPL"
        assert "_id" not in res

    def test_ticker_options_unknown_fallback(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/ticker-options",
                     json={"ticker": "ZZZX", "expiration_range": "week"},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200
        assert r.json()["result"]["ticker"] == "ZZZX"


class TestStockAnalysis:
    def test_requires_auth(self, api, base_url):
        r = api.post(f"{base_url}/api/screener/stock-analysis", json={"ticker": "AAPL", "purpose": "day"}, timeout=10)
        assert r.status_code == 401

    @pytest.mark.parametrize("purpose", ["day", "swing"])
    def test_stock_analysis_short_term(self, api, base_url, auth_headers, purpose):
        r = api.post(f"{base_url}/api/screener/stock-analysis",
                     json={"ticker": "NVDA", "purpose": purpose},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        for k in ["ticker", "buy_point", "sell_point", "stop_loss", "candles", "verdict", "ai_summary"]:
            assert k in res, f"missing {k}"
        assert res["purpose"] == purpose
        assert isinstance(res["candles"], list) and len(res["candles"]) >= 20
        assert res["verdict"] in ("BUY", "SELL", "HOLD")
        assert "_id" not in res

    def test_stock_analysis_long(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/stock-analysis",
                     json={"ticker": "MSFT", "purpose": "long"},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        for k in ["intrinsic_value", "price_target", "analyst_ratings", "verdict", "ai_summary"]:
            assert k in res
        ar = res["analyst_ratings"]
        assert all(k in ar for k in ["buy", "hold", "sell"])
        # financials
        for k in ["revenue_billions", "net_cash_billions", "net_profit_billions", "debt_billions"]:
            assert k in res
        assert res["verdict"] in ("BUY", "SELL", "HOLD")
