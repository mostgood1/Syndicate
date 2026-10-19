"""The MLB betting-card page's static assets come from Syndicate (lane mlb-betting-card-assets-native).

syndicate/features/mlb/betting_card.py serves them from syndicate/static/mlb/betting_card/ (frozen from the vendored
app on 2026-10-16, served bytes verified equal on the fleet). syndicate/static/mlb/{cards.css,back_to_top.js} are
different files for other pages and are not what this page serves.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.mlb import betting_card as bc

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("cards.css", "season.css", "betting_card.js", "back_to_top.js")
NATIVE = ROOT / "syndicate" / "static" / "mlb" / "betting_card"
ACCESSORS = {"cards.css": bc.source_cards_css, "season.css": bc.source_season_css,
             "betting_card.js": bc.source_betting_card_js, "back_to_top.js": bc.source_back_to_top_js}


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def test_assets_are_served_from_syndicate():
    assert bc._web_static_dir() == NATIVE.resolve()
    for name in NAMES:
        assert (NATIVE / name).is_file(), name



@pytest.mark.parametrize("name", NAMES)
def test_every_accessor_serves_text(name):
    accessor = ACCESSORS[name]
    accessor.cache_clear()
    text = accessor()
    accessor.cache_clear()
    assert text and len(text) > 500, name
