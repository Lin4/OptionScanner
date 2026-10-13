"""
Auth + core-flows regression (iteration 5).
Focuses on the user bug report: 'Sign in not working'.
Validates seeded trader@optiscreen.app login end-to-end, plus a quick
regression on screener/watchlist/alerts/learn since this iteration only
shipped frontend polish.
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
BASE_URL = BASE_URL.rstrip("/")

SEED_EMAIL = "trader@optiscreen.app"
SEED_PASSWORD = "TestPass123!"


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def login_body(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": SEED_EMAIL, "password": SEED_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Seeded login failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def token(login_body):
    return login_body["session_token"]


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ========== AUTH ==========
class TestAuthReportedBug:
    """Reproduces the user bug: 'Sign in not working with given email/password'."""

    def test_login_seeded_user_returns_200(self, login_body):
        assert "session_token" in login_body
        assert isinstance(login_body["session_token"], str) and len(login_body["session_token"]) > 10

    def test_login_user_shape(self, login_body):
        user = login_body["user"]
        assert user["email"] == SEED_EMAIL
        assert user.get("plan") == "advance"
        assert user.get("questionnaire_complete") is True
        assert user.get("consent_signed") is True
        # No MongoDB _id leak
        assert "_id" not in user
        # Password must never be returned
        assert "password" not in user

    def test_login_wrong_password_returns_401(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": SEED_EMAIL, "password": "WrongPassword!"}, timeout=15)
        assert r.status_code == 401
        assert r.json().get("detail") == "Invalid credentials"

    def test_login_unknown_email_returns_401(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": f"nope_{uuid.uuid4().hex[:6]}@optiscreen.app", "password": "x"},
                     timeout=15)
        assert r.status_code == 401

    def test_auth_me_with_bearer_returns_same_user(self, api, auth_headers, login_body):
        r = api.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        me = r.json()["user"]
        assert me["email"] == SEED_EMAIL
        assert me["user_id"] == login_body["user"]["user_id"]
        assert "_id" not in me
        assert "password" not in me

    def test_auth_me_without_token_returns_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 401

    def test_auth_me_with_bad_token_returns_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Bearer not-a-real-token"}, timeout=15)
        assert r.status_code == 401

    def test_register_duplicate_email_returns_400(self, api):
        r = api.post(f"{BASE_URL}/api/auth/register",
                     json={"email": SEED_EMAIL, "password": "whatever", "name": "dup"},
                     timeout=15)
        assert r.status_code == 400
        assert "already" in r.json().get("detail", "").lower()


# ========== REGRESSION: SCREENER ticker-options ==========
class TestScreenerTickerOptions:
    def test_aapl_month(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/screener/ticker-options",
                     json={"ticker": "AAPL", "expiration_range": "month"},
                     headers=auth_headers, timeout=45)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "result" in payload, f"missing result wrapper: {list(payload.keys())}"
        body = payload["result"]
        # Required enriched fields
        for key in ("strategy", "legs", "premium_net", "breakevens",
                    "max_profit", "max_loss", "greeks", "scenario_matrix"):
            assert key in body, f"missing {key} in response"
        # legs with theo_price + per-leg greeks
        assert isinstance(body["legs"], list) and len(body["legs"]) >= 1
        for leg in body["legs"]:
            assert "theo_price" in leg, "legs must carry theo_price"
            assert isinstance(leg["theo_price"], (int, float))
            # Per-leg greeks
            for g in ("delta", "gamma", "theta", "vega"):
                assert g in leg, f"leg missing greek {g}"
        # Aggregate greeks dict
        for g in ("delta", "gamma", "theta", "vega"):
            assert g in body["greeks"]
        # breakevens is a list
        assert isinstance(body["breakevens"], list)
        # premium_net is numeric
        assert isinstance(body["premium_net"], (int, float))
        # max_profit numeric; max_loss can be None for undefined (e.g. Short Strangle)
        assert isinstance(body["max_profit"], (int, float))
        assert body["max_loss"] is None or isinstance(body["max_loss"], (int, float))
        # scenario_matrix
        assert isinstance(body["scenario_matrix"], list) and len(body["scenario_matrix"]) >= 1
        assert "days_elapsed" in body["scenario_matrix"][0]
        assert "pnl" in body["scenario_matrix"][0]
        # No _id leak
        assert "_id" not in body


# ========== REGRESSION: WATCHLIST ==========
class TestWatchlistFlow:
    TICKER = "NVDA"

    def test_add_list_delete(self, api, auth_headers):
        # Clean slate
        api.delete(f"{BASE_URL}/api/watchlist/{self.TICKER}", headers=auth_headers, timeout=10)

        r_add = api.post(f"{BASE_URL}/api/watchlist/add",
                         json={"ticker": self.TICKER}, headers=auth_headers, timeout=15)
        assert r_add.status_code == 200, r_add.text

        r_list = api.get(f"{BASE_URL}/api/watchlist", headers=auth_headers, timeout=20)
        assert r_list.status_code == 200
        body = r_list.json()
        assert "items" in body and "fetched_at" in body
        tickers = [it["ticker"] for it in body["items"]]
        assert self.TICKER in tickers
        for it in body["items"]:
            assert "_id" not in it
            assert "user_id" not in it

        r_del = api.delete(f"{BASE_URL}/api/watchlist/{self.TICKER}",
                           headers=auth_headers, timeout=10)
        assert r_del.status_code == 200
        r_list2 = api.get(f"{BASE_URL}/api/watchlist", headers=auth_headers, timeout=20)
        assert self.TICKER not in [it["ticker"] for it in r_list2.json()["items"]]


# ========== REGRESSION: ALERTS ==========
class TestAlertsFlow:
    def test_add_list_delete(self, api, auth_headers):
        r_add = api.post(f"{BASE_URL}/api/alerts/add",
                         json={"ticker": "TSLA", "kind": "price_above", "threshold": 500.0},
                         headers=auth_headers, timeout=15)
        assert r_add.status_code == 200, r_add.text
        body = r_add.json()
        assert body["ticker"] == "TSLA"
        assert body["kind"] == "price_above"
        assert body["active"] is True
        assert "alert_id" in body
        assert "user_id" not in body
        assert "_id" not in body
        alert_id = body["alert_id"]

        r_list = api.get(f"{BASE_URL}/api/alerts", headers=auth_headers, timeout=10)
        assert r_list.status_code == 200
        items = r_list.json()["items"]
        assert alert_id in [a["alert_id"] for a in items]
        for a in items:
            assert "_id" not in a
            assert "user_id" not in a

        r_del = api.delete(f"{BASE_URL}/api/alerts/{alert_id}", headers=auth_headers, timeout=10)
        assert r_del.status_code == 200
        r_list2 = api.get(f"{BASE_URL}/api/alerts", headers=auth_headers, timeout=10)
        assert alert_id not in [a["alert_id"] for a in r_list2.json()["items"]]


# ========== REGRESSION: LEARN (public) ==========
class TestLearnPublic:
    def test_learn_cards_public_min_six(self, api):
        r = api.get(f"{BASE_URL}/api/learn/cards", timeout=15)
        assert r.status_code == 200, r.text
        cards = r.json().get("cards", [])
        assert len(cards) >= 6
        for c in cards:
            for k in ("id", "category", "title", "summary"):
                assert k in c, f"card missing {k}"
