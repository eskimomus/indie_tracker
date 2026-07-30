"""
Rasterizes every "chrome" shape that still carries the hand-drawn
feTurbulence/feDisplacementMap wobble (panels, badges, buttons, dropdown
backgrounds) into white-on-transparent PNG masks at frontend/assets/masks/.

Why: Safari renders that filter soft/blocky no matter how the SVG is
hosted or how the page is scaled (see scripts/render-icons.py — same root
cause, already fixed for the small brand icons the same way). These masks
let the shapes stay theme-recolorable (CSS `background-color: var(--x)`
via `mask-image`) while eliminating the live filter that Safari mishandles.

Each shape's canvas size *is* the CSS box size used in index.html. The
rect/circle is inset a couple of px inside that canvas (matching how the
original Figma exports always left a small margin around the wobbly
shape) so the displacement has room without clipping.

Usage (needs Google Chrome and Pillow installed locally, run from repo root):
    pip3 install pillow
    python3 scripts/render-masks.py
"""
import subprocess
import os
import tempfile
import sys

from PIL import Image, ImageDraw

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "frontend/assets/masks")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
RENDER_SCALE = 4

# headless Chrome's --screenshot capture writes a ~15px-wide band of
# mis-encoded pixels (alpha=255, but RGB scaled down as if premultiplied —
# i.e. treated as straight alpha by every normal PNG reader, it paints as a
# solid, dead-straight rectangle) along the right and bottom edge of large
# screenshots — reproduced with a plain unfiltered rect at large canvas
# sizes, so it's a Chrome/Skia readback bug, not anything about our SVGs or
# filters (only triggers above some size threshold, which is why smaller
# shapes here don't show it). Every shape's visible content already sits
# `margin` px clear of its own canvas edge (see below) purely so the wobble
# filter has room to displace into — that same reserved band is clamped back
# to transparent post-render, which both papers over this bug (as long as
# margin*RENDER_SCALE covers the ~15px band) and is a no-op otherwise.
def _clear_edge_bleed(png_path, margin_px):
    # Chrome screenshot bug writes a ~15px-wide band of solid pixels on right/bottom edges.
    # By using margin=10 (40 image px), the wobble is at 24..40 px from edge, and Chrome bug is at 0..15 px.
    # Clearing 20 image px (5 canvas px) erases 100% of Chrome bug without touching any wobble.
    clear_px = min(margin_px, round(5 * RENDER_SCALE))
    if clear_px <= 0:
        return
    im = Image.open(png_path).convert("RGBA")
    w, h = im.size
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, w - 1, clear_px - 1], fill=(0, 0, 0, 0))
    draw.rectangle([0, h - clear_px, w - 1, h - 1], fill=(0, 0, 0, 0))
    draw.rectangle([0, 0, clear_px - 1, h - 1], fill=(0, 0, 0, 0))
    draw.rectangle([w - clear_px, 0, w - 1, h - 1], fill=(0, 0, 0, 0))
    im.save(png_path)


def turbulence_filter(fid, w, h, freq, scale, seed):
    # userSpaceOnUse with the filter region set to the *exact* canvas size,
    # exactly like every source Figma export does — objectBoundingBox +
    # percentage regions turned out to clip rotated/circular shapes badly
    # (Chrome computed the wrong effective region), so don't use that.
    return f'''<filter id="{fid}" x="0" y="0" width="{w}" height="{h}" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape"/>
<feTurbulence type="fractalNoise" baseFrequency="{freq} {freq}" numOctaves="3" seed="{seed}"/>
<feDisplacementMap in="shape" scale="{scale}" xChannelSelector="R" yChannelSelector="G" result="displacedImage" width="100%" height="100%"/>
<feMerge result="merged"><feMergeNode in="displacedImage"/></feMerge>
</filter>'''


