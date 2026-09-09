"""Derive every brand asset in `syndicate/static/shared/` from two sources.

Syndicate carries TWO marks and they are not interchangeable. This script is
where the split is made mechanical, so a future re-render cannot quietly put
the wrong one in the wrong slot:

  * the WORDMARK (`syndicate-logo.png`, 815x193) -- understated, and the only
    mark whose "S" is still legible at 16px. It owns the browser chrome
    (favicons) and the in-app header lockup, which no code here touches.
  * the MASCOT CREST (an opaque 1254x1254 illustration) -- loud, square, and
    mud below ~64px. It owns every slot that renders large: the iOS home
    screen icon, the PWA install icons, the link-preview card, and the
    `/syndicate` hero.

That split was measured, not assumed: `--contact-sheets` regenerates the
16/32/64/128/512 grids the decision rests on, for the full art, for a tight
hood-only crop, and for the squared S on both a light and a dark ground.

The mascot art contains its OWN "SYNDICATE" lettering (top edge at y~715 in
source pixels). Anything that pairs it with the wordmark crops above that
line -- two wordmarks on one image reads as a mistake, not as branding.

The master art is checked in at `docs/brand/syndicate-mascot-source.png`
(2.4 MB, deliberately OUTSIDE `static/` so it is never served) -- without it
this script would only be re-runnable from whoever's Downloads folder the art
last landed in.

Usage:
    py -3 scripts/build_brand_assets.py
    py -3 scripts/build_brand_assets.py --contact-sheets <dir>

Requires Pillow, which is not in `requirements.txt`: this is an offline,
run-once-per-art-change tool, not a runtime dependency of the web service.
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - offline tool, not part of the app
    sys.exit("Pillow is required: py -3 -m pip install pillow")


SHARED = os.path.join("syndicate", "static", "shared")
SOURCE_ART = os.path.join("docs", "brand", "syndicate-mascot-source.png")

# Page ground, kept in sync with --cards-bg / theme-color in app.css.
BG = (8, 19, 31)

# The figure alone, stopping above the art's own "SYNDICATE" lettering.
FIGURE_BOX = (110, 0, 1150, 712)
# Same crop with a little more headroom, for the wide social card.
FIGURE_BOX_WIDE = (110, 0, 1150, 770)


def _quantized(img: Image.Image, path: str, colors: int = 256) -> None:
    """Save a PNG at `colors`. The art is stylized flat-shaded neon, so a
    256-colour palette is visually indistinguishable at icon sizes and cuts
    the 512px icon from 494 KB to ~172 KB."""
    img.convert("RGB").quantize(
        colors=colors, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG
    ).save(path, optimize=True)


def build_app_icons(mascot: Image.Image, out: str) -> None:
    """Square icons for the home screen and the PWA install prompt.

    Full square art, uncropped: these render at 180px and up, where the whole
    crest reads, and a home-screen icon should fill its tile.
    """
    for name, size in (
        ("syndicate-mascot.png", 512),
        ("syndicate-mascot-192.png", 192),
        ("apple-touch-icon.png", 180),
    ):
        _quantized(mascot.resize((size, size), Image.LANCZOS), os.path.join(out, name))


def build_favicons(wordmark: Image.Image, out: str) -> None:
    """16/32/48px favicons and a .ico from the wordmark's S, squared and padded.

    The S is isolated by the alpha gap between it and the lettering rather
    than a hardcoded x -- measured at columns 247..274 in the current
    wordmark, but re-derived here so a re-exported wordmark still works.
    There is deliberately NO scalable favicon. `syndicate-logo.svg` looks
    like the obvious source and is not: rendered at 240px beside the PNG it
    draws two parallel bars where the real mark is an interlocking S, and
    sets the wordmark in Arial. It is referenced nowhere in the app. A real
    SVG icon needs the mark re-vectorised first.
    """
    alpha = wordmark.split()[-1]
    width, height = wordmark.size
    cut = None
    run_start = None
    for x in range(int(width * 0.15), int(width * 0.45)):
        column_empty = not any(
            alpha.getpixel((x, y)) > 10 for y in range(0, height, 3)
        )
        if column_empty:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None and x - run_start >= 12:
                cut = (run_start + x) // 2
                break
            run_start = None
    if cut is None:
        raise SystemExit(
            "could not find the gap between the S and the wordmark -- the "
            "source logo changed shape; re-check the crop before shipping"
        )

    s_mark = wordmark.crop((0, 0, cut, height))
    s_mark = s_mark.crop(s_mark.getbbox())
    side = max(s_mark.size)
    pad = int(side * 0.06)
    square = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    square.paste(
        s_mark,
        (pad + (side - s_mark.size[0]) // 2, pad + (side - s_mark.size[1]) // 2),
        s_mark,
    )
    for name, size in (("favicon-48.png", 48), ("favicon-32.png", 32),
                       ("favicon-16.png", 16)):
        square.resize((size, size), Image.LANCZOS).save(
            os.path.join(out, name), optimize=True
        )
    square.resize((64, 64), Image.LANCZOS).save(
        os.path.join(out, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)]
    )


def build_hero_crest(mascot: Image.Image, out: str) -> None:
    """The `/syndicate` hero art: the figure only, as a plain rectangle.

    No feathering and no cutout. The source is opaque to its edges with no
    separable background, so a fade just looks like a failed mask; the page
    frames it with border-radius + a hairline border instead, which is the
    card language the rest of the app already speaks. JPEG because the art is
    photographic smoke -- 108 KB against 584 KB for the same PNG.
    """
    crest = mascot.crop(FIGURE_BOX)
    width = 720
    crest.resize(
        (width, int(width * crest.size[1] / crest.size[0])), Image.LANCZOS
    ).save(
        os.path.join(out, "syndicate-crest.jpg"),
        quality=86,
        optimize=True,
        progressive=True,
    )


def build_social_card(mascot: Image.Image, wordmark: Image.Image, out: str) -> None:
    """1200x630 og:image. Both marks, each doing the job it can do.

    The wordmark carries the NAME on flat ground at the left; the crest
    carries the personality at the right, cropped above its own lettering and
    faded into the page ground on all four sides so the crop never reads as a
    hard cut.
    """
    width, height = 1200, 630
    card = Image.new("RGB", (width, height), BG)

    crest = mascot.crop(FIGURE_BOX_WIDE)
    scale = height / crest.size[1]
    art = crest.resize((int(crest.size[0] * scale), height), Image.LANCZOS)
    art_x = width - art.size[0] + 60
    card.paste(art, (art_x, 0))

    # Left fade has to be wide enough that the text sits on flat ground, not
    # on smoke -- 340px was tuned against the wordmark's rendered width.
    fade = Image.linear_gradient("L").rotate(270, expand=True).resize((340, height))
    card.paste(Image.new("RGB", (340, height), BG), (art_x, 0), fade)
    right = Image.linear_gradient("L").rotate(90, expand=True).resize((140, height))
    card.paste(Image.new("RGB", (140, height), BG), (width - 140, 0), right)
    vignette = Image.linear_gradient("L").resize((width, 100))
    card.paste(Image.new("RGB", (width, 100), BG), (0, height - 100), vignette)
    card.paste(
        Image.new("RGB", (width, 100), BG),
        (0, 0),
        vignette.transpose(Image.FLIP_TOP_BOTTOM),
    )

    mark = wordmark.resize(
        (520, int(520 * wordmark.size[1] / wordmark.size[0])), Image.LANCZOS
    )
    card.paste(mark, (66, 214), mark)

    draw = ImageDraw.Draw(card)
    bold = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                           "Fonts", "arialbd.ttf"), 25)
    plain = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                            "Fonts", "arial.ttf"), 23)
    draw.text((74, 330), "MULTI-SPORT BETTING INTELLIGENCE", font=bold,
              fill=(154, 243, 222))
    draw.text((74, 372), "Sim-backed edges, live boards, graded results.",
              font=plain, fill=(191, 208, 223))

    card.save(os.path.join(out, "syndicate-og.jpg"), quality=88, optimize=True,
              progressive=True)


def build_contact_sheets(mascot: Image.Image, wordmark: Image.Image, out: str) -> None:
    """Regenerate the evidence the mark split rests on.

    Each row is one candidate rendered at 512/128/64/32/16 and blown back up
    nearest-neighbour, so what a tab strip actually shows is visible. The
    conclusion these produced: mascot unreadable at 32 and mud at 16, in both
    the full-art and the hood-crop framing; the squared S clean at 32 and
    legible at 16 on light AND dark.
    """
    os.makedirs(out, exist_ok=True)
    sizes = (512, 128, 64, 32, 16)

    def sheet(img: Image.Image, path: str, ground: tuple) -> None:
        canvas = Image.new("RGBA", (len(sizes) * 140 + 20, 160), ground)
        x = 10
        for size in sizes:
            small = img.resize((size, size), Image.LANCZOS)
            view = small.resize(
                (128, 128), Image.NEAREST if size <= 64 else Image.LANCZOS
            )
            canvas.paste(view, (x, 16), view if view.mode == "RGBA" else None)
            x += 140
        canvas.convert("RGB").save(path)

    opaque = BG + (255,)
    sheet(mascot.convert("RGBA"), os.path.join(out, "contact_mascot_full.png"), opaque)
    sheet(mascot.crop((230, 30, 1030, 830)).convert("RGBA"),
          os.path.join(out, "contact_mascot_hood.png"), opaque)

    alpha_bbox = wordmark.crop((0, 0, 261, wordmark.size[1]))
    alpha_bbox = alpha_bbox.crop(alpha_bbox.getbbox())
    side = max(alpha_bbox.size)
    pad = int(side * 0.06)
    square = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    square.paste(alpha_bbox,
                 (pad + (side - alpha_bbox.size[0]) // 2,
                  pad + (side - alpha_bbox.size[1]) // 2), alpha_bbox)
    sheet(square, os.path.join(out, "contact_s_dark.png"), opaque)
    sheet(square, os.path.join(out, "contact_s_light.png"), (240, 242, 245, 255))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=SOURCE_ART,
                        help="the square mascot illustration (default: %(default)s)")
    parser.add_argument("--out", default=SHARED,
                        help="target directory (default: %(default)s)")
    parser.add_argument("--contact-sheets", metavar="DIR",
                        help="also regenerate the legibility contact sheets there")
    args = parser.parse_args()

    mascot = Image.open(args.source).convert("RGB")
    if mascot.size[0] != mascot.size[1]:
        return int(bool(sys.stderr.write(
            "source must be square -- every crop offset here is in the "
            "1254x1254 frame and will be wrong otherwise\n")))
    if mascot.size[0] != 1254:
        mascot = mascot.resize((1254, 1254), Image.LANCZOS)

    wordmark = Image.open(os.path.join(args.out, "syndicate-logo.png")).convert("RGBA")

    build_app_icons(mascot, args.out)
    build_favicons(wordmark, args.out)
    build_hero_crest(mascot, args.out)
    build_social_card(mascot, wordmark, args.out)
    if args.contact_sheets:
        build_contact_sheets(mascot, wordmark, args.contact_sheets)

    for name in sorted(os.listdir(args.out)):
        if name.startswith(("syndicate-", "apple-", "favicon")):
            size_kb = os.path.getsize(os.path.join(args.out, name)) // 1024
            print(f"{name:28s} {size_kb:>5d} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
