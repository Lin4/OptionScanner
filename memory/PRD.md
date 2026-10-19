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

## Phase A (Untitled.docx plan) — DONE
- `engine.py`: deterministic engine (code calculates, AI explains). 13 strategies, mid + slippage + fees pricing, lognormal POP, EV vs realized vol, numeric payoff stats.
- Risk profiles low_low / low_high / high_high + sliders (max loss %, min POP, min ROC, min IV rank, min OI, max spread %, skip earnings, bias).
- Liquidity (OI/volume/bid-ask) = MODEL ESTIMATE (labelled). IV = HV-blended estimate; IV rank from rolling HV.
- Collateral/ROC/annualized for Cash, IRA, Reg T, Portfolio margin (naked blocked in cash/IRA).
- Events: earnings in window, dividend early-assignment, pin risk, assignment notes.
- Swing/day trade plan: ATR stops, support/resistance, min R:R, position sizing, short-side view, bull/base/bear scenarios.
- Long-term: editable DCF bull/base/bear + buy/sell zones (`/screener/valuation`).
- Speed: background pre-warm of universe, 6h candle cache, 60s scan cache, AI explanations async via `/screener/explain` (cached 30m).
- Alert threshold validation.

## Phase B — POP floor + options-level gating — DONE
- Discover always enforces POP >= 70% (MIN_POP_FLOOR) for every profile; slider min 70.
- Strategies gated by questionnaire options_level, capped by experience (None/Beginner→L1, Intermediate→L3).
  L1: CSP, Covered Call · L3: + credit spreads, iron condor, debit spreads · L4 (Full): + naked Sell Put, Sell Call, Short Strangle.
- New naked strategies Sell Put / Sell Call (margin only). Credit strategies scanned at 3 strike distances.
- CSP/CC/Sell Put sized by collateral <= account size (not max-loss %).
- Locked profile cards + level banner on Discover.

## Phase C — Track record, Smart alerts, Level-up lessons — DONE (`backend/extras.py`)
- Track record (`/track-record` screen, `GET /api/track-record`): every Discover pick logged in `picks` (dedup key) and settled at real close on expiry; hypothetical 90-day backtest (engine re-run on past daily closes, refreshed every 6h) with predicted-vs-actual POP buckets.
- Smart alerts: alert kind `smart_setup` (note = profile); loop every 30 min in US market hours, max 3/day, 24h dedup, level-gated; feed `GET /api/alerts/feed`, manual `POST /api/alerts/smart/check`; push via Emergent push (native build only).
- Level-up lessons: 4 levels × 3 lessons + 3-question quiz (`/api/learn/levels`, `/lesson/[level]` screen), badges in `lesson_progress`; doesn't change options level.
- Note: `import extras` must stay AFTER load_dotenv in server.py (market.py reads API keys at import).

## Phase D — Membership & payments — DONE (`backend/billing.py`, `frontend/src/plans.tsx`, `src/revenuecat.tsx`, `app/upgrade.tsx`)
- 7-day free trial from registration (tier "trial", Simple features, 5 scans/day); then "expired" → full paywall (PlanGate) on Discover/Analyze/Portfolio/Alerts; Learn & Profile stay open.
- Tiers: Simple $9 (10 scans, CC/CSP, 3 alerts), Advance $29 (unlimited scans, spreads/IC, custom periods, collateral views, smart alerts, 20 alerts, AI explain, backtest), Expert $79 (+naked, day lab, voice, daily push, unlimited alerts).
- Payments: Stripe subscription Checkout (card/Apple Pay/Google Pay, verified via session status polling — Emergent Stripe proxy has no webhooks/subscription API, so plan_expires_at = +31d), PayPal sandbox (30 days), RevenueCat Apple IAP on iPhone (entitlement `pro`, tier from package; see /app/memory/revenuecat.md).
- Gating is enforced client-side via usePlan() (server tier merged with RevenueCat tier); server counts scans (`usage`) and restricts strategies by `tier`.

## Backlog (from plan)
- Phase 2: long-term research page (ownership, dividends history, filings risks, price-target dispersion), paper trading + public track record, IV/setup alerts, nav order (stock screening first), tier data rules.
- Phase 3: backtesting, position monitoring, broker connection, trade journal, intraday tools, real options data feed.

## Not in MVP
- Automatic order execution
- Real option-chain premiums (currently theoretical via Black-Scholes)
- Broker integrations
- Paper trading / trade journal / outcome tracking (roadmap Phase 4)
- Portfolio stress tests / correlation (roadmap Phase 5)

