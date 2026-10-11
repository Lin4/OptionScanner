"""OptiScreen backend - Option & Stock Screening."""
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request, UploadFile, File
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import random
import json
import re
import asyncio
import bcrypt
import jwt as pyjwt
import httpx
from pathlib import Path
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from integrations import (
    RegisterPushBody, register_push_token, send_push,
    TTSReq, tts_generate, stt_transcribe,
    paypal_create_order, paypal_capture_order, PLAN_PRICES,
)
from market import (
    UNIVERSE, UNIVERSE_INDEX, fetch_stock_bundle, get_quote, get_candles,
    sma as calc_sma, rsi as calc_rsi, support_resistance, detect_candle_patterns, detect_chart_patterns,
)

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret')

app = FastAPI(title="OptiScreen API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("optiscreen")


# ========== MODELS ==========
class RegisterReq(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None

class LoginReq(BaseModel):
    email: EmailStr
    password: str

class SessionReq(BaseModel):
    session_id: str

class PlanReq(BaseModel):
    plan: str  # free | simple | advance | expert

class QuestionnaireReq(BaseModel):
    answers: Dict[str, Any]

class ConsentReq(BaseModel):
    agreed: bool
    signature: str  # typed signature

class FindStockReq(BaseModel):
    risk: str  # high | low
    reward: str  # high | low
    expiration: str  # daily | week | month
    sectors: List[str] = []
    limit: int = 5

class BestOptionsReq(BaseModel):
    period: str  # day | week | month | custom
    custom_days: Optional[int] = None
    limit: int = 5

class TickerOptionsReq(BaseModel):
    ticker: str
    expiration_range: str  # week | month | 3months

class StockAnalysisReq(BaseModel):
    ticker: str
    purpose: str  # day | swing | long


# ========== UTIL ==========
def now_utc():
    return datetime.now(timezone.utc)

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def make_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": now_utc() + timedelta(days=7), "iat": now_utc(), "jti": uuid.uuid4().hex}
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

async def store_session(session_token: str, user_id: str):
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user_id,
            "created_at": now_utc(),
            "expires_at": now_utc() + timedelta(days=7),
        }},
        upsert=True,
    )

