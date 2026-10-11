"""Shared fixtures for OptiScreen backend tests."""
import os
import uuid
import requests
import pytest

BASE_URL = "https://optionscope.preview.emergentagent.com"

SEED_EMAIL = "trader@optiscreen.app"
SEED_PASSWORD = "TestPass123!"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def seed_token(api):
    """Login seeded user. If missing, register with full onboarding."""
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}, timeout=15)
    if r.status_code == 200:
        return r.json()["session_token"]
    # register
    r = api.post(f"{BASE_URL}/api/auth/register", json={"email": SEED_EMAIL, "password": SEED_PASSWORD, "name": "Jane Trader"}, timeout=15)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    token = r.json()["session_token"]
    hdr = {"Authorization": f"Bearer {token}"}
    api.post(f"{BASE_URL}/api/user/plan", json={"plan": "advance"}, headers=hdr, timeout=10)
    api.post(f"{BASE_URL}/api/user/questionnaire", json={"answers": {"experience": "Intermediate", "goal": "Growth"}}, headers=hdr, timeout=10)
    api.post(f"{BASE_URL}/api/user/consent", json={"agreed": True, "signature": "Jane"}, headers=hdr, timeout=10)
    return token


@pytest.fixture(scope="session")
def auth_headers(seed_token):
    return {"Authorization": f"Bearer {seed_token}", "Content-Type": "application/json"}


@pytest.fixture
def fresh_user(api):
    """Create a throwaway user for isolated profile tests."""
    email = f"TEST_user_{uuid.uuid4().hex[:10]}@mail.com"
    r = api.post(f"{BASE_URL}/api/auth/register", json={"email": email, "password": "Passw0rd!", "name": "Test User"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    yield {"email": email, "token": body["session_token"], "user": body["user"]}
