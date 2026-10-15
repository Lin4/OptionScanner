# Fix the Profile Screen (opened from the Discover avatar)

Tapping the round avatar in the top-right of Discover should open your Profile screen without errors. That screen should clearly show who you are, which plan you're on, and what the plan includes.

## Who it's for
Any signed-in OptiScreen user, mainly on iPhone with Expo Go, who wants to check their account, see their plan, or upgrade.

## What's wrong today
- On iPhone, tapping the Discover avatar shows a red error screen instead of opening Profile.
- Likely cause: two different screens claim the same "/profile" address. One of them is an old placeholder that only redirects to the other, so the app can't tell which one to open. Removing the duplicate should fix it. Two other old placeholder screens of the same kind (old Stocks and Options tabs) will be removed for the same reason.

## Core features and experience
1. **Avatar opens Profile, every time.** No red screen. The back arrow returns you to where you were.
2. **Account details card:**
   - Initial/avatar, name and email
   - How you sign in (email or Google)
   - Member since (date the account was created)
3. **Plan details card:**
   - Current plan name and monthly price (Free, Simple $9, Advance $29, Expert $79)
   - A short "What's included" list for your current plan, using the tier descriptions from your product plan:
     - **Free:** delayed data, limited screens per day, education
     - **Simple:** stock screener, covered calls, cash-secured puts
     - **Advance:** full strategy library, custom periods, collateral & margin views, alerts
     - **Expert:** backtesting, portfolio analytics, real-time data, unlimited AI
   - A side-by-side tier picker. Tapping a higher paid plan goes to PayPal checkout (sandbox), as it does today. Tapping Free switches you down straight away.
4. **Trading profile summary:**
   - Your saved questionnaire answers: experience, risk tolerance, capital, account type, options level
   - An "Edit answers" button that reopens the questionnaire
5. **Kept as-is:** sample push notification row, onboarding checklist, sign out, research-only disclaimer.

## User flow
1. Discover → tap avatar (top-right) → Profile screen slides in.
2. Read account details and the plan card.
3. Optional: tap a plan → PayPal checkout → return → the plan card shows the new plan.
4. Optional: tap "Edit answers" → questionnaire → save → back to Profile with updated answers.
5. Tap back → return to Discover.

## UI/UX feel
- Same clean teal look as the rest of the app. Cards with soft borders and bold headings.
- The current plan is highlighted in teal, and its included features are listed with check marks.
- Large tap targets (at least 44pt) and safe-area spacing for the iPhone notch.
- If profile data hasn't loaded yet, a placeholder skeleton shows instead of a blank screen or an error.

## Implementation phases
- **Phase 1 (MVP, built now):**
  - Fix the avatar crash by removing the duplicate and old placeholder screens.
  - Add the account details card, plan details card with "What's included", and trading profile summary with "Edit answers".
  - Check that the avatar opens Profile on the web preview, and check the iPhone flow.
- **Phase 2:**
  - Change name or email from Profile
  - Payment history (past PayPal upgrades)
  - Cancel or downgrade confirmation
- **Phase 3:**
  - Profile photo upload
  - Delete account
  - Plan usage meters (e.g. screens used today on Free)

## Assumptions
- The "user tab" means the Profile screen opened from the Discover avatar. No new bottom tab is added; the 5 tabs stay as they are.
- The crash is the duplicate "/profile" screen. The fix is confirmed by checking that the avatar opens Profile. If a different error shows up, that error gets fixed in this phase too.
- Plan feature lists come from the tiers in the uploaded product plan. They only describe each plan; features aren't locked or unlocked by plan in this phase.
- PayPal stays in sandbox (test) mode.
- "Edit answers" reuses the existing questionnaire screen and saves over your previous answers.
- "Member since" uses the account creation date. Accounts created without one show nothing for that field.
