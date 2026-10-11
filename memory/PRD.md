# OptiScreen - AI Stock & Options Intelligence Platform

## Vision
Research-first, transparent, trust-driven AI intelligence platform. AI acts as an interpreter — explaining structured evidence, surfacing uncertainty — not predicting markets.

## Core Modules (5-tab navigation)
1. **Discover** — Find candidates. Best Opportunities (period-based ranking) + Find Stocks (filter by risk/reward/expiration/sector). Hard eligibility filters applied before ranking.
2. **Analyze** — Understand one instrument. Options Strategy Lab (Greeks, breakevens, max profit/loss, scenario matrix, assumptions, data provenance) + Day/Swing/Long-term engines.
3. **Portfolio** — Watchlist with live quotes and sector concentration view.
4. **Alerts** — Price above/below and earnings-approaching alerts; push notifications on native build.
5. **Learn** — Strategy playbook (options strategies) + Risk primer + Fundamentals education + Options glossary. Progressive disclosure. ElevenLabs TTS to listen.

## Onboarding
- Account (email+password or Google) → Plan selection → Expanded questionnaire → Consent
- Questionnaire captures: objectives (multi), experience, horizon, risk tolerance vs risk capacity, capital range, max single-trade loss, options approval level, preferred sectors, exclusions.
- Explicit disclosure (no financial advice, model limitations).

## Options Strategy Lab Output
- Full leg details (action, type, strike, exp, qty, theo price)
- Black-Scholes Greeks per leg + aggregate (delta, gamma, theta/day, vega)
- Breakevens (list)
- Max profit, max loss (null for undefined-risk)
- Probability of profit (model-based estimate)
- Scenario matrix (P&L across ±10% price moves × 3 time slices)
- Collateral, APR with/without margin
- Explicit assumptions (IV, risk-free rate, model name)
- Data provenance (source, fetched_at)

## Data stack
- **Finnhub** — real-time US quotes, fundamentals, peers, analyst ratings, earnings dates
- **Polygon** — daily candles (free tier, delayed 15 min)
- **Alpha Vantage** — fallback for candles
- All numbers cached (30s quotes / 1h+ profile/metrics) to respect free-tier limits.

## Integrations
- **Claude Sonnet 5.5** via Emergent Universal Key — explanation layer (AI as interpreter)
- **Emergent Push** — daily top pick + earnings reminders (signed native build)
- **ElevenLabs** — TTS reads AI summaries; STT voice ticker entry
- **PayPal (sandbox)** — plan upgrades Simple $9 / Advance $29 / Expert $79

## Backend endpoints
- Auth: register/login/session (Google)/me/logout
- User: /plan, /questionnaire, /consent
- Screener: /find-stocks, /best-options, /ticker-options, /stock-analysis, /quote/{ticker}, /stocks
- Watchlist: add/list/remove
- Alerts: add/list/remove
- Learn: /cards (public)
- Push: /register-push, /push/test, /push/daily-pick, /push/earnings-reminder
- Voice: /tts/generate, /stt/transcribe
- PayPal: /create-order, /capture-order, /config

## Not in MVP
- Automatic order execution
- Real option-chain premiums (currently theoretical via Black-Scholes)
- Broker integrations
- Paper trading / trade journal / outcome tracking (roadmap Phase 4)
- Portfolio stress tests / correlation (roadmap Phase 5)

## Testing
- 21/21 backend tests pass (/app/backend/tests/test_pivot_features.py).
