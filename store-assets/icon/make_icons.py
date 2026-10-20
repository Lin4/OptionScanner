"""TradeSI app icon concepts (1024x1024 vector -> PNG)."""
import math, asyncio
from playwright.async_api import async_playwright

BLUE_D, BLUE, GREEN, GREEN_L, NAVY = "#1E40AF", "#2563EB", "#10B981", "#6EE7B7", "#0B2A6B"

def svg(body, defs=""):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><defs>{defs}</defs>{body}</svg>'

# A - "Scan Lens": magnifier scanning a rising market line
A = svg(f'''
<rect width="1024" height="1024" fill="url(#g)"/>
<circle cx="450" cy="450" r="252" fill="#FFFFFF" fill-opacity="0.14" stroke="#FFFFFF" stroke-width="66"/>
<line x1="640" y1="640" x2="812" y2="812" stroke="#FFFFFF" stroke-width="96" stroke-linecap="round"/>
<polyline points="298,540 392,448 478,506 598,372" fill="none" stroke="#FFFFFF" stroke-width="50" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="598" cy="372" r="40" fill="{GREEN_L}" stroke="#FFFFFF" stroke-width="18"/>''',
 f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE_D}"/><stop offset=".55" stop-color="{BLUE}"/><stop offset="1" stop-color="{GREEN}"/></linearGradient>')

# B - "Rising Bars": three friendly rounded bars + upward spark
bars = "".join(f'<rect x="{x}" y="{790-h}" width="150" height="{h}" rx="75" fill="{c}"/>' for x, h, c in
               [(222, 250, "#FFFFFF"), (437, 400, "#FFFFFF"), (652, 560, GREEN_L)])
B = svg(f'''
<rect width="1024" height="1024" fill="url(#g)"/>
<path d="M 160 860 A 700 700 0 0 1 860 160" fill="none" stroke="#FFFFFF" stroke-opacity="0.16" stroke-width="26"/>
<path d="M 160 860 A 480 480 0 0 1 640 380" fill="none" stroke="#FFFFFF" stroke-opacity="0.12" stroke-width="22"/>
{bars}''',
 f'<linearGradient id="g" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="{NAVY}"/><stop offset=".6" stop-color="{BLUE}"/><stop offset="1" stop-color="#22C1A3"/></linearGradient>')

# C - "Smart Check": a check mark that rises into an arrow, inside a scan ring
k0, k1 = (292, 548), (446, 700)
d = (296, -372); n = math.hypot(*d); u = (d[0] / n, d[1] / n)
tip = (k1[0] + u[0] * 500, k1[1] + u[1] * 500)
def rot(v, a):
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a))
back = (-u[0] * 150, -u[1] * 150)
w1, w2 = rot(back, math.radians(38)), rot(back, math.radians(-38))
p = lambda q: f"{q[0]:.0f},{q[1]:.0f}"
end = (tip[0] - u[0] * 40, tip[1] - u[1] * 40)
C = svg(f'''
<rect width="1024" height="1024" fill="url(#g)"/>
<circle cx="512" cy="512" r="330" fill="none" stroke="#FFFFFF" stroke-opacity="0.22" stroke-width="30" stroke-dasharray="1500 600" transform="rotate(130 512 512)"/>
<polyline points="{p(k0)} {p(k1)} {p(end)}" fill="none" stroke="url(#s)" stroke-width="92" stroke-linecap="round" stroke-linejoin="round"/>
<polygon points="{p(tip)} {p((tip[0]+w1[0], tip[1]+w1[1]))} {p((tip[0]+w2[0], tip[1]+w2[1]))}" fill="{GREEN_L}" stroke="{GREEN_L}" stroke-width="34" stroke-linejoin="round"/>''',
 f'''<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>
<linearGradient id="s" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#FFFFFF"/><stop offset=".55" stop-color="#FFFFFF"/><stop offset="1" stop-color="{GREEN_L}"/></linearGradient>''')

ICONS = {"A_scan_lens": A, "B_rising_bars": B, "C_smart_check": C}

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/root/bin/chromium", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1024, "height": 1024})
        for name, s in ICONS.items():
            open(f"{name}.svg", "w").write(s)
            await pg.set_content(f'<html><body style="margin:0">{s}</body></html>')
            await pg.screenshot(path=f"{name}.png", omit_background=False)
        # comparison sheet: iOS-masked previews at large + small sizes, light & dark home screens
        cells = ""
        for name, s in ICONS.items():
            uri = "data:image/svg+xml;utf8," + s.replace("#", "%23").replace('"', "'")
            sizes = "".join(f'<img src="{uri}" style="width:{z}px;height:{z}px;border-radius:{z*0.2237:.0f}px;margin:0 10px;box-shadow:0 2px 6px rgba(0,0,0,.18)">' for z in (180, 120, 60, 40))
            cells += f'''<div style="display:flex;align-items:center;gap:24px;padding:28px 36px;border-bottom:1px solid #E5E7EB">
              <div style="width:220px;font:800 30px Inter">{name[0]}<div style="font:500 18px Inter;color:#6B7280;margin-top:6px">{name[2:].replace("_"," ").title()}</div></div>
              <img src="{uri}" style="width:300px;height:300px;border-radius:67px;box-shadow:0 10px 30px rgba(15,23,42,.25)">
              <div style="display:flex;align-items:center;background:#F3F4F6;padding:20px;border-radius:24px">{sizes}</div>
              <div style="display:flex;align-items:center;background:#111827;padding:20px;border-radius:24px">{sizes}</div></div>'''
        await pg.set_viewport_size({"width": 1700, "height": 1150})
        await pg.set_content(f'<html><body style="margin:0;background:#fff;font-family:Inter"><div style="padding:24px 36px;font:800 36px Inter">TradeSI · app icon concepts</div>{cells}</body></html>')
        await pg.wait_for_timeout(300)
        await pg.screenshot(path="icon_concepts_sheet.png", full_page=True)
        await b.close()

asyncio.run(main())