# Two kinds of entries:
#
# 1) (name, canvas_w, canvas_h, shape_svg, freq, scale, seed) — the CSS box
#    used in index.html already *is* the outer canvas (this matches how the
#    original Figma exports for these specific pieces work: the shape sits
#    inset a couple px inside a slightly bigger canvas). No margin needed.
#
# 2) (name, w, h, rx, freq, scale, seed, margin) — `w x h` is the *visible*
#    rect size exactly as specified in the design doc (e.g. "upload date
#    title: 288x65.78"). The canvas is grown by `margin` on every side so
#    the rect stays full-size; index.html then pulls each of these boxes
#    back by `margin` on left/top and grows width/height by 2*margin, so
#    the visible rect still lands exactly on the specified position.
#    (Getting this backwards — shrinking the rect to fit margin inside the
#    *stated* box instead of growing the box — was the original bug: the
#    painted shape came out ~2px undersized on every side and no longer
#    met its neighbors, e.g. the upload-date title pill vs. its arrow
#    button.)

SHAPES_CANVAS_IS_BOX = [
    ("divider", 1294, 20,
     '<rect x="1.5" y="1.5" width="1291" height="17" rx="8.5" fill="white"/>',
     0.0099999998, 3, 658),

    ("rank-circle", 111, 111,
     '<circle cx="55.5" cy="55.5" r="51.5" fill="white"/>',
     0.0166666675, 8, 786),

    ("fav-circle", 112, 112,
     '<circle cx="55.5096" cy="55.5096" r="51.5" transform="rotate(118.794 55.5096 55.5096)" fill="white"/>',
     0.0166666675, 8, 786),

    # plain/smooth heart now (no hand-drawn wobble in the source export),
    # scale=0 keeps this entry on the same turbulence-filter render path
    # as everything else without actually displacing anything
    ("fav-heart", 47, 41,
     '<path d="M0 13.9378C0 25.5194 9.44566 31.6912 16.3601 37.2153C18.8 39.1647 21.15 41 23.5 41C25.85 41 28.2 39.1647 30.64 37.2153C37.5544 31.6912 47 25.5194 47 13.9378C47 2.35603 34.0745 -5.8575 23.5 5.27703C12.9254 -5.8575 0 2.35603 0 13.9378Z" fill="white"/>',
     0.0444444455, 0, 1738),

    # play button, split into two masks (circle + triangle) sharing one
    # 118x118 canvas so both stay perfectly aligned as plain siblings with
    # inset:0 in CSS — same two-layer trick as badge-rank/badge-fav.
    # filter params identical between the two provided colorways (only the
    # circle's fill differs, and that's just --badge-rank in CSS), so one
    # pair of masks covers both themes.
    ("play-circle", 118, 118,
     '<circle cx="59" cy="59" r="55" fill="white"/>',
     0.016977928578853607, 8, 6108),

    ("play-triangle", 118, 118,
     '<path d="M81.827 54.2842C85.8727 56.5846 85.8727 62.4154 81.827 64.7158L50.4657 82.5479C46.4658 84.8222 41.5 81.9334 41.5 77.3321L41.5 41.6679C41.5 37.0666 46.4658 34.1778 50.4657 36.4521L81.827 54.2842Z" fill="white"/>',
     0.01666666753590107, 1.8, 2759),

    # description panel's "more" toggle button — background (wobbly) and
    # its +/x symbol (plain, no wobble in the source export).
    ("more-back", 67, 67,
     '<rect x="0.5" y="0.5" width="66" height="66" rx="16" fill="white"/>',
     0.036900367587804794, 1, 3476),

    # plain plus sign, no hand-drawn wobble in the source export — scale=0
    # keeps this on the same turbulence-filter render path as everything
    # else (see fav-heart above) without actually displacing anything.
    ("more-symbol", 26, 26,
     '<rect x="9" y="0" width="8" height="26" rx="3" fill="white"/>'
     '<rect x="26" y="9" width="8" height="26" rx="3" transform="rotate(90 26 9)" fill="white"/>',
     0.01, 0, 1),

    # filter drawer's tab icon (Group 74.svg's flag/pennant path) — also
    # plain, no wobble in the source export. Natural bbox in the source's
    # own coordinates is x:[1270,1338] y:[473,534.821]; translated by
    # (-1270,-473) so it sits flush in its own small canvas.
    ("filter-tab-flag", 68, 62,
     '<g transform="translate(-1270, -473)">'
     '<path d="M1327.8 473H1280.2C1275.39 473 1272.99 473 1271.49 474.397C1270 475.794 1270 478.042 1270 482.539V484.876C1270 488.393 1270 490.152 1270.88 491.61C1271.77 493.068 1273.38 493.972 1276.6 495.782L1286.51 501.339C1288.67 502.553 1289.75 503.16 1290.53 503.831C1292.14 505.227 1293.13 506.867 1293.58 508.879C1293.8 509.845 1293.8 510.975 1293.8 513.236V522.283C1293.8 525.365 1293.8 526.906 1294.66 528.108C1295.51 529.309 1297.03 529.902 1300.08 531.088C1306.46 533.576 1309.66 534.821 1311.93 533.405C1314.2 531.989 1314.2 528.754 1314.2 522.283V513.236C1314.2 510.975 1314.2 509.845 1314.42 508.879C1314.87 506.867 1315.86 505.227 1317.47 503.831C1318.25 503.16 1319.33 502.553 1321.49 501.339L1331.4 495.782C1334.62 493.972 1336.23 493.068 1337.12 491.61C1338 490.152 1338 488.393 1338 484.876V482.539C1338 478.042 1338 475.794 1336.51 474.397C1335.01 473 1332.61 473 1327.8 473Z" fill="white"/>'
     '</g>',
     0.01, 0, 1),

    # mobile favorites tab's heart (Group 75.svg) — also plain, no wobble
    # in the source export. Natural bbox is x:[42,114] y:[84.1423,155];
    # translated by (-42,-84.1423) so it sits flush in its own canvas.
    ("favorites-heart-tab", 72, 70.8577,
     '<g transform="translate(-42, -84.1423)">'
     '<path d="M42 114.077C42 131.59 56.4699 140.923 67.0622 149.277C70.8 152.225 74.4 155 78 155C81.6 155 85.2 152.225 88.9379 149.277C99.5302 140.923 114 131.59 114 114.077C114 96.5628 94.1993 84.1423 78 100.98C61.8006 84.1423 42 96.5628 42 114.077Z" fill="white"/>'
     '</g>',
     0.01, 0, 1),
]

