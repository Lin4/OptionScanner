"""Preview sheet for the final Scan Lens icon set (iOS mask, Android circle/squircle, splash, notif)."""
import asyncio, base64
from pathlib import Path
from playwright.async_api import async_playwright

F = Path(__file__).parent / "final"
u = lambda n: "data:image/png;base64," + base64.b64encode((F / n).read_bytes()).decode()


def adaptive(z, radius):
    return (f'<div style="width:{z}px;height:{z}px;border-radius:{radius};overflow:hidden;position:relative;margin:0 10px">'
            f'<img src="{u("adaptive-background.png")}" style="position:absolute;inset:0;width:100%;height:100%">'
            f'<img src="{u("adaptive-icon.png")}" style="position:absolute;inset:0;width:100%;height:100%"></div>')


async def main():
    ios = "".join(f'<img src="{u("icon.png")}" style="width:{z}px;height:{z}px;border-radius:{z*.2237:.0f}px;margin:0 10px">' for z in (180, 120, 60))
    andr = adaptive(150, "50%") + adaptive(150, "28%") + (
        f'<div style="width:150px;height:150px;border-radius:50%;background:#DCE7F7;margin:0 10px;display:flex;align-items:center;justify-content:center">'
        f'<img src="{u("adaptive-monochrome.png")}" style="width:150px;height:150px;filter:brightness(0) saturate(100%) invert(19%) sepia(70%) saturate(3000%) hue-rotate(215deg)"></div>')
    splash = lambda bg: f'<div style="width:190px;height:400px;background:{bg};border-radius:28px;display:flex;align-items:center;justify-content:center;margin:0 10px;border:1px solid #E5E7EB"><img src="{u("splash-image.png")}" style="width:80px"></div>'
    notif = f'<div style="background:#2563EB;padding:16px;border-radius:16px"><img src="{u("notification-icon.png")}" style="width:48px"></div>'
    row = lambda t, c: f'<div style="display:flex;align-items:center;padding:22px 32px;border-bottom:1px solid #E5E7EB"><div style="width:200px;font:700 20px Inter">{t}</div>{c}</div>'
    html = (f'<html><body style="margin:0;font-family:Inter;background:#fff"><div style="padding:22px 32px;font:800 30px Inter">TradeSI · Scan Lens icon set</div>'
            + row("iOS", ios) + row("Android (circle / squircle / themed)", andr)
            + row("Splash (light / dark)", splash("#FFFFFF") + splash("#0B1220")) + row("Notification", notif) + "</body></html>")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/root/bin/chromium", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1000, "height": 900})
        await pg.set_content(html)
        await pg.wait_for_timeout(300)
        await pg.screenshot(path=str(F / "icon_set_preview.png"), full_page=True)
        await b.close()

asyncio.run(main())
