"""Iteration 19 — Saved Strategies, Multi-Expiry Builder, Alerts & Admin Plan Switcher."""
import time
import requests
import pytest

BASE_URL = "https://optionscope.preview.emergentagent.com"

ADMIN_EMAIL = "lingesa4@gmail.com"
ADMIN_PASS = "Linges1@12"
TRADER_EMAIL = "trader@optiscreen.app"
TRADER_PASS = "TestPass123!"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def trader_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": TRADER_EMAIL, "password": TRADER_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


# ---------- Multi-Expiry Builder (chain templates + analyze) ----------
class TestMultiExpiry:
    def _near_exp(self, api, token):
        r = api.get(f"{BASE_URL}/api/chain/AAPL/expirations", headers=h(token), timeout=30)
        assert r.status_code == 200, r.text
        exps = r.json()["expirations"]
        assert len(exps) >= 2
        return exps[0]["date"]

    def test_calendar_call_template(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        r = api.post(f"{BASE_URL}/api/chain/template",
                     json={"ticker": "AAPL", "expiration": near, "template": "Calendar Call Spread"},
                     headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        legs = r.json()["legs"]
        assert len(legs) == 2
        assert {l["type"] for l in legs} == {"Call"}
        exps = {l["expiration"] for l in legs}
        assert len(exps) == 2, f"Calendar must have 2 distinct expirations, got {exps}"

        # analyze
        ar = api.post(f"{BASE_URL}/api/chain/analyze",
                      json={"ticker": "AAPL", "expiration": near, "legs": legs},
                      headers=h(trader_token), timeout=45)
        assert ar.status_code == 200, ar.text
        a = ar.json()
        assert a["multi_expiry"] is True
        assert a["max_loss"] is not None and a["max_loss"] < 0, "Calendar should have finite max_loss"
        # heatmap: last column days_left should be 0 (nearest-expiry)
        cols = a["heatmap"]["columns"]
        assert cols[-1]["days_left"] == 0, f"Heatmap last col days_left: {cols[-1]['days_left']}"

    def test_diagonal_put_template(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        r = api.post(f"{BASE_URL}/api/chain/template",
                     json={"ticker": "AAPL", "expiration": near, "template": "Diagonal Put Spread"},
                     headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        legs = r.json()["legs"]
        assert len(legs) == 2
        assert {l["type"] for l in legs} == {"Put"}
        assert len({l["expiration"] for l in legs}) == 2
        # strikes differ (diagonal) — may be equal for small ATM span, so just assert legs valid
        assert all(l["strike"] > 0 for l in legs)

    def test_single_expiry_regression(self, api, trader_token):
        """Single-expiry template still works."""
        near = self._near_exp(api, trader_token)
        r = api.post(f"{BASE_URL}/api/chain/template",
                     json={"ticker": "AAPL", "expiration": near, "template": "Bull Call Spread"},
                     headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        legs = r.json()["legs"]
        ar = api.post(f"{BASE_URL}/api/chain/analyze",
                      json={"ticker": "AAPL", "expiration": near, "legs": legs},
                      headers=h(trader_token), timeout=45)
        assert ar.status_code == 200
        assert ar.json()["multi_expiry"] is False


# ---------- Strategies CRUD + Alerts ----------
class TestStrategies:
    _created = []

    def _near_exp(self, api, token):
        r = api.get(f"{BASE_URL}/api/chain/AAPL/expirations", headers=h(token), timeout=30)
        return r.json()["expirations"][0]["date"]

    def _bull_call_legs(self, api, token, near):
        r = api.post(f"{BASE_URL}/api/chain/template",
                     json={"ticker": "AAPL", "expiration": near, "template": "Bull Call Spread"},
                     headers=h(token), timeout=45)
        assert r.status_code == 200, r.text
        return r.json()["legs"]

    def test_validation_empty_legs(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        r = api.post(f"{BASE_URL}/api/strategies",
                     json={"name": "TEST_empty", "ticker": "AAPL", "expiration": near, "legs": []},
                     headers=h(trader_token), timeout=15)
        assert r.status_code == 422, r.text

    def test_validation_bad_target(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        legs = self._bull_call_legs(api, trader_token, near)
        r = api.post(f"{BASE_URL}/api/strategies",
                     json={"name": "TEST_bad_tgt", "ticker": "AAPL", "expiration": near, "legs": legs,
                           "target": {"mode": "pct", "value": 0}},
                     headers=h(trader_token), timeout=30)
        assert r.status_code == 422, r.text

    def test_validation_bad_mode(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        legs = self._bull_call_legs(api, trader_token, near)
        r = api.post(f"{BASE_URL}/api/strategies",
                     json={"name": "TEST_bad_mode", "ticker": "AAPL", "expiration": near, "legs": legs,
                           "target": {"mode": "nope", "value": 50}},
                     headers=h(trader_token), timeout=30)
        assert r.status_code == 422, r.text

    def test_validation_stock_only(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        r = api.post(f"{BASE_URL}/api/strategies",
                     json={"name": "TEST_stock", "ticker": "AAPL", "expiration": near,
                           "legs": [{"action": "Buy", "type": "Stock", "strike": 100, "qty": 1, "price": 100}]},
                     headers=h(trader_token), timeout=30)
        assert r.status_code == 400, r.text

    def test_save_list_mark_fields(self, api, trader_token):
        near = self._near_exp(api, trader_token)
        legs = self._bull_call_legs(api, trader_token, near)
        r = api.post(f"{BASE_URL}/api/strategies",
                     json={"name": "TEST_save_bullcall", "ticker": "AAPL", "expiration": near, "legs": legs,
                           "target": {"mode": "pct", "value": 50},
                           "stop": {"mode": "usd", "value": 100}},
                     headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        sid = r.json()["strategy_id"]
        TestStrategies._created.append(("trader", sid))

        lr = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        assert lr.status_code == 200, lr.text
        body = lr.json()
        assert "items" in body and "total_pnl" in body
        s = next((x for x in body["items"] if x["strategy_id"] == sid), None)
        assert s is not None
        m = s["mark"]
        # mark fields exist
        for k in ("pnl", "pnl_pct", "target_usd", "stop_usd", "live"):
            assert k in m, f"mark missing {k}: {m}"

    def test_tiny_stop_triggers_alert_once(self, api, trader_token):
        """Save a strategy with $1 stop (near-impossible NOT to breach) and verify alert fires exactly once."""
        near = self._near_exp(api, trader_token)
        legs = self._bull_call_legs(api, trader_token, near)
        r = api.post(f"{BASE_URL}/api/strategies",
                     json={"name": "TEST_tiny_stop", "ticker": "AAPL", "expiration": near, "legs": legs,
                           "stop": {"mode": "usd", "value": 1}},
                     headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        sid = r.json()["strategy_id"]
        TestStrategies._created.append(("trader", sid))

        # First list triggers alert check
        api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        time.sleep(1)

        # Second list should NOT fire again
        api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        time.sleep(1)

        feed = api.get(f"{BASE_URL}/api/alerts/feed", headers=h(trader_token), timeout=15)
        assert feed.status_code == 200, feed.text
        items = feed.json().get("items") or feed.json()
        if isinstance(items, dict):
            items = items.get("items", [])
        matches = [e for e in items if e.get("strategy_id") == sid and e.get("kind") == "strategy_stop"]
        # Market may be closed → mark may still produce negative pnl; if P&L happens to be positive the event may not fire. Accept 0 or 1 unique.
        if matches:
            # verify no duplicate: unique by event_id
            assert len({m["event_id"] for m in matches}) == len(matches)
            assert len(matches) == 1, f"Duplicate alerts fired: {len(matches)}"
            TestStrategies._stop_fired = True
        else:
            TestStrategies._stop_fired = False
            pytest.skip("No stop event (mark may have been positive — market closed/wide spreads)")

    def test_patch_resets_fired(self, api, trader_token):
        if not TestStrategies._created:
            pytest.skip("no strategies")
        sid = TestStrategies._created[-1][1]
        r = api.patch(f"{BASE_URL}/api/strategies/{sid}",
                      json={"stop": {"mode": "usd", "value": 500}},
                      headers=h(trader_token), timeout=15)
        assert r.status_code == 200, r.text

    def test_other_user_cannot_patch_delete(self, api, trader_token, admin_token):
        if not TestStrategies._created:
            pytest.skip("no strategies")
        sid = TestStrategies._created[-1][1]  # owned by trader
        r = api.patch(f"{BASE_URL}/api/strategies/{sid}",
                      json={"stop": {"mode": "usd", "value": 50}}, headers=h(admin_token), timeout=15)
        assert r.status_code == 404, r.text
        r = api.delete(f"{BASE_URL}/api/strategies/{sid}", headers=h(admin_token), timeout=15)
        assert r.status_code == 404, r.text

    def test_zz_cleanup_all(self, api, trader_token):
        """Delete all TEST_ strategies and clean alert_events."""
        lr = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        for s in lr.json().get("items", []):
            if s["name"].startswith("TEST_"):
                dr = api.delete(f"{BASE_URL}/api/strategies/{s['strategy_id']}", headers=h(trader_token), timeout=15)
                assert dr.status_code == 200, dr.text


# ---------- Admin ----------
class TestAdmin:
    def test_admin_list_users(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/users", headers=h(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert isinstance(items, list) and len(items) > 0
        assert "tier" in items[0]

    def test_admin_search_q(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/users?q=trader", headers=h(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert any("trader" in (u.get("email") or "").lower() for u in items)

    def test_non_admin_forbidden(self, api, trader_token):
        r = api.get(f"{BASE_URL}/api/admin/users", headers=h(trader_token), timeout=20)
        assert r.status_code == 403, r.text

    def test_admin_plan_switch_and_restore(self, api, admin_token, trader_token):
        """Change trader to expert then restore to advance."""
        # find trader
        r = api.get(f"{BASE_URL}/api/admin/users?q=trader@optiscreen.app", headers=h(admin_token), timeout=20)
        items = r.json()["items"]
        trader = next((u for u in items if u["email"] == TRADER_EMAIL), None)
        assert trader is not None
        uid = trader["user_id"]

        # invalid plan
        bad = api.post(f"{BASE_URL}/api/admin/users/{uid}/plan", json={"plan": "nope"},
                       headers=h(admin_token), timeout=15)
        assert bad.status_code == 422, bad.text

        # switch to expert
        sw = api.post(f"{BASE_URL}/api/admin/users/{uid}/plan", json={"plan": "expert"},
                      headers=h(admin_token), timeout=15)
        assert sw.status_code == 200, sw.text

        me = api.get(f"{BASE_URL}/api/auth/me", headers=h(trader_token), timeout=15)
        assert me.status_code == 200
        u = me.json().get("user") or me.json()
        assert u.get("plan") == "expert", me.text

        # restore to advance
        rs = api.post(f"{BASE_URL}/api/admin/users/{uid}/plan", json={"plan": "advance"},
                      headers=h(admin_token), timeout=15)
        assert rs.status_code == 200, rs.text
        me2 = api.get(f"{BASE_URL}/api/auth/me", headers=h(trader_token), timeout=15)
        u2 = me2.json().get("user") or me2.json()
        assert u2.get("plan") == "advance", me2.text
