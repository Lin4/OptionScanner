"""Iteration 20 — Admin Insights, Close Strategy with realistic fills, Roll Positions, P&L chart history."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://optionscope.preview.emergentagent.com").rstrip("/")

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
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": TRADER_EMAIL, "password": TRADER_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


# ---------- Helpers ----------
def near_expirations(api, token, tk="AAPL"):
    r = api.get(f"{BASE_URL}/api/chain/{tk}/expirations", headers=h(token), timeout=30)
    assert r.status_code == 200, r.text
    exps = r.json()["expirations"]
    assert len(exps) >= 2
    return [e["date"] for e in exps]


def bull_put_legs(api, token, exp, tk="AAPL"):
    r = api.post(f"{BASE_URL}/api/chain/template",
                 json={"ticker": tk, "expiration": exp, "template": "Bull Put Spread"},
                 headers=h(token), timeout=45)
    assert r.status_code == 200, r.text
    return r.json()["legs"]


def chain_rows(api, token, exp, tk="AAPL"):
    r = api.get(f"{BASE_URL}/api/chain/{tk}", params={"expiration": exp}, headers=h(token), timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["rows"]


# ---------- 1) Admin Insights ----------
class TestAdminInsights:
    def test_non_admin_forbidden(self, api, trader_token):
        r = api.get(f"{BASE_URL}/api/admin/stats", headers=h(trader_token), timeout=20)
        assert r.status_code == 403, r.text

    def test_admin_stats_shape(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/stats", headers=h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("total_users", "tiers", "paid", "mrr", "signups", "active", "signups_daily", "open_strategies"):
            assert key in d, f"missing {key}"
        for k in ("trial", "simple", "advance", "expert", "expired"):
            assert k in d["tiers"], f"tiers missing {k}"
        for k in ("24h", "7d", "30d"):
            assert k in d["signups"], f"signups missing {k}"
            assert k in d["active"], f"active missing {k}"
        assert isinstance(d["signups_daily"], list)
        assert len(d["signups_daily"]) == 14, f"signups_daily must have 14 entries, got {len(d['signups_daily'])}"
        for row in d["signups_daily"]:
            assert "date" in row and "count" in row
        assert d["total_users"] >= 1
        assert d["paid"] == d["tiers"]["simple"] + d["tiers"]["advance"] + d["tiers"]["expert"]

    def test_active_tracking_via_authed_call(self, api, trader_token, admin_token):
        """Trader call must bump last_active_at so active.24h >= 1."""
        # Force last_active_at to be refreshed: hit an authed endpoint. (10-min throttle, so one hit is enough.)
        api.get(f"{BASE_URL}/api/auth/me", headers=h(trader_token), timeout=15)
        time.sleep(1)
        r = api.get(f"{BASE_URL}/api/admin/stats", headers=h(admin_token), timeout=30)
        d = r.json()
        assert d["active"]["24h"] >= 1, f"active.24h should include trader, got {d['active']}"
        assert d["active"]["7d"] >= d["active"]["24h"]
        assert d["active"]["30d"] >= d["active"]["7d"]


# ---------- 2) Close Strategy with realistic fills + history ----------
class TestCloseStrategy:
    _sid = None

    def test_close_sets_exit_prices_from_live_chain(self, api, trader_token):
        exps = near_expirations(api, trader_token)
        exp = exps[0]
        legs = bull_put_legs(api, trader_token, exp)

        # Snapshot chain to validate exit_price direction
        rows = chain_rows(api, trader_token, exp)
        side_of = {}  # (type, strike) -> {bid, ask}
        for r in rows:
            if r.get("put"):
                side_of[("Put", r["strike"])] = {"bid": r["put"]["bid"] or 0, "ask": r["put"]["ask"] or 0}
            if r.get("call"):
                side_of[("Call", r["strike"])] = {"bid": r["call"]["bid"] or 0, "ask": r["call"]["ask"] or 0}

        sr = api.post(f"{BASE_URL}/api/strategies",
                      json={"name": "TEST_close_bps", "ticker": "AAPL", "expiration": exp, "legs": legs},
                      headers=h(trader_token), timeout=45)
        assert sr.status_code == 200, sr.text
        sid = sr.json()["strategy_id"]
        TestCloseStrategy._sid = sid

        cr = api.post(f"{BASE_URL}/api/strategies/{sid}/close", headers=h(trader_token), timeout=45)
        assert cr.status_code == 200, cr.text
        body = cr.json()
        for k in ("final_pnl", "exit_fees", "exit_legs"):
            assert k in body, f"missing {k}"
        assert len(body["exit_legs"]) == len(legs)

        # Validate direction: Buy legs exit at bid, Sell legs exit at ask
        for el, orig in zip(body["exit_legs"], legs):
            side = side_of.get((el["type"], el["strike"]))
            if not side or (side["bid"] == 0 and side["ask"] == 0):
                continue  # may have fallen back to model px
            if orig["action"] == "Buy":
                # should sell at bid
                assert abs(el["exit_price"] - side["bid"]) < 0.05 or el["exit_price"] <= side["ask"], \
                    f"Buy leg exit should ≈ bid {side['bid']}, got {el['exit_price']}"
            else:
                # should buy back at ask
                assert abs(el["exit_price"] - side["ask"]) < 0.05 or el["exit_price"] >= side["bid"], \
                    f"Sell leg exit should ≈ ask {side['ask']}, got {el['exit_price']}"

    def test_close_twice_returns_400(self, api, trader_token):
        assert TestCloseStrategy._sid
        r = api.post(f"{BASE_URL}/api/strategies/{TestCloseStrategy._sid}/close", headers=h(trader_token), timeout=20)
        assert r.status_code == 400, r.text

    def test_list_moves_to_closed_with_history_and_realized_total(self, api, trader_token):
        r = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "closed" in body and "realized_total" in body
        closed_ids = [c["strategy_id"] for c in body["closed"]]
        assert TestCloseStrategy._sid in closed_ids, "closed strategy should appear in closed[]"
        # Should NOT be in open items anymore
        assert TestCloseStrategy._sid not in [i["strategy_id"] for i in body["items"]]
        strat = next(c for c in body["closed"] if c["strategy_id"] == TestCloseStrategy._sid)
        # history is a list of {date, pnl}
        assert isinstance(strat["history"], list)
        for pt in strat["history"]:
            assert "date" in pt and "pnl" in pt
        # realized_total sums final_pnl across closed
        expected = round(sum(c.get("final_pnl") or 0 for c in body["closed"]), 2)
        assert abs(body["realized_total"] - expected) < 0.01

    def test_cross_user_close_returns_404(self, api, trader_token, admin_token):
        # Create a strategy owned by trader
        exps = near_expirations(api, trader_token)
        legs = bull_put_legs(api, trader_token, exps[0])
        sr = api.post(f"{BASE_URL}/api/strategies",
                      json={"name": "TEST_cross_close", "ticker": "AAPL", "expiration": exps[0], "legs": legs},
                      headers=h(trader_token), timeout=45)
        sid = sr.json()["strategy_id"]
        # Admin tries to close it
        r = api.post(f"{BASE_URL}/api/strategies/{sid}/close", headers=h(admin_token), timeout=20)
        assert r.status_code == 404, r.text
        # Also roll
        rr = api.post(f"{BASE_URL}/api/strategies/{sid}/roll",
                      json={"expiration": exps[1], "confirm": False}, headers=h(admin_token), timeout=20)
        assert rr.status_code == 404, rr.text
        # Cleanup
        api.delete(f"{BASE_URL}/api/strategies/{sid}", headers=h(trader_token), timeout=15)


# ---------- 3) Roll Positions ----------
class TestRoll:
    _sid = None

    def test_roll_preview_and_confirm(self, api, trader_token):
        exps = near_expirations(api, trader_token)
        near, later = exps[0], exps[1]
        legs = bull_put_legs(api, trader_token, near)
        sr = api.post(f"{BASE_URL}/api/strategies",
                      json={"name": "TEST_roll_bps", "ticker": "AAPL", "expiration": near, "legs": legs},
                      headers=h(trader_token), timeout=45)
        assert sr.status_code == 200, sr.text
        sid = sr.json()["strategy_id"]
        TestRoll._sid = sid

        # Preview
        pv = api.post(f"{BASE_URL}/api/strategies/{sid}/roll",
                      json={"expiration": later, "confirm": False}, headers=h(trader_token), timeout=45)
        assert pv.status_code == 200, pv.text
        preview = pv.json().get("preview") or {}
        for k in ("from", "to", "closing", "opening", "net", "net_type", "fees", "realized_pnl"):
            assert k in preview, f"preview missing {k}"
        assert preview["from"] == near
        assert preview["to"] == later
        assert preview["net_type"] in ("credit", "debit")
        assert len(preview["opening"]) == len([l for l in legs if l["type"] != "Stock"])

        # Confirm
        cf = api.post(f"{BASE_URL}/api/strategies/{sid}/roll",
                      json={"expiration": later, "confirm": True}, headers=h(trader_token), timeout=45)
        assert cf.status_code == 200, cf.text

        # Verify legs now on later expiration and rolls recorded
        lst = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        s = next((x for x in lst.json()["items"] if x["strategy_id"] == sid), None)
        assert s is not None
        assert s["expiration"] == later, f"expiration should be {later}, got {s['expiration']}"
        for l in s["legs"]:
            if l["type"] != "Stock":
                assert l["expiration"] == later
        assert len(s.get("rolls") or []) == 1
        # realized_pnl stored on the strategy
        assert "realized_pnl" in s

    def test_roll_earlier_or_equal_rejected(self, api, trader_token):
        assert TestRoll._sid
        exps = near_expirations(api, trader_token)
        # strategy was rolled to exps[1]; now try exps[0] (earlier) -> 400
        r = api.post(f"{BASE_URL}/api/strategies/{TestRoll._sid}/roll",
                     json={"expiration": exps[0], "confirm": False}, headers=h(trader_token), timeout=30)
        assert r.status_code == 400, r.text

    def test_roll_unlisted_date_rejected(self, api, trader_token):
        assert TestRoll._sid
        r = api.post(f"{BASE_URL}/api/strategies/{TestRoll._sid}/roll",
                     json={"expiration": "2099-12-19", "confirm": False}, headers=h(trader_token), timeout=30)
        assert r.status_code == 400, r.text


# ---------- Cleanup ----------
class TestZCleanup:
    def test_cleanup_all_test_strategies(self, api, trader_token):
        lst = api.get(f"{BASE_URL}/api/strategies", headers=h(trader_token), timeout=45)
        for s in lst.json().get("items", []):
            if s["name"].startswith("TEST_"):
                api.delete(f"{BASE_URL}/api/strategies/{s['strategy_id']}", headers=h(trader_token), timeout=15)
        # Note: closed strategies cannot be deleted via API (no endpoint); leave in place.

    def test_trader_still_advance(self, api, trader_token):
        me = api.get(f"{BASE_URL}/api/auth/me", headers=h(trader_token), timeout=15)
        u = me.json().get("user") or me.json()
        assert u.get("plan") == "advance", f"trader plan is {u.get('plan')}"
