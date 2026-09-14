"""The brand assets the pages reference exist, and the logo is never cropped.

Two regressions this pins, both invisible in a browser that still has the old
file cached:

  * a template or the manifest pointing at an asset name that is not on disk.
    Every asset whose content changed was renamed (crest -> brand-hero, mascot
    -> icon, og -> social) so caches cannot serve the old art under the new
    logo's URL, and each rename is one missed reference away from a broken
    image on the live site;
  * a hero panel going back to `object-fit: cover`, which crops the logo in the
    browser however whole the file is `[user decision, 2026-09-14: "dont crop
    the image, resize it. The logo must be maintained"]`.

Rebuild the assets with `py -3 scripts/build_brand_assets.py`.
"""

from __future__ import annotations

import json
import re
import struct
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # Pillow is an offline build tool here, not a runtime dep
    Image = None

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "syndicate" / "static" / "shared"
TEMPLATES = ROOT / "syndicate" / "templates"

BRAND_TEMPLATES = (
    "shared/base.html",
    "shared/_standalone_app_header.html",
    "syndicate.html",
    "market_board_hub.html",
    "errors/error.html",
    "intelligence_status.html",
)
HERO_ART_CLASSES = {
    "syndicate.html": "syndicate-hero__art",
    "market_board_hub.html": "market-board-hub__art",
    "errors/error.html": "error-panel__art",
    "intelligence_status.html": "intel-status-hero__art",
}
RETIRED = (
    "syndicate-crest.jpg",
    "syndicate-mascot.png",
    "syndicate-mascot-192.png",
    "apple-touch-icon.png",
    "syndicate-og.jpg",
    "syndicate-logo.svg",
)


def _image_size(path: Path) -> tuple[int, int]:
    """(width, height) from a PNG's IHDR or a JPEG's SOF marker."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF or data[i + 1] == 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            if 0xD0 <= marker <= 0xD9 or marker == 0x01:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise AssertionError(f"not a PNG or JPEG with a readable size: {path}")


def _css_rules(text: str, css_class: str) -> str:
    """Every declaration block for `.css_class` in `text`, comments removed."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return " ".join(re.findall(r"\." + re.escape(css_class) + r"\s*\{([^}]*)\}", text))


