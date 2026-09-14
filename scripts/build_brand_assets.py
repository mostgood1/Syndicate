"""Derive every brand asset in `syndicate/static/shared/` from two sources.

Syndicate carries TWO marks, split on the size the slot actually renders at.
This script is where the split is made mechanical, so a future re-render
cannot quietly put the wrong one in the wrong slot:

  * the LOGO (`docs/brand/syndicate-logo-source.png`, an opaque 1536x1024
    piece: hooded mascot, crown, the green/blue S swoosh and its own
    "SYNDICATE" lettering). It is THE brand `[user decision, 2026-09-14]` and
    owns every slot that renders at ~50px and up: the header on every page,
    the four hero panels, the iOS/PWA icons and the link-preview card.
  * the WORDMARK (`syndicate-logo.png`, 815x193: the S swoosh plus silver
    "SYNDICATE" lettering), split in two:
      - its S feeds the favicons. The mascot art was measured unreadable at
        32px and mud at 16px on 2026-09-09; the logo puts lettering on top of
        that same art, so it can only be worse. The S is the swoosh the logo
        is built around, so the tab icon still matches `[user decision,
        2026-09-14: keep the S favicon]`.
      - its LETTERING, without the S, sits beside the logo in the header where
        the menu row has room for it `[user decision, 2026-09-14]`. At header
        size the logo's own lettering is ~68px wide and hard to read; this is
        what names the site there. The S is left out because the logo beside
        it already carries the swoosh.

THE LOGO IS NEVER CROPPED `[user decision, 2026-09-14: "dont crop the image,
resize it. The logo must be maintained"]`. Every asset is the whole piece,
resized. A slot whose shape differs from 3:2 (the square icons, the 1200x630
card) gets the whole logo fitted inside it and the remainder filled with the
logo's own ground colour -- padding, never trimming. The pages hold the same
line in CSS: the hero panels use `object-fit: contain` at the art's own
aspect ratio, because `cover` would crop in the browser a file this script
kept whole.

`--contact-sheets` regenerates the 16/32/64/128/512 grids that split rests on,
for the logo's icon and for the squared S on a light and a dark ground.

The master art is checked in at `docs/brand/syndicate-logo-source.png`
(deliberately OUTSIDE `static/` so it is never served) -- without it this
script would only be re-runnable from whoever's Downloads folder the art last
landed in.

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
    from PIL import Image
except ImportError:  # pragma: no cover - offline tool, not part of the app
    sys.exit("Pillow is required: py -3 -m pip install pillow")


SHARED = os.path.join("syndicate", "static", "shared")
SOURCE_ART = os.path.join("docs", "brand", "syndicate-logo-source.png")

# Page ground, kept in sync with --cards-bg / theme-color in app.css. Used
# only behind the transparent favicon contact sheets -- the logo pads with
# its OWN ground (read from the art), or the padding would show as a band.
BG = (8, 19, 31)


def _quantized(img: Image.Image, path: str, colors: int = 256) -> None:
    """Save a PNG at `colors`. A 256-colour palette with dithering is visually
    indistinguishable at icon sizes and keeps the 512px icon a fraction of
    the full-colour PNG's size."""
    img.convert("RGB").quantize(
        colors=colors, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG
    ).save(path, optimize=True)


def _jpeg(img: Image.Image, path: str, quality: int) -> None:
    """JPEG for the opaque slots: the swooshes are smooth gradients, which a
    256-colour PNG bands and a JPEG does not, at a fraction of the bytes."""
    img.convert("RGB").save(path, quality=quality, optimize=True, progressive=True)