SHAPES_RECT_IS_SPEC_SIZE = [
    # name, w, h, rx, freq, scale, seed, margin
    #
    # margin=6 (vs. the usual 2px) is deliberately oversized: video/
    # contacts-bg are large enough to hit a headless-Chrome screenshot bug
    # that bleeds a ~15px-wide band of mis-encoded pixels along the right/
    # bottom edge of the capture (verified by inspecting the rendered PNGs'
    # alpha channel), so their margin has to be big enough for
    # `_clear_edge_bleed` to fully cover that band. video/contacts-bg used
    # to live in SHAPES_CANVAS_IS_BOX above with their old 2-3px margin
    # baked directly into the rect coordinates — moved here instead so
    # index.html can grow their CSS box the same way everything else with
    # a margin does (inset: -6px in place of inset: 0).
    ("video", 884, 509, 16, 0.0166666675, 4, 8124, 6),
    ("contacts-bg", 391, 509, 16, 0.0099999998, 6, 7089, 6),
    ("toolbar", 1291, 101, 16, 0.0099999998, 3.2, 658, 6),

    # description panel backdrops — one per line count (1..10), so the
    # "more" panel's own backdrop always matches however many lines the
    # description text actually needs (see fitRowDescription() in the
    # script below), instead of one fixed size for every row. All ten
    # share the same wobble parameters across the Figma exports, only ever
    # differing in height; width is 1291 (matching .row/.divider's visible
    # width everywhere else on the page) — description 1.svg's own export
    # showed 1291 and turned out to be the one CORRECT one; 2 through 10
    # showed 1294 (a 3px export slip), and an earlier pass here wrongly
    # "fixed" the 1291 outlier to match that wider majority instead of the
    # other way around, which pushed the backdrop 3px past .row's own
    # 1291-wide box on both sides and got its right edge clipped by
    # .row-description-wrap's overflow:hidden. margin=6 (not the 3 the
    # exports actually show) for the same reason as toolbar/video/
    # contacts-bg above — these are large enough on their own to plausibly
    # hit the same Chrome edge-bleed bug, and using a bigger margin here
    # only grows the invisible wobble buffer, not the visible 1291xH rect
    # itself.
    ("description-1", 1291, 70, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-2", 1291, 106, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-3", 1291, 142, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-4", 1291, 177, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-5", 1291, 212, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-6", 1291, 245, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-7", 1291, 282, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-8", 1291, 314, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-9", 1291, 354, 16, 0.0099999997764825821, 6, 7089, 6),
    ("description-10", 1291, 385, 16, 0.0099999997764825821, 6, 7089, 6),
    # ud-title/ud-strip/ud-arrow moved to SHAPES_SHARED_CANVAS_GROUPS below —
    # they sit flush against each other (title's right edge a couple px
    # from the strip, the strip's right edge a couple px from the arrow),
    # and rendering each in its own locally-zeroed canvas (like every other
    # entry here) gave each one an independent, uncorrelated wobble at
    # those shared edges — visible as a seam that opens and closes as the
    # noise pattern drifts between neighbors instead of moving together.
    ("ud-opened", 288, 335, 16, 0.0111111114, 4.0, 3476, 10),
    # mv-title/mv-strip/mv-arrow moved to SHAPES_SHARED_CANVAS_GROUPS below,
    # same reason as the ud-* trio above. mv-opened moved to
    # SHAPES_CANVAS_IS_BOX_WITH_MARGIN below — its current design isn't a
    # uniform-corner rect anymore (small radius on the top two corners,
    # much larger on the bottom two), so it needs a real path instead of
    # this list's `rx` template.
    ("contacts-cap", 414, 65, 16, 0.013888888992369175, 4.0, 9984, 10),
    # contacts-panel moved to SHAPES_CANVAS_IS_BOX_WITH_MARGIN below — same
    # reason as mv-opened: its top-left corner alone has a much bigger
    # radius (~33px, matching contacts-cap's own corner above it) than the
    # other three (~16px, this design's usual radius), so it needs a real
    # path instead of this list's uniform `rx` template.
    ("header-fav-bg", 67, 65, 16, 0.019685039296746254, 2.7999999523162842, 4946, 10),

    # Mobile template (1601px-wide reference canvas, separate from the
    # 1920px desktop one — see index.html's mobile row markup). Each of
    # these three came from its own standalone Figma export with its own
    # <filter>, so — unlike ud-/mv- above — they're independent entries
    # here rather than a SHAPES_SHARED_CANVAS_GROUPS group: nothing here
    # sits flush/touching another piece of this trio (top-line to
    # video-back alone is a 20px gap), so there's no shared edge whose
    # wobble needs to correlate.
    # m-video-back: freq/scale/seed match desktop's own "video" entry
    # above exactly (same visual family) — margin=6 for the same reason
    # (big enough to plausibly hit the Chrome edge-bleed bug).
    ("m-video-back", 1281, 738, 16, 0.01666666753590107, 4, 8124, 6),
    # m-line: shared by both the top and bottom line under each mobile
    # video (same "one shape, several CSS classes" reuse as desktop's own
    # .divider). Long/thin but still wide enough on its own to plausibly
    # hit the same bug, hence margin=6 rather than the smaller pills' 10.
    ("m-line", 1281, 28, 14, 0.01666666753590107, 4, 8124, 6),
    # m-contacts-back: one shape, tiled 5x per row (see index.html) — freq/
    # scale/seed match desktop's contacts-bg/description-N family exactly.
    ("m-contacts-back", 230, 194, 16, 0.0099999997764825821, 6, 7089, 10),

    # Filter drawer (Group 74.svg) — full-page-height sliding panel, mostly
    # off-screen to the left except for a small tab that always peeks out
    # (see index.html's #filterDrawerMobile). Both pieces share the exact
    # same freq/scale/seed in the source export.
    ("filter-drawer-back", 1240, 3468, 16, 0.0099999997764825821, 6, 7089, 6),
    ("filter-tab-back", 470, 248, 16, 0.0099999997764825821, 6, 7089, 6),

    # Mobile favorites tab (Group 75.svg) — a standalone peeking tab on the
    # opposite (right) edge, same freq/scale/seed family as the filter
    # drawer/tab above. Source rect is 683x242 with its own 3px margin
    # baked in (689x248 canvas); using this file's usual margin=6 instead,
    # same as filter-tab-back/m-contacts-back.
    ("favorites-tab-back", 683, 242, 16, 0.0099999997764825821, 6, 7089, 6),

    # Filter drawer contents — title back.svg's 3 layers (upload date /
    # max. views backdrops) and pref contacts back.svg's single layer.
    # Each rect has its own independently-fitted <filter> region in the
    # source (x=512/-627/916, each just ~2px past its own rect) rather than
    # one shared canvas, so — unlike ud-/mv- above — there's no shared-edge
    # wobble to correlate here: rendering each independently, same as
    # m-video-back/m-line, faithfully matches how the source itself was
    # built. freq/scale/seed match that family exactly.
    ("filter-title-strip", 1452, 201, 16, 0.01666666753590107, 4, 8124, 6),
    ("filter-title-accent", 532, 201, 16, 0.01666666753590107, 4, 8124, 6),
    ("filter-title-icon-bg", 201, 201, 16, 0.01666666753590107, 4, 8124, 6),
    ("filter-contacts-strip", 1744, 201, 16, 0.01666666753590107, 4, 8124, 6),

    # The entire header — its dark background, every button ("upload
    # date" / "max. views" / "preferred contacts" / the heart favorites
    # toggle), and the dropdown panels underneath them — *used* to live
    # here too (toolbar, header-fav-bg, ud-title, mv-title, ud-panel,
    # mv-panel, contacts-panel, contacts-cap): hand-drawn wobble
    # rasterized to a PNG mask, same as everything else in this file. Per
    # the user, that whole family is now plain flat CSS rounded rects
    # instead (border-radius: 16px directly in index.html, no mask): the
    # raster approach kept producing edge artifacts and seams between
    # adjacent/stacked pieces, and after several rounds of chasing those
    # (margin tuning, matching wobble seeds/margins between paired shapes,
    # edge-bleed workarounds) it wasn't worth the fragility for shapes
    # that are simple rounded rectangles to begin with.
]