class BrandAssetReferenceTests(unittest.TestCase):
    def test_every_shared_asset_a_brand_template_references_exists(self) -> None:
        for name in BRAND_TEMPLATES:
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            referenced = re.findall(r"filename='shared/([^']+)'", text)
            self.assertTrue(referenced, f"{name} references no shared asset")
            for asset in referenced:
                self.assertTrue((SHARED / asset).is_file(), f"{name} -> missing {asset}")

    def test_manifest_icons_exist_at_their_declared_size(self) -> None:
        manifest = json.loads((SHARED / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["icons"])
        for icon in manifest["icons"]:
            path = ROOT / "syndicate" / icon["src"].lstrip("/")
            self.assertTrue(path.is_file(), f"manifest -> missing {icon['src']}")
            width, height = (int(v) for v in icon["sizes"].split("x"))
            self.assertEqual(_image_size(path), (width, height), icon["src"])

    def test_no_page_references_a_retired_brand_asset(self) -> None:
        files = [*TEMPLATES.rglob("*.html"), *SHARED.rglob("*.css"),
                 *SHARED.rglob("*.js"), *SHARED.rglob("*.json")]
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            for retired in RETIRED:
                self.assertNotIn(retired, text, f"{path.relative_to(ROOT)} -> {retired}")

    def test_every_header_shows_the_logo(self) -> None:
        for name in ("shared/base.html", "shared/_standalone_app_header.html"):
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn("shared/syndicate-brand-header.jpg", text, name)
            self.assertIn("shared/syndicate-wordmark.png", text, name)

    def test_the_wordmark_image_matches_its_markup(self) -> None:
        size = _image_size(SHARED / "syndicate-wordmark.png")
        for name in ("shared/base.html", "shared/_standalone_app_header.html"):
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            match = re.search(
                r"syndicate-wordmark\.png'\) \}\}\" alt=\"\" width=\"(\d+)\" height=\"(\d+)\"", text
            )
            self.assertIsNotNone(match, name)
            self.assertEqual(size, (int(match.group(1)), int(match.group(2))), name)

    def test_the_wordmark_shows_only_where_the_row_has_room(self) -> None:
        """`[user decision, 2026-09-14]`: the silver lettering sits beside the
        logo only where the menu row has room. The mechanism is pure CSS and
        every part is load-bearing: a GROWING nav leaves the slot nothing; a
        slot with a basis takes width from the pills; without the zero-width
        first item and the clip, lettering that does not fit shows cut
        part-way instead of hiding; a row gap sits on both sides of the empty
        slot and takes width from the pills on a phone."""
        for sheet, slot, img, nav, row in (
            ("app.css", "syndicate-title-wordmark", "syndicate-title-wordmark__img",
             "syndicate-menu-row .syndicate-nav", "syndicate-menu-row"),
            ("standalone_shell.css", "standalone-app-header__wordmark",
             "standalone-app-header__wordmark-img", "standalone-app-header__nav",
             "standalone-app-header__inner"),
        ):
            text = (SHARED / sheet).read_text(encoding="utf-8")
            slot_rules = _css_rules(text, slot)
            self.assertRegex(slot_rules, r"flex:\s*1 1 0\b", sheet)
            self.assertRegex(slot_rules, r"overflow:\s*hidden", sheet)
            self.assertRegex(slot_rules, r"flex-wrap:\s*wrap", sheet)
            self.assertRegex(_css_rules(text, slot + "::before"), r"width:\s*0", sheet)
            self.assertRegex(_css_rules(text, img), r"flex:\s*0 0 auto", sheet)
            nav_rules = _css_rules(text, nav)
            self.assertRegex(nav_rules, r"flex:\s*0 1 auto", sheet)
            self.assertNotRegex(nav_rules, r"flex:\s*1\b", sheet)
            self.assertNotRegex(_css_rules(text, row), r"\bgap:\s*[1-9]", sheet)

    def test_the_logo_is_inline_on_the_menu_row(self) -> None:
        """`[user decision, 2026-09-14]`: the logo sits on the menu row and the
        pills wrap beside it. A `wrap` on the row itself is what drops the
        whole nav onto its own line under the logo."""
        base = (TEMPLATES / "shared/base.html").read_text(encoding="utf-8")
        self.assertIn('class="cards-title-row syndicate-menu-row"', base)
        for sheet, row, brand in (
            ("app.css", "syndicate-menu-row", "syndicate-menu-row .syndicate-title-lockup"),
            ("standalone_shell.css", "standalone-app-header__inner", "standalone-app-header__brand"),
        ):
            text = (SHARED / sheet).read_text(encoding="utf-8")
            rules = _css_rules(text, row)
            self.assertRegex(rules, r"flex-wrap:\s*nowrap", sheet)
            self.assertNotRegex(rules, r"flex-wrap:\s*wrap\b", sheet)
            # A shrinkable logo wrapper collapses under the logo on a phone and
            # the pills draw across it.
            self.assertRegex(_css_rules(text, brand), r"flex:\s*0 0 auto", sheet)

    def test_the_standalone_header_is_never_wider_than_the_page(self) -> None:
        """Its `width: min(1640px, 100%)` only fits when padding and border sit
        INSIDE it. Pages that include the header without a global border-box
        reset scrolled sideways by 34px (measured 2026-09-14)."""
        text = (SHARED / "standalone_shell.css").read_text(encoding="utf-8")
        rules = _css_rules(text, "standalone-app-header")
        self.assertRegex(rules, r"width:\s*min\(1640px,\s*100%\)")
        self.assertRegex(rules, r"box-sizing:\s*border-box")


class LogoIsNeverCroppedTests(unittest.TestCase):
    def test_hero_panels_contain_the_art_and_never_cover_it(self) -> None:
        for name, css_class in HERO_ART_CLASSES.items():
            rules = _css_rules((TEMPLATES / name).read_text(encoding="utf-8"), css_class)
            self.assertRegex(rules, r"object-fit:\s*contain", name)
            self.assertRegex(rules, r"aspect-ratio:\s*3\s*/\s*2", name)
            # Every rule for the class, media queries included. Comments are
            # stripped first: they explain WHY cover is wrong, in those words.
            self.assertNotRegex(rules, r"object-fit:\s*cover", name)
            self.assertNotRegex(rules, r"object-position:", name)

    def test_the_cover_check_can_fail(self) -> None:
        """Control: the check above reads real declarations, not prose."""
        sabotaged = ".x__art { object-fit: contain; }\n@media (max-width: 900px) { .x__art { object-fit: cover; } }"
        self.assertRegex(_css_rules(sabotaged, "x__art"), r"object-fit:\s*cover")
        commented = ".x__art { /* never cover */ object-fit: contain; }"
        self.assertNotRegex(_css_rules(commented, "x__art"), r"object-fit:\s*cover")

    def test_logo_assets_keep_the_logos_3_to_2_shape(self) -> None:
        self.assertEqual(_image_size(SHARED / "syndicate-brand-header.jpg"), (480, 320))
        self.assertEqual(_image_size(SHARED / "syndicate-brand-hero.jpg"), (960, 640))
        self.assertEqual(_image_size(SHARED / "syndicate-social.jpg"), (1200, 630))

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_non_3_to_2_slots_are_padded_not_cropped(self) -> None:
        """A square crop of the logo would put the green swoosh on the icon's
        top row; the fitted logo leaves a band of its own black ground there.
        Same for the card's left and right edges."""
        icon = Image.open(SHARED / "syndicate-icon-512.png").convert("RGB")
        band = 512 // 2 - round(512 * 2 / 3) // 2  # rows above the fitted logo
        for y in (0, band - 2):
            row = [icon.getpixel((x, y)) for x in range(0, 512, 4)]
            self.assertLessEqual(max(max(p) for p in row), 24, f"icon row {y} is not ground")

        card = Image.open(SHARED / "syndicate-social.jpg").convert("RGB")
        side = (1200 - round(630 * 3 / 2)) // 2  # columns beside the fitted logo
        for x in (0, side - 3):
            col = [card.getpixel((x, y)) for y in range(0, 630, 4)]
            self.assertLessEqual(max(max(p) for p in col), 24, f"card column {x} is not ground")


if __name__ == "__main__":
    unittest.main()