async def get_user_from_token(authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth header")
    token = authorization[7:]
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        try:
            data = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            user_id = data["user_id"]
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        exp = session.get("expires_at")
        if exp and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp and exp < now_utc():
            raise HTTPException(status_code=401, detail="Session expired")
        user_id = session["user_id"]
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "password": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ========== MARKET HELPERS ==========
STRATEGIES = ["Cash Secured Put", "Covered Call", "Bull Put Spread", "Iron Condor", "Bear Call Spread", "Short Strangle"]

def sparkline_from_candles(candles: List[Dict], points: int = 20) -> List[float]:
    if not candles:
        return []
    closes = [c["c"] for c in candles[-points:]]
    return [round(float(c), 2) for c in closes]

def build_option_strategy(ticker: str, name: str, sector: str, price: float, expiration: str, sparkline: List[float]) -> Dict:
    """Build an option strategy priced around the REAL current price."""
    strat = random.choice(STRATEGIES)
    exp_days = {"daily": 1, "day": 1, "week": 7, "month": 30, "3months": 90, "custom": 14}.get(expiration, 30)
    exp_date = (now_utc() + timedelta(days=exp_days)).strftime("%Y-%m-%d")
    pop = random.randint(60, 90)
    premium = round(price * random.uniform(0.008, 0.028), 2)
    collateral = round(price * 100, 2)
    collat_margin = round(collateral * 0.25, 2)
    annual_pct_collat = round((premium * 100) / collateral * (365 / exp_days) * 100, 2)
    annual_pct_margin = round((premium * 100) / collat_margin * (365 / exp_days) * 100, 2)
    legs = []
    if strat == "Cash Secured Put":
        legs = [{"action": "Sell", "type": "Put", "strike": round(price * 0.95, 2), "exp": exp_date}]
    elif strat == "Covered Call":
        legs = [{"action": "Sell", "type": "Call", "strike": round(price * 1.05, 2), "exp": exp_date}]
    elif strat == "Bull Put Spread":
        legs = [
            {"action": "Sell", "type": "Put", "strike": round(price * 0.97, 2), "exp": exp_date},
            {"action": "Buy", "type": "Put", "strike": round(price * 0.92, 2), "exp": exp_date},
        ]
    elif strat == "Bear Call Spread":
        legs = [
            {"action": "Sell", "type": "Call", "strike": round(price * 1.03, 2), "exp": exp_date},
            {"action": "Buy", "type": "Call", "strike": round(price * 1.08, 2), "exp": exp_date},
        ]
    elif strat == "Iron Condor":
        legs = [
            {"action": "Sell", "type": "Put", "strike": round(price * 0.95, 2), "exp": exp_date},
            {"action": "Buy", "type": "Put", "strike": round(price * 0.90, 2), "exp": exp_date},
            {"action": "Sell", "type": "Call", "strike": round(price * 1.05, 2), "exp": exp_date},
            {"action": "Buy", "type": "Call", "strike": round(price * 1.10, 2), "exp": exp_date},
        ]
    else:
        legs = [
            {"action": "Sell", "type": "Put", "strike": round(price * 0.95, 2), "exp": exp_date},
            {"action": "Sell", "type": "Call", "strike": round(price * 1.05, 2), "exp": exp_date},
        ]
    return {
        "ticker": ticker, "name": name, "sector": sector, "price": round(price, 2),
        "strategy": strat, "legs": legs, "premium": premium, "expiration": exp_date,
        "expiration_days": exp_days, "pop": pop, "collateral": collateral,
        "collateral_margin": collat_margin, "annual_pct_no_margin": annual_pct_collat,
        "annual_pct_margin": annual_pct_margin, "sparkline": sparkline,
    }

async def enrich_universe_pick(ticker: str, expiration: str) -> Optional[Dict]:
    """Fetch REAL quote + a short sparkline for a universe ticker, return option strategy."""
    try:
        async with httpx.AsyncClient() as client:
            q, c = await asyncio.gather(get_quote(client, ticker), get_candles(client, ticker, 30))
        if not q or not q.get("price"):
            return None
        info = UNIVERSE_INDEX.get(ticker, {"name": ticker, "sector": "Unknown"})
        spark = sparkline_from_candles(c) if c else []
        return build_option_strategy(ticker, info.get("name", ticker), info.get("sector", "Unknown"), q["price"], expiration, spark)
    except Exception as e:
        logger.warning(f"enrich {ticker} failed: {e}")
        return None


# ========== AI ==========
async def call_claude(system: str, prompt: str) -> str:
    """Call Claude Sonnet 5.5 via emergentintegrations."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"optiscreen-{uuid.uuid4().hex[:8]}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-5-5")
        resp = await chat.send_message(UserMessage(text=prompt))
        return resp if isinstance(resp, str) else str(resp)
    except Exception as e:
        logger.exception(f"Claude call failed: {e}")
        return ""

def extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ========== AUTH ROUTES ==========
@api_router.post("/auth/register")
async def register(req: RegisterReq):
    existing = await db.users.find_one({"email": req.email.lower()}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user = {
        "user_id": user_id,
        "email": req.email.lower(),
        "name": req.name or req.email.split("@")[0],
        "password": hash_pw(req.password),
        "plan": None,
        "questionnaire_complete": False,
        "consent_signed": False,
        "picture": None,
        "created_at": now_utc(),
    }
    await db.users.insert_one(user)
    token = make_token(user_id)
    await store_session(token, user_id)
    return {"session_token": token, "user": {k: v for k, v in user.items() if k not in ("password", "_id")}}

@api_router.post("/auth/login")
async def login(req: LoginReq):
    user = await db.users.find_one({"email": req.email.lower()}, {"_id": 0})
    if not user or not user.get("password") or not verify_pw(req.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = make_token(user["user_id"])
    await store_session(token, user["user_id"])
    user.pop("password", None)
    return {"session_token": token, "user": user}

@api_router.post("/auth/session")
async def oauth_session(req: SessionReq):
    """Emergent Google OAuth exchange."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": req.session_id},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session")
        data = r.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"OAuth exchange failed: {e}")
        raise HTTPException(status_code=401, detail="Auth service error")

    email = data.get("email", "").lower()
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")
    session_token = data.get("session_token")
    if not email or not session_token:
        raise HTTPException(status_code=401, detail="Incomplete auth data")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one({"user_id": user_id}, {"$set": {"picture": picture, "name": name}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "password": None,
            "plan": None,
            "questionnaire_complete": False,
            "consent_signed": False,
            "created_at": now_utc(),
        })

    await store_session(session_token, user_id)
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "password": 0})
    return {"session_token": session_token, "user": user}