# Same idea as SHAPES_CANVAS_IS_BOX (canvas *is* the CSS box, arbitrary
# shape_svg instead of a plain rect/circle template) — but big enough on
# its own to plausibly hit the same Chrome-screenshot edge-bleed bug that
# made video/contacts-bg move into SHAPES_RECT_IS_SPEC_SIZE below (see that
# comment), so these also carry a real `margin` for _clear_edge_bleed to
# work with, unlike SHAPES_CANVAS_IS_BOX's always-margin-0 entries.
SHAPES_CANVAS_IS_BOX_WITH_MARGIN = [
    # name, canvas_w, canvas_h, shape_svg, freq, scale, seed, margin
    #
    # mv-opened's design isn't a uniform-corner rounded rect: the top two
    # corners are a small ~11px radius (matching the closed pill above it),
    # the bottom two are a much larger ~27px radius. That only comes through
    # as a raw path, straight from the Figma export, translated by
    # (margin - path's own natural left/top) so it sits with a clean 10px
    # margin on every side inside this shape's own canvas (256x281 natural
    # size + 10px margin per side = 276x301), the same margin convention
    # every other "opened panel" shape here uses.
    ("mv-opened", 276, 301,
     '<g transform="translate(8.3999, 8.3999)">'
     '<path d="M1.6001 12.6001C1.6001 6.52496 6.52497 1.6001 12.6001 1.6001H248.6C253.571 1.6001 257.6 5.62954 257.6 10.6001V255.6C257.6 270.512 245.512 282.6 230.6 282.6H28.6001C13.6884 282.6 1.6001 270.512 1.6001 255.6V12.6001Z" fill="white"/>'
     '</g>',
     0.01342281885445118, 3.2000000476837158, 4584, 10),

    # contacts-panel: only the top-left corner is enlarged (~33px, matching
    # contacts-cap's own corner directly above it), the other three stay
    # this design's usual ~16px — natural bbox is 414x249 (2..416, 2..251),
    # translated by (10-2, 10-2) = (8, 8) for a clean 10px margin all round.
    ("contacts-panel", 434, 269,
     '<g transform="translate(8, 8)">'
     '<path d="M2 35C2 16.7746 16.7746 2 35 2H400C408.837 2 416 9.16344 416 18V235C416 243.837 408.837 251 400 251H18C9.16345 251 2 243.837 2 235V35Z" fill="white"/>'
     '</g>',
     0.013888888992369175, 4.0, 9984, 10),

    # Filter drawer's sort-direction icon (three bars, tall-to-short —
    # "sorting max to min.svg"; "sorting min to max.svg" turned out
    # pixel-identical, so index.html flips this one asset via CSS instead
    # of using a second shape here). Natural bbox is ~89.55x91.59 starting
    # at (1.9, 1.9); translated by (6-1.9, 6-1.9) for a clean 6px margin on
    # every side, same convention as the rect-margin family above.
    ("filter-sort-icon", 106, 108,
     '<g transform="translate(4.0996, 4.1001)">'
     '<rect x="1.90039" y="1.8999" width="21.0314" height="91.5885" rx="10.5157" fill="white"/>'
     '<rect x="36.5" y="37.1787" width="21.0314" height="56.31" rx="10.5157" fill="white"/>'
     '<rect x="70.4219" y="62.9595" width="21.0314" height="30.5295" rx="10.5157" fill="white"/>'
     '</g>',
     0.02500000037252903, 3.7999999523162842, 5172, 6),
]

