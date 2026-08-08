"""NFL's board was date-blind: the same game for every date.

MEASURED on production 2026-08-07: `/api/board/game-chips?sports=nfl` returned
the SAME game_key 401873271 (CAR @ ARI) for 08-05, 08-06, 08-07, 08-08 AND
08-12. Two defects stacked:

1. `_HomeSportDataProviderBase.resolve_context` packs the requested date into
   `context_label` and leaves `week=None`. `_NFLDataProvider.games()` is
   WEEK-KEYED and never read the date at all.
2. With `week=None` it takes the preseason branch, where
   `preseason_target_week` returns `min(weeks whose status != "final")`. Nothing
   rewrites that status column -- `fetch_nfl_preseason_schedule.py` is a manual
   CLI wired into no pipeline -- so it returns 1 forever, and preseason week 1
   contains exactly one game.

Consequence beyond a wrong chip: with no date-correct schedule, NFL
`game.state` never populates, which silently disables `opportunity_gate`'s
dead-market rule and blocks the S2 cadence tiers (they key on game state).
"""

from __future__ import annotations

import pytest

from syndicate.blueprints.home import _nfl_games_on_requested_date


def _games():
    return [
        {"gamePk": "401873271", "label": "CAR@ARI"},   # preseason wk1, played 08-06
        {"gamePk": "401873272", "label": "DET@CIN"},   # preseason wk2, 08-13
    ]


def _fake_events(monkeypatch, ids):
    class _E:
        def __init__(self, event_id):
            self.event_id = event_id

    monkeypatch.setattr(
        "syndicate.features.shared.schedule_adapter.fetch_schedule_for_date",
        lambda sport, date_str, **_k: [_E(i) for i in ids],
    )


def test_only_the_games_on_that_date_survive(monkeypatch):
    _fake_events(monkeypatch, ["401873271"])
    out = _nfl_games_on_requested_date(_games(), "2026-08-06")
    assert [g["label"] for g in out] == ["CAR@ARI"]


def test_a_different_date_yields_a_different_game(monkeypatch):
    """The actual defect: every date returned the same game."""
    _fake_events(monkeypatch, ["401873272"])
    out = _nfl_games_on_requested_date(_games(), "2026-08-13")
    assert [g["label"] for g in out] == ["DET@CIN"]


def test_a_date_with_no_nfl_games_returns_empty(monkeypatch):
    """08-07 genuinely had no NFL games. Returning yesterday's is the bug."""
    _fake_events(monkeypatch, [])
    assert _nfl_games_on_requested_date(_games(), "2026-08-07") == []


def test_a_schedule_failure_leaves_the_board_ALONE(monkeypatch):
    """Fails closed. This is a display filter -- a network blip must not blank
    a board that has real cards."""
    def _boom(*_a, **_k):
        raise RuntimeError("espn unreachable")

    monkeypatch.setattr("syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", _boom)
    out = _nfl_games_on_requested_date(_games(), "2026-08-13")
    assert len(out) == 2


def test_an_id_space_mismatch_does_not_empty_the_board(monkeypatch):
    """If no card matches any event id the two sources are keyed differently.
    Filtering to nothing would replace a wrong board with an empty one -- and
    id-space mismatch is real here: the board keys on OddsAPI hex ids while the
    schedule keys on ESPN numerics."""
    _fake_events(monkeypatch, ["999999999"])
    out = _nfl_games_on_requested_date(_games(), "2026-08-13")
    assert len(out) == 2


@pytest.mark.parametrize("date_value", ["", None, "   "])
def test_no_date_means_no_filtering(monkeypatch, date_value):
    _fake_events(monkeypatch, ["401873271"])
    assert len(_nfl_games_on_requested_date(_games(), date_value)) == 2


def test_empty_input_is_a_no_op(monkeypatch):
    _fake_events(monkeypatch, ["401873271"])
    assert _nfl_games_on_requested_date([], "2026-08-06") == []
