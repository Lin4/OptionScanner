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


# ========== MOCK MARKET DATA ==========
STOCKS = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Tech", "price": 232.14},
    {"ticker": "MSFT", "name": "Microsoft Corp.", "sector": "Tech", "price": 428.90},
    {"ticker": "NVDA", "name": "NVIDIA Corp.", "sector": "Tech", "price": 142.56},
    {"ticker": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary", "price": 348.72},
    {"ticker": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary", "price": 215.33},
    {"ticker": "META", "name": "Meta Platforms", "sector": "Tech", "price": 612.44},
    {"ticker": "GOOGL", "name": "Alphabet Inc.", "sector": "Tech", "price": 192.08},
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "Financials", "price": 248.19},
    {"ticker": "XOM", "name": "Exxon Mobil", "sector": "Energy", "price": 115.26},
    {"ticker": "PFE", "name": "Pfizer Inc.", "sector": "Healthcare", "price": 26.44},
    {"ticker": "DIS", "name": "Walt Disney", "sector": "Consumer Discretionary", "price": 112.08},
    {"ticker": "AMD", "name": "Advanced Micro Devices", "sector": "Tech", "price": 128.72},
    {"ticker": "SPY", "name": "S&P 500 ETF", "sector": "Index", "price": 598.33},
    {"ticker": "COST", "name": "Costco Wholesale", "sector": "Consumer Staples", "price": 962.11},
    {"ticker": "BA", "name": "Boeing Co.", "sector": "Industrials", "price": 178.44},
]

STRATEGIES = ["Cash Secured Put", "Covered Call", "Bull Put Spread", "Iron Condor", "Bear Call Spread", "Short Strangle"]

def gen_sparkline(base: float) -> List[float]:
    """Generate 20-point sparkline with mild walk."""
    pts = []
    cur = base * 0.95
    for _ in range(20):
        cur += (random.random() - 0.47) * base * 0.015
        pts.append(round(cur, 2))
    return pts