SHAPES = (
    [(name, w, h, shape_svg, freq, scale, seed, 0) for name, w, h, shape_svg, freq, scale, seed in SHAPES_CANVAS_IS_BOX]
    + [(name, w, h, shape_svg, freq, scale, seed, margin) for name, w, h, shape_svg, freq, scale, seed, margin in SHAPES_CANVAS_IS_BOX_WITH_MARGIN]
    + [
        (name, w + 2 * margin, h + 2 * margin,
         f'<rect x="{margin}" y="{margin}" width="{w}" height="{h}" rx="{rx}" fill="white"/>',
         freq, scale, seed, margin)
        for name, w, h, rx, freq, scale, seed, margin in SHAPES_RECT_IS_SPEC_SIZE
    ]
)

# Some Figma layers stack more than one independent wobble pass on the
# same shape instead of combining them into a single feTurbulence — nested
# <g filter="url(#a)"><g filter="url(#b)"><rect/></g></g>, each with its
# own freq/scale/seed. Two sequential low-frequency-then-high-frequency
# displacements compound into a richer, less regular texture than either
# alone; refresh-back's export does this (see render_layered_png below).
SHAPES_LAYERED = [
    # name, canvas_w, canvas_h, shape_svg (bare fill="white" shape, no
    # filter/<g> wrapper — that's added automatically), layers (outermost-
    # first, matching the raw SVG's own nesting order: filters[0] wraps
    # everything else and is applied *last*, to the already-displaced
    # result of the inner layers; filters[-1] sits immediately around the
    # shape and is applied *first*), margin (0 here — refresh-back's
    # source already bakes its own small wobble-margin into an 83x83
    # canvas around a 79x79 rect, matching the CSS `inset:0` box exactly,
    # the same "canvas is the box" convention as SHAPES_CANVAS_IS_BOX
    # above, just with more than one filter pass).
    ("refresh-back-new", 83, 83,
     '<rect x="2" y="2" width="79" height="79" rx="16" fill="white"/>',
     [
         (0.0099999997764825821, 4, 7898),
         (0.019342359155416489, 2.7999999523162842, 4946),
     ],
     0),
]


