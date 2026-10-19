"""Live option chain browser + strategy builder (payoff curve, P&L heatmap, POP, Greeks)."""
from __future__ import annotations
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Literal, Optional

import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

import tradier
from engine import (RISK_FREE, FEE_PER_CONTRACT, build_legs, snap_legs, payoff_stats,
                    probability_and_ev, STRATEGY_META, _prob_grid)
from options_math import bs_greeks

TICKER_RE = re.compile(r"^[A-Z.]{1,10}$")
MULTI_TEMPLATES = ["Calendar Call Spread", "Calendar Put Spread", "Diagonal Call Spread", "Diagonal Put Spread"]
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
    expiration: Optional[str] = None  # per-leg expiry (calendars/diagonals); defaults to request expiration


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


def _value_at(legs: List[Dict], Sn: float, d: float) -> float:
    """Position value per share-unit at price Sn, d days from now (each leg uses its own expiry)."""
    v = 0.0
    for l in legs:
        s, q, K = (1 if l["action"] == "Buy" else -1), l["qty"], l["strike"]
        left = l.get("dte", 0) - d
        if l["type"] == "Stock":
            v += s * q * Sn
        elif left <= 0:
            v += s * q * (max(Sn - K, 0) if l["type"] == "Call" else max(K - Sn, 0))
        else:
            v += s * q * bs_greeks(Sn, K, left / 365, l["iv"], r=RISK_FREE, call=l["type"] == "Call")["price"]
    return v


def _mixed_stats(pnl_near: Callable[[float], float], S: float, iv: float, near: int) -> Dict[str, Any]:
    grid = [S * (0.3 + 2.2 * i / 400) for i in range(401)]
    vals = [pnl_near(x) for x in grid]
    slope = (vals[-1] - vals[-2]) / (grid[-1] - grid[-2])  # $ P&L per $1 move at the far right
    up, down = slope > 10, slope < -10  # real unlimited exposure ≈ 100 $/$ per uncovered contract
    bes = []
    for i in range(1, len(grid)):
        a, b = vals[i - 1], vals[i]
        if (a < 0 <= b) or (a >= 0 > b):
            bes.append(round(grid[i - 1] + (grid[i] - grid[i - 1]) * (0 - a) / ((b - a) or 1), 2))
    pts, cdf = _prob_grid(S, iv, max(near, 1), RISK_FREE)
    pop = ev = 0.0
    for k in range(1, len(pts), 3):
        mid = (pts[k] + pts[k - 1]) / 2
        w = cdf[min(k + 2, len(cdf) - 1)] - cdf[k - 1]
        v = pnl_near(mid)
        ev += v * w
        pop += w if v > 0 else 0
    return {"max_profit": None if up else round(max(vals), 2), "max_loss": None if down else round(min(min(vals), 0), 2),
            "breakevens": bes, "unlimited_profit": up, "unlimited_loss": down,
            "pop": round(pop * 100, 1), "expected_value": round(ev, 2)}


def analyze_position(legs: List[Dict], S: float) -> Dict[str, Any]:
    opts = [l for l in legs if l["type"] != "Stock"]
    near = min(l["dte"] for l in opts)
    multi = len({l["dte"] for l in opts}) > 1
    for l in legs:
        if l["type"] == "Stock":
            l["dte"] = near
    contracts = sum(l["qty"] for l in opts)
    fees = round(contracts * FEE_PER_CONTRACT, 2)
    entry = sum((1 if l["action"] == "Buy" else -1) * l["qty"] * l["price"] for l in legs)
    avg_iv = sum(l["iv"] for l in opts) / len(opts)
    pnl = lambda Sn, d: round((_value_at(legs, Sn, d) - entry) * 100 - fees, 2)
    premium_net = -sum((1 if l["action"] == "Buy" else -1) * l["qty"] * l["price"] for l in opts)

    if multi:
        st = _mixed_stats(lambda x: pnl(x, near), S, avg_iv, near)
    else:
        eng = [{"action": l["action"], "type": l["type"], "qty": l["qty"],
                "strike": l["price"] if l["type"] == "Stock" else l["strike"]} for l in legs]
        st = {**payoff_stats(eng, S, premium_net, fees),
              **{k: v for k, v in probability_and_ev(eng, S, premium_net, fees, avg_iv, avg_iv, max(near, 1)).items()
                 if k in ("pop", "expected_value")}}

    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in legs:
        s = (1 if l["action"] == "Buy" else -1) * l["qty"]
        if l["type"] == "Stock":
            greeks["delta"] += s
            continue
        g = bs_greeks(S, l["strike"], max(l["dte"], 0.5) / 365, l["iv"], r=RISK_FREE, call=l["type"] == "Call")
        for k in greeks:
            greeks[k] += s * g[k]
    greeks = {k: round(v * 100, 2) for k, v in greeks.items()}

    strikes = [l["strike"] for l in opts]
    lo, hi = min(min(strikes), S) * 0.8, max(max(strikes), S) * 1.2
    curve = [{"price": round(lo + (hi - lo) * i / 60, 2)} for i in range(61)]
    for p in curve:
        p["expiry"] = pnl(p["price"], near)
        p["today"] = pnl(p["price"], 0)

    n = min(6, max(near, 1))
    days = sorted({round(near * i / (n - 1)) if n > 1 else near for i in range(n)}) if near > 0 else [0]
    cols = [{"date": (date.today() + timedelta(days=d)).isoformat(), "days_left": near - d} for d in days]
    moves = [0.15, 0.10, 0.06, 0.03, 0.0, -0.03, -0.06, -0.10, -0.15]
    rows = [{"move_pct": round(m * 100), "price": round(S * (1 + m), 2),
             "pnl": [pnl(S * (1 + m), near - c["days_left"]) for c in cols]} for m in moves]

    return {
        "price": round(S, 2), "expiration": (date.today() + timedelta(days=near)).isoformat(), "dte": near, "multi_expiry": multi,
        "net_premium": round(premium_net * 100, 2), "premium_type": "credit" if premium_net > 0 else "debit",
        "cost_basis": round(entry * 100, 2), "fees": fees,
        "max_profit": st["max_profit"], "max_loss": st["max_loss"], "breakevens": st["breakevens"],
        "unlimited_profit": st["unlimited_profit"], "unlimited_loss": st["unlimited_loss"],
        "pop": st["pop"], "expected_value": st["expected_value"], "avg_iv": round(avg_iv, 4),
        "greeks": greeks, "curve": curve, "heatmap": {"columns": cols, "rows": rows},
    }


