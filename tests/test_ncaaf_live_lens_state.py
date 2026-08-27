"""The NCAAF live lens must know whether a game is live.

MEASURED ON PRODUCTION 2026-08-27, before this change. The lens rendered 51
cards and not one of them said anything about game state:

    every card's eyebrow  "Enhanced Totals Engine"   <- a constant, x51
    header stats          Games | Season | Week | Source
    MLB's header          Games 7 | Live 0 | Final 0 | Pregame 7 | Props 41

`shared_game_state` carries `live`, `final`, `period` and `clock` on every
game, and the lens read none of them. `polling.js` was already loaded and the
live-lens contract was already in the DOM -- the refresh machinery worked and
had nothing state-dependent to refresh.

NO LIVE SCORE, and that is a boundary not an omission:
`publication_adapter._shared_game_state` carries no score field, and the only
`score` in the contract is the PROJECTED one. Rendering a projection beside a
live clock would read as the current score.

These tests run pregame, which is the only state available before Saturday --
so they drive `_game_state_label` directly rather than waiting for a real
in-progress game.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import live_lens as ll


def _game(**overrides):
    game = {
        "away": {"abbr": "NC"},
        "home": {"abbr": "TCU"},
        "ncaaf_card": {"scoreboard": {"kickoff_label": "Sat Aug 29, 11:00 AM CDT"}},
    }
    game.update(overrides)
    return game


def test_pregame_shows_the_kickoff_not_a_constant_label():
    """The measured failure: every card said "Enhanced Totals Engine"."""
    eyebrow, phase = ll._game_state_label(_game())
    assert phase == "pregame"
    assert eyebrow == "Sat Aug 29, 11:00 AM CDT"


def test_a_live_game_shows_period_and_clock():
    eyebrow, phase = ll._game_state_label(
        _game(shared_game_state={"live": True, "final": False, "period": 2, "clock": "7:31"})
    )
    assert phase == "live"
    assert "Q2" in eyebrow and "7:31" in eyebrow


def test_a_live_game_without_a_clock_falls_back_to_its_status():
    """Never render an empty eyebrow just because the clock has not arrived."""
    eyebrow, phase = ll._game_state_label(
        _game(shared_game_state={"live": True, "period": None, "clock": "", "status": "In Progress"})
    )
    assert phase == "live"
    assert eyebrow == "In Progress"


def test_the_shared_is_live_flag_is_honoured_too():
    """Two producers set liveness; reading only one is how a live board stays pregame."""
    eyebrow, phase = ll._game_state_label(
        _game(shared_is_live=True, shared_game_state={"period": 4, "clock": "0:42"})
    )
    assert phase == "live"
    assert "Q4" in eyebrow


def test_a_final_game_says_final():
    eyebrow, phase = ll._game_state_label(_game(shared_game_state={"live": False, "final": True}))
    assert phase == "final"
    assert eyebrow == "Final"


def test_live_beats_final_when_both_are_set():
    """A contradictory payload must not report a live game as over."""
    _, phase = ll._game_state_label(
        _game(shared_game_state={"live": True, "final": True, "period": 3, "clock": "2:00"})
    )
    assert phase == "live"


def test_phase_counts_split_the_slate_the_way_mlb_does():
    games = [
        _game(),
        _game(shared_game_state={"live": True, "period": 1, "clock": "10:00"}),
        _game(shared_game_state={"live": True, "period": 4, "clock": "1:12"}),
        _game(shared_game_state={"final": True}),
    ]
    assert ll._phase_counts(games) == {"live": 2, "final": 1, "pregame": 1}


def test_phase_counts_tolerate_junk_entries():
    assert ll._phase_counts([None, "x", 3]) == {"live": 0, "final": 0, "pregame": 0}


def test_the_card_eyebrow_uses_the_game_state():
    """Reachability: the helper must actually reach the rendered card."""
    card = ll._runtime_rank_card(
        _game(shared_game_state={"live": True, "period": 2, "clock": "7:31"})
    )
    assert "Q2" in card["eyebrow"], f"card eyebrow is {card['eyebrow']!r}, not the live state"


def test_no_live_score_is_invented():
    """The contract has no live score. A projection must not be shown as one."""
    card = ll._runtime_rank_card(
        _game(shared_game_state={"live": True, "period": 2, "clock": "7:31"})
    )
    blob = " ".join(str(v) for v in card.values())
    assert "Score:" not in blob
