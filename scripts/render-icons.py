"""
Rasterizes the brand/badge SVGs (contact icons, priority stars, missing
crosses) into PNGs at frontend/assets/png/.

Why these are PNGs and not live SVG: every one of them carries the same
hand-drawn feTurbulence/feDisplacementMap "wobble" filter as the big panels
elsewhere on the page. Safari has a rendering bug where that filter comes
out soft/blocky no matter how the SVG is hosted (inline vs <img>) or how
the page is scaled (CSS transform vs zoom) — Chromium is unaffected, which
is what made it look like a hosting/scaling problem at first. A plain
raster image sidesteps the bug entirely: there's no filter left for any
engine to mis-render at request time, and browsers have always downscaled
regular bitmaps identically. We render at 8x the source viewBox so the
result stays crisp even on hi-DPI displays at every size these are shown.

Usage (needs Google Chrome and Pillow installed locally, run from repo root):
    pip3 install pillow
    python3 scripts/render-icons.py
"""
import re
import subprocess
import os
import tempfile

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "frontend/assets/svg/contacts")
OUT_PNG_DIR = os.path.join(REPO_ROOT, "frontend/assets/png")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCALE = 8

# headless Chrome's --screenshot capture bleeds a ~15px-wide band of
# mis-encoded pixels along the right/bottom edge of any large-enough
# capture — same bug diagnosed in scripts/render-masks.py's
# _clear_edge_bleed, and these icon canvases (500-600px at SCALE=8) are
# well past the size where it kicks in. Unlike the mask shapes, these
# brand-icon SVGs don't reserve a margin around their own artwork (some,
# like discord's, paint right up to the edge), so clearing a border after
# the fact risks shaving off real content. Instead: pad outward by this
# many px before capturing, then crop the padding — and the corruption
# living inside it — back off afterward, leaving the original SVG content
# untouched and the output PNG at exactly the intended size.
EDGE_PAD = 24

FILES = ["steam.svg", "discord.svg", "twitter.svg", "insta.svg", "web.svg",
         "steam-inactive.svg", "discord-inactive.svg", "twitter-inactive.svg",
         "insta-inactive.svg", "web-inactive.svg", "web-favorites.svg",
         "star-1.svg", "star-2.svg", "cross-1.svg", "cross-2.svg"]


def main():
    os.makedirs(OUT_PNG_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        for fname in FILES:
            path = os.path.join(SRC, fname)
            with open(path) as f:
                content = f.read()

            m = re.search(r'<svg\s+width="([\d.]+)"\s+height="([\d.]+)"', content)
            w, h = float(m.group(1)), float(m.group(2))
            new_w, new_h = int(round(w * SCALE)), int(round(h * SCALE))

            # only the root <svg> tag's width/height (first match), not any
            # of the filter primitives further down that share the pattern
            new_content = content.replace(
                f'width="{m.group(1)}" height="{m.group(2)}"',
                f'width="{new_w}" height="{new_h}"',
                1,
            )

            render_w, render_h = new_w + 2 * EDGE_PAD, new_h + 2 * EDGE_PAD
            html = (
                "<!DOCTYPE html><html><head><style>"
                "html,body{margin:0;background:transparent;}"
                f"body{{padding:{EDGE_PAD}px;}}"
                f"</style></head><body>{new_content}</body></html>"
            )

            base = fname.replace(".svg", "")
            html_path = os.path.join(tmp_dir, base + ".html")
            png_path = os.path.join(OUT_PNG_DIR, base + ".png")
            with open(html_path, "w") as f:
                f.write(html)

            subprocess.run(
                [
                    CHROME, "--headless", "--disable-gpu",
                    f"--screenshot={png_path}",
                    f"--window-size={render_w},{render_h}",
                    "--default-background-color=00000000",
                    "--force-device-scale-factor=1",
                    f"file://{html_path}",
                ],
                capture_output=True,
                check=True,
            )

            im = Image.open(png_path).convert("RGBA")
            im.crop((EDGE_PAD, EDGE_PAD, EDGE_PAD + new_w, EDGE_PAD + new_h)).save(png_path)
            print(f"{base}: {new_w}x{new_h} -> {png_path}")


if __name__ == "__main__":
    main()
