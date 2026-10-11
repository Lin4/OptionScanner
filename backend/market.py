"""Real-time market data layer.

Finnhub-first with Polygon fallback for candles, Alpha Vantage as last-resort.
In-memory TTL cache to respect free-tier rate limits.
"""
from __future__ import annotations
import os
import time
import asyncio
import logging
import math
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("optiscreen.market")

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
AV_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")

_cache: Dict[str, tuple[float, Any]] = {}

def _cache_get(key: str, ttl: float):
    v = _cache.get(key)
    if not v: return None
    t, data = v
    if time.time() - t > ttl: return None
    return data

def _cache_set(key: str, data: Any):
    _cache[key] = (time.time(), data)


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Optional[dict]:
    try:
        r = await client.get(url, params=params, timeout=10.0)
        if r.status_code != 200:
            logger.warning(f"GET {url} -> {r.status_code} {r.text[:120]}")
            return None
        return r.json()
    except Exception as e:
        logger.warning(f"GET {url} failed: {e}")
        return None


# =========== TICKER UNIVERSE ===========
UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Tech"},
    {"ticker": "MSFT", "name": "Microsoft Corp.", "sector": "Tech"},
    {"ticker": "NVDA", "name": "NVIDIA Corp.", "sector": "Tech"},
    {"ticker": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary"},
    {"ticker": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary"},
    {"ticker": "META", "name": "Meta Platforms", "sector": "Tech"},
    {"ticker": "GOOGL", "name": "Alphabet Inc.", "sector": "Tech"},
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "Financials"},
    {"ticker": "XOM", "name": "Exxon Mobil", "sector": "Energy"},
    {"ticker": "PFE", "name": "Pfizer Inc.", "sector": "Healthcare"},
    {"ticker": "DIS", "name": "Walt Disney", "sector": "Consumer Discretionary"},
    {"ticker": "AMD", "name": "Advanced Micro Devices", "sector": "Tech"},
    {"ticker": "SPY", "name": "S&P 500 ETF", "sector": "Index"},
    {"ticker": "COST", "name": "Costco Wholesale", "sector": "Consumer Staples"},
    {"ticker": "BA", "name": "Boeing Co.", "sector": "Industrials"},
]
UNIVERSE_INDEX = {s["ticker"]: s for s in UNIVERSE}


# =========== QUOTE ===========
async def get_quote(client: httpx.AsyncClient, ticker: str) -> Optional[Dict[str, float]]:
    """Return {price, change, change_pct, high, low, prev_close, open} or None."""
    key = f"q:{ticker}"
    hit = _cache_get(key, 30.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/quote", {"symbol": ticker, "token": FINNHUB_KEY})
    if data and (data.get("c") or 0) > 0:
        q = {
            "price": float(data["c"]),
            "change": float(data.get("d") or 0),
            "change_pct": float(data.get("dp") or 0),
            "high": float(data.get("h") or 0),
            "low": float(data.get("l") or 0),
            "open": float(data.get("o") or 0),
            "prev_close": float(data.get("pc") or 0),
        }
        _cache_set(key, q)
        return q
    return None


# =========== CANDLES ===========
async def get_candles(client: httpx.AsyncClient, ticker: str, days: int = 30) -> List[Dict[str, float]]:
    """Return list of {o,h,l,c,v} daily candles. Polygon-first (free tier works), fallback Alpha Vantage."""
    key = f"c:{ticker}:{days}"
    hit = _cache_get(key, 300.0)
    if hit is not None: return hit

    # Polygon aggs (free tier gives 2-year history delayed)
    import datetime as dt
    end = dt.date.today()
    start = end - dt.timedelta(days=max(days * 2, 60))
    pdata = await _get(
        client,
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}",
        {"adjusted": "true", "sort": "asc", "limit": 300, "apiKey": POLYGON_KEY},
    )
    if pdata and pdata.get("results"):
        candles = [
            {"o": float(x["o"]), "h": float(x["h"]), "l": float(x["l"]), "c": float(x["c"]), "v": float(x.get("v", 0)), "t": int(x["t"])}
            for x in pdata["results"]
        ][-days:]
        if candles:
            _cache_set(key, candles)
            return candles

    # Alpha Vantage daily fallback (rate-limited but okay)
    adata = await _get(
        client, "https://www.alphavantage.co/query",
        {"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": "compact", "apikey": AV_KEY},
    )
    series = (adata or {}).get("Time Series (Daily)")
    if series:
        rows = sorted(series.items())[-days:]
        candles = [{
            "o": float(v["1. open"]),
            "h": float(v["2. high"]),
            "l": float(v["3. low"]),
            "c": float(v["4. close"]),
            "v": float(v["5. volume"]),
        } for _, v in rows]
        if candles:
            _cache_set(key, candles)
            return candles

    return []