def turbulence_filter_layers(base_fid, w, h, layers):
    open_tags, filter_defs = "", ""
    for i, (freq, scale, seed) in enumerate(layers):
        fid = f"{base_fid}_{i}"
        open_tags += f'<g filter="url(#{fid})">'
        filter_defs += turbulence_filter(fid, w, h, freq, scale, seed)
    close_tags = "</g>" * len(layers)
    return open_tags, filter_defs, close_tags


def render_layered_png(name, canvas_w, canvas_h, shape_svg, layers, margin, tmp_dir):
    render_w, render_h = round(canvas_w * RENDER_SCALE), round(canvas_h * RENDER_SCALE)
    base_fid = f"f_{name.replace('-', '_')}"
    open_tags, filter_defs, close_tags = turbulence_filter_layers(base_fid, canvas_w, canvas_h, layers)
    svg = (
        f'<svg width="{render_w}" height="{render_h}" viewBox="0 0 {canvas_w} {canvas_h}" '
        f'xmlns="http://www.w3.org/2000/svg">{open_tags}{shape_svg}{close_tags}<defs>{filter_defs}</defs></svg>'
    )
    html = (
        "<!DOCTYPE html><html><head><style>"
        "html,body{margin:0;padding:0;background:transparent;}"
        f"</style></head><body>{svg}</body></html>"
    )
    html_path = os.path.join(tmp_dir, name + ".html")
    png_path = os.path.join(OUT_DIR, name + ".png")
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
    if margin > 0:
        _clear_edge_bleed(png_path, round(margin * RENDER_SCALE))
    print(f"{name}: {render_w}x{render_h} -> {png_path} (layered filters)")