## Testing
- 21/21 backend tests pass (/app/backend/tests/test_pivot_features.py).

## Update (Jun 2026)
- Alerts: AlertAddReq now validates kind (Literal), threshold (>0, <=1e7, no NaN/inf), and requires threshold for price alerts -> 422 on bad payloads.
- Login: retitled 'Sign in to OptiScreen' + hint that it's not the Expo account.

## Update (Jun 2026) — Live options + new OptiIQ
- Tradier live options (backend/tradier.py): TRADIER_ENV=production, tokens in backend/.env. Nearest listed expiration to target DTE, chain cached 60s, exp list 6h. engine.build_idea(chain=...) snaps strikes to listed ones, prices from bid/ask mid, real OI/volume/Greeks/ATM IV. Falls back to Black-Scholes per leg if missing. Fields: live_quotes, quote_source, quotes_as_of, data_source.options_live. Backtest/smart alerts still use model.
- OptiIQ Value replaced: IV = (Σ PV of 10y operating cash flow + cash − debt) / shares. Years 1–5 revenue growth (capped -5..20## Update (Jun 2026) - Live options + new OptiIQ
- Tradier live options (backend/tradier.py): TRADIER_ENV=production, tokens in backend/.env. Nearest listed expiration to target DTE, chain cached 60s, expirations 6h. engine.build_idea(chain=...) snaps strikes to listed ones, prices from bid/ask mid, real OI/volume/Greeks/ATM IV; per-leg Black-Scholes fallback. Fields: live_quotes, quote_source, quotes_as_of, data_source.options_live. Backtest/smart alerts still use the model.
- OptiIQ Value replaced: IV = (sum PV of 10y operating cash flow + cash - debt) / shares. Years 1-5 at revenue growth (capped -5..20 pct), 6-10 at half; CAPM discount; no terminal value. Negative CFO returns available=false with reason. Stress test kept.

## Update (Jun 2026) - Chain tab + OptiIQ v3
- New "Chain" tab (frontend/app/(tabs)/chain.tsx, src/pnl.tsx with react-native-svg): ticker search, expiration chips, live Tradier chain (bid=sell, ask=buy taps, ITM shading, price line, near-money/all strikes), Strategy view with 12 templates, legs qty/remove, KPIs (net credit/debit, max P/L, POP), P&L line chart (expiry green/red + today dashed, breakevens), date x price heatmap, breakevens, EV, fees, net Greeks.
- Backend chain.py: GET /api/chain/templates, GET /api/chain/{tk}/expirations, GET /api/chain/{tk}?expiration=, POST /api/chain/template, POST /api/chain/analyze.
- OptiIQ v3 (engine.optiiq_value): non-financials = 10y DCF of max(TTM FCF, net income), growth median(rev TTM, rev 5y, EPS 5y) capped 2-15% fading to 3% yrs 6-10, Gordon terminal 3%, + cash - debt, / shares; discount CAPM w/ Blume beta (8-12%). Banks/financials (sector contains financ/bank/insurance): BV x (ROE-g)/(r-g). UI shows only value + "% vs price" tag.

## Update (Jun 2026) - Saved strategies, multi-expiry, strategy alerts, admin
- Chain builder: legs carry their own expiration (switching expiration no longer clears legs). New templates: Calendar/Diagonal Call/Put Spread (far leg ~30d later). Analyze for mixed expiries: payoff at nearest expiry, later legs BS-valued with remaining time; numeric max P/L, breakevens, POP (chain._mixed_stats).
- backend/strategies.py: POST/GET/PATCH/DELETE /api/strategies (live mark from Tradier mids, P&L, target/stop in usd or pct of max profit/max risk). Hits create alert_events kind strategy_target/strategy_stop + push; checked on GET and by 5-min loop in market hours.
- Admin: users.is_admin (lingesa4@gmail.com). GET /api/admin/users?q=, POST /api/admin/users/{uid}/plan {plan}. Frontend app/admin.tsx, entry in Profile.
- Frontend: src/SaveStrategy.tsx (save sheet), src/StrategiesList.tsx (Portfolio cards), Alerts tab shows "Recent alerts" feed incl. strategy events.

## Update (Jun 2026) - Admin insights, close/roll, daily P&L
- users.last_active_at updated (throttled 10 min) in get_user_from_token. GET /api/admin/stats: total_users, tiers, paid, mrr, signups/active (24h/7d/30d), signups_daily (14d), open_strategies. Admin screen shows Insights block.
- POST /api/strategies/{id}/close: realistic fills (Buy legs at bid, Sell legs at ask, intrinsic if expired) + exit fees -> status closed, final_pnl, exit_legs. GET /api/strategies returns items(open), closed[], realized_total; history as list [{date,pnl}] (one point/day).
- POST /api/strategies/{id}/roll {expiration, confirm}: soonest-expiring option legs closed at fills and reopened at nearest listed strikes on the later expiry; preview shows net credit/debit, fees, realized; confirm updates legs, realized_pnl, rolls[], recomputed max P/L, resets fired.
- Frontend: StrategiesList (DailyPnLChart, Close two-tap confirm, Roll sheet src/RollSheet.tsx), ClosedHistory in Portfolio.

## Update (Jun 2026) - Admin user detail, history insights, archive/delete
- plan_events collection (billing.log_plan_event) logged on admin change, Stripe, PayPal, downgrade/free. GET /api/admin/users/{uid}: user, access, profile, activity (scans 14d daily, alerts, watchlist, recent events), strategies (open/closed, realized), plan_history (+ synthetic sign-up), payments. Screen app/admin-user/[uid].tsx (link from admin list).
- strategies.strategy_type (classify() from legs at save; computed for legacy). GET /api/strategies returns insights {overall, by_type[]} (win rate, avg, avg win/loss, best/worst) over all closed incl. archived, closed (non-archived) and archived lists. POST /api/strategies/{id}/archive {archived}. DELETE works for closed. UI: HistoryInsights + Trades/Archived toggle + archive/delete (two-tap) per row.

## Update (Jun 2026) - Admin broadcasts
- backend/broadcasts.py: POST/GET /api/admin/broadcasts, DELETE /api/admin/broadcasts/{id} (end), GET /api/announcements (active, audience all or user's tier, not dismissed), POST /api/announcements/{id}/dismiss. Collections broadcasts, broadcast_reads. Optional push to audience.
- Frontend: app/admin-broadcast.tsx (compose, audience chips, push switch, preview, sent list with reach/dismissed/end), button in Admin header; src/Announcements.tsx banner on Discover.

## Update (Jun 2026) - 5-step Quant pipeline (Scan → Rank → Plan → Validate → Track), 40-stock universe
- backend/quant.py: scan_report (liquidity, ATM IV vs HV, true IV rank once 20+ daily IV snapshots in `iv_history`, options flow/unusual activity, fundamentals quality, trend, flags), validate_idea (own-history backtest hold vs managed with equity curves, cost check, 8 stress tests).
- engine.py: OptiScore 0-100 = 35% expected return + 25% risk + 20% premium quality + 20% user fit (apply_fit / apply_history), skew-aware POP (live IV at breakevens), management_plan (entry limit, TP, stop, invalidation, time exit, risk-budget sizing). Stock trade_plan has entry_trigger / invalidation / time_stop.
- extras.py: risk_adjusted (PF, per-trade Sharpe/Sortino, max DD, return on risk, expectancy, equity curve), accuracy (Brier, calibration error, buckets), POP auto-calibration per bucket once 30+ settled live picks (shrunk toward prediction) -> pop_calibrated/calibration_n on ideas; track-record live.calibration {active, buckets, progress}.
- Rate limits: market._get enforces per-minute budgets (Polygon 5, Finnhub 55, AV 5); on 429 the minute budget is spent; failed lookups are no longer cached as empty (stale fallback). Candles: one 250-day series per ticker (sliced), persisted in Mongo `candle_cache` (survives restarts). Warm loop paces 13s only when it actually called Polygon. Backtest recomputes every 10 min until ≥90% of universe has history.
- Frontend: src/quality.tsx (PipelineStrip, OptiScoreCard w/ SVG ring, PlanCard w/ risk-reward bar + breakeven win rate, ValidationCard w/ verdict, win-rate bars, equity curve, cost gauge, diverging stress bars, ScanCard w/ IV-rank gauge, flow bar, fundamentals bars), src/quantcharts.tsx (ScoreRing, EquityCurve, CalibrationChart, Gauge). Analyze: OptiScore + Plan open, Validation + Scan collapsed. Discover cards: OptiScore pill, calibrated POP, plan strip. Track record: calibration chart, equity curve, calibration progress (live).
