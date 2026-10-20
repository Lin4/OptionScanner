# RevenueCat — integrated (2026-10-16; bundle id changed + /setup re-run 2026-10-20)
This file is a memory for interacting with the user's RevenueCat account via the integration proxy.

## Identifiers (from /setup response)
- rc_project_id: proj630c7007
- apple_app_id: appe9a446b2ed
- play_app_id: appcaa98a3e2a
- entitlement_lookup_key: pro
- offering_lookup_key: default
- bundle_id / package: com.optiiq.app
- Packages (package -> product_id, price):
  - $rc_monthly -> prod8cf8ab9d8e ($9 / P1M) = Simple tier
  - advance_monthly -> prod3936fd5215 ($29 / P1M) = Advance tier
  - expert_monthly -> prod2e5e83f64e ($79 / P1M) = Expert tier
  - $rc_annual deleted
- Dashboard: https://app.revenuecat.com/projects/proj630c7007
- App maps package identifier -> tier in frontend/src/revenuecat.tsx (PACKAGE_TIER); all packages unlock entitlement `pro`.

## Status check (project_state must be >= project_created; else re-fetch playbook)
curl -sS -H "$AUTH" "$INTEGRATION_PROXY_URL/internal/revenuecat/projects/e0231c41-d631-4bdb-9ec4-f123d586a727/status"

## Later updates (integration proxy only — NEVER the RevenueCat REST API)
- Upsert price/package: POST $INTEGRATION_PROXY_URL/internal/revenuecat/projects/e0231c41-d631-4bdb-9ec4-f123d586a727/products
  body {"products":[{"package":"advance_monthly","price":29.0,"currency":"USD","period":"P1M","prices":[{"amount_micros":29000000,"currency":"USD"}]}]}
- Remove: DELETE .../products/%24rc_monthly
- Recover identifiers / keys: re-run idempotent /setup and /build-config.

## Taking in-app purchases LIVE (user's manual steps)
1. Upload App Store Connect in-app purchase key / API key (.p8) and Google Play service-account JSON in the RevenueCat dashboard.
2. Set up payment profiles in App Store Connect / Play Console.
3. Create matching auto-renewable subscription products with the SAME product IDs as in the RevenueCat dashboard.
4. Release build -> TestFlight / Play internal testing -> submit for review.
All steps are in the FAQ section of the payments panel.
