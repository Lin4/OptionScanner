"""Export each icon as its own single image file.

individual/<name>.png          1024 square (store-ready, no transparency)
individual/<name>_rounded.png  1024 rounded-corner preview (transparent corners)
individual/scan_lens_sizes/    Scan Lens at every standard iOS / Android size
"""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).parent
OUT = HERE / "individual"
SIZES = HERE / "individual" / "scan_lens_sizes"
OUT.mkdir(exist_ok=True)
SIZES.mkdir(exist_ok=True)


def rounded(im):
    s = 4096  # supersample the mask for smooth edges
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.2237), fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask.resize(im.size, Image.LANCZOS))
    return out


for src, name in [("final/icon.png", "A_scan_lens"), ("B_rising_bars.png", "B_rising_bars"), ("C_smart_check.png", "C_smart_check")]:
    im = Image.open(HERE / src).convert("RGB")
    im.save(OUT / f"{name}.png", optimize=True)
    rounded(im).save(OUT / f"{name}_rounded.png", optimize=True)
    print(name)

master = Image.open(HERE / "final/icon.png").convert("RGB")
for z in (1024, 512, 192, 180, 167, 152, 144, 120, 96, 87, 80, 76, 72, 60, 58, 48, 40, 29, 20):
    master.resize((z, z), Image.LANCZOS).save(SIZES / f"scan_lens_{z}x{z}.png", optimize=True)
print("sizes done")
