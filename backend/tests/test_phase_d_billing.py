"""Phase D - Billing & 7-day Trial tests.

Covers:
- GET /api/auth/me access block {tier, trial_days_left, trial_ends_at, source, renews_at}
- GET /api/billing/status features matrix, scans_today, alerts_count
- Fresh user -> tier 'trial' ~7 days
- Mongo backdate created_at -> tier 'expired'
- POST /api/user/plan {plan:'expert'} -> 402; {plan:'free'} OK
- POST /api/billing/downgrade OK
- POST /api/billing/stripe/checkout -> url + session_id; invalid plan 400
- GET /api/billing/stripe/status/{session_id} unpaid; unknown 404
- POST /api/screener/best-options strategy gating by tier + scans_today increments
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://optionscope.preview.emergentagent.com"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "optiscreen_db")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


# Fresh trial user
@pytest.fixture(scope="module")
def trial_user(api):
    email = f"test_trial_{uuid.uuid4().hex[:10]}@optiscreen.app"
    r = api.post(f"{BASE_URL}/api/auth/register",
                 json={"email": email, "password": "Passw0rd!", "name": "Trial User"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    return {"email": email, "token": body["session_token"], "user_id": body["user"]["user_id"]}


@pytest.fixture(scope="module")
def expired_user(api, mongo):
    email = f"test_expired_{uuid.uuid4().hex[:10]}@optiscreen.app"
    r = api.post(f"{BASE_URL}/api/auth/register",
                 json={"email": email, "password": "Passw0rd!", "name": "Expired User"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    uid = body["user"]["user_id"]
    # Backdate created_at 8 days ago; ensure plan None (free)
    mongo.users.update_one(
        {"user_id": uid},
        {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(days=8),
                  "plan": None, "plan_source": None, "plan_expires_at": None}},
    )
    return {"email": email, "token": body["session_token"], "user_id": uid}


@pytest.fixture(scope="module")
def seed_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": "trader@optiscreen.app", "password": "TestPass123!"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --------- /auth/me access block ---------
class TestAuthMeAccess:
    def test_trial_user_me_has_access_block(self, api, trial_user):
        r = api.get(f"{BASE_URL}/api/auth/me", headers=auth(trial_user["token"]), timeout=15)
        assert r.status_code == 200
        u = r.json()["user"]
        assert "access" in u
        a = u["access"]
        for k in ("tier", "trial_days_left", "trial_ends_at", "source", "renews_at"):
            assert k in a, f"missing key {k}"
        assert a["tier"] == "trial"
        # Trial for freshly registered user: ~7 days left (compute_access returns int days)
        assert 6 <= a["trial_days_left"] <= 7
        assert a["source"] is None
        assert a["renews_at"] is None

    def test_expired_user_me_tier_expired(self, api, expired_user):
        r = api.get(f"{BASE_URL}/api/auth/me", headers=auth(expired_user["token"]), timeout=15)
        assert r.status_code == 200
        a = r.json()["user"]["access"]
        assert a["tier"] == "expired"
        assert a["trial_days_left"] == 0


# --------- /billing/status ---------
class TestBillingStatus:
    def test_billing_status_shape(self, api, trial_user):
        r = api.get(f"{BASE_URL}/api/billing/status", headers=auth(trial_user["token"]), timeout=15)
        assert r.status_code == 200
        data = r.json()
        for k in ("tier", "features", "scans_today", "alerts_count", "prices"):
            assert k in data
        # Features matrix sanity for trial
        f = data["features"]
        assert f["scans_per_day"] == 5
        assert f["strategy_tier"] == 1
        assert f["smart_alerts"] is False
        assert isinstance(data["scans_today"], int)
        assert isinstance(data["alerts_count"], int)

    def test_billing_status_advance(self, api, seed_token):
        r = api.get(f"{BASE_URL}/api/billing/status", headers=auth(seed_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["tier"] == "advance"
        f = d["features"]
        assert f["smart_alerts"] is True
        assert f["custom_period"] is True
        assert f["collateral_views"] is True
        assert f["day_lab"] is False
        assert f["scans_per_day"] >= 10000  # treated as unlimited (INF=100000)


# --------- /user/plan ---------
class TestUserPlan:
    def test_set_plan_expert_rejected_with_402(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/user/plan",
                     json={"plan": "expert"}, headers=auth(trial_user["token"]), timeout=10)
        assert r.status_code == 402, r.text

    def test_set_plan_advance_rejected_with_402(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/user/plan",
                     json={"plan": "advance"}, headers=auth(trial_user["token"]), timeout=10)
        assert r.status_code == 402

    def test_set_plan_free_ok(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/user/plan",
                     json={"plan": "free"}, headers=auth(trial_user["token"]), timeout=10)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_set_plan_invalid_400(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/user/plan",
                     json={"plan": "pro"}, headers=auth(trial_user["token"]), timeout=10)
        assert r.status_code == 400


# --------- /billing/downgrade ---------
class TestDowngrade:
    def test_downgrade_ok(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/billing/downgrade",
                     headers=auth(trial_user["token"]), timeout=10)
        assert r.status_code == 200
        assert r.json()["ok"] is True


# --------- Stripe checkout ---------
class TestStripeCheckout:
    def test_checkout_advance_creates_session(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/billing/stripe/checkout",
                     json={"plan": "advance"}, headers=auth(trial_user["token"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "url" in d and d["url"].startswith("https://")
        assert "session_id" in d and d["session_id"].startswith("cs_")
        # stash on module via pytest attr
        pytest.STRIPE_SESSION = d["session_id"]
        pytest.STRIPE_URL = d["url"]

    def test_checkout_invalid_plan_400(self, api, trial_user):
        r = api.post(f"{BASE_URL}/api/billing/stripe/checkout",
                     json={"plan": "ultra"}, headers=auth(trial_user["token"]), timeout=10)
        assert r.status_code == 400

    def test_status_unpaid_session(self, api, trial_user):
        sid = getattr(pytest, "STRIPE_SESSION", None)
        assert sid, "need session from previous test"
        r = api.get(f"{BASE_URL}/api/billing/stripe/status/{sid}",
                    headers=auth(trial_user["token"]), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["paid"] is False
        assert d["plan"] == "advance"

    def test_status_unknown_session_404(self, api, trial_user):
        r = api.get(f"{BASE_URL}/api/billing/stripe/status/cs_test_unknown_xyz",
                    headers=auth(trial_user["token"]), timeout=15)
        assert r.status_code == 404


# --------- Screener best-options tier gating ---------
NAKED = {"Sell Put", "Sell Call", "Short Strangle"}


class TestScreenerTierGating:
    def test_simple_tier_allowed_strategies_only_csp_cc(self, api, seed_token):
        r = api.post(
            f"{BASE_URL}/api/screener/best-options",
            json={"period": "week", "limit": 3, "tier": "simple", "profile": "low_low"},
            headers=auth(seed_token), timeout=90,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        allowed = set(d.get("allowed_strategies", []))
        assert allowed.issubset({"Cash Secured Put", "Covered Call"}), f"got {allowed}"
        assert "scans_today" in d
        assert isinstance(d["scans_today"], int)

    def test_advance_tier_no_naked_strategies(self, api, seed_token):
        r = api.post(
            f"{BASE_URL}/api/screener/best-options",
            json={"period": "week", "limit": 3, "tier": "advance", "profile": "high_high"},
            headers=auth(seed_token), timeout=90,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        allowed = set(d.get("allowed_strategies", []))
        assert not (allowed & NAKED), f"advance should not allow naked: {allowed & NAKED}"

    def test_scans_today_increments(self, api, trial_user):
        # Trial user gets 5/day. Downgrade test above didn't tick usage.
        r1 = api.post(
            f"{BASE_URL}/api/screener/best-options",
            json={"period": "week", "limit": 2, "profile": "low_low"},
            headers=auth(trial_user["token"]), timeout=90,
        )
        assert r1.status_code == 200, r1.text
        s1 = r1.json()["scans_today"]
        r2 = api.post(
            f"{BASE_URL}/api/screener/best-options",
            json={"period": "week", "limit": 2, "profile": "low_low"},
            headers=auth(trial_user["token"]), timeout=90,
        )
        assert r2.status_code == 200
        s2 = r2.json()["scans_today"]
        assert s2 == s1 + 1, f"expected {s1}+1, got {s2}"


# --------- Cleanup ---------
def test_zz_cleanup(mongo, trial_user, expired_user):
    for uid in (trial_user["user_id"], expired_user["user_id"]):
        mongo.users.delete_one({"user_id": uid})
        mongo.user_sessions.delete_many({"user_id": uid})
        mongo.usage.delete_many({"user_id": uid})
        mongo.payment_transactions.delete_many({"user_id": uid})
    # Ensure trader user is still advance (safety per agent note)
    mongo.users.update_one(
        {"email": "trader@optiscreen.app"},
        {"$set": {"plan": "advance", "plan_source": None, "plan_expires_at": None}},
    )