def _ground(logo: Image.Image) -> tuple:
    """The logo's own background colour, from its four corners."""
    w, h = logo.size
    corners = [logo.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return tuple(sum(c[i] for c in corners) // 4 for i in range(3))


def _fitted(logo: Image.Image, size: tuple) -> Image.Image:
    """The WHOLE logo, resized to fit inside `size` and centred on its own
    ground. Nothing is cropped; only the leftover space is filled."""
    scale = min(size[0] / logo.size[0], size[1] / logo.size[1])
    art = logo.resize(
        (round(logo.size[0] * scale), round(logo.size[1] * scale)), Image.LANCZOS
    )
    canvas = Image.new("RGB", size, _ground(logo))
    canvas.paste(art, ((size[0] - art.size[0]) // 2, (size[1] - art.size[1]) // 2))
    return canvas


def _s_cut(wordmark: Image.Image) -> int:
    """The x between the wordmark's S and its lettering.

    Found from the alpha gap rather than a hardcoded x -- measured at columns
    247..274 in the current wordmark (cut 261), but re-derived here so a
    re-exported wordmark still works. Both the favicons (left of the cut) and
    the header lettering (right of it) depend on this one answer.
    """
    alpha = wordmark.split()[-1]
    width, height = wordmark.size
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
                return (run_start + x) // 2
            run_start = None
    raise SystemExit(
        "could not find the gap between the S and the wordmark -- the "
        "source logo changed shape; re-check the crop before shipping"
    )


def build_header_logo(logo: Image.Image, out: str) -> None:
    """The header lockup on every page. 480x320 for a slot that renders at
    60-84px tall, so it stays sharp on a 2x screen and is still small."""
    _jpeg(_fitted(logo, (480, 320)), os.path.join(out, "syndicate-brand-header.jpg"),
          quality=88)


def build_header_wordmark(wordmark: Image.Image, out: str) -> None:
    """The silver "SYNDICATE" lettering alone, for the header beside the logo.

    Everything right of the S, trimmed to its alpha bbox, at NATIVE size
    (521x58 today). It renders 28px tall, so native is already ~2x for a retina
    screen, and resampling would only soften it. Transparent PNG: it sits on
    the header's own gradient. The page shows it only where the menu row has
    room (see `.syndicate-title-wordmark` in app.css).
    """
    width, height = wordmark.size
    letters = wordmark.crop((_s_cut(wordmark), 0, width, height))
    letters.crop(letters.getbbox()).save(
        os.path.join(out, "syndicate-wordmark.png"), optimize=True
    )


def build_hero(logo: Image.Image, out: str) -> None:
    """The hero panels (`/syndicate`, market-board hub, error page,
    `/intelligence/status`) -- the whole piece at 960x640, which covers the
    widest stacked panel (~420 CSS px) on a 2x screen."""
    _jpeg(_fitted(logo, (960, 640)), os.path.join(out, "syndicate-brand-hero.jpg"),
          quality=86)


def build_app_icons(logo: Image.Image, out: str) -> None:
    """Square icons for the iOS home screen and the PWA install prompt: the
    whole 3:2 logo fitted across the square, black above and below."""
    for name, size in (
        ("syndicate-icon-512.png", 512),
        ("syndicate-icon-192.png", 192),
        ("syndicate-icon-180.png", 180),
    ):
        _quantized(_fitted(logo, (size, size)), os.path.join(out, name))


def build_favicons(wordmark: Image.Image, out: str) -> None:
    """16/32/48px favicons and a .ico from the wordmark's S, squared and padded.

    There is deliberately NO scalable favicon: a real SVG icon needs the mark
    re-vectorised first.
    """
    height = wordmark.size[1]
    s_mark = wordmark.crop((0, 0, _s_cut(wordmark), height))
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


def build_social_card(logo: Image.Image, out: str) -> None:
    """1200x630 og:image / twitter:image: the whole logo fitted to the card's
    height, its own black ground either side. The logo carries the name, and
    the page's og:description carries the words."""
    _jpeg(_fitted(logo, (1200, 630)), os.path.join(out, "syndicate-social.jpg"),
          quality=88)


def build_contact_sheets(logo: Image.Image, wordmark: Image.Image, out: str) -> None:
    """Regenerate the evidence the mark split rests on.

    Each row is one candidate rendered at 512/128/64/32/16 and blown back up
    nearest-neighbour, so what a tab strip actually shows is visible.
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
    sheet(_fitted(logo, (512, 512)).convert("RGBA"),
          os.path.join(out, "contact_logo_icon.png"), opaque)

    alpha_bbox = wordmark.crop((0, 0, _s_cut(wordmark), wordmark.size[1]))
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
                        help="the logo art (default: %(default)s)")
    parser.add_argument("--out", default=SHARED,
                        help="target directory (default: %(default)s)")
    parser.add_argument("--contact-sheets", metavar="DIR",
                        help="also regenerate the legibility contact sheets there")
    args = parser.parse_args()

    logo = Image.open(args.source).convert("RGB")
    wordmark = Image.open(os.path.join(args.out, "syndicate-logo.png")).convert("RGBA")

    build_header_logo(logo, args.out)
    build_header_wordmark(wordmark, args.out)
    build_hero(logo, args.out)
    build_app_icons(logo, args.out)
    build_favicons(wordmark, args.out)
    build_social_card(logo, args.out)
    if args.contact_sheets:
        build_contact_sheets(logo, wordmark, args.contact_sheets)

    for name in sorted(os.listdir(args.out)):
        if name.startswith(("syndicate-", "favicon")):
            size_kb = os.path.getsize(os.path.join(args.out, name)) // 1024
            print(f"{name:28s} {size_kb:>5d} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
