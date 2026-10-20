"""Export the chosen TradeSI icon (A - Scan Lens) as a full app icon set.

Outputs to ./final and copies into /app/frontend/assets/images.
"""
import asyncio, shutil
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

BLUE_D, BLUE, GREEN, GREEN_L = "#1E40AF", "#2563EB", "#10B981", "#6EE7B7"
OUT = Path(__file__).parent / "final"
APP = Path("/app/frontend/assets/images")

GRAD = (f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE_D}"/>'
        f'<stop offset=".55" stop-color="{BLUE}"/><stop offset="1" stop-color="{GREEN}"/></linearGradient>')


def glyph(mono=False):
    dot = "#FFFFFF" if mono else GREEN_L
    lens_fill = 'fill="none"' if mono else 'fill="#FFFFFF" fill-opacity="0.14"'
    return f'''<circle cx="450" cy="450" r="252" {lens_fill} stroke="#FFFFFF" stroke-width="66"/>
<line x1="640" y1="640" x2="812" y2="812" stroke="#FFFFFF" stroke-width="96" stroke-linecap="round"/>
<polyline points="298,540 392,448 478,506 598,372" fill="none" stroke="#FFFFFF" stroke-width="50" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="598" cy="372" r="40" fill="{dot}" stroke="#FFFFFF" stroke-width="18"/>'''


def svg(body, size=1024, radius=0):
    clip = f'<clipPath id="c"><rect width="1024" height="1024" rx="{radius}"/></clipPath>' if radius else ""
    inner = f'<g clip-path="url(#c)">{body}</g>' if radius else body
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 1024 1024">'
            f'<defs>{GRAD}{clip}</defs>{inner}</svg>')


BG = '<rect width="1024" height="1024" fill="url(#g)"/>'
# Android adaptive: keep glyph inside the 66% safe circle
SAFE = lambda g: f'<g transform="translate(512 512) scale(0.66) translate(-512 -512)">{g}</g>'

ASSETS = {
    # name: (svg, transparent)
    "icon.png": (svg(BG + glyph()), False),                                  # iOS / Expo 1024, no alpha
    "adaptive-icon.png": (svg(SAFE(glyph())), True),                         # Android foreground
    "adaptive-background.png": (svg(BG), False),                             # Android background
    "adaptive-monochrome.png": (svg(SAFE(glyph(mono=True))), True),          # Android 13 themed icon
    "splash-image.png": (svg(BG + glyph(), radius=229), True),               # rounded mark for splash
    "favicon.png": (svg(BG + glyph(), size=196, radius=229), True),
    "notification-icon.png": (svg(glyph(mono=True), size=96), True),         # white silhouette
}


async def main():
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/root/bin/chromium", args=["--no-sandbox"])
        pg = await b.new_page()
        for name, (s, transparent) in ASSETS.items():
            size = int(s.split('width="')[1].split('"')[0])
            await pg.set_viewport_size({"width": size, "height": size})
            bg = "transparent" if transparent else "#fff"
            await pg.set_content(f'<html><body style="margin:0;background:{bg}">{s}</body></html>')
            path = OUT / name
            await pg.screenshot(path=str(path), omit_background=transparent)
            im = Image.open(path)
            im = im.convert("RGBA" if transparent else "RGB")
            im.save(path, optimize=True)
            (OUT / name.replace(".png", ".svg")).write_text(s)
            shutil.copy(path, APP / name)
            print(name, im.size, im.mode)
        await b.close()

asyncio.run(main())
