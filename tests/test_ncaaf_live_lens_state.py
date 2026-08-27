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


# ---------------------------------------------------------------------------
# THE SERVED BUILDER. Everything above pins the helper and the card. None of it
# could catch the gap found on production 2026-08-27: the Live/Final/Pregame
# header split was added to `build_live_lens_page_context` -- the LEGACY
# FALLBACK -- while `/ncaaf/live-lens` routes to
# `build_smartsim_live_lens_page_context`. Production served
# `Games 51 | Season 2026 | Week 1 | Source ...` with no split at all.
#
# A module-level test ("does live_lens.py compute phases?") passes in that
# state. These drive the builder the ROUTE calls, which is the only thing that
# discriminates.
# ---------------------------------------------------------------------------

import pytest


def _cards_context(games, *, source_kind="smartsim_runtime"):
    return {
        "board_contract": {"source_kind": source_kind},
        "control_value": 1,
        "date": "2026 Week 1",
        "games": games,
        "source_path": "/data/ncaaf_source/smartsim2_projections_2026_wk1.csv",
        "available_weeks": [1],
    }


def _mixed_slate():
    return [
        _game(),
        _game(),
        _game(shared_game_state={"live": True, "period": 1, "clock": "10:00"}),
        _game(shared_game_state={"live": True, "period": 3, "clock": "4:05"}),
        _game(shared_game_state={"final": True}),
    ]


def _stats(context):
    return {s["label"]: s["value"] for s in context["header_stats"]}


def test_THE_SERVED_BUILDER_CARRIES_THE_PHASE_SPLIT(monkeypatch):
    """THE REGRESSION. This is the builder `/ncaaf/live-lens` actually calls."""
    monkeypatch.setattr(ll, "build_smartsim_cards_page_context", lambda w: _cards_context(_mixed_slate()))
    stats = _stats(ll.build_smartsim_live_lens_page_context(1))
    assert stats["Live"] == "2"
    assert stats["Final"] == "1"
    assert stats["Pregame"] == "2"
    assert stats["Games"] == "5"


def test_the_split_sits_beside_games_not_after_source(monkeypatch):
    """Order is the point of a header: what is happening now reads before
    provenance. MLB leads Games | Live | Final | Pregame."""
    monkeypatch.setattr(ll, "build_smartsim_cards_page_context", lambda w: _cards_context(_mixed_slate()))
    labels = [s["label"] for s in ll.build_smartsim_live_lens_page_context(1)["header_stats"]]
    assert labels.index("Live") == labels.index("Games") + 1
    assert labels.index("Live") < labels.index("Source")


def test_the_counts_track_the_slate_they_are_given(monkeypatch):
    """A constant would satisfy the test above. Change the slate, change the
    numbers -- otherwise this pins a hardcoded string."""
    monkeypatch.setattr(
        ll, "build_smartsim_cards_page_context",
        lambda w: _cards_context([_game(shared_game_state={"final": True}) for _ in range(3)]),
    )
    stats = _stats(ll.build_smartsim_live_lens_page_context(1))
    assert (stats["Live"], stats["Final"], stats["Pregame"]) == ("0", "3", "0")


def test_an_all_pregame_slate_reads_zero_not_blank(monkeypatch):
    """Today's real state, 2 days out. "0" is a reading; "" is a broken stat."""
    monkeypatch.setattr(ll, "build_smartsim_cards_page_context", lambda w: _cards_context([_game(), _game()]))
    stats = _stats(ll.build_smartsim_live_lens_page_context(1))
    assert (stats["Live"], stats["Final"], stats["Pregame"]) == ("0", "0", "2")


def test_the_legacy_fallback_keeps_its_split_too(monkeypatch):
    """The fallback still serves when the runtime path is unavailable, so the
    split must not have MOVED from one builder to the other."""
    monkeypatch.setattr(ll, "build_cards_page_context", lambda w: _cards_context(_mixed_slate()))
    stats = _stats(ll.build_live_lens_page_context(1))
    assert (stats["Live"], stats["Final"], stats["Pregame"]) == ("2", "1", "2")


def test_a_non_runtime_board_still_falls_back(monkeypatch):
    """Guard the dispatch this whole gap turned on: a non-smartsim board must
    still reach the legacy builder, split and all."""
    monkeypatch.setattr(
        ll, "build_smartsim_cards_page_context",
        lambda w: _cards_context(_mixed_slate(), source_kind="artifact"),
    )
    monkeypatch.setattr(ll, "build_cards_page_context", lambda w: _cards_context(_mixed_slate()))
    context = ll.build_smartsim_live_lens_page_context(1)
    assert "Cards-backed lens" in str(context.get("warning_panel", {}).get("eyebrow", "")), "did not fall back"
    assert _stats(context)["Live"] == "2"
