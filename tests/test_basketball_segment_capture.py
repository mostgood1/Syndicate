"""`#343` — WNBA/NBA interval capture goes through the CENTRAL record.

This fetcher wrote every quote with a hardcoded `segment: "full"`, so basketball
had no interval capture in `book_quotes` at all -- measured on production
2026-08-11, wnba carried 395 rows and one segment while MLB carried four.

Live Q1-Q4/H1/H2 lines DID exist, from a separate Bovada scrape into
`period_lines_<date>.csv` consumed only by the live lens. The board, Layer 2 and
CLV never saw them. One record, one route.
"""

from __future__ import annotations

import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "_bb_seg", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fetch_basketball_oddsapi_props_local.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def test_wnba_interval_keys_map_to_their_own_segment():
    assert _MOD._segment_for_market("totals_q1", "wnba") == "q1"
    assert _MOD._canonical_market("totals_q1", "wnba") == "totals"
    assert _MOD._segment_for_market("h2h_h2", "wnba") == "h2"
    assert _MOD._segment_for_market("alternate_totals_q4", "wnba") == "q4"
    assert _MOD._canonical_market("alternate_totals_q4", "wnba") == "totals_alt"


def test_full_game_keys_still_read_full():
    assert _MOD._segment_for_market("totals", "wnba") == "full"
    assert _MOD._canonical_market("totals", "wnba") == "totals"


def test_player_props_pass_through_untouched():
    # Props are full-game by nature and keep their own market name.
    assert _MOD._segment_for_market("player_points", "wnba") == "full"
    assert _MOD._canonical_market("player_points", "wnba") == "player_points"


def test_an_unmapped_interval_key_keeps_its_raw_name():
    # NCAAB plays halves, so `totals_q1` is not in its vocabulary and is never
    # requested. If one arrived anyway it must NOT collapse into the full-game
    # `totals` row -- keeping the raw name means it lands as its own market
    # rather than silently merging a quarter price into a full-game line.
    assert _MOD._canonical_market("totals_q1", "ncaab") == "totals_q1"


def test_the_fetcher_asks_for_interval_markets():
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fetch_basketball_oddsapi_props_local.py").read_text(encoding="utf-8")
    # Requested via the shared vocabulary, not a second literal list.
    assert "segment_market_keys(league)" in src
    assert "full_game_market_keys()" in src
    # And intersected with what OddsAPI says the event offers, so a key that
    # does not exist for a fixture is never paid for.
    assert "discovered" in src
