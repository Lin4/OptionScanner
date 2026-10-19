"""Iteration 21 — Admin User Detail, History Insights, Delete/Archive Closed Trades."""
import os
import time
import requests
import pytest

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://optionscope.preview.emergentagent.com").rstrip("/")

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


@pytest.fixture(scope="module")
def trader_uid(api, trader_token):
    r = api.get(f"{BASE_URL}/api/auth/me", headers=h(trader_token), timeout=15)
    u = r.json().get("user") or r.json()
    return u["user_id"]


def expirations(api, tok, tk="AAPL"):
    r = api.get(f"{BASE_URL}/api/chain/{tk}/expirations", headers=h(tok), timeout=30)
    assert r.status_code == 200, r.text
    return [e["date"] for e in r.json()["expirations"]]


def template_legs(api, tok, exp, template, tk="AAPL"):
    r = api.post(f"{BASE_URL}/api/chain/template",
                 json={"ticker": tk, "expiration": exp, "template": template},
                 headers=h(tok), timeout=45)
    assert r.status_code == 200, r.text
    return r.json()["legs"]


def create_strategy(api, tok, name, exp, legs, strategy_type=None, tk="AAPL"):
    payload = {"name": name, "ticker": tk, "expiration": exp, "legs": legs}
    if strategy_type:
        payload["strategy_type"] = strategy_type
    r = api.post(f"{BASE_URL}/api/strategies", json=payload, headers=h(tok), timeout=45)
    assert r.status_code == 200, r.text
    return r.json()


