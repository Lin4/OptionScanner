"""Iteration 16 — OptiIQ Value: smart-weighted DCF + DDM + Earnings blend.

Covers (per spec):
  - POST /api/screener/stock-analysis purpose='long' for AAPL, NVDA, KO, JPM, DUK, SPY
  - Shape of result.optiiq: value, upside_pct, price, methods[3], weight_reasons[],
    confidence, models_gap_pct, assumptions{...}, stress{low,high,spread_pct,fragility,factors[3]}
  - No 'residual_income' key anywhere.
  - Weights of applicable methods sum to ~100; value ≈ Σ value*weight (rounding tolerance).
  - AAPL / NVDA: ddm applicable=False (tiny dividend).
  - KO / DUK: ddm applicable=True with a positive value.
  - JPM: dcf applicable=False (no meaningful FCF for banks).
  - fair_pe within [10, 30] and = clamp(8.5 + 2*growth_pct).
  - stress.low <= value <= stress.high.
  - SPY -> optiiq is None, no 5xx.
"""
import math
import time

import pytest


def _analyze(api, base_url, headers, ticker):
    return api.post(
        f"{base_url}/api/screener/stock-analysis",
        json={"ticker": ticker, "purpose": "long"},
        headers=headers,
        timeout=90,
    )


def _get_optiiq(resp, ticker):
    assert resp.status_code == 200, f"{ticker} status {resp.status_code}: {resp.text[:200]}"
    body = resp.json().get("result", resp.json())
    return body.get("optiiq"), body


class TestOptiIQSchema:
    """Shape validation + no residual_income key, for every stock ticker that returns a card."""

    @pytest.mark.parametrize("ticker", ["AAPL", "NVDA", "KO", "DUK"])
    def test_schema_and_blend_math(self, api, base_url, auth_headers, ticker):
        time.sleep(1.3)  # Finnhub 60 rpm — serial
        o, body = _get_optiiq(_analyze(api, base_url, auth_headers, ticker), ticker)
        assert o is not None, f"{ticker} optiiq missing (keys={list(body.keys())[:10]})"

        # No residual_income anywhere.
        assert "residual_income" not in o, f"{ticker} must NOT expose residual_income"

        # Top-level fields
        for k in ("value", "upside_pct", "price", "methods", "weight_reasons",
                  "confidence", "models_gap_pct", "assumptions", "stress"):
            assert k in o, f"{ticker} missing {k}"
        assert o["confidence"] in {"High", "Medium", "Low"}, f"{ticker} bad confidence {o['confidence']}"

        # Methods: exactly 3 entries with keys dcf/ddm/earnings
        methods = o["methods"]
        assert isinstance(methods, list) and len(methods) == 3, f"{ticker} methods len={len(methods)}"
        keys = [m["key"] for m in methods]
        assert keys == ["dcf", "ddm", "earnings"], f"{ticker} method keys {keys}"
        for m in methods:
            for sub in ("key", "name", "value", "weight_pct", "applicable"):
                assert sub in m, f"{ticker} method {m.get('key')} missing {sub}"
            assert isinstance(m["applicable"], bool)
            if m["applicable"]:
                assert m["value"] is not None and m["value"] > 0, f"{ticker} applicable {m['key']} value={m['value']}"
                assert m["weight_pct"] > 0, f"{ticker} applicable {m['key']} weight 0"
            else:
                # non-applicable: either value None or weight 0 (skipped)
                assert m["weight_pct"] == 0, f"{ticker} non-applicable {m['key']} has weight {m['weight_pct']}"

        # Weights of applicable methods ~100 (rounding -> allow ±2)
        applicable = [m for m in methods if m["applicable"]]
        assert len(applicable) >= 1, f"{ticker} no applicable method"
        wsum = sum(m["weight_pct"] for m in applicable)
        assert 98 <= wsum <= 102, f"{ticker} applicable weights sum {wsum} (expected ~100)"

        # Blend: value ≈ Σ value * weight_pct / 100 (per-method weights rounded, so give larger tolerance)
        expected = sum(m["value"] * m["weight_pct"] for m in applicable) / 100.0
        tolerance = max(abs(o["value"]) * 0.03, 1.0)  # 3% or $1
        assert abs(o["value"] - expected) <= tolerance, \
            f"{ticker} blend mismatch: got {o['value']} vs expected {expected} (methods={applicable})"

        # weight_reasons: non-empty list of strings
        assert isinstance(o["weight_reasons"], list) and len(o["weight_reasons"]) >= 1
        assert all(isinstance(x, str) for x in o["weight_reasons"])

        # Assumptions
        a = o["assumptions"]
        for k in ("required_return_pct", "growth_pct", "terminal_growth_pct",
                  "fcf_ttm", "net_cash", "dividend_ps", "payout_pct", "eps_ttm", "fair_pe"):
            assert k in a, f"{ticker} assumptions missing {k}"

        # fair_pe within [10, 30] and matches clamp(8.5 + 2*growth_pct)
        fp = a["fair_pe"]
        assert 10 <= fp <= 30, f"{ticker} fair_pe {fp} out of [10, 30]"
        expected_pe = min(max(8.5 + 2 * a["growth_pct"], 10), 30)
        assert abs(fp - expected_pe) <= 0.11, f"{ticker} fair_pe {fp} vs expected {expected_pe}"

        # Stress
        st = o["stress"]
        for k in ("low", "high", "spread_pct", "fragility", "factors"):
            assert k in st, f"{ticker} stress.{k} missing"
        assert isinstance(st["factors"], list) and len(st["factors"]) == 3, \
            f"{ticker} stress.factors len={len(st.get('factors', []))}"
        assert st["fragility"] in {"Robust", "Moderate", "Fragile"}
        assert st["low"] <= o["value"] <= st["high"], \
            f"{ticker} value {o['value']} outside stress [{st['low']}, {st['high']}]"


