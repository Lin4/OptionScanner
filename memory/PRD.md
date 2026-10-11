# OptiScreen - Product Requirements

## Vision
AI-powered mobile app for options and stock screening. Helps retail traders find high-probability option strategies and analyze stocks for day trading, swing trading, and long-term investing.

## Core Modules
1. **Onboarding** - Account creation (email+password or Google), plan selection (Free/Simple/Advance/Expert), broker-style questionnaire, consent form.
2. **Find Stocks** - Filter optionable stocks by risk, reward, expiration, sector; AI returns top N stocks with recommended option strategies.
3. **Best Options** - Period-based ranking (day/week/month/custom) of top strategies with legs, premium, expiration, probability of profit, collateral (with/without margin), annual return %.
4. **Ticker Options** - User-entered ticker + expiration range -> best option strategy with full details.
5. **Day/Swing Trading Analysis** - Candlestick/chart patterns, moving averages, support/resistance, buy/sell/stop-loss points, RSI, short float, option volume, market sentiment, profit probability.
6. **Long-term Investing** - Intrinsic value, price target, earnings projections, revenue/net cash/net profit/debt, business moat, competitors, analyst ratings, buy/sell points.
7. **Voice** - Tap speaker to hear AI summary (ElevenLabs TTS); tap mic to speak ticker (ElevenLabs STT).
8. **Plan upgrade** - PayPal (sandbox) checkout for Simple $9 / Advance $29 / Expert $79 per month.
9. **Push notifications** - Daily top AI pick + earnings-date-approaching reminders (works after deploy + build).

## Stack
- Backend: FastAPI + MongoDB (motor), bcrypt+JWT, Emergent Google OAuth, Claude Sonnet 5.5 via emergentintegrations, ElevenLabs SDK, PayPal REST v2, SuprSend push relay (Emergent).
- Frontend: Expo 57 / React Native, expo-router, expo-notifications, expo-audio, react-native-webview, @react-native-vector-icons/feather.
- Market data: MOCKED (realistic sample data) for MVP; swap to Alpha Vantage/Finnhub later.

## Design
- Personality: iOS-Native Clean (teal/pine green brand).
- Theme tokens filled from `/app/design_guidelines.json` into `/app/frontend/src/theme.ts`.

## Deployment notes
- Push notifications only work in signed native builds (not Expo Go preview).
- PayPal sandbox credentials in `.env`; swap to live in production.
- `EMERGENT_PUSH_KEY=placeholder` is auto-replaced at deploy.

## Not in MVP
- Real-time market data.
- iOS in-app purchase (using PayPal for all plans).
