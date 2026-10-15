"""Iteration 7 backend tests: /api/auth/me (auth_method, created_at) and plan switching."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://optionscope.preview.emergentagent.com").rstrip("/")
EMAIL = "trader@optiscreen.app"
PASSWORD = "TestPass123!"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    tok = data.get("session_token") or data.get("token")
    assert tok, data
    return tok


@pytest.fixture()
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --- /api/auth/me: must expose auth_method and created_at ---
class TestAuthMe:
    def test_me_returns_auth_method_email(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        user = r.json().get("user") or {}
        assert user.get("email") == EMAIL
        assert user.get("auth_method") == "email", f"expected email, got {user.get('auth_method')}"

    def test_me_returns_created_at(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15)
        user = r.json().get("user") or {}
        assert user.get("created_at"), "created_at missing on user"

    def test_me_returns_plan_and_questionnaire(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15)
        user = r.json().get("user") or {}
        assert user.get("plan") in ("free", "simple", "advance", "expert")
        assert isinstance(user.get("questionnaire") or {}, dict)


# --- Plan switch (free immediate, advance restore) ---
class TestPlanSwitch:
    def test_switch_free_then_advance(self, auth_headers):
        r1 = requests.post(f"{BASE_URL}/api/user/plan", headers=auth_headers, json={"plan": "free"}, timeout=15)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("plan") == "free"

        me = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json().get("user") or {}
        assert me.get("plan") == "free"

        # restore advance (what test user is supposed to be on)
        r2 = requests.post(f"{BASE_URL}/api/user/plan", headers=auth_headers, json={"plan": "advance"}, timeout=15)
        assert r2.status_code == 200, r2.text
        me2 = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json().get("user") or {}
        assert me2.get("plan") == "advance"

    def test_invalid_plan_rejected(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/user/plan", headers=auth_headers, json={"plan": "pro"}, timeout=15)
        assert r.status_code == 400


# --- PayPal create-order sanity (paid plan path exists) ---
class TestPaypalCreate:
    def test_create_order_advance(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/paypal/create-order", headers=auth_headers, json={"plan": "advance"}, timeout=20)
        # Accept either real sandbox or mock-mode as long as it returns order_id + approve_url
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("order_id"), body
        assert body.get("approve_url"), body


# --- Questionnaire save roundtrip (no onboarding loop) ---
class TestQuestionnaireRoundtrip:
    def test_save_and_retrieve(self, auth_headers):
        before = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json().get("user") or {}
        q_before = dict(before.get("questionnaire") or {})
        # Flip risk_tolerance to a known value
        new_risk = "moderate" if q_before.get("risk_tolerance") != "moderate" else "aggressive"
        answers = {**q_before, "risk_tolerance": new_risk}
        r = requests.post(f"{BASE_URL}/api/user/questionnaire", headers=auth_headers, json={"answers": answers}, timeout=15)
        assert r.status_code == 200, r.text
        after = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json().get("user") or {}
        assert (after.get("questionnaire") or {}).get("risk_tolerance") == new_risk
        assert after.get("questionnaire_complete") is True
        # Restore original value if different
        if q_before and q_before.get("risk_tolerance") and q_before.get("risk_tolerance") != new_risk:
            requests.post(f"{BASE_URL}/api/user/questionnaire", headers=auth_headers, json={"answers": q_before}, timeout=15)