@api_router.get("/auth/me")
async def me(authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    return {"user": user}

@api_router.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        await db.user_sessions.delete_many({"session_token": token})
    return {"ok": True}


# ========== PROFILE ==========
@api_router.post("/user/plan")
async def set_plan(req: PlanReq, authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    if req.plan not in ("free", "simple", "advance", "expert"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"plan": req.plan}})
    return {"ok": True, "plan": req.plan}

@api_router.post("/user/questionnaire")
async def save_questionnaire(req: QuestionnaireReq, authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"questionnaire": req.answers, "questionnaire_complete": True}},
    )
    return {"ok": True}

@api_router.post("/user/consent")
async def save_consent(req: ConsentReq, authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    if not req.agreed or not req.signature.strip():
        raise HTTPException(status_code=400, detail="Must agree & sign")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"consent_signed": True, "consent": {"signature": req.signature, "at": now_utc().isoformat()}}},
    )
    return {"ok": True}


# ========== SCREENER ROUTES ==========
@api_router.post("/screener/find-stocks")
async def find_stocks(req: FindStockReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    pool = UNIVERSE[:]
    if req.sectors:
        pool = [s for s in pool if s["sector"] in req.sectors]
    if not pool:
        pool = UNIVERSE[:]
    random.shuffle(pool)
    # Fetch more than needed in parallel; keep first `limit` that return quotes.
    candidates = pool[: min(len(pool), max(req.limit * 2, req.limit))]
    enriched = await asyncio.gather(*[enrich_universe_pick(c["ticker"], req.expiration) for c in candidates])
    results = [r for r in enriched if r][: req.limit]

    system = "You are a sharp options strategist. Reply with ONLY valid JSON, no markdown."
    tickers = [r["ticker"] for r in results]
    prompt = (
        f"User seeks optionable stocks matching: risk={req.risk}, reward={req.reward}, "
        f"expiration={req.expiration}, sectors={req.sectors or 'any'}.\n"
        f"For each ticker in {tickers} (real quotes: {[(r['ticker'], r['price']) for r in results]}), "
        f"give a 1-sentence rationale and a bullish/bearish/neutral bias. "
        f'Reply JSON: {{"picks":[{{"ticker":"XX","bias":"bullish","rationale":"..."}}]}}'
    )
    txt = await call_claude(system, prompt)
    ai = extract_json(txt) or {"picks": []}
    ai_map = {p.get("ticker"): p for p in ai.get("picks", [])}
    for r in results:
        a = ai_map.get(r["ticker"], {})
        r["bias"] = a.get("bias", "neutral")
        r["rationale"] = a.get("rationale", f"Fits {req.risk} risk / {req.reward} reward profile.")
    return {"results": results}

@api_router.post("/screener/best-options")
async def best_options(req: BestOptionsReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    period_map = {"day": "daily", "week": "week", "month": "month", "custom": "custom"}
    exp = period_map.get(req.period, "week")
    pool = random.sample(UNIVERSE, min(max(req.limit * 2, req.limit), len(UNIVERSE)))
    enriched = await asyncio.gather(*[enrich_universe_pick(c["ticker"], exp) for c in pool])
    results = [r for r in enriched if r][: req.limit]
    results.sort(key=lambda r: r["annual_pct_no_margin"], reverse=True)

    system = "You are an options strategist. Reply with ONLY valid JSON."
    prompt = (
        f"For a {req.period} horizon with REAL current prices {[(r['ticker'], r['price']) for r in results]}, "
        f"pick the top ticker and summarize in one line. "
        f'JSON: {{"summary":"...","top_pick":"TICKER"}}'
    )
    txt = await call_claude(system, prompt)
    ai = extract_json(txt) or {}
    return {"results": results, "ai_summary": ai.get("summary", "Top yield plays this period."), "top_pick": ai.get("top_pick")}

@api_router.post("/screener/ticker-options")
async def ticker_options(req: TickerOptionsReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    tk = req.ticker.upper()
    opt = await enrich_universe_pick(tk, req.expiration_range)
    if not opt:
        # Try outside universe
        async with httpx.AsyncClient() as client:
            q, c = await asyncio.gather(get_quote(client, tk), get_candles(client, tk, 30))
        if not q or not q.get("price"):
            raise HTTPException(status_code=404, detail=f"No live quote found for {tk}")
        spark = sparkline_from_candles(c) if c else []
        opt = build_option_strategy(tk, tk, "Unknown", q["price"], req.expiration_range, spark)

    system = "You are an options strategist. Reply with ONLY valid JSON, no markdown."
    prompt = (
        f"Analyze {tk} at REAL price ${opt['price']} for {req.expiration_range} options play. "
        f"Give a strategy recommendation summary. "
        f'JSON: {{"summary":"...","risk_note":"...","entry_tip":"..."}}'
    )
    txt = await call_claude(system, prompt)
    ai = extract_json(txt) or {}
    opt["ai_summary"] = ai.get("summary", f"Best {req.expiration_range} play for {tk}.")
    opt["risk_note"] = ai.get("risk_note", "Monitor earnings and macro events.")
    opt["entry_tip"] = ai.get("entry_tip", "Enter mid-week for optimal theta.")
    return {"result": opt}

@api_router.post("/screener/stock-analysis")
async def stock_analysis(req: StockAnalysisReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    tk = req.ticker.upper()
    bundle = await fetch_stock_bundle(tk)
    if not bundle.get("price"):
        raise HTTPException(status_code=404, detail=f"No live quote found for {tk}")

    price = bundle["price"]
    candles = bundle["candles"]
    sma_20 = bundle["sma_20"] or round(price, 2)
    sma_50 = bundle["sma_50"] or round(price, 2)
    rsi_val = bundle["rsi"] or 50
    sup = bundle["support"] or round(price * 0.94, 2)
    res = bundle["resistance"] or round(price * 1.07, 2)

    if req.purpose in ("day", "swing"):
        # Derive buy/sell/stop from real levels
        atr_proxy = (res - sup) / 10 if res > sup else price * 0.01
        buy = round(max(sup, price - atr_proxy), 2)
        sell = round(min(res, price + atr_proxy * 2), 2)
        stop = round(sup * 0.97, 2)
        sent = bundle.get("news_sentiment") or {}
        if sent and sent.get("bullish", 0) > sent.get("bearish", 0):
            market_sentiment = "Bullish"
        elif sent and sent.get("bearish", 0) > sent.get("bullish", 0):
            market_sentiment = "Bearish"
        else:
            market_sentiment = "Neutral"
        resp = {
            "ticker": tk, "name": bundle["name"], "price": price,
            "purpose": req.purpose,
            "candles": candles,
            "buy_point": buy, "sell_point": sell, "stop_loss": stop,
            "support": sup, "resistance": res,
            "sma_20": sma_20, "sma_50": sma_50, "rsi": rsi_val,
            "short_float_pct": None,  # premium data, left null on free tier
            "short_interest": None,
            "option_volume": None,
            "candlestick_patterns": bundle["candlestick_patterns"],
            "chart_patterns": bundle["chart_patterns"],
            "market_sentiment": market_sentiment,
            "intrinsic_value": bundle.get("price_target") or round(price, 2),
            "profit_probability": max(50, min(90, int(50 + (sma_20 - sma_50) / price * 500 if sma_20 and sma_50 else 50))),
        }
        system = "You are a short-term trading analyst. Reply ONLY valid JSON."
        prompt = (
            f"Analyze {tk} for {req.purpose} trading. Real-time data: price ${price}, SMA20 ${sma_20}, SMA50 ${sma_50}, "
            f"RSI {rsi_val}, support ${sup}, resistance ${res}, trend {bundle['trend']}, patterns {bundle['candlestick_patterns']}. "
            f'JSON: {{"summary":"...","verdict":"BUY|SELL|HOLD","confidence":"low|med|high"}}'
        )
    else:
        metrics = bundle.get("metrics") or {}
        earnings = bundle.get("earnings") or {}
        pt = bundle.get("price_target")
        eps = metrics.get("eps_ttm") or 0
        pe = metrics.get("pe_ttm") or 0
        intrinsic = round((pt or price * (1.1 if (metrics.get("revenue_growth_ttm") or 0) > 10 else 1.0)), 2)
        resp = {
            "ticker": tk, "name": bundle["name"], "price": price,
            "purpose": "long",
            "candles": candles,
            "intrinsic_value": intrinsic,
            "price_target": pt or round(price * 1.15, 2),
            "stock_trend": bundle["trend"],
            "earnings_date": earnings.get("date"),
            "earnings_eps_estimate": earnings.get("eps_estimate"),
            "revenue_billions": None,  # exact value needs reported financials call (left optional)
            "net_cash_billions": None,
            "net_profit_billions": None,
            "debt_billions": None,
            "pe_ratio": pe,
            "eps_ttm": eps,
            "roe": metrics.get("roe_ttm"),
            "revenue_growth_pct": metrics.get("revenue_growth_ttm"),
            "net_margin_pct": metrics.get("net_profit_margin"),
            "beta": metrics.get("beta"),
            "fifty_two_week_high": metrics.get("52w_high"),
            "fifty_two_week_low": metrics.get("52w_low"),
            "business_moat": "Wide" if (metrics.get("roe_ttm") or 0) > 20 else ("Narrow" if (metrics.get("roe_ttm") or 0) > 10 else "None"),
            "competitors": bundle["peers"][:4],
            "analyst_ratings": bundle["analyst_ratings"] or {"buy": 0, "hold": 0, "sell": 0},
            "buy_point": round(price * 0.92, 2),
            "sell_point": round((pt or price * 1.3), 2),
        }
        system = "You are a long-term value investor. Reply ONLY valid JSON."
        prompt = (
            f"Give a long-term thesis for {tk}. Real-time data: price ${price}, P/E {pe}, EPS ${eps}, "
            f"ROE {metrics.get('roe_ttm')}%, revenue growth {metrics.get('revenue_growth_ttm')}%, "
            f"price target ${pt}, peers {bundle['peers'][:3]}, "
            f"analyst ratings {bundle['analyst_ratings']}. "
            f'JSON: {{"summary":"...","verdict":"BUY|SELL|HOLD","confidence":"low|med|high","moat_note":"..."}}'
        )

    txt = await call_claude(system, prompt)
    ai = extract_json(txt) or {}
    resp["ai_summary"] = ai.get("summary", f"{tk} shows a solid setup for {req.purpose} horizon.")
    resp["verdict"] = ai.get("verdict", "HOLD")
    resp["confidence"] = ai.get("confidence", "med")
    if req.purpose == "long":
        resp["moat_note"] = ai.get("moat_note", "Durable competitive advantage.")
    return {"result": resp}

@api_router.get("/screener/stocks")
async def list_stocks():
    return {"stocks": UNIVERSE}

@api_router.get("/screener/quote/{ticker}")
async def live_quote(ticker: str, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    async with httpx.AsyncClient() as client:
        q = await get_quote(client, ticker.upper())
    if not q:
        raise HTTPException(status_code=404, detail=f"No quote for {ticker}")
    return {"ticker": ticker.upper(), **q}


# ========== PUSH NOTIFICATIONS ==========
@api_router.post("/register-push", status_code=201)
async def register_push(body: RegisterPushBody):
    return await register_push_token(body)


class PushTestReq(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None

@api_router.post("/push/test")
async def push_test(req: PushTestReq, authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    try:
        await send_push(
            recipients=[user["user_id"]],
            data={
                "title": req.title or "OptiScreen",
                "message": req.message or "Your daily top pick is ready - open to view",
                "action_url": "/(tabs)",
            },
        )
    except Exception as e:
        logger.warning(f"push_test failed: {e}")
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@api_router.post("/push/daily-pick")
async def push_daily_pick(authorization: Optional[str] = Header(default=None)):
    """Simulate the daily top AI pick push for the current user."""
    user = await get_user_from_token(authorization)
    base = random.choice(UNIVERSE)
    async with httpx.AsyncClient() as client:
        q = await get_quote(client, base["ticker"])
    price_str = f"${q['price']:.2f}" if q else "live price"
    try:
        await send_push(
            recipients=[user["user_id"]],
            data={
                "title": f"Today's top pick: {base['ticker']}",
                "message": f"{base['name']} shows strong setup at {price_str}. Tap to analyze.",
                "action_url": f"/ticker/{base['ticker']}",
            },
        )
    except Exception as e:
        logger.warning(f"daily pick push failed: {e}")
        return {"ok": False, "ticker": base["ticker"], "error": str(e)}
    return {"ok": True, "ticker": base["ticker"]}


class EarningsReminderReq(BaseModel):
    ticker: str
    earnings_date: str  # YYYY-MM-DD

@api_router.post("/push/earnings-reminder")
async def push_earnings_reminder(req: EarningsReminderReq, authorization: Optional[str] = Header(default=None)):
    """Send a reminder that an earnings date is approaching for a ticker."""
    user = await get_user_from_token(authorization)
    try:
        await send_push(
            recipients=[user["user_id"]],
            data={
                "title": f"{req.ticker} earnings approaching",
                "message": f"Earnings on {req.earnings_date} - review your position",
                "action_url": f"/ticker/{req.ticker}",
            },
        )
    except Exception as e:
        logger.warning(f"earnings push failed: {e}")
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ========== ELEVENLABS TTS / STT ==========
@api_router.post("/tts/generate")
async def tts_route(req: TTSReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    return tts_generate(req)


@api_router.post("/stt/transcribe")
async def stt_route(audio: UploadFile = File(...), authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    content = await audio.read()
    return stt_transcribe(content, audio.filename or "audio")


# ========== PAYPAL ==========
class CreateOrderReq(BaseModel):
    plan: str

@api_router.post("/paypal/create-order")
async def paypal_create(req: CreateOrderReq, authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    return await paypal_create_order(req.plan, user["user_id"])


class CaptureOrderReq(BaseModel):
    order_id: str

@api_router.post("/paypal/capture-order")
async def paypal_capture(req: CaptureOrderReq, authorization: Optional[str] = Header(default=None)):
    user = await get_user_from_token(authorization)
    res = await paypal_capture_order(req.order_id)
    if res.get("status") == "COMPLETED" and res.get("plan"):
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"plan": res["plan"]}},
        )
        await db.payments.insert_one({
            "user_id": user["user_id"],
            "order_id": req.order_id,
            "plan": res["plan"],
            "amount": PLAN_PRICES.get(res["plan"]),
            "status": res["status"],
            "created_at": now_utc(),
        })
    return {"status": res.get("status"), "plan": res.get("plan"), "order_id": req.order_id}


@api_router.get("/paypal/config")
async def paypal_config():
    return {"client_id": os.environ.get("PAYPAL_CLIENT_ID", ""), "mode": os.environ.get("PAYPAL_MODE", "sandbox")}


# ========== STARTUP ==========
@app.on_event("startup")
async def startup():
    try:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("user_id", unique=True)
        await db.user_sessions.create_index("session_token", unique=True)
        await db.user_sessions.create_index("user_id")
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    except Exception as e:
        logger.warning(f"index: {e}")
    logger.info("OptiScreen API ready")

@app.on_event("shutdown")
async def shutdown():
    client.close()


@api_router.get("/")
async def root():
    return {"service": "OptiScreen API", "ok": True}


app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