# Pieces that sit flush against each other in the design (e.g. upload
# date's strip+title+arrow trio) need their wobble to actually correlate
# at the shared edges, or the seam between them visibly opens/closes as
# each piece's independent noise pattern drifts differently. feTurbulence's
# noise field is a pure function of (x, y) position for a given
# baseFrequency/seed/numOctaves — completely independent of whatever shape
# feDisplacementMap later applies it to — so rendering each piece
# separately but within one *shared* coordinate system (rather than each
# one's own locally-zeroed canvas, like every entry above) reproduces the
# exact same per-pixel displacement wherever two pieces touch. Pieces still
# come out as separate PNGs (unlike SHAPES_CANVAS_IS_BOX/
# SHAPES_RECT_IS_SPEC_SIZE, which are 1 shape = 1 mask = 1 CSS
# background-color), since these still need independent theme colors in
# CSS (e.g. --pill-dim for the strip vs. --pill-bright for the title/
# arrow) — mask-image can only carry one background-color per element.
SHAPES_SHARED_CANVAS_GROUPS = [
    # (group_canvas_w, group_canvas_h, freq, scale, seed, [
    #   (name, x, y, w, h, rx, margin), ...  — x/y/w/h/rx straight from the
    #   Figma export's shared coordinate system; margin is whatever that
    #   piece used before it became part of a group, so its own output
    #   canvas size (and the CSS `inset` already wired to it in index.html)
    #   stays unchanged.
    # ])
    (367, 69, 0.011614401824772358, 3.5999999046325684, 3511, [
        ("ud-strip", 237.137, 1.80005, 116, 65, 16, 10),
        ("ud-title", 1.7998, 1.80005, 288, 65, 16, 10),
        ("ud-arrow", 297.8, 1.80005, 67, 65, 16, 10),
    ]),
    (334, 68, 0.016778523102402687, 2.2000000476837158, 9765, [
        ("mv-strip", 191.16, 1.1001, 125, 65, 16, 10),
        ("mv-title", 1.1001, 1.1001, 256, 65, 16, 10),
        ("mv-arrow", 265.1, 1.1001, 67, 65, 16, 10),
    ]),
]

# Extra headroom rendered around the *whole* group canvas before cropping
# per piece — without it, a piece sitting flush against the group
# canvas's own edge (e.g. ud-title starting at x=1.7998) would have no
# room left to crop its own `margin` on that side. Purely about leaving
# blank space to crop into; doesn't touch the noise field's alignment
# between pieces, since every piece is still offset by the exact same
# amount.
GROUP_PAD = 20


