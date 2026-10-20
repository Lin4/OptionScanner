"""Capture real TradeSI screens at iPhone 6.5" resolution (428x926 @3x = 1284x2778)."""
import asyncio
from playwright.async_api import async_playwright

URL = "https://optionscope.preview.emergentagent.com"
OUT = "/app/store-assets/screenshots/raw"


async def top(page, test_id, offset=0):
    el = page.get_by_test_id(test_id).first
    await el.wait_for(timeout=90000)
    await el.evaluate("(e, o) => { e.scrollIntoView({block: 'start'}); let p = e.parentElement;"
                      " while (p) { if (p.scrollHeight > p.clientHeight + 4 && getComputedStyle(p).overflowY !== 'visible') { p.scrollTop -= o; break; } p = p.parentElement; } }", offset)
    await page.wait_for_timeout(1200)


async def shot(page, name):
    await page.wait_for_timeout(800)
    await page.screenshot(path=f"{OUT}/{name}.png")
    print("saved", name)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/root/bin/chromium", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 428, "height": 926}, device_scale_factor=3, is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        await page.goto(URL)
        await page.wait_for_function("document.querySelector('#root') && document.querySelector('#root').innerText.length > 20", timeout=120000)
        await page.wait_for_timeout(2500)
        if await page.get_by_test_id("login-email").count():
            await page.get_by_test_id("login-email").fill("trader@optiscreen.app")
            await page.get_by_test_id("login-password").fill("TestPass123!")
            await page.get_by_test_id("login-submit").click()
        await page.get_by_test_id("disc-run").wait_for(timeout=60000)
        await page.wait_for_timeout(1500)

        # 1 market scan results
        await page.get_by_test_id("disc-run").click()
        await page.locator("[data-testid^='disc-result-']").first.wait_for(timeout=120000)
        try:
            await page.wait_for_function("!document.body.innerText.includes('AI is writing explanations')", timeout=90000)
        except Exception:
            pass
        await top(page, "scan-stats", 8)
        await shot(page, "1_scan")

        # 2-4 analyze: ranking, plan, validation
        await page.goto(f"{URL}/analyze?ticker=SPY")
        await page.get_by_test_id("optiscore-card").wait_for(timeout=120000)
        await top(page, "pipeline-strip", 230)
        await shot(page, "2_rank")
        await top(page, "plan-card", 12)
        await shot(page, "3_plan")
        await page.evaluate("window.scrollTo(0,0)")
        await top(page, "analyze-ticker", 300)
        await page.get_by_test_id("strat-Bull Call Spread").click()
        await page.get_by_test_id("analyze-run").click()
        await page.wait_for_timeout(1500)
        await page.get_by_test_id("plan-card").wait_for(timeout=120000)
        await page.wait_for_timeout(2500)
        await top(page, "plan-card", 12)
        await shot(page, "3b_plan_debit")
        await page.get_by_test_id("strat-auto").click()
        await page.get_by_test_id("analyze-run").click()
        await page.wait_for_timeout(1500)
        await page.get_by_test_id("optiscore-card").wait_for(timeout=120000)
        await page.wait_for_timeout(2500)
        await page.get_by_test_id("validation-card-toggle").click()
        await page.get_by_test_id("validation-verdict").wait_for()
        await top(page, "validation-card", 12)
        await shot(page, "4_validate")

        # 5 performance tracking
        await page.goto(f"{URL}/track-record")
        await page.get_by_test_id("track-tab-backtest").click()
        await page.get_by_test_id("track-backtest").wait_for(timeout=60000)
        await page.wait_for_timeout(1500)
        await shot(page, "5_track")
        await top(page, "track-risk-adjusted", 12)
        await shot(page, "5b_track_equity")
        await top(page, "track-accuracy", 12)
        await shot(page, "5c_track_accuracy")
        await b.close()


asyncio.run(main())