# -------- 1) Admin User Detail --------
class TestAdminUserDetail:
    def test_non_admin_forbidden(self, api, trader_token, trader_uid):
        r = api.get(f"{BASE_URL}/api/admin/users/{trader_uid}", headers=h(trader_token), timeout=20)
        assert r.status_code == 403, r.text

    def test_unknown_uid_404(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/users/user_does_not_exist", headers=h(admin_token), timeout=20)
        assert r.status_code == 404, r.text

    def test_admin_user_detail_shape(self, api, admin_token, trader_uid):
        r = api.get(f"{BASE_URL}/api/admin/users/{trader_uid}", headers=h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # top-level keys
        for key in ("user", "access", "profile", "activity", "strategies", "plan_history", "payments"):
            assert key in d, f"missing {key}"
        # user
        assert d["user"]["user_id"] == trader_uid
        assert d["user"]["email"] == TRADER_EMAIL
        # access.tier
        assert "tier" in d["access"]
        assert d["access"]["tier"] in ("trial", "simple", "advance", "expert", "expired")
        # activity
        act = d["activity"]
        for k in ("scans_14d", "usage_daily", "alerts", "watchlist", "recent_events"):
            assert k in act, f"activity missing {k}"
        assert isinstance(act["usage_daily"], list)
        assert len(act["usage_daily"]) == 14, f"usage_daily must have 14 entries, got {len(act['usage_daily'])}"
        for row in act["usage_daily"]:
            assert "date" in row and "scans" in row
        # strategies
        strat = d["strategies"]
        for k in ("open", "closed", "open_count", "closed_count", "realized_total"):
            assert k in strat, f"strategies missing {k}"
        assert isinstance(strat["open"], list)
        assert isinstance(strat["closed"], list)
        # plan_history: last entry is sign-up
        assert isinstance(d["plan_history"], list)
        assert len(d["plan_history"]) >= 1
        last = d["plan_history"][-1]
        assert last["source"] == "sign-up", f"last plan_history entry should be sign-up, got {last}"
        # payments is a list
        assert isinstance(d["payments"], list)


# -------- 2) Admin Set Plan appends plan_events entry --------
class TestAdminSetPlan:
    def test_admin_plan_change_appears_first_in_history(self, api, admin_token, trader_uid):
        # Change to simple
        r = api.post(f"{BASE_URL}/api/admin/users/{trader_uid}/plan",
                     json={"plan": "simple"}, headers=h(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["plan"] == "simple"
        time.sleep(0.5)
        d = api.get(f"{BASE_URL}/api/admin/users/{trader_uid}", headers=h(admin_token), timeout=20).json()
        first = d["plan_history"][0]
        assert first["plan"] == "simple"
        assert first["source"] == "admin"
        assert first["by"] == ADMIN_EMAIL, f"by should be admin email, got {first.get('by')}"
        # Sign-up still last
        assert d["plan_history"][-1]["source"] == "sign-up"

    def test_restore_advance(self, api, admin_token, trader_uid):
        r = api.post(f"{BASE_URL}/api/admin/users/{trader_uid}/plan",
                     json={"plan": "advance"}, headers=h(admin_token), timeout=20)
        assert r.status_code == 200
        me = api.get(f"{BASE_URL}/api/auth/me", headers=h(api.post(
            f"{BASE_URL}/api/auth/login", json={"email": TRADER_EMAIL, "password": TRADER_PASS}, timeout=15
        ).json()["session_token"]), timeout=15).json()
        u = me.get("user") or me
        assert u.get("plan") == "advance", f"trader plan should be advance, got {u.get('plan')}"


# -------- 3) Strategy auto-classification --------
class TestStrategyClassification:
    created_ids = []

    @pytest.mark.parametrize("template", ["Iron Condor", "Bull Call Spread", "Calendar Call Spread"])
    def test_classify_from_template(self, api, trader_token, template):
        exps = expirations(api, trader_token)
        # Calendar needs 2 expirations; others just use the first
        if template == "Calendar Call Spread":
            if len(exps) < 2:
                pytest.skip("Need 2 expirations")
            legs = template_legs(api, trader_token, exps[0], template)
        else:
            legs = template_legs(api, trader_token, exps[0], template)
        # Create WITHOUT strategy_type so backend auto-classifies
        payload = {"name": f"TEST_cls_{template.replace(' ', '_')}", "ticker": "AAPL",
                   "expiration": exps[0], "legs": legs}
        r = api.post(f"{BASE_URL}/api/strategies", json=payload, headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        doc = r.json()
        TestStrategyClassification.created_ids.append(doc["strategy_id"])
        assert doc["strategy_type"] == template, \
            f"expected {template}, got {doc['strategy_type']}"


# -------- 4) GET /api/strategies insights + closed/archived lists --------
class TestInsights:
    _closed_ids = []
    _open_cleanup = []

    @classmethod
    def setup_class(cls):
        cls._closed_ids = []
        cls._open_cleanup = []

    def test_closed_list_and_insights(self, api, trader_token):
        # Need at least 1 closed trade to see insights. Create+close 1 Bull Call Spread.
        exps = expirations(api, trader_token)
        legs = template_legs(api, trader_token, exps[0], "Bull Call Spread")
        s = create_strategy(api, trader_token, "TEST_insights_bcs", exps[0], legs)
        sid = s["strategy_id"]
        TestInsights._open_cleanup.append(sid)
        cr = api.post(f"{BASE_URL}/api/strategies/{sid}/close", headers=h(trader_token), timeout=45)
        assert cr.status_code == 200, cr.text
        TestInsights._closed_ids.append(sid)

        r = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        assert r.status_code == 200
        d = r.json()
        for k in ("items", "closed", "archived", "insights"):
            assert k in d, f"missing {k}"
        ins = d["insights"]
        assert ins is not None, "insights should not be None when there are closed trades"
        # overall shape
        o = ins["overall"]
        for k in ("count", "wins", "win_rate", "avg_pnl", "avg_win", "avg_loss", "total", "best", "worst"):
            assert k in o, f"overall missing {k}"
        assert o["count"] >= 1
        # win_rate is 0..100
        assert 0 <= o["win_rate"] <= 100
        # by_type
        assert isinstance(ins["by_type"], list) and len(ins["by_type"]) >= 1
        for t in ins["by_type"]:
            for k in ("type", "count", "wins", "win_rate", "avg_pnl", "total", "best", "worst"):
                assert k in t, f"by_type missing {k}"
        # Our new closed is in closed list
        closed_ids = [c["strategy_id"] for c in d["closed"]]
        assert sid in closed_ids

    def test_archive_moves_between_lists(self, api, trader_token):
        assert TestInsights._closed_ids
        sid = TestInsights._closed_ids[0]
        # Archive
        ar = api.post(f"{BASE_URL}/api/strategies/{sid}/archive",
                      json={"archived": True}, headers=h(trader_token), timeout=20)
        assert ar.status_code == 200, ar.text
        assert ar.json()["archived"] is True
        d = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45).json()
        assert sid in [c["strategy_id"] for c in d["archived"]]
        assert sid not in [c["strategy_id"] for c in d["closed"]]
        # Insights still include archived trades
        archived_in_insights = d["insights"]["overall"]["count"]
        assert archived_in_insights >= 1

        # Un-archive
        ar = api.post(f"{BASE_URL}/api/strategies/{sid}/archive",
                      json={"archived": False}, headers=h(trader_token), timeout=20)
        assert ar.status_code == 200
        d = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45).json()
        assert sid in [c["strategy_id"] for c in d["closed"]]
        assert sid not in [c["strategy_id"] for c in d["archived"]]

    def test_archive_open_strategy_rejected_400(self, api, trader_token):
        # Create fresh open strategy, try to archive -> 400
        exps = expirations(api, trader_token)
        legs = template_legs(api, trader_token, exps[0], "Bull Put Spread")
        s = create_strategy(api, trader_token, "TEST_arch_open", exps[0], legs)
        sid = s["strategy_id"]
        TestInsights._open_cleanup.append(sid)
        r = api.post(f"{BASE_URL}/api/strategies/{sid}/archive",
                     json={"archived": True}, headers=h(trader_token), timeout=20)
        assert r.status_code == 400, r.text

    def test_archive_other_users_strategy_404(self, api, trader_token, admin_token):
        # admin trying to archive trader's strategy -> 404
        assert TestInsights._closed_ids
        sid = TestInsights._closed_ids[0]
        r = api.post(f"{BASE_URL}/api/strategies/{sid}/archive",
                     json={"archived": True}, headers=h(admin_token), timeout=20)
        assert r.status_code == 404, r.text

    def test_delete_closed_trade_removes_from_history_and_insights(self, api, trader_token):
        # Create+close another one so we can delete and verify
        exps = expirations(api, trader_token)
        legs = template_legs(api, trader_token, exps[0], "Bull Put Spread")
        s = create_strategy(api, trader_token, "TEST_del_bps", exps[0], legs)
        sid = s["strategy_id"]
        cr = api.post(f"{BASE_URL}/api/strategies/{sid}/close", headers=h(trader_token), timeout=45)
        assert cr.status_code == 200

        before = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45).json()
        before_count = before["insights"]["overall"]["count"]
        before_ids = set(c["strategy_id"] for c in before["closed"])
        assert sid in before_ids

        dr = api.delete(f"{BASE_URL}/api/strategies/{sid}", headers=h(trader_token), timeout=20)
        assert dr.status_code == 200, dr.text

        after = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45).json()
        after_ids = set(c["strategy_id"] for c in after["closed"]) | set(c["strategy_id"] for c in after["archived"])
        assert sid not in after_ids, "deleted strategy should not be in closed/archived"
        assert after["insights"]["overall"]["count"] == before_count - 1


# -------- Cleanup --------
class TestZCleanup:
    def test_cleanup(self, api, trader_token, admin_token, trader_uid):
        # Delete all TEST_ strategies (open and closed)
        lst = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45).json()
        all_strats = lst.get("items", []) + lst.get("closed", []) + lst.get("archived", [])
        for s in all_strats:
            if s["name"].startswith("TEST_"):
                api.delete(f"{BASE_URL}/api/strategies/{s['strategy_id']}", headers=h(trader_token), timeout=15)

        # Restore trader to advance
        api.post(f"{BASE_URL}/api/admin/users/{trader_uid}/plan",
                 json={"plan": "advance"}, headers=h(admin_token), timeout=20)
        me = api.get(f"{BASE_URL}/api/auth/me", headers=h(trader_token), timeout=15).json()
        u = me.get("user") or me
        assert u.get("plan") == "advance"
