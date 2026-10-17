"""Live option chain browser + strategy builder (payoff curve, P&L heatmap, POP, Greeks)."""
from __future__ import annotations
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Literal, Optional

import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

import tradier
from engine import (RISK_FREE, FEE_PER_CONTRACT, build_legs, snap_legs, payoff_exp, payoff_stats,
                    probability_and_ev, STRATEGY_META)
from options_math import bs_greeks

TICKER_RE = re.compile(r"^[A-Z.]{1,10}$")
TEMPLATES = ["Bull Call Spread", "Bear Put Spread", "Bull Put Spread", "Bear Call Spread", "Iron Condor",
             "Long Call Butterfly", "Long Straddle", "Long Strangle", "Covered Call", "Cash Secured Put",
             "Long Call", "Long Put"]


class LegIn(BaseModel):
    action: Literal["Buy", "Sell"]
    type: Literal["Call", "Put", "Stock"]
    strike: float = Field(gt=0, le=1e6)
    qty: int = Field(default=1, ge=1, le=100)
    price: float = Field(ge=0, le=1e6)  # entry price per share (option premium or stock price)
    iv: Optional[float] = Field(default=None, gt=0, le=10)


class AnalyzeReq(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    expiration: str
    legs: List[LegIn] = Field(min_length=1, max_length=8)


class TemplateReq(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    expiration: str
    template: str


def _tk(t: str) -> str:
    t = t.upper().strip()
    if not TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    return t


def _exp(e: str) -> date:
    try:
        return date.fromisoformat(e)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expiration date")


def _side(o: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not o:
        return None
    g = o.get("greeks") or {}
    bid, ask = o.get("bid") or 0, o.get("ask") or 0
    return {"bid": bid, "ask": ask, "last": o.get("last"), "mid": round((bid + ask) / 2, 2) if ask else None,
            "iv": g.get("mid_iv") or g.get("smv_vol"), "delta": g.get("delta"),
            "oi": o.get("open_interest") or 0, "volume": o.get("volume") or 0, "symbol": o.get("symbol")}


def _value_at(legs: List[Dict], Sn: float, days_left: float) -> float:
    """Position value per share-unit at price Sn with days_left to expiration."""
    v = 0.0
    for l in legs:
        s, q, K = (1 if l["action"] == "Buy" else -1), l["qty"], l["strike"]
        if l["type"] == "Stock":
            v += s * q * Sn
        elif days_left <= 0:
            v += s * q * (max(Sn - K, 0) if l["type"] == "Call" else max(K - Sn, 0))
        else:
            v += s * q * bs_greeks(Sn, K, days_left / 365, l["iv"], r=RISK_FREE, call=l["type"] == "Call")["price"]
    return v


def analyze_position(legs: List[Dict], S: float, dte: int, exp: date) -> Dict[str, Any]:
    opts = [l for l in legs if l["type"] != "Stock"]
    contracts = sum(l["qty"] for l in opts)
    fees = round(contracts * FEE_PER_CONTRACT, 2)
    entry = sum((1 if l["action"] == "Buy" else -1) * l["qty"] * l["price"] for l in legs)
    # engine conventions: options carry premium_net, stock legs use strike as entry price
    eng = [{"action": l["action"], "type": l["type"], "qty": l["qty"],
            "strike": l["price"] if l["type"] == "Stock" else l["strike"]} for l in legs]
    premium_net = -sum((1 if l["action"] == "Buy" else -1) * l["qty"] * l["price"] for l in opts)
    stats = payoff_stats(eng, S, premium_net, fees)
    avg_iv = sum(l["iv"] for l in opts) / len(opts) if opts else 0.3
    prob = probability_and_ev(eng, S, premium_net, fees, avg_iv, avg_iv, max(dte, 1))

    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in legs:
        s = (1 if l["action"] == "Buy" else -1) * l["qty"]
        if l["type"] == "Stock":
            greeks["delta"] += s
            continue
        g = bs_greeks(S, l["strike"], max(dte, 0.5) / 365, l["iv"], r=RISK_FREE, call=l["type"] == "Call")
        for k in greeks:
            greeks[k] += s * g[k]
    greeks = {k: round(v * 100, 2) for k, v in greeks.items()}  # per position (×100 multiplier)

    pnl = lambda Sn, d: round((_value_at(legs, Sn, d) - entry) * 100 - fees, 2)
    strikes = [l["strike"] for l in opts] or [S]
    lo, hi = min(min(strikes), S) * 0.8, max(max(strikes), S) * 1.2
    curve = [{"price": round(lo + (hi - lo) * i / 60, 2)} for i in range(61)]
    for p in curve:
        p["expiry"] = pnl(p["price"], 0)
        p["today"] = pnl(p["price"], dte)

    n = min(6, max(dte, 1))
    days = sorted({round(dte * i / (n - 1)) if n > 1 else dte for i in range(n)}) if dte > 0 else [0]
    cols = [{"date": (date.today() + timedelta(days=d)).isoformat(), "days_left": dte - d} for d in days]
    moves = [0.15, 0.10, 0.06, 0.03, 0.0, -0.03, -0.06, -0.10, -0.15]
    rows = [{"move_pct": round(m * 100), "price": round(S * (1 + m), 2),
             "pnl": [pnl(S * (1 + m), c["days_left"]) for c in cols]} for m in moves]

    return {
        "price": round(S, 2), "expiration": exp.isoformat(), "dte": dte,
        "net_premium": round(premium_net * 100, 2), "premium_type": "credit" if premium_net > 0 else "debit",
        "cost_basis": round(entry * 100, 2), "fees": fees,
        "max_profit": stats["max_profit"], "max_loss": stats["max_loss"], "breakevens": stats["breakevens"],
        "unlimited_profit": stats["unlimited_profit"], "unlimited_loss": stats["unlimited_loss"],
        "pop": prob["pop"], "expected_value": prob["expected_value"], "avg_iv": round(avg_iv, 4),
        "greeks": greeks, "curve": curve, "heatmap": {"columns": cols, "rows": rows},
    }


def register(api_router, *, get_user: Callable, get_quote: Callable):
    async def spot(client, tk) -> float:
        q = await get_quote(client, tk)
        if not isinstance(q, dict) or not q.get("price"):
            raise HTTPException(status_code=404, detail=f"No live quote found for {tk}")
        return float(q["price"])

    async def load_chain(client, tk: str, exp: str, S: float) -> Dict[str, Any]:
        c = await tradier.chain_for(client, tk, exp, S)
        if not c:
            raise HTTPException(status_code=502, detail="Live option chain unavailable for this expiration")
        return c

    @api_router.get("/chain/templates")
    async def chain_templates(authorization: Optional[str] = Header(default=None)):
        await get_user(authorization)
        return {"templates": [{"name": t, "bias": STRATEGY_META[t]["bias"][0]} for t in TEMPLATES]}

    @api_router.get("/chain/{ticker}/expirations")
    async def chain_expirations(ticker: str, authorization: Optional[str] = Header(default=None)):
        await get_user(authorization)
        tk = _tk(ticker)
        async with httpx.AsyncClient() as client:
            S = await spot(client, tk)
            dates = await tradier.expirations(client, tk)
        today = date.today()
        exps = [{"date": d, "dte": (date.fromisoformat(d) - today).days} for d in dates]
        exps = [e for e in exps if e["dte"] >= 0]
        if not exps:
            raise HTTPException(status_code=404, detail=f"No listed options for {tk}")
        return {"ticker": tk, "price": round(S, 2), "expirations": exps, "source": tradier.ENV}

    @api_router.get("/chain/{ticker}")
    async def chain_get(ticker: str, expiration: str, authorization: Optional[str] = Header(default=None)):
        await get_user(authorization)
        tk = _tk(ticker)
        _exp(expiration)
        async with httpx.AsyncClient() as client:
            S = await spot(client, tk)
            c = await load_chain(client, tk, expiration, S)
        strikes = sorted(set(c["calls"]) | set(c["puts"]))
        rows = [{"strike": k, "call": _side(c["calls"].get(k)), "put": _side(c["puts"].get(k))} for k in strikes]
        return {"ticker": tk, "price": round(S, 2), "expiration": c["expiration"], "dte": c["dte"],
                "atm_iv": c["atm_iv"], "source": c["source"], "delayed": c["delayed"], "as_of": c["as_of"], "rows": rows}

    @api_router.post("/chain/template")
    async def chain_template(req: TemplateReq, authorization: Optional[str] = Header(default=None)):
        await get_user(authorization)
        if req.template not in TEMPLATES:
            raise HTTPException(status_code=400, detail="Unknown template")
        tk = _tk(req.ticker)
        _exp(req.expiration)
        async with httpx.AsyncClient() as client:
            S = await spot(client, tk)
            c = await load_chain(client, tk, req.expiration, S)
        iv = c["atm_iv"] or 0.3
        legs = snap_legs(build_legs(req.template, S, iv, max(c["dte"], 1), c["expiration"]), c, S, c["expiration"])
        out = []
        for l in legs:
            if l["type"] == "Stock":
                out.append({"action": "Buy", "type": "Stock", "strike": round(S, 2), "qty": 1, "price": round(S, 2), "iv": None})
                continue
            o = (c["calls"] if l["type"] == "Call" else c["puts"]).get(float(l["strike"])) or {}
            g = o.get("greeks") or {}
            px = (o.get("ask") if l["action"] == "Buy" else o.get("bid")) or 0
            out.append({"action": l["action"], "type": l["type"], "strike": float(l["strike"]), "qty": l.get("qty", 1),
                        "price": round(float(px), 2), "iv": g.get("mid_iv") or g.get("smv_vol") or iv})
        return {"template": req.template, "legs": out}

    @api_router.post("/chain/analyze")
    async def chain_analyze(req: AnalyzeReq, authorization: Optional[str] = Header(default=None)):
        await get_user(authorization)
        tk = _tk(req.ticker)
        exp = _exp(req.expiration)
        async with httpx.AsyncClient() as client:
            S = await spot(client, tk)
            c = await tradier.chain_for(client, tk, req.expiration, S)
        default_iv = (c or {}).get("atm_iv") or 0.3
        legs = [{**l.model_dump(), "iv": l.iv or default_iv} for l in req.legs]
        if all(l["type"] == "Stock" for l in legs):
            raise HTTPException(status_code=400, detail="Add at least one option leg")
        return analyze_position(legs, S, max((exp - date.today()).days, 0), exp)