def gen_candles(base: float, n: int = 30) -> List[Dict[str, float]]:
    out = []
    cur = base * 0.9
    for i in range(n):
        o = cur
        c = cur + (random.random() - 0.48) * base * 0.025
        h = max(o, c) + random.random() * base * 0.01
        l = min(o, c) - random.random() * base * 0.01
        out.append({"o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2)})
        cur = c
    return out

def gen_option_strategy(stock: Dict, expiration: str) -> Dict:
    price = stock["price"]
    strat = random.choice(STRATEGIES)
    exp_days = {"daily": 1, "day": 1, "week": 7, "month": 30, "3months": 90, "custom": 14}.get(expiration, 30)
    exp_date = (now_utc() + timedelta(days=exp_days)).strftime("%Y-%m-%d")
    pop = random.randint(55, 92)
    premium = round(price * random.uniform(0.005, 0.025), 2)
    collateral = round(price * random.uniform(0.9, 1.1) * 100, 2)
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
        "ticker": stock["ticker"],
        "name": stock["name"],
        "sector": stock["sector"],
        "price": price,
        "strategy": strat,
        "legs": legs,
        "premium": premium,
        "expiration": exp_date,
        "expiration_days": exp_days,
        "pop": pop,
        "collateral": collateral,
        "collateral_margin": collat_margin,
        "annual_pct_no_margin": annual_pct_collat,
        "annual_pct_margin": annual_pct_margin,
        "sparkline": gen_sparkline(price),
    }


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
    pool = STOCKS[:]
    if req.sectors:
        pool = [s for s in pool if s["sector"] in req.sectors]
    if not pool:
        pool = STOCKS[:]
    random.shuffle(pool)
    picks = pool[: req.limit]

    system = "You are a sharp options strategist. Reply with ONLY valid JSON, no markdown."
    tickers = [p["ticker"] for p in picks]
    prompt = (
        f"User seeks optionable stocks matching: risk={req.risk}, reward={req.reward}, "
        f"expiration={req.expiration}, sectors={req.sectors or 'any'}.\n"
        f"For each ticker in {tickers}, give a 1-sentence rationale and a bullish/bearish/neutral bias. "
        f'Reply JSON: {{"picks":[{{"ticker":"XX","bias":"bullish","rationale":"..."}}]}}'
    )
    txt = await call_claude(system, prompt)
    ai = extract_json(txt) or {"picks": []}
    ai_map = {p.get("ticker"): p for p in ai.get("picks", [])}

    results = []
    for s in picks:
        opt = gen_option_strategy(s, req.expiration)
        ai_p = ai_map.get(s["ticker"], {})
        opt["bias"] = ai_p.get("bias", "neutral")
        opt["rationale"] = ai_p.get("rationale", f"Fits {req.risk} risk / {req.reward} reward profile.")
        results.append(opt)
    return {"results": results}

@api_router.post("/screener/best-options")
async def best_options(req: BestOptionsReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    period_map = {"day": "daily", "week": "week", "month": "month", "custom": "custom"}
    exp = period_map.get(req.period, "week")
    picks = random.sample(STOCKS, min(req.limit, len(STOCKS)))
    results = [gen_option_strategy(s, exp) for s in picks]
    # Sort by annual pct desc so "best" ranked first
    results.sort(key=lambda r: r["annual_pct_no_margin"], reverse=True)

    system = "You are an options strategist. Reply with ONLY valid JSON."
    prompt = (
        f"For a {req.period} horizon, rank the top strategies for {[r['ticker'] for r in results]} "
        f'and provide a 1-line summary. JSON: {{"summary":"...","top_pick":"TICKER"}}'
    )
    txt = await call_claude(system, prompt)
    ai = extract_json(txt) or {}
    return {"results": results, "ai_summary": ai.get("summary", "Top yield plays this period."), "top_pick": ai.get("top_pick")}

@api_router.post("/screener/ticker-options")
async def ticker_options(req: TickerOptionsReq, authorization: Optional[str] = Header(default=None)):
    await get_user_from_token(authorization)
    tk = req.ticker.upper()
    stock = next((s for s in STOCKS if s["ticker"] == tk), None)
    if not stock:
        stock = {"ticker": tk, "name": tk, "sector": "Unknown", "price": round(random.uniform(50, 400), 2)}
    opt = gen_option_strategy(stock, req.expiration_range)

    system = "You are an options strategist. Reply with ONLY valid JSON, no markdown."
    prompt = (
        f"Analyze {tk} for {req.expiration_range} options play. "
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
    stock = next((s for s in STOCKS if s["ticker"] == tk), None)
    if not stock:
        stock = {"ticker": tk, "name": tk, "sector": "Unknown", "price": round(random.uniform(50, 400), 2)}
    price = stock["price"]
    candles = gen_candles(price, 30)

    if req.purpose in ("day", "swing"):
        buy = round(price * random.uniform(0.97, 0.99), 2)
        sell = round(price * random.uniform(1.03, 1.08), 2)
        stop = round(price * random.uniform(0.93, 0.96), 2)
        patterns = random.sample(
            ["Bullish Engulfing", "Double Bottom", "Golden Cross", "Hammer", "Ascending Triangle", "Flag"],
            k=3,
        )
        resp = {
            "ticker": tk, "name": stock["name"], "price": price,
            "purpose": req.purpose,
            "candles": candles,
            "buy_point": buy, "sell_point": sell, "stop_loss": stop,
            "support": round(price * 0.94, 2), "resistance": round(price * 1.07, 2),
            "sma_20": round(price * random.uniform(0.97, 1.02), 2),
            "sma_50": round(price * random.uniform(0.94, 1.05), 2),
            "rsi": random.randint(35, 72),
            "short_float_pct": round(random.uniform(1.2, 15.4), 2),
            "short_interest": round(random.uniform(5, 80), 1),
            "option_volume": random.randint(50000, 2500000),
            "candlestick_patterns": patterns,
            "chart_patterns": random.sample(["Double Bottom", "Head & Shoulders", "Cup & Handle", "Bull Flag"], k=2),
            "market_sentiment": random.choice(["Bullish", "Neutral", "Bearish"]),
            "intrinsic_value": round(price * random.uniform(0.85, 1.15), 2),
            "profit_probability": random.randint(55, 85),
        }
        system = "You are a short-term trading analyst. Reply ONLY valid JSON."
        prompt = (
            f"Analyze {tk} for {req.purpose} trading at ${price}. "
            f'JSON: {{"summary":"...","verdict":"BUY|SELL|HOLD","confidence":"low|med|high"}}'
        )
    else:
        resp = {
            "ticker": tk, "name": stock["name"], "price": price,
            "purpose": "long",
            "candles": candles,
            "intrinsic_value": round(price * random.uniform(0.85, 1.25), 2),
            "price_target": round(price * random.uniform(1.1, 1.4), 2),
            "stock_trend": random.choice(["Uptrend", "Downtrend", "Sideways"]),
            "earnings_date": (now_utc() + timedelta(days=random.randint(5, 60))).strftime("%Y-%m-%d"),
            "earnings_eps_estimate": round(random.uniform(0.5, 4.5), 2),
            "revenue_billions": round(random.uniform(5, 400), 2),
            "net_cash_billions": round(random.uniform(-50, 200), 2),
            "net_profit_billions": round(random.uniform(-10, 100), 2),
            "debt_billions": round(random.uniform(0, 200), 2),
            "business_moat": random.choice(["Wide", "Narrow", "None"]),
            "competitors": random.sample(["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"], k=3),
            "analyst_ratings": {
                "buy": random.randint(5, 25),
                "hold": random.randint(1, 10),
                "sell": random.randint(0, 5),
            },
            "buy_point": round(price * random.uniform(0.88, 0.95), 2),
            "sell_point": round(price * random.uniform(1.2, 1.5), 2),
        }
        system = "You are a long-term value investor. Reply ONLY valid JSON."
        prompt = (
            f"Give a long-term thesis for {tk} at ${price}. "
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
    return {"stocks": STOCKS}


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
    pick = random.choice(STOCKS)
    try:
        await send_push(
            recipients=[user["user_id"]],
            data={
                "title": f"Today's top pick: {pick['ticker']}",
                "message": f"{pick['name']} shows strong setup at ${pick['price']}. Tap to analyze.",
                "action_url": f"/ticker/{pick['ticker']}",
            },
        )
    except Exception as e:
        logger.warning(f"daily pick push failed: {e}")
        return {"ok": False, "ticker": pick["ticker"], "error": str(e)}
    return {"ok": True, "ticker": pick["ticker"]}


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
