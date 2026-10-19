"""Scan reports, per-idea validation (own-history backtest, cost check, stress tests) and IV-history ranks."""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional

from engine import (RISK_FREE, build_legs, price_legs, payoff_exp, hist_vol, atr, _is_opt, _sign, _clip)
from options_math import bs_greeks


# ---------------------------------------------------------------- 1. scan
def iv_rank_from_history(hist: List[float], current: Optional[float]) -> Optional[Dict[str, Any]]:
    """True IV rank/percentile once ≥20 daily ATM-IV snapshots exist."""
    if current is None or len(hist) < 20:
        return None
    lo, hi = min(hist + [current]), max(hist + [current])
    return {"iv_rank": round((current - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0,
            "iv_percentile": round(sum(1 for v in hist if v <= current) / len(hist) * 100, 1),
            "days": len(hist), "low": round(lo, 4), "high": round(hi, 4)}


def _score(v: Optional[float], lo: float, hi: float) -> Optional[float]:
    return None if v is None else _clip((v - lo) / (hi - lo) * 100)


def fundamentals_quality(m: Dict[str, Any], sector: str) -> Dict[str, Any]:
    if sector == "Index":
        return {"score": None, "label": "ETF — fundamentals not applicable", "parts": {}}
    de = m.get("debt_to_equity_q")
    parts = {"ROE": _score(m.get("roe_ttm"), 0, 25), "Net margin": _score(m.get("net_profit_margin"), 0, 25),
             "Revenue growth": _score(m.get("revenue_growth_ttm"), -5, 20),
             "Low debt": None if de is None else _clip((3 - de) / 2.5 * 100)}
    vals = [v for v in parts.values() if v is not None]
    sc = round(sum(vals) / len(vals)) if vals else None
    label = "—" if sc is None else "Strong" if sc >= 70 else "Average" if sc >= 45 else "Weak"
    return {"score": sc, "label": label, "parts": {k: round(v) for k, v in parts.items() if v is not None}}


def options_activity(chain: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not chain:
        return None
    rows = [("Call", k, o) for k, o in chain["calls"].items()] + [("Put", k, o) for k, o in chain["puts"].items()]
    cv = sum(o.get("volume") or 0 for t, _, o in rows if t == "Call")
    pv = sum(o.get("volume") or 0 for t, _, o in rows if t == "Put")
    coi = sum(o.get("open_interest") or 0 for t, _, o in rows if t == "Call")
    poi = sum(o.get("open_interest") or 0 for t, _, o in rows if t == "Put")
    unusual = sorted(
        [{"type": t, "strike": k, "volume": o.get("volume") or 0, "open_interest": o.get("open_interest") or 0}
         for t, k, o in rows if (o.get("volume") or 0) >= max(500, (o.get("open_interest") or 0))],
        key=lambda x: -x["volume"])[:3]
    vol_oi = (cv + pv) / max(coi + poi, 1)
    pc = pv / cv if cv else None
    tone = "—" if pc is None else "Bearish tilt" if pc > 1.2 else "Bullish tilt" if pc < 0.6 else "Balanced"
    return {"expiration": chain["expiration"], "call_volume": cv, "put_volume": pv, "call_oi": coi, "put_oi": poi,
            "put_call_volume": round(pc, 2) if pc is not None else None,
            "put_call_oi": round(poi / coi, 2) if coi else None, "volume_to_oi": round(vol_oi, 2),
            "activity": "Heavy" if vol_oi > 0.5 else "Normal" if vol_oi > 0.1 else "Quiet", "tone": tone, "unusual": unusual}


def scan_report(snap: Dict[str, Any], iv_hist: List[float]) -> Dict[str, Any]:
    c = snap.get("candles") or []
    S = snap["price"]
    vols = [x.get("v") or 0 for x in c[-20:]]
    adv = sum(vols) / len(vols) if vols else 0
    dollar = adv * S
    liq = "High" if dollar >= 5e8 else "Medium" if dollar >= 5e7 else "Low"
    closes = [x["c"] for x in c]
    ret = lambda n: round((closes[-1] / closes[-n - 1] - 1) * 100, 1) if len(closes) > n else None
    sma = lambda n: sum(closes[-n:]) / n if len(closes) >= n else None
    s20, s50 = sma(20), sma(50)
    trend = "Uptrend" if s20 and s50 and S > s20 > s50 else "Downtrend" if s20 and s50 and S < s20 < s50 else "Sideways"
    chain = snap.get("chain")
    v = snap["vol"]
    atm = (chain or {}).get("atm_iv")
    ivr = iv_rank_from_history(iv_hist, atm)
    a = atr(c)
    act = options_activity(chain)
    fq = fundamentals_quality(snap.get("metrics") or {}, snap["info"].get("sector", ""))
    flags = []
    if liq == "Low":
        flags.append("Thin share volume — wider spreads and slippage likely")
    if atm and v.get("hv20") and atm / v["hv20"] > 1.3:
        flags.append("Options price in more movement than the stock has shown — rich premium")
    if atm and v.get("hv20") and atm / v["hv20"] < 0.85:
        flags.append("Options are cheap vs realized movement")
    if act and act["unusual"]:
        u = act["unusual"][0]
        flags.append(f"Unusual activity: {u['volume']:,} {u['type'].lower()}s at ${u['strike']:g} (OI {u['open_interest']:,})")
    if snap.get("earnings_date"):
        flags.append(f"Next earnings {snap['earnings_date']}")
    return {
        "liquidity": {"avg_volume_20d": int(adv), "avg_dollar_volume": round(dollar), "grade": liq},
        "volatility": {"atm_iv": atm, "hv20": v.get("hv20"), "hv60": v.get("hv60"),
                       "iv_hv_ratio": round(atm / v["hv20"], 2) if atm and v.get("hv20") else v.get("iv_vs_hv"),
                       "iv_rank": ivr["iv_rank"] if ivr else v.get("iv_rank"),
                       "iv_percentile": ivr["iv_percentile"] if ivr else v.get("iv_percentile"),
                       "iv_rank_source": f"{ivr['days']} days of recorded implied vol" if ivr else
                                         f"Historical-vol proxy (IV history builds daily — {len(iv_hist)}/20 days)",
                       "atr_pct": round(a / S * 100, 2) if a else None},
        "options_activity": act,
        "fundamentals": fq,
        "trend": {"label": trend, "return_1m_pct": ret(21), "return_3m_pct": ret(63)},
        "flags": flags,
    }


# ---------------------------------------------------------------- 4. validate
def _position_value(legs: List[Dict], S: float, days_left: float, iv: float) -> float:
    v = 0.0
    for l in legs:
        s, q = _sign(l), l.get("qty", 1)
        if not _is_opt(l):
            v += s * q * S
        elif days_left <= 0:
            K = float(l["strike"])
            v += s * q * (max(S - K, 0) if l["type"].lower() == "call" else max(K - S, 0))
        else:
            v += s * q * bs_greeks(S, float(l["strike"]), days_left / 365, iv, r=RISK_FREE, call=l["type"].lower() == "call")["price"]
    return v


def _trade_stats(pnls: List[float]) -> Dict[str, Any]:
    if not pnls:
        return {"trades": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    cum = peak = dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return {"trades": len(pnls), "win_rate": round(len(wins) / len(pnls) * 100, 1), "avg_pnl": round(sum(pnls) / len(pnls), 2),
            "total_pnl": round(sum(pnls), 2), "worst": round(min(pnls), 2), "best": round(max(pnls), 2),
            "max_drawdown": round(dd, 2),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None}


def backtest_same(i: Dict[str, Any], candles: List[Dict], plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Re-run this exact strategy (same structure & strike distance) on the ticker's own history.
    Entries every 5 trading days, priced with the model + slippage + fees; settled hold-to-expiry and with the plan's rules."""
    closes = [c["c"] for c in candles]
    dte = max(i["expiration_days"], 1)
    H = max(1, round(dte * 252 / 365))
    hold, managed = [], []
    rules = (plan or {}).get("rules") or {}
    for t in range(60, len(closes) - H, 5):
        S = closes[t]
        hv20 = hist_vol(closes[: t + 1], 20) or 0.3
        hv60 = hist_vol(closes[: t + 1], 60) or hv20
        iv = min(max((0.6 * hv20 + 0.4 * hv60) * 1.10, 0.12), 1.50)
        try:
            legs, pr = price_legs(i["ticker"], build_legs(i["strategy"], S, iv, dte, "", i.get("scale", 1.0)), S, iv, dte)
        except Exception:
            continue
        prem, fees = pr["net_fill"], pr["fees"]
        entry_val = -prem  # value of the position per share at entry (debit > 0, credit < 0)
        hold.append(round(payoff_exp(closes[t + H], legs, prem) - fees, 2))
        if rules:
            # this trade's own thresholds (payoff is piecewise-linear: extremes sit at strikes or the ends)
            kinks = [0.01, S * 3] + [float(l["strike"]) for l in legs if _is_opt(l)]
            vals = [payoff_exp(x, legs, prem) for x in kinks]
            unl = payoff_exp(S * 3, legs, prem) < payoff_exp(S * 3.1, legs, prem)
            ml_t, mp_t, p100 = -min(min(vals), 0), max(vals), abs(prem) * 100
            if rules["credit"]:
                tp, sl = 0.5 * p100, min(2 * p100, ml_t) if ml_t else 2 * p100
            else:
                tp, sl = (p100 if unl else min(p100, 0.5 * mp_t)), 0.5 * p100
            out = None
            for d in range(1, H + 1):
                left = dte - d * 365 / 252
                pnl = (_position_value(legs, closes[t + d], max(left, 0), iv) - entry_val) * 100 - 2 * fees
                if pnl >= tp - 2 * fees or pnl <= -(sl + 2 * fees) or left <= rules["time_exit_days_left"]:
                    out = pnl
                    break
            managed.append(round(out if out is not None else hold[-1], 2))
    def curve(xs: List[float]) -> List[float]:
        out, c = [], 0.0
        for x in xs:
            c += x
            out.append(round(c, 2))
        return out

    return {"hold_to_expiry": _trade_stats(hold), "managed": _trade_stats(managed) if rules else None,
            "equity": {"hold": curve(hold), "managed": curve(managed) if rules else None},
            "model_pop": i["pop"], "period_days": len(closes), "holding_days": H,
            "method": f"Same {i['strategy']} rules re-run every 5 trading days over {len(closes)} days of {i['ticker']} history "
                      f"(model prices from that day's volatility, slippage & fees). Managed = take-profit / stop / time-exit rules applied daily."}


def cost_check(i: Dict[str, Any]) -> Dict[str, Any]:
    p = i["pricing"]
    slip = abs(p["slippage_cost"])
    rt = round(2 * (slip + p["fees"]), 2)  # entry + exit
    base = i["max_profit"] if i["max_profit"] is not None else i["premium"] * 100
    pct = rt / base * 100 if base else 100.0
    grade = "Low" if pct <= 10 else "Moderate" if pct <= 25 else "High"
    return {"fees_round_trip": round(2 * p["fees"], 2), "slippage_round_trip": round(2 * slip, 2), "total_round_trip": rt,
            "pct_of_max_profit": round(pct, 1), "grade": grade,
            "note": {"Low": "Costs barely dent the edge.", "Moderate": "Costs eat a noticeable share — use limit orders at mid.",
                     "High": "Costs consume most of the reward — consider a more liquid ticker or wider structure."}[grade]}


def stress_tests(i: Dict[str, Any]) -> Dict[str, Any]:
    legs, S, dte = i["legs"], i["price"], max(i["expiration_days"], 1)
    iv = i["iv_assumed"]
    fees = i["pricing"]["fees"]
    entry = sum(_sign(l) * l.get("qty", 1) * (l["fill"] if _is_opt(l) else float(l["strike"])) for l in legs)
    wk = iv * math.sqrt(5 / 252)

    def pnl(Sx: float, days_left: float, ivx: float) -> float:
        return round((_position_value(legs, Sx, days_left, ivx) - entry) * 100 - fees, 2)

    rows = [
        ("Crash −2σ this week", S * math.exp(-2 * wk), max(dte - 5, 0), iv * 1.5),
        ("Drop −1σ this week", S * math.exp(-wk), max(dte - 5, 0), iv * 1.15),
        ("Overnight gap −8%", S * 0.92, dte, iv * 1.4),
        ("Rally +1σ this week", S * math.exp(wk), max(dte - 5, 0), iv * 0.95),
        ("Squeeze +2σ this week", S * math.exp(2 * wk), max(dte - 5, 0), iv * 1.1),
        ("IV spike +50%, price flat", S, dte, iv * 1.5),
        ("IV crush −30%, price flat", S, dte, iv * 0.7),
        ("Half the time passes, flat", S, dte / 2, iv),
    ]
    out = [{"name": n, "price": round(px, 2), "pnl": pnl(px, d, v)} for n, px, d, v in rows]
    worst = min(out, key=lambda r: r["pnl"])
    return {"scenarios": out, "worst": worst,
            "survives": all(r["pnl"] > -(abs(i["max_loss"]) if i["max_loss"] is not None else 1e12) * 1.0001 for r in out)}


def validate_idea(i: Dict[str, Any], candles: List[Dict], plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    bt = backtest_same(i, candles, plan) if len(candles) >= 80 else None
    verdict = []
    if bt and bt["hold_to_expiry"].get("trades"):
        h = bt["hold_to_expiry"]
        gap = h["win_rate"] - i["pop"]
        verdict.append(f"History: won {h['win_rate']}% of {h['trades']} similar trades vs {i['pop']}% predicted"
                       + (" — in line" if abs(gap) <= 10 else " — model looks optimistic here" if gap < 0 else " — history did better"))
    return {"backtest": bt, "costs": cost_check(i), "stress": stress_tests(i), "verdict": verdict}
