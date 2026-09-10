"""A past-date MLB game the feed calls Final must be SERVED Final.

`_merge_live_lens_row_into_game` used to copy the per-date live-lens report's
`status` over the feed-derived one unconditionally. That report is last written
when the live-lens loop rolls to the next date at midnight Central, so a game
still in progress at that moment keeps a frozen `Live` row -- and the merge
served it forever.

Measured on production 2026-09-10 (lane `mlb-final-state-mapping`): web's
`live_lens_report_2026_09_03.json` (generatedAt 23:59:10 CT, never rewritten)
holds 823095 and 823907 at `Live / In Progress`; both ended 00:05/00:09 CT;
`/mlb/api/cards?date=2026-09-03` and `/api/board/game-chips` still served them
`live`. Census 2026-09-01..09-09: 9 games on 7 of 9 dates.

These pin the case through the same writers production uses, in order:
`_source_status` over a feed payload (the FIRST writer of `game["status"]`, the
one the 09-04 trace followed), then the merge (the LATER writer it missed),
then the board chip's `_game_flags`, which is where `state=live` was published.
"""
from __future__ import annotations

import pytest

from syndicate.features.mlb import cards
from syndicate.features.shared.game_chip_scoreboard import _game_flags


def _feed(abstract, detailed):
    return {"gameData": {"status": {"abstractGameState": abstract, "detailedState": detailed}}}


def _frozen_live_row():
    """The 823095 row as web holds it: in progress, with the other lens fields."""
    return {
        "gamePk": 823095,
        "status": {"abstract": "Live", "detailed": "In Progress"},
        "markets": {"moneyline": {"home": -120}},
        "gameLens": [{"key": "live", "label": "Bot 9"}],
    }


def _game_from_feed(abstract, detailed):
    return {"gamePk": 823095, "status": cards._source_status(_feed(abstract, detailed))}


def test_a_final_feed_status_survives_a_frozen_live_lens_row():
    game = _game_from_feed("Final", "Final")
    assert cards._cards_status_is_final(game["status"]), "fixture: the feed writer must say Final"
    merged = cards._merge_live_lens_row_into_game(game, _frozen_live_row())
    assert merged["status"] == {"abstract": "Final", "detailed": "Final"}, (
        "the frozen lens row overwrote the feed's Final -- the 09-03 defect"
    )


def test_the_board_chip_reads_final_not_live():
    """Where the symptom was published: the chip's live/final decision."""
    merged = cards._merge_live_lens_row_into_game(_game_from_feed("Final", "Final"), _frozen_live_row())
    is_live, is_final = _game_flags(merged)
    assert (is_live, is_final) == (False, True)


@pytest.mark.parametrize("detailed", ["Final", "Game Over", "Completed Early"])
def test_every_final_spelling_is_protected(detailed):
    merged = cards._merge_live_lens_row_into_game(_game_from_feed("Final", detailed), _frozen_live_row())
    assert merged["status"]["detailed"] == detailed


def test_the_lens_still_advances_a_game_that_is_not_final():
    """Only one direction is held back. For a pregame or live game the lens is
    the fresher source and must still win."""
    pregame = cards._merge_live_lens_row_into_game(_game_from_feed("Preview", "Scheduled"), _frozen_live_row())
    assert pregame["status"] == {"abstract": "Live", "detailed": "In Progress"}

    final_row = {**_frozen_live_row(), "status": {"abstract": "Final", "detailed": "Final"}}
    live = cards._merge_live_lens_row_into_game(_game_from_feed("Live", "In Progress"), final_row)
    assert live["status"] == {"abstract": "Final", "detailed": "Final"}


def test_a_final_lens_row_still_replaces_a_final_status():
    final_row = {**_frozen_live_row(), "status": {"abstract": "Final", "detailed": "Game Over"}}
    merged = cards._merge_live_lens_row_into_game(_game_from_feed("Final", "Final"), final_row)
    assert merged["status"] == {"abstract": "Final", "detailed": "Game Over"}


def test_only_status_is_held_back_for_a_final_game():
    merged = cards._merge_live_lens_row_into_game(_game_from_feed("Final", "Final"), _frozen_live_row())
    assert merged["markets"] == {"moneyline": {"home": -120}}
    assert merged["gameLens"] == [{"key": "live", "label": "Bot 9"}]
