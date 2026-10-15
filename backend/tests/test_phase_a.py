"""OptiScreen Phase A regression tests - numeric profiles, account types, Phase A screener/analysis."""
import uuid
import pytest


# ---------- /screener/profiles ----------
class TestProfiles:
    def test_profiles_endpoint(self, api, base_url, auth_headers):
        r = api.get(f"{base_url}/api/screener/profiles", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        b = r.json()
        assert set(b["profiles"].keys()) == {"low_low", "low_high", "high_high"}
        for pname, p in b["profiles"].items():
            assert "label" in p and "filters" in p and "strategies" in p
            assert isinstance(p["strategies"], list) and len(p["strategies"]) >= 1
        assert "strategies" in b and len(b["strategies"]) == 13
        assert set(b["account_types"]) == {"cash", "ira", "reg_t", "portfolio_margin"}
        assert "defaults" in b and "account_size" in b["defaults"] and "account_type" in b["defaults"]


# ---------- /screener/best-options ----------
class TestBestOptions:
    @pytest.mark.parametrize("profile", ["low_low", "low_high", "high_high"])
    def test_profile_variants(self, api, base_url, auth_headers, profile):
        payload = {"profile": profile, "period": "month", "limit": 4, "account_size": 50000, "account_type": "reg_t"}
        r = api.post(f"{base_url}/api/screener/best-options", json=payload, headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["profile"] == profile
        assert "stats" in b and "rejected_by" in b["stats"]
        assert isinstance(b["results"], list)
        assert b["filters"]["min_pop"] >= 0
        assert "top_pick" in b
        # Check filters respected
        f = b["filters"]
        for item in b["results"]:
            assert item["pop"] >= f["min_pop"] - 0.1
            if item["max_loss"] is None:
                # only high_high allows undefined risk
                assert profile == "high_high"
            else:
                loss_pct = abs(item["max_loss"]) / 50000 * 100
                assert loss_pct <= f["max_loss_pct"] + 0.1
            assert "liquidity" in item and item["liquidity"].get("grade") in ("High", "Medium", "Low")
            assert "collateral_by_account" in item

    def test_custom_period(self, api, base_url, auth_headers):
        payload = {"profile": "low_low", "period": "custom", "custom_days": 21, "limit": 3}
        r = api.post(f"{base_url}/api/screener/best-options", json=payload, headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        b = r.json()
        for item in b["results"]:
            assert item["expiration_days"] == 21

    def test_slider_min_pop(self, api, base_url, auth_headers):
        payload = {"profile": "low_low", "period": "month", "limit": 5, "min_pop": 80, "account_size": 25000}
        r = api.post(f"{base_url}/api/screener/best-options", json=payload, headers=auth_headers, timeout=90)
        assert r.status_code == 200
        for item in r.json()["results"]:
            assert item["pop"] >= 80

    def test_warm_cache_fast(self, api, base_url, auth_headers):
        """Second call with same payload should be served from cache quickly."""
        import time
        payload = {"profile": "low_low", "period": "week", "limit": 3, "account_size": 25000}
        api.post(f"{base_url}/api/screener/best-options", json=payload, headers=auth_headers, timeout=90)
        t0 = time.time()
        r = api.post(f"{base_url}/api/screener/best-options", json=payload, headers=auth_headers, timeout=10)
        elapsed = time.time() - t0
        assert r.status_code == 200
        assert elapsed < 5, f"Cached scan took {elapsed}s"


# ---------- /screener/find-stocks ----------
class TestFindStocks:
    def test_find_stocks_sectors(self, api, base_url, auth_headers):
        payload = {"profile": "low_low", "expiration": "month", "sectors": ["Tech"], "limit": 3, "account_size": 50000}
        r = api.post(f"{base_url}/api/screener/find-stocks", json=payload, headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        b = r.json()
        for item in b["results"]:
            assert item["sector"] == "Tech"

    def test_legacy_risk_reward_mapping(self, api, base_url, auth_headers):
        payload = {"risk": "high", "reward": "high", "expiration": "month", "sectors": [], "limit": 2}
        r = api.post(f"{base_url}/api/screener/find-stocks", json=payload, headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        assert r.json()["profile"] == "high_high"


# ---------- /screener/ticker-options ----------
class TestTickerOptions:
    def test_auto_strategy(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/ticker-options",
                     json={"ticker": "AAPL", "expiration_range": "month", "strategy": "auto",
                           "account_type": "reg_t", "account_size": 50000},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        for k in ("legs", "collateral_by_account", "pricing", "liquidity", "volatility",
                  "events", "why", "risks", "alternatives", "max_loss", "breakevens"):
            assert k in res, f"missing {k}"
        # Pricing fields
        for k in ("net_mid", "net_fill", "slippage_cost", "fees"):
            assert k in res["pricing"]
        # Volatility
        for k in ("iv", "hv20", "iv_rank"):
            assert k in res["volatility"]
        # Liquidity labeled estimated
        assert res["liquidity"]["estimated"] is True
        # max_loss <= 0 or None
        assert res["max_loss"] is None or res["max_loss"] <= 0
        # alternatives list
        assert isinstance(res["alternatives"], list)

    def test_short_strangle_not_allowed_in_cash(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/ticker-options",
                     json={"ticker": "TSLA", "expiration_range": "month", "strategy": "Short Strangle",
                           "account_type": "cash", "account_size": 50000},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        coll = res["collateral_by_account"]
        assert coll["cash"]["allowed"] is False
        assert coll["ira"]["allowed"] is False
        assert coll["reg_t"]["allowed"] is True

    def test_unknown_strategy_400(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/ticker-options",
                     json={"ticker": "AAPL", "expiration_range": "month", "strategy": "Bogus Strategy"},
                     headers=auth_headers, timeout=20)
        assert r.status_code == 400

    def test_all_13_strategies_price(self, api, base_url, auth_headers):
        strategies = ["Cash Secured Put", "Covered Call", "Bull Put Spread", "Bear Call Spread",
                      "Iron Condor", "Bull Call Spread", "Bear Put Spread", "Long Call Butterfly",
                      "Long Call", "Long Put", "Long Straddle", "Long Strangle", "Short Strangle"]
        for s in strategies:
            r = api.post(f"{base_url}/api/screener/ticker-options",
                         json={"ticker": "SPY", "expiration_range": "month", "strategy": s,
                               "account_type": "reg_t", "account_size": 100000},
                         headers=auth_headers, timeout=60)
            assert r.status_code == 200, f"{s}: {r.status_code} {r.text[:200]}"
            res = r.json()["result"]
            assert res["strategy"] == s
            assert len(res["legs"]) >= 1


# ---------- /screener/stock-analysis ----------
class TestStockAnalysis:
    @pytest.mark.parametrize("purpose", ["day", "swing"])
    def test_short_term_trade_plan(self, api, base_url, auth_headers, purpose):
        r = api.post(f"{base_url}/api/screener/stock-analysis",
                     json={"ticker": "AAPL", "purpose": purpose, "account_size": 50000, "risk_pct": 1.0, "min_rr": 2.0},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        plan = res["trade_plan"]
        for k in ("direction", "entry", "stop", "target", "atr", "reward_risk", "shares", "logic"):
            assert k in plan
        assert plan["direction"] in ("long", "short")
        assert isinstance(plan["logic"], list) and len(plan["logic"]) >= 2
        assert plan["shares"] >= 0
        # Scenarios
        scen = res["scenarios"]
        assert isinstance(scen, list) and len(scen) == 3
        names = {s["name"] for s in scen}
        assert names == {"Bull", "Base", "Bear"}

    def test_long_valuation(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/stock-analysis",
                     json={"ticker": "MSFT", "purpose": "long", "account_size": 100000},
                     headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert "valuation" in res
        assert "valuation_inputs" in res
        v = res["valuation"]
        if v is not None:
            assert "weighted_value" in v
            assert "buy_zone_below" in v
            assert "sell_zone_above" in v
            assert isinstance(v["scenarios"], list) and len(v["scenarios"]) == 3


# ---------- /screener/valuation ----------
class TestValuation:
    def test_recalculate(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/valuation",
                     json={"ticker": "MSFT", "growth_bull": 15, "growth_base": 8, "growth_bear": 2,
                           "discount_pct": 9, "terminal_pe": 20, "w_bull": 25, "w_base": 50, "w_bear": 25},
                     headers=auth_headers, timeout=30)
        # Either 200 with valuation or 400 if EPS not available
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            v = r.json()["valuation"]
            assert "weighted_value" in v


# ---------- /screener/explain ----------
class TestExplain:
    def test_explain_runs(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/screener/explain",
                     json={"ideas": [{"ticker": "AAPL", "strategy": "Iron Condor", "pop": 72, "premium": 1.2}],
                           "context": "neutral monthly scan"},
                     headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        b = r.json()
        assert "summary" in b and "picks" in b


# ---------- /alerts/add validation ----------
class TestAlertValidation:
    def test_price_above_without_threshold_400(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/alerts/add",
                     json={"ticker": "AAPL", "kind": "price_above"},
                     headers=auth_headers, timeout=10)
        assert r.status_code == 400, r.text

    def test_price_above_negative_threshold_422(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/alerts/add",
                     json={"ticker": "AAPL", "kind": "price_above", "threshold": -5},
                     headers=auth_headers, timeout=10)
        assert r.status_code == 422

    def test_earnings_without_threshold_ok(self, api, base_url, auth_headers):
        r = api.post(f"{base_url}/api/alerts/add",
                     json={"ticker": "AAPL", "kind": "earnings"},
                     headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        alert_id = r.json()["alert_id"]
        api.delete(f"{base_url}/api/alerts/{alert_id}", headers=auth_headers, timeout=10)
