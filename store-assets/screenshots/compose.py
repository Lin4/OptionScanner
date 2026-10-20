"""Compose App Store screenshots (iPhone 6.5", 1284x2778): branded background + headline + real app screen in a phone frame."""
import asyncio
import base64
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path("/app/store-assets/screenshots")
FONT = Path.home() / ".fonts"

SHOTS = [
    ("1_scan", "Find the best <g>opportunities</g> instantly", "Scan 40 liquid stocks and get ranked options setups in seconds."),
    ("2_rank", "Every idea <g>scored 0–100</g>", "OptiScore weighs return, risk, premium quality and your fit."),
    ("3_plan", "Know your <g>entry, target &amp; stop</g>", "A clear trade plan with position size — before you commit."),
    ("4_validate", "See how it did <g>before you trade</g>", "Backtests, trading costs and stress tests in plain English."),
    ("5_track", "Track <g>real results</g>, honestly", "Win rate, drawdown and prediction accuracy you can verify."),
]

STATUS_ICONS = """
<svg width="150" height="40" viewBox="0 0 150 40" fill="#0B1220">
  <rect x="0" y="26" width="9" height="12" rx="2"/><rect x="13" y="19" width="9" height="19" rx="2"/>
  <rect x="26" y="11" width="9" height="27" rx="2"/><rect x="39" y="3" width="9" height="35" rx="2"/>
  <path d="M74 14a26 26 0 0 1 34 0l-4 4a20 20 0 0 0-26 0z M80 21a17 17 0 0 1 22 0l-4 4a11 11 0 0 0-14 0z M86 28a8 8 0 0 1 10 0l-5 6z"/>
  <rect x="114" y="6" width="31" height="28" rx="7" fill="none" stroke="#0B1220" stroke-width="3"/>
  <rect x="118" y="10" width="23" height="20" rx="4"/><rect x="146" y="15" width="3" height="10" rx="1.5"/>
</svg>"""


def page_html(raw: Path, headline: str, sub: str) -> str:
    img = base64.b64encode(raw.read_bytes()).decode()
    headline = headline.replace("<g>", '<span class="g">').replace("</g>", "</span>")
    return f"""<html><head><style>
@font-face {{ font-family: InterX; src: url('file://{FONT}/Inter-ExtraBold.ttf'); font-weight: 800; }}
@font-face {{ font-family: InterX; src: url('file://{FONT}/Inter-SemiBold.ttf'); font-weight: 600; }}
@font-face {{ font-family: InterX; src: url('file://{FONT}/Inter-Medium.ttf'); font-weight: 500; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: 1284px; height: 2778px; overflow: hidden; font-family: InterX, sans-serif; }}
.c {{ position: relative; width: 1284px; height: 2778px; overflow: hidden;
      background: linear-gradient(170deg, #EAF2FF 0%, #F5F9FF 45%, #ECFDF5 100%); }}
.blob1 {{ position: absolute; width: 900px; height: 900px; border-radius: 50%; left: -380px; top: -300px;
          background: radial-gradient(circle, rgba(37,99,235,.16), rgba(37,99,235,0) 70%); }}
.blob2 {{ position: absolute; width: 1000px; height: 1000px; border-radius: 50%; right: -420px; top: 1500px;
          background: radial-gradient(circle, rgba(16,185,129,.18), rgba(16,185,129,0) 70%); }}
.brand {{ position: absolute; top: 120px; left: 0; right: 0; text-align: center; font-weight: 800; font-size: 40px;
          color: #1E40AF; letter-spacing: 1px; }}
.brand i {{ display: inline-block; width: 22px; height: 22px; border-radius: 50%; margin-right: 14px; vertical-align: 2px;
            background: linear-gradient(135deg, #2563EB, #10B981); }}
h1 {{ position: absolute; top: 210px; left: 90px; right: 90px; text-align: center; font-weight: 800; font-size: 100px;
      line-height: 1.08; letter-spacing: -2.5px; color: #0B1B3F; }}
.g {{ background: linear-gradient(90deg, #1D4ED8, #059669); -webkit-background-clip: text; color: transparent; }}
p {{ position: absolute; top: 470px; left: 130px; right: 130px; text-align: center; font-weight: 500; font-size: 44px;
     line-height: 1.38; color: #475569; }}
.phone {{ position: absolute; left: 50%; transform: translateX(-50%); top: 700px; width: 900px; padding: 22px;
          border-radius: 128px; background: #0B1220; box-shadow: 0 50px 120px rgba(15,23,42,.30), 0 0 0 3px #1F2937 inset; }}
.screen {{ position: relative; border-radius: 108px; overflow: hidden; background: #fff; }}
.status {{ height: 116px; display: flex; align-items: center; justify-content: space-between; padding: 14px 76px 0 92px;
           font-weight: 600; font-size: 40px; color: #0B1220; }}
.island {{ position: absolute; top: 30px; left: 50%; transform: translateX(-50%); width: 290px; height: 82px;
           border-radius: 41px; background: #000; }}
.screen img {{ display: block; width: 100%; }}
</style></head><body><div class="c">
<div class="blob1"></div><div class="blob2"></div>
<div class="brand"><i></i>TradeSI</div>
<h1>{headline}</h1>
<p>{sub}</p>
<div class="phone"><div class="screen">
  <div class="island"></div>
  <div class="status"><span>9:41</span>{STATUS_ICONS}</div>
  <img src="data:image/png;base64,{img}">
</div></div>
</div></body></html>"""


async def main():
    out = ROOT / "final"
    out.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/root/bin/chromium", args=["--no-sandbox", "--allow-file-access-from-files"])
        pg = await b.new_page(viewport={"width": 1284, "height": 2778}, device_scale_factor=1)
        for name, head, sub in SHOTS:
            html = ROOT / f"_{name}.html"
            html.write_text(page_html(ROOT / "raw" / f"{name}.png", head, sub))
            await pg.goto(f"file://{html}")
            await pg.wait_for_timeout(500)
            png = out / f"{name}.png"
            await pg.screenshot(path=str(png))
            Image.open(png).convert("RGB").save(png)  # App Store: no alpha channel
            html.unlink()
            print("composed", png, Image.open(png).size)
        await b.close()


asyncio.run(main())
