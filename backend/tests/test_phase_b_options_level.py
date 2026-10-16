"""Phase B — Discover 70% POP floor + options-level gating + Sell Put/Sell Call strategies."""
import pytest
from conftest import BASE_URL

# A canonical full questionnaire payload. Only overrides change what we're testing.
FULL_Q = {
    "experience": "Intermediate",
    "horizon": "Swing (days-weeks)",
    "risk_tolerance": "Moderate",
    "risk_capacity": "Moderate",
    "capital": "$25k–$100k",
    "max_loss": "5%",
    "options_level": "Level 3+",
    "account_type": "Margin (Reg T)",
    "objectives": "Growth",
    "goal": "Growth",
}

RESTORE_Q = dict(FULL_Q)  # restore at the end


def _set_q(api, auth_headers, overrides):
    body = {"answers": {**FULL_Q, **overrides}}
    r = api.post(f"{BASE_URL}/api/user/questionnaire", json=body, headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text


# ---------- min_pop floor ----------
@pytest.mark.parametrize("profile", ["low_low", "low_high", "high_high"])
def test_best_options_min_pop_floor_70(api, auth_headers, profile):
    """Even if request asks for min_pop=30 the floor must clamp to 70."""
    _set_q(api, auth_headers, {})  # intermediate / level 3
    body = {"profile": profile, "min_pop": 30, "period": "week", "limit": 5}
    r = api.post(f"{BASE_URL}/api/screener/best-options", json=body, headers=auth_headers, timeout=90)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["min_pop_floor"] == 70
    assert data["filters"]["min_pop"] >= 70, data["filters"]
    for idea in data["results"]:
        assert idea["pop"] >= 70, f"{profile} idea {idea['ticker']} pop={idea['pop']}"
    # Response must carry level info + allowed_strategies
    assert "options_level" in data and isinstance(data["options_level"], int)
    assert "options_level_label" in data and data["options_level_label"]
    assert isinstance(data["allowed_strategies"], list)


def test_find_stocks_min_pop_floor_70(api, auth_headers):
    _set_q(api, auth_headers, {})
    body = {"profile": "low_low", "min_pop": 30, "expiration": "month", "limit": 5}
    r = api.post(f"{BASE_URL}/api/screener/find-stocks", json=body, headers=auth_headers, timeout=90)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["filters"]["min_pop"] >= 70
    for idea in data["results"]:
        assert idea["pop"] >= 70


# ---------- level gating via /profiles ----------
def test_profiles_level_advanced_full(api, auth_headers):
    """Advanced experience + Full access -> level 4 with Sell Put/Sell Call/Short Strangle on high_high."""
    _set_q(api, auth_headers, {"experience": "Advanced", "options_level": "Full access"})
    r = api.get(f"{BASE_URL}/api/screener/profiles", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["options_level"] == 4
    hh = data["profiles"]["high_high"]
    assert hh["locked"] is False
    strats = set(hh["strategies"])
    assert {"Sell Put", "Sell Call", "Short Strangle"}.issubset(strats), strats


def test_profiles_beginner_full_capped_to_1(api, auth_headers):
    """Beginner caps level to 1 even with Full access selected."""
    _set_q(api, auth_headers, {"experience": "Beginner", "options_level": "Full access"})
    r = api.get(f"{BASE_URL}/api/screener/profiles", headers=auth_headers, timeout=15)
    data = r.json()
    assert data["options_level"] == 1
    ll_strats = set(data["profiles"]["low_low"]["strategies"])
    # Only CSP + CC at level 1
    assert ll_strats == {"Cash Secured Put", "Covered Call"}, ll_strats
    # Spread / naked profiles should be locked
    assert data["profiles"]["low_high"]["locked"] is True
    assert data["profiles"]["high_high"]["locked"] is True


def test_profiles_intermediate_full_capped_to_3(api, auth_headers):
    """Intermediate caps to level 3 even with Full access."""
    _set_q(api, auth_headers, {"experience": "Intermediate", "options_level": "Full access"})
    r = api.get(f"{BASE_URL}/api/screener/profiles", headers=auth_headers, timeout=15)
    data = r.json()
    assert data["options_level"] == 3
    hh_strats = set(data["profiles"]["high_high"]["strategies"])
    # Level 4 naked strategies must be excluded
    assert "Sell Put" not in hh_strats and "Sell Call" not in hh_strats and "Short Strangle" not in hh_strats
    # Level 2 longs still allowed on high_high
    assert "Long Call" in hh_strats


def test_profiles_advanced_level12_only_level1(api, auth_headers):
    """Advanced + 'Level 1-2' broker approval -> level 1 (approval still gates)."""
    _set_q(api, auth_headers, {"experience": "Advanced", "options_level": "Level 1-2"})
    r = api.get(f"{BASE_URL}/api/screener/profiles", headers=auth_headers, timeout=15)
    data = r.json()
    assert data["options_level"] == 1


# ---------- naked strategies in Ticker Options ----------
def test_ticker_options_sell_put_cash_not_allowed(api, auth_headers):
    _set_q(api, auth_headers, {"experience": "Advanced", "options_level": "Full access"})
    body = {"ticker": "AAPL", "strategy": "Sell Put", "expiration_range": "month", "account_type": "reg_t"}
    r = api.post(f"{BASE_URL}/api/screener/ticker-options", json=body, headers=auth_headers, timeout=60)
    assert r.status_code == 200, r.text
    idea = r.json()["result"]
    assert idea["strategy"] == "Sell Put"
    cba = idea["collateral_by_account"]
    assert cba["cash"]["allowed"] is False
    assert cba["ira"]["allowed"] is False
    assert cba["reg_t"]["allowed"] is True


def test_ticker_options_sell_call_unlimited_loss(api, auth_headers):
    _set_q(api, auth_headers, {"experience": "Advanced", "options_level": "Full access"})
    body = {"ticker": "AAPL", "strategy": "Sell Call", "expiration_range": "month", "account_type": "reg_t"}
    r = api.post(f"{BASE_URL}/api/screener/ticker-options", json=body, headers=auth_headers, timeout=60)
    assert r.status_code == 200, r.text
    idea = r.json()["result"]
    assert idea["strategy"] == "Sell Call"
    # Short naked call: unlimited loss -> engine returns None
    assert idea["max_loss"] is None
    assert idea["unlimited_loss"] is True
    cba = idea["collateral_by_account"]
    assert cba["cash"]["allowed"] is False
    assert cba["ira"]["allowed"] is False
    assert cba["reg_t"]["allowed"] is True


def test_ticker_options_auto_respects_level(api, auth_headers):
    """Beginner cap -> auto strategy must pick a level-1 only strategy."""
    _set_q(api, auth_headers, {"experience": "Beginner", "options_level": "Full access"})
    body = {"ticker": "AAPL", "strategy": "auto", "expiration_range": "month",
            "account_type": "reg_t", "profile": "low_low"}
    r = api.post(f"{BASE_URL}/api/screener/ticker-options", json=body, headers=auth_headers, timeout=60)
    assert r.status_code == 200, r.text
    idea = r.json()["result"]
    assert idea["strategy"] in {"Cash Secured Put", "Covered Call"}, idea["strategy"]
    assert idea["options_level"] == 1


# ---------- high_high scan with level 4 should surface naked strategies ----------
def test_best_options_high_high_advanced_full_contains_naked(api, auth_headers):
    _set_q(api, auth_headers, {"experience": "Advanced", "options_level": "Full access"})
    body = {"profile": "high_high", "period": "month", "limit": 10, "account_type": "reg_t"}
    r = api.post(f"{BASE_URL}/api/screener/best-options", json=body, headers=auth_headers, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["options_level"] == 4
    allowed = set(data["allowed_strategies"])
    assert {"Sell Put", "Sell Call", "Short Strangle"}.issubset(allowed)
    # Every result still ≥70 POP
    for idea in data["results"]:
        assert idea["pop"] >= 70


# ---------- rejected_by stats include new keys ----------
def test_rejected_by_includes_capital_or_options_level(api, auth_headers):
    """Beginner profile scanning high_high should reject by options_level."""
    _set_q(api, auth_headers, {"experience": "Beginner", "options_level": "Full access"})
    body = {"profile": "high_high", "period": "week", "limit": 5}
    r = api.post(f"{BASE_URL}/api/screener/best-options", json=body, headers=auth_headers, timeout=90)
    assert r.status_code == 200, r.text
    data = r.json()
    # Either options_level reject appears, or results are empty (beginner has no HH strategies)
    rej = data["stats"]["rejected_by"]
    # With no strategies, no ideas evaluated; otherwise should contain options_level/capital
    if data["stats"]["ideas_evaluated"] > 0:
        assert any(k in rej for k in ("options_level", "capital", "account_type")), rej


# ---------- restore ----------
def test_zz_restore_questionnaire(api, auth_headers):
    r = api.post(f"{BASE_URL}/api/user/questionnaire",
                 json={"answers": RESTORE_Q}, headers=auth_headers, timeout=10)
    assert r.status_code == 200
