"""`#343` — every sport requests and tags intervals from ONE vocabulary.

Before this, MLB had a bespoke literal map and every other sport wrote a
hardcoded `segment: "full"`. Measured on production 2026-08-11: mlb carried four
segments, wnba/soccer/nfl carried one.

These assert the WIRING rather than the output, deliberately: the defect is that
a fetcher never asks for the keys, and a behavioural test would need a live slate
for each sport to notice that.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (label, file, token proving it REQUESTS from the shared vocab, token proving it TAGS from it)
WIRED = [
    ("mlb", "scripts/fetch_mlb_oddsapi_local.py", 'segment_market_keys("mlb")', 'segment_market_keys("mlb")'),
    ("basketball", "scripts/fetch_basketball_oddsapi_props_local.py", "segment_market_keys(league)", "_segment_for_market"),
    ("soccer", "scripts/fetch_soccer_oddsapi_odds_local.py", 'segment_market_keys("soccer")', "_segment_market_map()"),
    ("nfl-team", "scripts/fetch_nfl_team_odds_local.py", 'segment_market_keys("nfl")', "_nfl_segment_market_map()"),
    ("nfl-pre", "scripts/fetch_nfl_preseason_odds.py", 'segment_market_keys("nfl")', "_nfl_segment_market_map()"),
    ("nhl", "syndicate/local_nhl_odds.py", 'segment_market_keys("nhl")', "_nhl_segment_of"),
]

HARDCODED = '"segment": "full",'
PROP_MARKER = '"kind": "prop"'


@pytest.mark.parametrize("label,path,requests_token,tags_token", WIRED)
def test_each_sport_uses_the_shared_vocabulary(label, path, requests_token, tags_token):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert requests_token in src, f"{label}: does not request interval keys from the shared vocabulary"
    assert tags_token in src, f"{label}: does not tag quotes from the shared vocabulary"


@pytest.mark.parametrize("label,path,_requests,_tags", WIRED)
def test_no_game_writer_hardcodes_a_full_segment(label, path, _requests, _tags):
    """A hardcoded `full` on a GAME row is the defect; on a PROP row it is right.

    Player props are full-game by nature -- there is no first-quarter "player
    points over 12.5" in this feed -- so MLB's prop writer hardcoding `full` is
    correct and must not be flagged. What must never happen is a GAME-line
    writer doing it, because then every interval key the fetcher requests is
    stored as a full-game line.

    Scoped by the row block each occurrence sits in rather than by exempting a
    file, so a game writer that regresses is still caught inside a file that
    also happens to write props.
    """
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if HARDCODED not in line:
            continue
        block = "\n".join(lines[max(0, idx - 14):idx])
        assert PROP_MARKER in block, (
            f"{label}: line {idx + 1} hardcodes segment=full on a row not declared a "
            "prop, so interval keys would be stored as full-game lines"
        )


def test_mlb_keeps_its_literal_only_as_a_parity_fixture():
    # The bespoke map proved the shared one reproduces working capture 18/18 and
    # caught 3 missing h2h_3_way keys. Kept for that test; must not be what runs.
    src = (ROOT / "scripts/fetch_mlb_oddsapi_local.py").read_text(encoding="utf-8")
    assert "_legacy_segment_market_map" in src
    assert "segment_market_map = {**full_game_market_keys()" in src


def test_every_sport_with_declared_segments_has_a_wired_fetcher():
    """The vocabulary and the fetchers must not drift apart.

    A sport can legitimately have no fetcher here (NCAAB game lines run through
    the basketball path), but a sport with declared segments and NO wiring
    anywhere is the gap this whole item exists to close.
    """
    from syndicate.features.shared.market_segments import SPORT_SEGMENTS

    wired_files = "\n".join((ROOT / path).read_text(encoding="utf-8") for _, path, _, _ in WIRED)
    unwired = [
        sport
        for sport in SPORT_SEGMENTS
        if f'segment_market_keys("{sport}")' not in wired_files
        and "segment_market_keys(league)" not in wired_files
    ]
    assert not unwired, f"declared segments with no fetcher wiring: {unwired}"