class TestOptiIQDividendApplicability:
    """DDM applicability: AAPL/NVDA skipped (yield<1% or payout<20%); KO/DUK applicable."""

    @pytest.mark.parametrize("ticker", ["AAPL", "NVDA"])
    def test_ddm_skipped_for_tiny_dividends(self, api, base_url, auth_headers, ticker):
        time.sleep(1.3)
        o, _ = _get_optiiq(_analyze(api, base_url, auth_headers, ticker), ticker)
        assert o is not None, f"{ticker} optiiq missing"
        ddm = next(m for m in o["methods"] if m["key"] == "ddm")
        assert ddm["applicable"] is False, f"{ticker} expected DDM skipped, got {ddm}"
        assert ddm["weight_pct"] == 0, f"{ticker} DDM weight should be 0 when skipped"

    @pytest.mark.parametrize("ticker", ["KO", "DUK"])
    def test_ddm_applicable_for_steady_payers(self, api, base_url, auth_headers, ticker):
        time.sleep(1.3)
        o, _ = _get_optiiq(_analyze(api, base_url, auth_headers, ticker), ticker)
        assert o is not None, f"{ticker} optiiq missing"
        ddm = next(m for m in o["methods"] if m["key"] == "ddm")
        assert ddm["applicable"] is True, f"{ticker} expected DDM applicable, got {ddm}"
        assert ddm["value"] is not None and ddm["value"] > 0


class TestOptiIQBank:
    """JPM: no meaningful free cash flow -> dcf skipped."""

    def test_jpm_dcf_skipped(self, api, base_url, auth_headers):
        time.sleep(1.3)
        o, _ = _get_optiiq(_analyze(api, base_url, auth_headers, "JPM"), "JPM")
        assert o is not None, "JPM optiiq missing"
        dcf = next(m for m in o["methods"] if m["key"] == "dcf")
        assert dcf["applicable"] is False, f"JPM expected DCF skipped, got {dcf}"
        assert dcf["weight_pct"] == 0
        # At least one method is applicable (earnings or ddm)
        applicable = [m for m in o["methods"] if m["applicable"]]
        assert len(applicable) >= 1, "JPM must still produce a value from earnings/DDM"
        assert o["stress"]["low"] <= o["value"] <= o["stress"]["high"]


class TestOptiIQETF:
    """SPY: graceful null, no 5xx."""

    def test_spy_optiiq_null_no_error(self, api, base_url, auth_headers):
        time.sleep(1.3)
        r = _analyze(api, base_url, auth_headers, "SPY")
        assert r.status_code == 200, f"SPY status {r.status_code}: {r.text[:200]}"
        body = r.json().get("result", r.json())
        assert body.get("optiiq") is None, f"SPY optiiq expected None, got {body.get('optiiq')}"
