"""Iteration 23 — OptiScore pipeline (Scan/Rank/Plan/Validate/Track) tests."""
import os
import time
import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

CRED = {"email": "trader@optiscreen.app", "password": "TestPass123!"}


# ------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json=CRED, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    tok = data.get("session_token") or data.get("token")
    assert tok, f"no token: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------------------------------------------------------------- helpers
def _assert_optiscore_shape(result):
    assert "optiscore" in result, "result missing optiscore"
    opt = result["optiscore"]
    assert isinstance(opt, int), f"optiscore not int: {opt!r}"
    assert 0 <= opt <= 100, f"optiscore out of range: {opt}"
    assert "optiscore_grade" in result, "missing optiscore_grade"
    p = result.get("pillars") or {}
    for k in ("expected_return", "risk", "premium_quality", "user_fit"):
        assert k in p, f"pillars missing {k}"
    plan = result.get("plan") or {}
    for k in ("entry", "take_profit", "stop", "invalidation", "time_exit", "sizing"):
        assert k in plan, f"plan missing {k}"
    val = result.get("validation") or {}
    assert "backtest" in val and "costs" in val and "stress" in val, f"validation shape: {list(val.keys())}"
    bt = val["backtest"]
    # backtest may be None if candles missing, but shape should exist as a key
    if bt is not None:
        # hold_to_expiry / managed can be None if not enough history
        assert "hold_to_expiry" in bt or "managed" in bt or "equity" in bt, f"backtest keys: {bt}"
    stress = val["stress"]
    if stress is not None:
        assert "scenarios" in stress or "worst" in stress or "survives" in stress
    scan = result.get("scan") or {}
    for k in ("liquidity", "volatility", "options_activity", "fundamentals", "trend", "flags"):
        assert k in scan, f"scan missing {k}"


# ------------------------------------------------------------- Auth
class TestAuth:
    def test_login_returns_session_token(self):
        r = requests.post(f"{API}/auth/login", json=CRED, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("session_token") or data.get("token"), data


# ------------------------------------------------------------- Ticker Options
class TestTickerOptions:
    @pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "SPY", "JPM"])
    def test_default(self, auth_headers, ticker):
        r = requests.post(f"{API}/screener/ticker-options",
                          json={"ticker": ticker}, headers=auth_headers, timeout=90)
        assert r.status_code == 200, f"{ticker}: {r.status_code} {r.text[:300]}"
        _assert_optiscore_shape(r.json()["result"])

    def test_strategy_override_long_call(self, auth_headers):
        r = requests.post(f"{API}/screener/ticker-options",
                          json={"ticker": "AAPL", "strategy": "Long Call"},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text[:300]
        res = r.json()["result"]
        _assert_optiscore_shape(res)
        assert res.get("strategy") == "Long Call" or "Long Call" in str(res.get("strategy", ""))

    def test_expiration_week(self, auth_headers):
        r = requests.post(f"{API}/screener/ticker-options",
                          json={"ticker": "AAPL", "expiration_range": "week"},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text[:300]
        _assert_optiscore_shape(r.json()["result"])

    def test_expiration_3months(self, auth_headers):
        r = requests.post(f"{API}/screener/ticker-options",
                          json={"ticker": "AAPL", "expiration_range": "3months"},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text[:300]
        _assert_optiscore_shape(r.json()["result"])


# ------------------------------------------------------------- Best Options
class TestBestOptions:
    def test_best_options_shape(self, auth_headers):
        r = requests.post(f"{API}/screener/best-options",
                          json={"profile": "low_low", "period": "month"},
                          headers=auth_headers, timeout=180)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        stats = data.get("stats") or {}
        assert stats.get("universe") == 40, f"expected universe=40, got {stats.get('universe')}"
        results = data.get("results") or []
        assert len(results) > 0, "no results returned"
        # Each result has optiscore/plan/validation/scan
        for res in results[:5]:
            _assert_optiscore_shape(res)
        # Sorted desc by score
        scores = [r.get("optiscore") for r in results if r.get("optiscore") is not None]
        assert scores == sorted(scores, reverse=True), f"scores not desc-sorted: {scores[:10]}"

    def test_three_back_to_back_scans(self, auth_headers):
        """Rate limiter stability — 3 scans, each should return 200 within reasonable time."""
        durations = []
        for i in range(3):
            t0 = time.time()
            r = requests.post(f"{API}/screener/best-options",
                              json={"profile": "low_low", "period": "month"},
                              headers=auth_headers, timeout=120)
            dt = time.time() - t0
            durations.append(dt)
            assert r.status_code == 200, f"scan {i}: {r.status_code} dt={dt:.1f}s"
        # not asserting on exact time, just logging
        print(f"scan durations (s): {[round(d, 1) for d in durations]}")


# ------------------------------------------------------------- Stock Analysis
class TestStockAnalysis:
    @pytest.mark.parametrize("purpose", ["day", "swing", "long"])
    def test_purposes(self, auth_headers, purpose):
        r = requests.post(f"{API}/screener/stock-analysis",
                          json={"ticker": "MSFT", "purpose": purpose},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, f"{purpose}: {r.status_code} {r.text[:300]}"
        data = r.json()
        res = data.get("result") or data
        if purpose in ("day", "swing"):
            tp = res.get("trade_plan") or {}
            for k in ("entry_trigger", "invalidation", "time_stop"):
                assert k in tp, f"{purpose} trade_plan missing {k}; keys={list(tp.keys())}"


# ------------------------------------------------------------- Track Record
class TestTrackRecord:
    def test_track_record_shape(self, auth_headers):
        r = requests.get(f"{API}/track-record", headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        live = data.get("live") or {}
        cal = live.get("calibration") or {}
        assert "active" in cal, f"calibration missing active: {cal}"
        assert cal.get("min_results_per_bucket") == 30, f"min_results_per_bucket={cal.get('min_results_per_bucket')}"
        assert "buckets" in cal
        prog = cal.get("progress") or []
        assert len(prog) == 6, f"expected 6 progress buckets, got {len(prog)}: {prog}"
        for b in prog:
            assert "n" in b and "range" in b
        bt = data.get("backtest") or {}
        if bt.get("status") == "ready":
            # Accuracy block
            acc = bt.get("accuracy") or {}
            for k in ("brier", "calibration_error", "buckets", "verdict"):
                assert k in acc, f"accuracy missing {k}: {list(acc.keys())}"
            # Risk-adjusted
            ra = bt.get("risk_adjusted") or {}
            for k in ("profit_factor", "sharpe", "max_drawdown", "equity"):
                assert k in ra, f"risk_adjusted missing {k}: {list(ra.keys())}"
            assert isinstance(ra.get("equity"), list), "equity should be list"
        else:
            print(f"backtest.status = {bt.get('status')} (not ready — skipping deep assert)")
