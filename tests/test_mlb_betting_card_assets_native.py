"""The MLB betting-card page's static assets come from Syndicate, not the vendored app (lane mlb-betting-card-assets-native).

syndicate/features/mlb/betting_card.py used to read vendor/mlb_bettingv2/tools/web/static/<name> on every request. It
now reads byte-identical copies in syndicate/static/mlb/betting_card/. This pins: the copies equal the vendored files
(normalised line endings), every accessor -- including betting_card.js's URL rewrites -- returns text, and that text is
what the vendored files would have produced. syndicate/static/mlb/{cards.css,back_to_top.js} are different files for
other pages and are not what this page serves.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.mlb import betting_card as bc

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("cards.css", "season.css", "betting_card.js", "back_to_top.js")
VENDORED = ROOT / "vendor" / "mlb_bettingv2" / "tools" / "web" / "static"
NATIVE = ROOT / "syndicate" / "static" / "mlb" / "betting_card"
ACCESSORS = {"cards.css": bc.source_cards_css, "season.css": bc.source_season_css,
             "betting_card.js": bc.source_betting_card_js, "back_to_top.js": bc.source_back_to_top_js}


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def test_assets_are_served_from_syndicate():
    assert bc._web_static_dir() == NATIVE.resolve()
    for name in NAMES:
        assert (NATIVE / name).is_file(), name


@pytest.mark.skipif(not VENDORED.exists(), reason="vendor tree absent")
@pytest.mark.parametrize("name", NAMES)
def test_copies_are_byte_identical_to_the_vendored_files(name):
    assert _norm((NATIVE / name).read_bytes()) == _norm((VENDORED / name).read_bytes())


@pytest.mark.skipif(not VENDORED.exists(), reason="vendor tree absent")
@pytest.mark.parametrize("name", NAMES)
def test_every_accessor_serves_what_the_vendored_file_produced(name, monkeypatch):
    accessor = ACCESSORS[name]
    accessor.cache_clear()
    native = accessor()
    accessor.cache_clear()
    monkeypatch.setattr(bc, "_web_static_dir", lambda: VENDORED.resolve())
    vendored = accessor()
    accessor.cache_clear()
    assert native is not None and vendored is not None
    assert native.replace("\r\n", "\n") == vendored.replace("\r\n", "\n")