# =========== PROFILE / FINANCIALS ===========
async def get_profile(client: httpx.AsyncClient, ticker: str) -> Dict[str, Any]:
    key = f"p:{ticker}"
    hit = _cache_get(key, 86400.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/stock/profile2", {"symbol": ticker, "token": FINNHUB_KEY}) or {}
    prof = {
        "name": data.get("name") or UNIVERSE_INDEX.get(ticker, {}).get("name") or ticker,
        "sector": data.get("finnhubIndustry") or UNIVERSE_INDEX.get(ticker, {}).get("sector") or "Unknown",
        "market_cap_bn": round((data.get("marketCapitalization") or 0) / 1000, 2),
        "logo": data.get("logo"),
        "country": data.get("country"),
        "exchange": data.get("exchange"),
        "ipo": data.get("ipo"),
    }
    _cache_set(key, prof)
    return prof


async def get_metrics(client: httpx.AsyncClient, ticker: str) -> Dict[str, Any]:
    key = f"m:{ticker}"
    hit = _cache_get(key, 3600.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/stock/metric", {"symbol": ticker, "metric": "all", "token": FINNHUB_KEY}) or {}
    m = data.get("metric") or {}
    result = {
        "pe_ttm": m.get("peBasicExclExtraTTM") or m.get("peNormalizedAnnual"),
        "ps_ttm": m.get("psTTM"),
        "eps_ttm": m.get("epsBasicExclExtraItemsTTM") or m.get("epsNormalizedAnnual"),
        "52w_high": m.get("52WeekHigh"),
        "52w_low": m.get("52WeekLow"),
        "beta": m.get("beta"),
        "dividend_yield": m.get("dividendYieldIndicatedAnnual"),
        "revenue_growth_ttm": m.get("revenueGrowthTTMYoy"),
        "net_profit_margin": m.get("netProfitMarginTTM"),
        "roe_ttm": m.get("roeTTM"),
        "debt_to_equity": m.get("totalDebt/totalEquityAnnual"),
    }
    _cache_set(key, result)
    return result


async def get_earnings(client: httpx.AsyncClient, ticker: str) -> Dict[str, Any]:
    key = f"e:{ticker}"
    hit = _cache_get(key, 3600.0)
    if hit is not None: return hit
    import datetime as dt
    today = dt.date.today()
    end = today + dt.timedelta(days=120)
    data = await _get(client, "https://finnhub.io/api/v1/calendar/earnings", {
        "symbol": ticker, "from": today.isoformat(), "to": end.isoformat(), "token": FINNHUB_KEY,
    }) or {}
    rows = data.get("earningsCalendar") or []
    if not rows:
        past = today - dt.timedelta(days=120)
        data2 = await _get(client, "https://finnhub.io/api/v1/calendar/earnings", {
            "symbol": ticker, "from": past.isoformat(), "to": today.isoformat(), "token": FINNHUB_KEY,
        }) or {}
        rows = data2.get("earningsCalendar") or []
    row = rows[0] if rows else {}
    result = {
        "date": row.get("date"),
        "eps_estimate": row.get("epsEstimate"),
        "eps_actual": row.get("epsActual"),
        "revenue_estimate": row.get("revenueEstimate"),
    }
    _cache_set(key, result)
    return result


async def get_peers(client: httpx.AsyncClient, ticker: str) -> List[str]:
    key = f"pr:{ticker}"
    hit = _cache_get(key, 86400.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/stock/peers", {"symbol": ticker, "token": FINNHUB_KEY}) or []
    peers = [p for p in data if p and p != ticker][:5]
    _cache_set(key, peers)
    return peers


async def get_recommendations(client: httpx.AsyncClient, ticker: str) -> Dict[str, int]:
    key = f"r:{ticker}"
    hit = _cache_get(key, 86400.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/stock/recommendation", {"symbol": ticker, "token": FINNHUB_KEY}) or []
    row = (data or [{}])[0]
    result = {
        "buy": int(row.get("strongBuy", 0) + row.get("buy", 0)),
        "hold": int(row.get("hold", 0)),
        "sell": int(row.get("sell", 0) + row.get("strongSell", 0)),
        "period": row.get("period"),
    }
    _cache_set(key, result)
    return result


async def get_price_target(client: httpx.AsyncClient, ticker: str) -> Optional[float]:
    key = f"pt:{ticker}"
    hit = _cache_get(key, 86400.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/stock/price-target", {"symbol": ticker, "token": FINNHUB_KEY}) or {}
    pt = data.get("targetMean") or data.get("targetMedian")
    if pt:
        _cache_set(key, float(pt))
        return float(pt)
    return None


async def get_news_sentiment(client: httpx.AsyncClient, ticker: str) -> Optional[Dict[str, float]]:
    key = f"ns:{ticker}"
    hit = _cache_get(key, 3600.0)
    if hit is not None: return hit
    data = await _get(client, "https://finnhub.io/api/v1/news-sentiment", {"symbol": ticker, "token": FINNHUB_KEY}) or {}
    s = data.get("sentiment") or {}
    if s:
        res = {"bullish": float(s.get("bullishPercent") or 0), "bearish": float(s.get("bearishPercent") or 0)}
        _cache_set(key, res)
        return res
    return None


# =========== TECHNICAL CALCS ===========
def sma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n: return None
    return round(sum(values[-n:]) / n, 2)


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1: return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff > 0: gains += diff
        else: losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def support_resistance(candles: List[Dict]) -> tuple[float, float]:
    if not candles: return 0.0, 0.0
    lows = [c["l"] for c in candles[-30:]]
    highs = [c["h"] for c in candles[-30:]]
    return round(min(lows), 2), round(max(highs), 2)


def detect_candle_patterns(candles: List[Dict]) -> List[str]:
    if len(candles) < 3: return []
    out = []
    c2, c1, c0 = candles[-3], candles[-2], candles[-1]
    # Hammer: small body, long lower wick
    body = abs(c0["c"] - c0["o"])
    lower_wick = min(c0["o"], c0["c"]) - c0["l"]
    upper_wick = c0["h"] - max(c0["o"], c0["c"])
    rng = c0["h"] - c0["l"] or 1
    if lower_wick > 2 * body and upper_wick < body and body / rng > 0.1:
        out.append("Hammer")
    # Bullish engulfing
    if c1["c"] < c1["o"] and c0["c"] > c0["o"] and c0["c"] > c1["o"] and c0["o"] < c1["c"]:
        out.append("Bullish Engulfing")
    # Bearish engulfing
    if c1["c"] > c1["o"] and c0["c"] < c0["o"] and c0["c"] < c1["o"] and c0["o"] > c1["c"]:
        out.append("Bearish Engulfing")
    # Three white soldiers
    if all(x["c"] > x["o"] for x in (c2, c1, c0)) and c0["c"] > c1["c"] > c2["c"]:
        out.append("Three White Soldiers")
    return out[:3] or ["Doji"]


def detect_chart_patterns(candles: List[Dict]) -> List[str]:
    if len(candles) < 20: return []
    closes = [c["c"] for c in candles]
    sma20 = sma(closes, 20)
    sma50 = sma(closes, min(50, len(closes)))
    out = []
    if sma20 and sma50:
        if sma20 > sma50 * 1.01: out.append("Golden Cross")
        elif sma20 < sma50 * 0.99: out.append("Death Cross")
    # Double bottom (two troughs in last 20 candles)
    lows = [c["l"] for c in candles[-20:]]
    mn = min(lows)
    close_to_min = [i for i, l in enumerate(lows) if abs(l - mn) / mn < 0.02]
    if len(close_to_min) >= 2 and (close_to_min[-1] - close_to_min[0]) >= 5:
        out.append("Double Bottom")
    # Uptrend / Downtrend
    if sma20 and candles[-1]["c"] > sma20 and sma20 > candles[-20]["c"]:
        out.append("Uptrend")
    return out[:3] or ["Consolidation"]


# =========== HIGH-LEVEL: full stock bundle ===========
async def fetch_stock_bundle(ticker: str) -> Dict[str, Any]:
    """Fetch everything we need for a ticker in parallel."""
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            get_quote(client, ticker),
            get_candles(client, ticker, 60),
            get_profile(client, ticker),
            get_metrics(client, ticker),
            get_earnings(client, ticker),
            get_peers(client, ticker),
            get_recommendations(client, ticker),
            get_price_target(client, ticker),
            get_news_sentiment(client, ticker),
            return_exceptions=True,
        )
    quote, candles, profile, metrics, earnings, peers, recs, pt, sentiment = results
    # Normalize exceptions
    def ok(x): return x if not isinstance(x, Exception) else None
    quote = ok(quote); candles = ok(candles) or []; profile = ok(profile) or {}
    metrics = ok(metrics) or {}; earnings = ok(earnings) or {}; peers = ok(peers) or []
    recs = ok(recs) or {}; pt = ok(pt); sentiment = ok(sentiment)

    closes = [c["c"] for c in candles]
    sma_20 = sma(closes, 20)
    sma_50 = sma(closes, 50)
    rsi_14 = rsi(closes)
    sup, res = support_resistance(candles)
    cp = detect_candle_patterns(candles)
    chartp = detect_chart_patterns(candles)
    trend = "Uptrend" if sma_20 and sma_50 and sma_20 > sma_50 else ("Downtrend" if sma_20 and sma_50 and sma_20 < sma_50 else "Sideways")

    return {
        "ticker": ticker,
        "name": profile.get("name") or ticker,
        "sector": profile.get("sector"),
        "profile": profile,
        "quote": quote,
        "price": quote["price"] if quote else None,
        "candles": candles,
        "sma_20": sma_20, "sma_50": sma_50, "rsi": rsi_14,
        "support": sup, "resistance": res,
        "candlestick_patterns": cp,
        "chart_patterns": chartp,
        "trend": trend,
        "metrics": metrics,
        "earnings": earnings,
        "peers": peers,
        "analyst_ratings": {k: v for k, v in recs.items() if k in ("buy", "hold", "sell")},
        "price_target": pt,
        "news_sentiment": sentiment,
    }
