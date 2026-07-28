"""
Rasterizes the page's diagonal-stripe background into a small seamlessly
tileable white-on-transparent PNG mask at frontend/assets/masks/bg-stripes.png
(same mask-image + background-color: var(--x) convention as every other
recolorable shape in scripts/render-masks.py — this is what lets the
stripe color itself be theme-driven via CSS instead of baked into pixels).

Why a mask instead of a plain colored tile: #bgStripes used to paint the
stripes directly as a CSS repeating-linear-gradient stretched across the
whole (position:fixed, viewport-sized) element. For large/tall renders of
that gradient, Chromium shows a faint but real horizontal seam where its
internal rasterizer tiles the paint — invisible whenever page content
covered most of the viewport, but glaringly visible once the row list is
short enough (e.g. filtering upload date to "today") to expose most of the
raw background. Chromium doesn't show this seam for small/normal image
tiling, so pre-rendering one period of the pattern as a `background-repeat`
mask sidesteps the bug entirely while staying recolorable.

The stripe is drawn at an exact 315deg (a plain diagonal), so one period
of the repeat measured *along the gradient axis* (280px: 200px stripe +
80px gap) tiles seamlessly in plain x/y as a square of side
280 / sin(45deg) = 280 * sqrt(2) =~ 395.98px. We render at 396px (a
0.02px/period rounding error — imperceptible over any realistic viewport
width) and at RENDER_SCALE for a crisp result at hi-DPI.

Usage (needs Google Chrome and Pillow installed locally, run from repo root):
    pip3 install pillow
    python3 scripts/render-bg-stripes.py
"""
import math
import subprocess
import os
import tempfile

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "frontend/assets/masks")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
RENDER_SCALE = 4

STRIPE_COLOR = "white"  # mask convention — shape/alpha only, actual color comes from CSS
# scaled up by 5/3 from the original 200/280 (same stripe:gap ratio) so
# fewer, wider stripes fit on screen — 7-8 visible at the old 396px tile,
# 4-5 at this one, on a typical desktop viewport height.
BAND_PX = 333
PERIOD_PX = 466
TILE = round(PERIOD_PX / math.sin(math.radians(45)))  # 659

# same headless-Chrome screenshot edge-bleed bug documented in
# render-icons.py / render-masks.py — the stripe paints right up to the
# tile's own edges (it must, to tile seamlessly), so pad outward before
# capturing and crop the padding (and the corruption living inside it)
# back off afterward, same technique as render-icons.py.
EDGE_PAD = 24


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    render_tile = TILE * RENDER_SCALE
    render_pad = EDGE_PAD * RENDER_SCALE
    render_total = render_tile + 2 * render_pad

    html = f"""<!DOCTYPE html><html><head><style>
html,body {{ margin:0; background:transparent; }}
body {{ padding:{render_pad}px; }}
.tile {{
  width:{render_tile}px;
  height:{render_tile}px;
  background-image: repeating-linear-gradient(
    315deg,
    {STRIPE_COLOR} 0px,
    {STRIPE_COLOR} {BAND_PX * RENDER_SCALE}px,
    transparent {BAND_PX * RENDER_SCALE}px,
    transparent {PERIOD_PX * RENDER_SCALE}px
  );
}}
</style></head><body><div class="tile"></div></body></html>"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        html_path = os.path.join(tmp_dir, "tile.html")
        png_path = os.path.join(OUT_DIR, "bg-stripes.png")
        with open(html_path, "w") as f:
            f.write(html)

        subprocess.run(
            [
                CHROME, "--headless", "--disable-gpu",
                f"--screenshot={png_path}",
                f"--window-size={render_total},{render_total}",
                "--default-background-color=00000000",
                "--force-device-scale-factor=1",
                f"file://{html_path}",
            ],
            capture_output=True,
            check=True,
        )

        im = Image.open(png_path).convert("RGBA")
        im.crop((render_pad, render_pad, render_pad + render_tile, render_pad + render_tile)).save(png_path)
        print(f"bg-stripes: tile={TILE}px (x{RENDER_SCALE} -> {render_tile}px) -> {png_path}")


if __name__ == "__main__":
    main()
