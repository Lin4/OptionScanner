"""Iteration 22 — Admin Broadcasts & In-app Announcements."""
import os
import time
import requests
import pytest

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://optionscope.preview.emergentagent.com"
).rstrip("/")

ADMIN_EMAIL = "lingesa4@gmail.com"
ADMIN_PASS = "Linges1@12"
TRADER_EMAIL = "trader@optiscreen.app"
TRADER_PASS = "TestPass123!"


def h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def trader_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": TRADER_EMAIL, "password": TRADER_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


# Shared state across tests
_created = {}


class TestCreateBroadcast:
    def test_non_admin_forbidden(self, api, trader_token):
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "TEST_x", "message": "nope", "audience": "all"},
                     headers=h(trader_token), timeout=20)
        assert r.status_code == 403, r.text

    def test_empty_title_422(self, api, admin_token):
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "", "message": "hello", "audience": "all"},
                     headers=h(admin_token), timeout=20)
        assert r.status_code == 422, r.text

    def test_bad_audience_422(self, api, admin_token):
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "TEST_bad", "message": "x", "audience": "nonsense"},
                     headers=h(admin_token), timeout=20)
        assert r.status_code == 422, r.text

    def test_create_all(self, api, admin_token):
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "TEST_all_ann", "message": "Everyone see me", "audience": "all", "push": False},
                     headers=h(admin_token), timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["broadcast_id"].startswith("bc_")
        assert d["active"] is True
        assert d["audience"] == "all"
        assert isinstance(d["reach"], int) and d["reach"] >= 1
        assert d.get("pushed") is False
        _created["all"] = d["broadcast_id"]

    def test_create_advance(self, api, admin_token):
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "TEST_advance_only", "message": "Advance tier msg", "audience": "advance"},
                     headers=h(admin_token), timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["audience"] == "advance"
        _created["advance"] = d["broadcast_id"]

    def test_create_expert(self, api, admin_token):
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "TEST_expert_only", "message": "Expert tier msg", "audience": "expert"},
                     headers=h(admin_token), timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["audience"] == "expert"
        assert d["reach"] >= 1  # lingesa4 is expert
        _created["expert"] = d["broadcast_id"]

    def test_push_shape_preview_env(self, api, admin_token):
        # push=True in preview should yield pushed:false (no device tokens)
        r = api.post(f"{BASE_URL}/api/admin/broadcasts",
                     json={"title": "TEST_push_shape", "message": "x", "audience": "all", "push": True},
                     headers=h(admin_token), timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("push") is True
        # pushed may be False in preview; we only assert key exists
        assert "pushed" in d
        _created["push_shape"] = d["broadcast_id"]


class TestAudienceVisibility:
    def test_trader_sees_all_and_advance_not_expert(self, api, trader_token):
        r = api.get(f"{BASE_URL}/api/announcements", headers=h(trader_token), timeout=20)
        assert r.status_code == 200, r.text
        ids = {it["broadcast_id"] for it in r.json()["items"]}
        assert _created["all"] in ids, "trader must see 'all' broadcast"
        assert _created["advance"] in ids, "trader(advance) must see 'advance' broadcast"
        assert _created["expert"] not in ids, "trader must NOT see 'expert' broadcast"

    def test_admin_sees_expert_and_all(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/announcements", headers=h(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        ids = {it["broadcast_id"] for it in r.json()["items"]}
        assert _created["all"] in ids, "admin(expert) must see 'all' broadcast"
        assert _created["expert"] in ids, "admin(expert) must see 'expert' broadcast"
        assert _created["advance"] not in ids, "admin(expert) must NOT see 'advance' broadcast"


class TestDismiss:
    def test_dismiss_unknown_404(self, api, trader_token):
        r = api.post(f"{BASE_URL}/api/announcements/bc_doesnotexist/dismiss",
                     headers=h(trader_token), timeout=20)
        assert r.status_code == 404, r.text

    def test_dismiss_hides_for_user_only_idempotent(self, api, trader_token, admin_token):
        bid = _created["all"]
        # Dismiss as trader
        r1 = api.post(f"{BASE_URL}/api/announcements/{bid}/dismiss",
                      headers=h(trader_token), timeout=20)
        assert r1.status_code == 200
        # Idempotent
        r2 = api.post(f"{BASE_URL}/api/announcements/{bid}/dismiss",
                      headers=h(trader_token), timeout=20)
        assert r2.status_code == 200
        # Hidden for trader
        anns = api.get(f"{BASE_URL}/api/announcements", headers=h(trader_token), timeout=20).json()["items"]
        assert bid not in {a["broadcast_id"] for a in anns}, "dismissed should be hidden"
        # Still visible for admin
        anns_a = api.get(f"{BASE_URL}/api/announcements", headers=h(admin_token), timeout=20).json()["items"]
        assert bid in {a["broadcast_id"] for a in anns_a}, "dismiss should be per-user"

    def test_admin_list_shows_dismissed_count(self, api, admin_token):
        bid = _created["all"]
        r = api.get(f"{BASE_URL}/api/admin/broadcasts", headers=h(admin_token), timeout=20)
        assert r.status_code == 200
        row = next((x for x in r.json()["items"] if x["broadcast_id"] == bid), None)
        assert row is not None
        assert row.get("dismissed", 0) >= 1


class TestEndBroadcast:
    def test_delete_ends_broadcast(self, api, admin_token):
        bid = _created["advance"]
        r = api.delete(f"{BASE_URL}/api/admin/broadcasts/{bid}", headers=h(admin_token), timeout=20)
        assert r.status_code == 200
        # Not visible to any trader
        # Admin list shows active False
        lst = api.get(f"{BASE_URL}/api/admin/broadcasts", headers=h(admin_token), timeout=20).json()["items"]
        row = next(x for x in lst if x["broadcast_id"] == bid)
        assert row["active"] is False

    def test_ended_not_in_announcements(self, api, trader_token):
        bid = _created["advance"]
        ids = {it["broadcast_id"] for it in api.get(f"{BASE_URL}/api/announcements", headers=h(trader_token), timeout=20).json()["items"]}
        assert bid not in ids, "ended broadcast should not appear"

    def test_delete_unknown_404(self, api, admin_token):
        r = api.delete(f"{BASE_URL}/api/admin/broadcasts/bc_nope_nope_nope", headers=h(admin_token), timeout=20)
        assert r.status_code == 404

    def test_admin_list_non_admin_403(self, api, trader_token):
        r = api.get(f"{BASE_URL}/api/admin/broadcasts", headers=h(trader_token), timeout=20)
        assert r.status_code == 403


class TestZCleanup:
    def test_cleanup_test_broadcasts(self, api, admin_token):
        """End ALL remaining TEST_* broadcasts so real users don't see them."""
        lst = api.get(f"{BASE_URL}/api/admin/broadcasts", headers=h(admin_token), timeout=20).json()["items"]
        ended = 0
        for b in lst:
            if b.get("active") and b.get("title", "").startswith("TEST_"):
                r = api.delete(f"{BASE_URL}/api/admin/broadcasts/{b['broadcast_id']}", headers=h(admin_token), timeout=20)
                if r.status_code == 200:
                    ended += 1
        print(f"cleanup: ended {ended} TEST_ broadcasts")
        # Trader should see no TEST_ live announcement after cleanup
        time.sleep(0.3)
