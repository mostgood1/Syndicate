"""`_live_props_from_game_detail` had FOUR silent `return []` paths.

On a LIVE game this function supplies the card row's props, so an empty result
empties the whole live prop tier without a word.

Measured on live-odds-worker 2026-09-23 18:48:14Z, the first tick after
`e7899507` put `_carry_live_probability` on the live path: 8 `LIVE_PROB_CARRIED`
lines, EVERY ONE a Scheduled or Pre-Game game with `source_rows=0` (correct --
a pregame game has no live rows), and the only two games `In Progress`
(824223, 824785, both priced by `LIVE_MC_PRICED` in that same tick) absent
entirely. The carry is guarded `if carried_props:`, so no line means the card
row had no `liveProps` -- which on a live game means this function returned []
and said nothing about which exit it took.
"""

from __future__ import annotations

import pytest

import syndicate.features.mlb.live_lens as live_lens


def test_no_game_pk_names_itself(capsys):
    assert live_lens._live_props_from_game_detail("2026-09-23", 0) == []
    out = capsys.readouterr().out
    assert "GAME_DETAIL_PROPS_EMPTY" in out and "reason=no_game_pk" in out


def test_a_request_path_refusal_names_itself(monkeypatch, capsys):
    # The prime suspect: a REQUEST-PATH guard firing on a worker tick would
    # empty every live game, silently, forever.
    import syndicate.features.shared.request_path_guard as guard

    def refuse(_label):
        raise RuntimeError("compute in request path")

    monkeypatch.setattr(guard, "refuse_if_compute_in_request_path", refuse)
    assert live_lens._live_props_from_game_detail("2026-09-23", 824785) == []
    out = capsys.readouterr().out
    assert "reason=request_path_refused" in out
    assert "gamePk=824785" in out
    assert "RuntimeError" in out


def test_a_producer_raise_names_itself(monkeypatch, capsys):
    import syndicate.features.mlb.cards as cards

    def boom(_date, _pk):
        raise ValueError("producer exploded")

    monkeypatch.setattr(cards, "live_prop_rows_for_game", boom)
    assert live_lens._live_props_from_game_detail("2026-09-23", 824785) == []
    out = capsys.readouterr().out
    assert "reason=producer_raised" in out
    assert "ValueError" in out


def test_every_refusal_reason_is_a_DIFFERENT_string(monkeypatch, capsys):
    """Four exits, four owners. One bare `return []` covered all of them."""
    seen = set()

    live_lens._live_props_from_game_detail("2026-09-23", 0)
    seen.add(capsys.readouterr().out.strip())

    import syndicate.features.shared.request_path_guard as guard
    monkeypatch.setattr(guard, "refuse_if_compute_in_request_path",
                        lambda _l: (_ for _ in ()).throw(RuntimeError("x")))
    live_lens._live_props_from_game_detail("2026-09-23", 824785)
    seen.add(capsys.readouterr().out.strip())

    monkeypatch.setattr(guard, "refuse_if_compute_in_request_path", lambda _l: None)
    import syndicate.features.mlb.cards as cards
    monkeypatch.setattr(cards, "live_prop_rows_for_game",
                        lambda _d, _p: (_ for _ in ()).throw(ValueError("y")))
    live_lens._live_props_from_game_detail("2026-09-23", 824785)
    seen.add(capsys.readouterr().out.strip())

    assert len(seen) == 3, seen


def test_the_succeeding_path_reports_raw_and_normalised(monkeypatch, capsys):
    # "the producer returned nothing" is a FIFTH state and must not be
    # indistinguishable from the four refusals.
    import syndicate.features.shared.request_path_guard as guard
    import syndicate.features.mlb.cards as cards
    monkeypatch.setattr(guard, "refuse_if_compute_in_request_path", lambda _l: None)
    monkeypatch.setattr(cards, "live_prop_rows_for_game", lambda _d, _p: [])

    assert live_lens._live_props_from_game_detail("2026-09-23", 824785) == []
    out = capsys.readouterr().out
    assert "GAME_DETAIL_PROPS " in out
    assert "raw=0" in out and "normalised=0" in out
    assert "GAME_DETAIL_PROPS_EMPTY" not in out


def test_a_real_row_set_is_reported_and_returned(monkeypatch, capsys):
    import syndicate.features.shared.request_path_guard as guard
    import syndicate.features.mlb.cards as cards
    monkeypatch.setattr(guard, "refuse_if_compute_in_request_path", lambda _l: None)
    monkeypatch.setattr(cards, "live_prop_rows_for_game", lambda _d, _p: [
        {"player_name": "Bo Bichette", "market": "batter_hits", "prop": "batter_hits",
         "selection": "Over", "threshold": 0.5, "live_projection": 0.8},
    ])
    rows = live_lens._live_props_from_game_detail("2026-09-23", 824785)
    assert len(rows) == 1
    out = capsys.readouterr().out
    assert "raw=1" in out and "normalised=1" in out
