"""Saved strategies (live P&L marks), profit-target / stop-loss alerts, and admin plan switching."""
from __future__ import annotations
import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

import tradier
from chain import LegIn, _tk, analyze_position, prepare_legs
from engine import RISK_FREE
from options_math import bs_greeks

PLANS = ("free", "simple", "advance", "expert")


class Threshold(BaseModel):
    mode: Literal["usd", "pct"]
    value: float = Field(gt=0, le=1e7)


class SaveStrategyReq(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    ticker: str = Field(min_length=1, max_length=10)
    expiration: str
    legs: List[LegIn] = Field(min_length=1, max_length=8)
    target: Optional[Threshold] = None
    stop: Optional[Threshold] = None


class UpdateStrategyReq(BaseModel):
    target: Optional[Threshold] = None
    stop: Optional[Threshold] = None


class AdminPlanReq(BaseModel):
    plan: Literal["free", "simple", "advance", "expert"]


def threshold_usd(t: Optional[Dict], base: Optional[float]) -> Optional[float]:
    """Threshold in dollars; pct is relative to max profit (target) or max risk (stop)."""
    if not t:
        return None
    return round(t["value"], 2) if t["mode"] == "usd" else round(abs(base or 0) * t["value"] / 100, 2) or None


def _iso(d: Dict) -> Dict:
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def register(api_router, *, db, get_user: Callable, get_quote: Callable, send_push: Callable, logger, market_open_now: Callable):

    async def mark(client, s: Dict) -> Dict[str, Any]:
        """Live mark: each leg at its chain mid (intrinsic if expired, model if unquoted)."""
        q = await get_quote(client, s["ticker"])
        S = float((q or {}).get("price") or 0)
        if not S:
            return {"error": "No live quote"}
        today = date.today()
        chains: Dict[str, Any] = {}
        value, live = 0.0, True
        for l in s["legs"]:
            sg, qty = (1 if l["action"] == "Buy" else -1), l["qty"]
            if l["type"] == "Stock":
                value += sg * qty * S
                continue
            left = (date.fromisoformat(l["expiration"]) - today).days
            K = l["strike"]
            if left < 0:
                px = max(S - K, 0) if l["type"] == "Call" else max(K - S, 0)
            else:
                if l["expiration"] not in chains:
                    chains[l["expiration"]] = await tradier.chain_for(client, s["ticker"], l["expiration"], S)
                c = chains[l["expiration"]]
                o = ((c or {}).get("calls" if l["type"] == "Call" else "puts") or {}).get(float(K)) or {}
                bid, ask = o.get("bid") or 0, o.get("ask") or 0
                if ask > 0:
                    px = (bid + ask) / 2
                else:
                    live = False
                    px = bs_greeks(S, K, max(left, 0.5) / 365, l.get("iv") or 0.3, r=RISK_FREE, call=l["type"] == "Call")["price"]
            value += sg * qty * px
        pnl = round((value - s["entry_value"]) * 100 - s["fees"], 2)
        tgt = threshold_usd(s.get("target"), s.get("max_profit") if s.get("max_profit") is not None else s["cost_basis"])
        stp = threshold_usd(s.get("stop"), s.get("max_loss") if s.get("max_loss") is not None else s["cost_basis"])
        risk = abs(s["max_loss"]) if s.get("max_loss") else abs(s["cost_basis"]) or None
        return {"price": round(S, 2), "pnl": pnl, "pnl_pct": round(pnl / risk * 100, 1) if risk else None,
                "market_value": round(value * 100, 2), "live": live, "target_usd": tgt, "stop_usd": stp,
                "as_of": datetime.now(timezone.utc).isoformat()}

    async def check_hits(s: Dict, m: Dict) -> List[Dict]:
        if "pnl" not in m or s.get("status") != "open":
            return []
        fired = s.get("fired") or {}
        hits = []
        if m["target_usd"] and m["pnl"] >= m["target_usd"] and not fired.get("target"):
            hits.append(("target", f"🎯 Profit target hit: {s['name']}", f"{s['ticker']} P&L +${m['pnl']:,.0f} (target ${m['target_usd']:,.0f})"))
        if m["stop_usd"] and m["pnl"] <= -m["stop_usd"] and not fired.get("stop"):
            hits.append(("stop", f"🛑 Stop loss hit: {s['name']}", f"{s['ticker']} P&L -${abs(m['pnl']):,.0f} (stop -${m['stop_usd']:,.0f})"))
        out = []
        for kind, title, msg in hits:
            ev = {"event_id": f"evt_{uuid.uuid4().hex[:12]}", "user_id": s["user_id"], "key": f"{s['strategy_id']}|{kind}",
                  "kind": f"strategy_{kind}", "ticker": s["ticker"], "strategy_id": s["strategy_id"], "strategy": s["name"],
                  "pnl": m["pnl"], "title": title, "message": msg, "created_at": datetime.now(timezone.utc), "read": False}
            await db.alert_events.insert_one(ev)
            await db.strategies.update_one({"strategy_id": s["strategy_id"]}, {"$set": {f"fired.{kind}": True}})
            ev.pop("_id", None)
            out.append(ev)
            try:
                await send_push(recipients=[s["user_id"]], data={"title": title, "message": msg, "action_url": "/(tabs)/portfolio"})
            except Exception as ex:
                logger.info(f"strategy push skipped: {ex}")
        return out

    async def strategy_loop():
        await asyncio.sleep(150)
        while True:
            try:
                if market_open_now():
                    rows = await db.strategies.find({"status": "open", "$or": [{"target": {"$ne": None}}, {"stop": {"$ne": None}}]},
                                                    {"_id": 0}).to_list(2000)
                    async with httpx.AsyncClient() as client:
                        for s in rows:
                            m = await mark(client, s)
                            await db.strategies.update_one({"strategy_id": s["strategy_id"]}, {"$set": {"last_mark": m}})
                            await check_hits(s, m)
            except Exception as ex:
                logger.warning(f"strategy loop: {ex}")
            await asyncio.sleep(5 * 60)

    # ------------------------------------------------ strategies
    @api_router.post("/strategies")
    async def save_strategy(req: SaveStrategyReq, authorization: Optional[str] = Header(default=None)):
        user = await get_user(authorization)
        tk = _tk(req.ticker)
        if all(l.type == "Stock" for l in req.legs):
            raise HTTPException(status_code=400, detail="Add at least one option leg")
        async with httpx.AsyncClient() as client:
            q = await get_quote(client, tk)
            S = float((q or {}).get("price") or 0)
            if not S:
                raise HTTPException(status_code=404, detail=f"No live quote found for {tk}")
            legs = await prepare_legs(client, tk, [l.model_dump() for l in req.legs], req.expiration, S)
        a = analyze_position([dict(l) for l in legs], S)
        doc = {
            "strategy_id": f"strat_{uuid.uuid4().hex[:12]}", "user_id": user["user_id"], "name": req.name.strip(), "ticker": tk,
            "legs": [{k: l[k] for k in ("action", "type", "strike", "qty", "price", "iv", "expiration")} for l in legs],
            "entry_value": sum((1 if l["action"] == "Buy" else -1) * l["qty"] * l["price"] for l in legs),
            "entry_underlying": round(S, 2), "cost_basis": a["cost_basis"], "net_premium": a["net_premium"],
            "premium_type": a["premium_type"], "fees": a["fees"], "max_profit": a["max_profit"], "max_loss": a["max_loss"],
            "pop": a["pop"], "breakevens": a["breakevens"], "multi_expiry": a["multi_expiry"],
            "expiration": min(l["expiration"] for l in legs if l["type"] != "Stock"),
            "target": req.target.model_dump() if req.target else None, "stop": req.stop.model_dump() if req.stop else None,
            "fired": {}, "status": "open", "created_at": datetime.now(timezone.utc),
        }
        await db.strategies.insert_one(doc)
        doc.pop("_id", None)
        return _iso(doc)

    @api_router.get("/strategies")
    async def list_strategies(authorization: Optional[str] = Header(default=None)):
        user = await get_user(authorization)
        rows = await db.strategies.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
        async with httpx.AsyncClient() as client:
            marks = await asyncio.gather(*[mark(client, s) for s in rows], return_exceptions=True)
        new_events = []
        for s, m in zip(rows, marks):
            s["mark"] = m if isinstance(m, dict) else {"error": "Mark unavailable"}
            new_events += await check_hits(s, s["mark"])
            _iso(s)
        total = round(sum(s["mark"].get("pnl", 0) for s in rows), 2)
        return {"items": rows, "total_pnl": total, "new_alerts": len(new_events)}

    @api_router.patch("/strategies/{sid}")
    async def update_strategy(sid: str, req: UpdateStrategyReq, authorization: Optional[str] = Header(default=None)):
        user = await get_user(authorization)
        r = await db.strategies.update_one(
            {"strategy_id": sid, "user_id": user["user_id"]},
            {"$set": {"target": req.target.model_dump() if req.target else None,
                      "stop": req.stop.model_dump() if req.stop else None, "fired": {}}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return {"ok": True}

    @api_router.delete("/strategies/{sid}")
    async def delete_strategy(sid: str, authorization: Optional[str] = Header(default=None)):
        user = await get_user(authorization)
        r = await db.strategies.delete_one({"strategy_id": sid, "user_id": user["user_id"]})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return {"ok": True}

    # ------------------------------------------------ admin
    async def require_admin(authorization: Optional[str]) -> Dict:
        user = await get_user(authorization)
        raw = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "is_admin": 1})
        if not (raw or {}).get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin only")
        return user

    @api_router.get("/admin/users")
    async def admin_users(q: str = "", authorization: Optional[str] = Header(default=None)):
        await require_admin(authorization)
        import re as _re
        filt = {"$or": [{"email": {"$regex": _re.escape(q.strip()), "$options": "i"}},
                        {"name": {"$regex": _re.escape(q.strip()), "$options": "i"}}]} if q.strip() else {}
        rows = await db.users.find(filt, {"_id": 0, "user_id": 1, "email": 1, "name": 1, "plan": 1, "plan_source": 1,
                                          "plan_expires_at": 1, "created_at": 1, "is_admin": 1}).sort("created_at", -1).to_list(200)
        import billing
        for r in rows:
            r["tier"] = billing.compute_access(r)["tier"]
            _iso(r)
        return {"items": rows}

    @api_router.post("/admin/users/{uid}/plan")
    async def admin_set_plan(uid: str, req: AdminPlanReq, authorization: Optional[str] = Header(default=None)):
        admin = await require_admin(authorization)
        upd = {"plan": req.plan, "plan_source": "admin", "plan_expires_at": None} if req.plan != "free" else \
              {"plan": "free", "plan_source": None, "plan_expires_at": None}
        r = await db.users.update_one({"user_id": uid}, {"$set": upd})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="User not found")
        logger.info(f"admin {admin['email']} set {uid} plan={req.plan}")
        return {"ok": True, "plan": req.plan}

    return {"loop": strategy_loop}