async def prepare_legs(client, tk: str, legs_in: List[Dict], default_exp: str, S: float) -> List[Dict]:
    """Attach dte + iv (from the leg's live chain) to each leg."""
    today = date.today()
    ivs: Dict[str, Optional[float]] = {}
    out = []
    for l in legs_in:
        e = l.get("expiration") or default_exp
        _exp(e)
        if e not in ivs:
            c = await tradier.chain_for(client, tk, e, S)
            ivs[e] = (c or {}).get("atm_iv")
        out.append({**l, "expiration": e, "dte": max((date.fromisoformat(e) - today).days, 0),
                    "iv": l.get("iv") or ivs[e] or 0.3})
    return out


def _leg_from_chain(c: Dict[str, Any], action: str, typ: str, target: float, exp: str) -> Optional[Dict[str, Any]]:
    side = c["calls"] if typ == "Call" else c["puts"]
    ks = [k for k, o in side.items() if (o.get("ask") or 0) > 0 and (o.get("bid") or 0) > 0]
    if not ks:
        return None
    k = min(ks, key=lambda x: abs(x - target))
    o = side[k]
    g = o.get("greeks") or {}
    return {"action": action, "type": typ, "strike": k, "qty": 1, "expiration": exp,
            "price": round(float(o["ask"] if action == "Buy" else o["bid"]), 2),
            "iv": g.get("mid_iv") or g.get("smv_vol") or c.get("atm_iv")}


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
        return {"templates": [{"name": t, "bias": STRATEGY_META[t]["bias"][0]} for t in TEMPLATES]
                + [{"name": t, "bias": "Neutral" if "Calendar" in t else ("Bullish" if "Call" in t else "Bearish")} for t in MULTI_TEMPLATES]}

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
        if req.template not in TEMPLATES + MULTI_TEMPLATES:
            raise HTTPException(status_code=400, detail="Unknown template")
        tk = _tk(req.ticker)
        near_d = _exp(req.expiration)
        async with httpx.AsyncClient() as client:
            S = await spot(client, tk)
            c = await load_chain(client, tk, req.expiration, S)
            if req.template in MULTI_TEMPLATES:
                later = [d for d in await tradier.expirations(client, tk) if (date.fromisoformat(d) - near_d).days >= 21]
                if not later:
                    raise HTTPException(status_code=400, detail="No later expiration available for a calendar/diagonal")
                far_exp = min(later, key=lambda d: abs((date.fromisoformat(d) - near_d).days - 30))
                fc = await load_chain(client, tk, far_exp, S)
                typ = "Call" if "Call" in req.template else "Put"
                diag = "Diagonal" in req.template
                sgn = 1 if typ == "Call" else -1
                short = _leg_from_chain(c, "Sell", typ, S * (1 + sgn * 0.04) if diag else S, c["expiration"])
                long_ = _leg_from_chain(fc, "Buy", typ, S * (1 - sgn * 0.01) if diag else (short or {}).get("strike", S), far_exp)
                if not short or not long_:
                    raise HTTPException(status_code=502, detail="Quotes unavailable for this template")
                return {"template": req.template, "legs": [short, long_]}
        iv = c["atm_iv"] or 0.3
        legs = snap_legs(build_legs(req.template, S, iv, max(c["dte"], 1), c["expiration"]), c, S, c["expiration"])
        out = []
        for l in legs:
            if l["type"] == "Stock":
                out.append({"action": "Buy", "type": "Stock", "strike": round(S, 2), "qty": 1, "price": round(S, 2), "iv": None,
                            "expiration": c["expiration"]})
                continue
            o = (c["calls"] if l["type"] == "Call" else c["puts"]).get(float(l["strike"])) or {}
            g = o.get("greeks") or {}
            px = (o.get("ask") if l["action"] == "Buy" else o.get("bid")) or 0
            out.append({"action": l["action"], "type": l["type"], "strike": float(l["strike"]), "qty": l.get("qty", 1),
                        "price": round(float(px), 2), "iv": g.get("mid_iv") or g.get("smv_vol") or iv, "expiration": c["expiration"]})
        return {"template": req.template, "legs": out}

    @api_router.post("/chain/analyze")
    async def chain_analyze(req: AnalyzeReq, authorization: Optional[str] = Header(default=None)):
        await get_user(authorization)
        tk = _tk(req.ticker)
        _exp(req.expiration)
        if all(l.type == "Stock" for l in req.legs):
            raise HTTPException(status_code=400, detail="Add at least one option leg")
        async with httpx.AsyncClient() as client:
            S = await spot(client, tk)
            legs = await prepare_legs(client, tk, [l.model_dump() for l in req.legs], req.expiration, S)
        return analyze_position(legs, S)
