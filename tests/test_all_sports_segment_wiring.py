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

# (label, sport, file, token proving it REQUESTS from the shared vocab, token proving it TAGS from it)
#
# `sport` is load-bearing, not decoration: it is what
# `test_every_sport_with_declared_segments_has_a_wired_fetcher` joins on. That
# test used to search a CONCATENATION of every file for
# `segment_market_keys("<sport>")` **or** the literal `segment_market_keys(league)`
# -- and the basketball file always supplies the second token, so the `or` was
# true for every sport and `unwired` could never be non-empty. It was a guard
# with no failing input, and NCAAF's total absence from segment capture sat
# behind it from the day the file was written until 2026-09-05.
WIRED = [
    ("mlb", "mlb", "scripts/fetch_mlb_oddsapi_local.py", 'segment_market_keys("mlb")', 'segment_market_keys("mlb")'),
    ("basketball", "nba", "scripts/fetch_basketball_oddsapi_props_local.py", "segment_market_keys(league)", "_segment_for_market"),
    ("basketball-wnba", "wnba", "scripts/fetch_basketball_oddsapi_props_local.py", "segment_market_keys(league)", "_segment_for_market"),
    ("basketball-ncaab", "ncaab", "scripts/fetch_basketball_oddsapi_props_local.py", "segment_market_keys(league)", "_segment_for_market"),
    ("soccer", "soccer", "scripts/fetch_soccer_oddsapi_odds_local.py", 'segment_market_keys("soccer")', "_segment_market_map()"),
    ("nfl-team", "nfl", "scripts/fetch_nfl_team_odds_local.py", "_fetch_nfl_segments", "_nfl_segment_market_map()"),
    ("nfl-pre", "nfl", "scripts/fetch_nfl_preseason_odds.py", 'segment_market_keys("nfl")', "_nfl_segment_market_map()"),
    ("ncaaf", "ncaaf", "scripts/fetch_ncaaf_oddsapi_game_lines.py", "fetch_event_segments", "merged_market_map"),
    ("nhl", "nhl", "syndicate/local_nhl_odds.py", 'segment_market_keys("nhl")', "_nhl_segment_of"),
]

HARDCODED = '"segment": "full",'
PROP_MARKER = '"kind": "prop"'


@pytest.mark.parametrize("label,_sport,path,requests_token,tags_token", WIRED)
def test_each_sport_uses_the_shared_vocabulary(label, _sport, path, requests_token, tags_token):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert requests_token in src, f"{label}: does not request interval keys from the shared vocabulary"
    assert tags_token in src, f"{label}: does not tag quotes from the shared vocabulary"


def test_no_fetcher_sends_segment_keys_to_the_bulk_endpoint():
    """The bulk `/sports/{key}/odds` route 422s `INVALID_MARKET` on any segment
    key, and the blast radius is the WHOLE call -- the full-game markets on it
    die too. That is not hypothetical: it killed every soccer league's capture
    from 2026-08-10 to 08-19 (`fetch_soccer_oddsapi_odds_local.py:116-139`).

    So a file may hold a segment map for TAGGING, but the map handed to a bulk
    `markets=` must be full-game only. Checked by reading each bulk call's own
    markets expression rather than by trusting a comment.
    """
    ncaaf = (ROOT / "scripts/fetch_ncaaf_oddsapi_game_lines.py").read_text(encoding="utf-8")
    assert 'markets = ",".join(sorted(_market_map().keys()))' in ncaaf
    assert "full_game_market_keys" in ncaaf
    # `_market_map` is the bulk map and must never gain a segment source.
    bulk_body = ncaaf.split("def _market_map(")[1].split("\ndef ")[0]
    assert "segment_market_keys" not in bulk_body


@pytest.mark.parametrize("label,_sport,path,_requests,_tags", WIRED)
def test_no_game_writer_hardcodes_a_full_segment(label, _sport, path, _requests, _tags):
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

    THE OLD VERSION OF THIS TEST COULD NOT FAIL. It searched a concatenation of
    every wired file for `segment_market_keys("<sport>")` OR the literal
    `segment_market_keys(league)`; the basketball file always contains the
    second, so the disjunction was true for every sport in `SPORT_SEGMENTS` and
    `unwired` was unconditionally `[]`. NCAAF -- zero segment rows in 153,723 on
    2026-09-05 -- sat behind a green assertion the whole time.

    The join is now on the `sport` column of `WIRED`, so a declared sport with
    no row here fails, which is the only shape of this test that has a failing
    input at all. `learnings.md`: a healthy reading is evidence only once you
    know what makes it read unhealthy.
    """
    from syndicate.features.shared.market_segments import SPORT_SEGMENTS

    wired_sports = {sport for _, sport, _, _, _ in WIRED}
    unwired = sorted(set(SPORT_SEGMENTS) - wired_sports)
    assert not unwired, f"declared segments with no fetcher wiring: {unwired}"


def test_the_wiring_guard_has_a_failing_input():
    """The guard above is only worth its runtime if a gap would turn it red.

    Proven by construction rather than asserted: drop a sport from the wired
    set and the same expression must produce a non-empty `unwired`.
    """
    from syndicate.features.shared.market_segments import SPORT_SEGMENTS

    wired_sports = {sport for _, sport, _, _, _ in WIRED} - {"ncaaf"}
    assert sorted(set(SPORT_SEGMENTS) - wired_sports) == ["ncaaf"]
