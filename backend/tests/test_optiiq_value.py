"""Iteration 15 — OptiIQ Value: DCF + Residual Income blend, multiples sanity, stress test.

Covers:
  - AAPL / KO / NVDA / JPM / SPY via POST /api/screener/stock-analysis purpose='long'
  - Shape of result.optiiq (value, confidence, weights, dcf, residual_income, sanity, stress)
  - 60/40 blend math and stress bounds
  - Bank (JPM): no meaningful FCF -> dcf.value None, weights={residual_income:100}
  - ETF (SPY): optiiq is None without 5xx error
"""
import time

import pytest


def _analyze(api, base_url, headers, ticker):
    r = api.post(
        f"{base_url}/api/screener/stock-analysis",
        json={"ticker": ticker, "purpose": "long"},
        headers=headers,
        timeout=90,
    )
    return r


class TestOptiIQValueStocks:
    """DCF + RI blend path (AAPL / KO / NVDA)."""

    @pytest.mark.parametrize("ticker", ["AAPL", "KO", "NVDA"])
    def test_optiiq_shape_and_blend(self, api, base_url, auth_headers, ticker):
        time.sleep(1.1)  # serial to respect Finnhub 60 rpm
        r = _analyze(api, base_url, auth_headers, ticker)
        assert r.status_code == 200, f"{ticker} status {r.status_code}: {r.text[:200]}"
        body = r.json().get("result", r.json())
        o = body.get("optiiq")
        assert o is not None, f"{ticker} optiiq missing (body keys={list(body.keys())[:12]})"

        # top-level fields
        for key in ("value", "upside_pct", "price", "weights", "confidence", "dcf", "residual_income", "sanity", "stress"):
            assert key in o, f"{ticker} missing {key}"
        assert o["confidence"] in {"High", "Medium", "Low"}, f"{ticker} bad confidence {o['confidence']}"

        # dcf sub-fields
        for key in ("value", "fcf_ttm", "growth_pct", "discount_pct", "net_cash"):
            assert key in o["dcf"], f"{ticker} dcf.{key} missing"
        # residual income sub-fields
        for key in ("value", "book_value_ps", "roe_pct"):
            assert key in o["residual_income"], f"{ticker} residual_income.{key} missing"

        # stress sub-fields
        for key in ("low", "high", "spread_pct", "fragility", "factors"):
            assert key in o["stress"], f"{ticker} stress.{key} missing"
        assert isinstance(o["stress"]["factors"], list) and len(o["stress"]["factors"]) == 3, \
            f"{ticker} expected 3 stress factors, got {len(o['stress']['factors'])}"

        # Both DCF and RI should exist for these equities
        dcf_v, ri_v = o["dcf"]["value"], o["residual_income"]["value"]
        assert dcf_v is not None, f"{ticker} dcf.value None (expected a number)"
        assert ri_v is not None, f"{ticker} residual_income.value None"
        # 60/40 blend within rounding
        expected = round(0.6 * dcf_v + 0.4 * ri_v, 2)
        assert abs(o["value"] - expected) <= 0.05, \
            f"{ticker} blend mismatch: got {o['value']} vs expected {expected} (dcf={dcf_v}, ri={ri_v})"
        assert o["weights"] == {"dcf": 60, "residual_income": 40}, f"{ticker} weights {o['weights']}"

        # stress bounds
        assert o["stress"]["low"] <= o["value"] <= o["stress"]["high"], \
            f"{ticker} value {o['value']} outside stress [{o['stress']['low']}, {o['stress']['high']}]"

        # sanity: implied P/E present when EPS available
        if o.get("sanity"):
            assert "implied_pe" in o["sanity"]
            assert o["sanity"]["status"] in {"within", "above", "below"}


class TestOptiIQBank:
    """JPM: no FCF -> residual-income-only path."""

    def test_jpm_residual_only(self, api, base_url, auth_headers):
        time.sleep(1.1)
        r = _analyze(api, base_url, auth_headers, "JPM")
        assert r.status_code == 200, f"JPM status {r.status_code}"
        o = r.json().get("result", {}).get("optiiq")
        assert o is not None, "JPM optiiq missing"
        assert o["dcf"]["value"] is None, f"JPM dcf.value should be None, got {o['dcf']['value']}"
        assert o["weights"] == {"residual_income": 100}, f"JPM weights {o['weights']}"
        assert o["residual_income"]["value"] is not None, "JPM residual_income.value None"
        assert abs(o["value"] - o["residual_income"]["value"]) <= 0.05
        assert o["stress"]["low"] <= o["value"] <= o["stress"]["high"]


class TestOptiIQETF:
    """SPY: graceful null — no 5xx."""

    def test_spy_optiiq_null_no_error(self, api, base_url, auth_headers):
        time.sleep(1.1)
        r = _analyze(api, base_url, auth_headers, "SPY")
        assert r.status_code == 200, f"SPY status {r.status_code}: {r.text[:200]}"
        body = r.json().get("result", r.json())
        # Either explicitly None or missing — both acceptable for ETFs
        assert body.get("optiiq") is None, f"SPY optiiq expected None, got {body.get('optiiq')}"