def render_shared_canvas_group(canvas_w, canvas_h, freq, scale, seed, pieces, tmp_dir):
    padded_w, padded_h = canvas_w + 2 * GROUP_PAD, canvas_h + 2 * GROUP_PAD
    render_w, render_h = round(padded_w * RENDER_SCALE), round(padded_h * RENDER_SCALE)
    fid = "f_group"
    filt = turbulence_filter(fid, padded_w, padded_h, freq, scale, seed)

    for name, x, y, w, h, rx, margin in pieces:
        # this piece's rect, in padded-canvas coordinates — every piece in
        # the group gets the same GROUP_PAD offset, so their relative
        # positions (and thus the noise field lining up between them) are
        # unchanged from the group's own original coordinate system
        px, py = x + GROUP_PAD, y + GROUP_PAD
        rect_svg = f'<rect x="{px}" y="{py}" width="{w}" height="{h}" rx="{rx}" fill="white"/>'
        svg = (
            f'<svg width="{render_w}" height="{render_h}" viewBox="0 0 {padded_w} {padded_h}" '
            f'xmlns="http://www.w3.org/2000/svg"><g filter="url(#{fid})">{rect_svg}</g><defs>{filt}</defs></svg>'
        )
        html = (
            "<!DOCTYPE html><html><head><style>"
            "html,body{margin:0;padding:0;background:transparent;}"
            f"</style></head><body>{svg}</body></html>"
        )
        html_path = os.path.join(tmp_dir, name + "_group.html")
        full_png_path = os.path.join(tmp_dir, name + "_group.png")
        with open(html_path, "w") as f:
            f.write(html)
        subprocess.run(
            [
                CHROME, "--headless", "--disable-gpu",
                f"--screenshot={full_png_path}",
                f"--window-size={render_w},{render_h}",
                "--default-background-color=00000000",
                "--force-device-scale-factor=1",
                f"file://{html_path}",
            ],
            capture_output=True,
            check=True,
        )
        full_im = Image.open(full_png_path).convert("RGBA")
        crop_box = (
            round((px - margin) * RENDER_SCALE),
            round((py - margin) * RENDER_SCALE),
            round((px + w + margin) * RENDER_SCALE),
            round((py + h + margin) * RENDER_SCALE),
        )
        cropped = full_im.crop(crop_box)
        png_path = os.path.join(OUT_DIR, name + ".png")
        cropped.save(png_path)
        _clear_edge_bleed(png_path, round(margin * RENDER_SCALE))
        print(f"{name}: {cropped.size[0]}x{cropped.size[1]} -> {png_path} (shared-canvas group)")


def render_png(name, w, h, body_svg, tmp_dir, margin):
    render_w, render_h = round(w * RENDER_SCALE), round(h * RENDER_SCALE)
    svg = f'<svg width="{render_w}" height="{render_h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">{body_svg}</svg>'
    html = (
        "<!DOCTYPE html><html><head><style>"
        "html,body{margin:0;padding:0;background:transparent;}"
        f"</style></head><body>{svg}</body></html>"
    )
    html_path = os.path.join(tmp_dir, name + ".html")
    png_path = os.path.join(OUT_DIR, name + ".png")
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
    _clear_edge_bleed(png_path, round(margin * RENDER_SCALE))
    print(f"{name}: {render_w}x{render_h} -> {png_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    with tempfile.TemporaryDirectory() as tmp_dir:
        for name, w, h, shape_svg, freq, scale, seed, margin in SHAPES:
            if targets and name not in targets:
                continue
            fid = f"f_{name.replace('-', '_')}"
            body_svg = (
                f'<g filter="url(#{fid})">{shape_svg}</g>'
                f'<defs>{turbulence_filter(fid, w, h, freq, scale, seed)}</defs>'
            )
            render_png(name, w, h, body_svg, tmp_dir, margin)

        for canvas_w, canvas_h, freq, scale, seed, pieces in SHAPES_SHARED_CANVAS_GROUPS:
            active_pieces = [p for p in pieces if not targets or p[0] in targets]
            if not active_pieces:
                continue
            render_shared_canvas_group(canvas_w, canvas_h, freq, scale, seed, active_pieces, tmp_dir)

        for name, canvas_w, canvas_h, shape_svg, layers, margin in SHAPES_LAYERED:
            if targets and name not in targets:
                continue
            render_layered_png(name, canvas_w, canvas_h, shape_svg, layers, margin, tmp_dir)


if __name__ == "__main__":
    main()
