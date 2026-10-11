"""Options math: breakevens, max profit/loss, Black-Scholes Greeks, scenario matrix."""
from __future__ import annotations
import math
from typing import Dict, List, Optional

SQRT_2PI = math.sqrt(2 * math.pi)

def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def bs_greeks(S: float, K: float, T: float, sigma: float, r: float = 0.045, call: bool = True) -> Dict[str, float]:
    """Black-Scholes European option Greeks. T in years, sigma annualized."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return {"price": 0.0, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if call:
        price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        delta = norm_cdf(d1)
        theta = -(S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm_cdf(d2)
        rho = K * T * math.exp(-r * T) * norm_cdf(d2) / 100
    else:
        price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1
        theta = -(S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm_cdf(-d2)
        rho = -K * T * math.exp(-r * T) * norm_cdf(-d2) / 100
    gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * norm_pdf(d1) * math.sqrt(T) / 100
    return {
        "price": round(price, 2),
        "delta": round(delta, 3),
        "gamma": round(gamma, 4),
        "theta": round(theta / 365, 3),  # per-day theta
        "vega": round(vega, 3),
        "rho": round(rho, 3),
    }


def enrich_legs_with_greeks(legs: List[Dict], S: float, iv: float = 0.35, dte_days: int = 30) -> List[Dict]:
    T = max(dte_days, 1) / 365
    out = []
    for l in legs:
        is_call = l.get("type", "Call").lower() == "call"
        K = float(l["strike"])
        g = bs_greeks(S, K, T, iv, call=is_call)
        sign = 1 if l.get("action", "Buy").lower() == "buy" else -1
        out.append({
            **l,
            "theo_price": g["price"],
            "delta": round(g["delta"] * sign, 3),
            "gamma": round(g["gamma"] * sign, 4),
            "theta": round(g["theta"] * sign, 3),
            "vega": round(g["vega"] * sign, 3),
        })
    return out


def analyze_strategy_payoff(strategy: str, legs: List[Dict], S: float, premium_net: float) -> Dict:
    """Compute breakevens, max profit, max loss for common strategies.

    `premium_net` convention: positive = credit received, negative = debit paid.
    """
    strikes = [float(l["strike"]) for l in legs]
    s = strategy.lower()
    if "cash secured put" in s and len(legs) == 1:
        K = strikes[0]
        max_profit = round(premium_net * 100, 2)
        max_loss = round((K - premium_net) * 100 * -1, 2) if (K - premium_net) > 0 else 0
        be = [round(K - premium_net, 2)]
    elif "covered call" in s and len(legs) == 1:
        K = strikes[0]
        max_profit = round((K - S + premium_net) * 100, 2)
        max_loss = round((-(S - premium_net)) * 100, 2)  # if stock to 0
        be = [round(S - premium_net, 2)]
    elif "bull put spread" in s and len(legs) == 2:
        short_K = max(strikes); long_K = min(strikes)
        width = short_K - long_K
        max_profit = round(premium_net * 100, 2)
        max_loss = round((premium_net - width) * 100, 2)
        be = [round(short_K - premium_net, 2)]
    elif "bear call spread" in s and len(legs) == 2:
        short_K = min(strikes); long_K = max(strikes)
        width = long_K - short_K
        max_profit = round(premium_net * 100, 2)
        max_loss = round((premium_net - width) * 100, 2)
        be = [round(short_K + premium_net, 2)]
    elif "iron condor" in s and len(legs) == 4:
        puts = sorted([float(l["strike"]) for l in legs if l["type"].lower() == "put"])
        calls = sorted([float(l["strike"]) for l in legs if l["type"].lower() == "call"])
        width = max(puts[1] - puts[0], calls[1] - calls[0]) if puts and calls else 5
        max_profit = round(premium_net * 100, 2)
        max_loss = round((premium_net - width) * 100, 2)
        be = [round(puts[1] - premium_net, 2), round(calls[0] + premium_net, 2)]
    elif "short strangle" in s and len(legs) == 2:
        put_K = min(strikes); call_K = max(strikes)
        max_profit = round(premium_net * 100, 2)
        max_loss = None  # undefined
        be = [round(put_K - premium_net, 2), round(call_K + premium_net, 2)]
    else:
        max_profit = round(premium_net * 100, 2)
        max_loss = None
        be = []
    return {"max_profit": max_profit, "max_loss": max_loss, "breakevens": be}


def scenario_matrix(S: float, premium_net: float, legs: List[Dict], iv: float = 0.35, dte_days: int = 30) -> List[Dict]:
    """Return P&L estimate across price moves and days-to-expiration shrinkage."""
    out = []
    price_moves = [-0.10, -0.05, -0.02, 0, 0.02, 0.05, 0.10]
    days_elapsed = [0, round(dte_days * 0.5), dte_days]
    for d in days_elapsed:
        T = max(dte_days - d, 0.001) / 365
        row = {"days_elapsed": d, "pnl": {}}
        for mv in price_moves:
            S_new = S * (1 + mv)
            total_premium_now = 0.0
            for l in legs:
                is_call = l.get("type", "Call").lower() == "call"
                sign = 1 if l.get("action", "Buy").lower() == "buy" else -1
                g = bs_greeks(S_new, float(l["strike"]), T, iv, call=is_call)
                total_premium_now += g["price"] * sign
            # P&L = (current - entry) * 100 ; entry = -premium_net (if credit, we received)
            # premium_net > 0 credit; we open at receiving abs(premium_net), close at paying total_premium_now (which is negative for net credit)
            # Net credit P&L: premium_received - cost_to_close = premium_net - (-total_premium_now) = premium_net + total_premium_now
            # Simpler: pnl = -(total_premium_now - (-premium_net))*100 = (premium_net + total_premium_now)*100 ... but sign conventions vary.
            # Use: entry debit = -premium_net; current value = total_premium_now; pnl = current - entry * 100
            pnl = round((total_premium_now - (-premium_net)) * 100, 2)
            row["pnl"][f"{int(mv*100):+d}%"] = pnl
        out.append(row)
    return out
