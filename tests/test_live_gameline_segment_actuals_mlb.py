"""MLB segment actuals for the live game-line scorer (first1 / first3 / first5).

The shapes here are PRODUCTION shapes, read 2026-09-28 off the 09-27 slate:
first5 ledger rows carry `game_pk=None` and an odds `event_id`; the grid row
for that event carries the gamePk as `game.game_key`; the finals index is keyed
by `event_id` only. A test built on a tidier shape (a ledger row with a
`game_pk`) would pass while production answered nothing -- the first draft of
this module did exactly that, keying finals on digit keys that 09-27 does not
have.
"""

from __future__ import annotations

import pytest

from syndicate.features.mlb import live_gameline_segment_actuals as mod
from syndicate.features.mlb.live_gameline_segment_actuals import (
    MlbSegmentActuals,
    event_to_game_pk_from_grid,
    segment_pairs_from_linescore,
    segment_score_blocks,
)
from syndicate.features.shared.live_gameline_score import (
    build_final_scores_index,
    finals_from_scores,
    score_ledger_records,
)


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """The final-linescore cache is process-global on purpose (a final never
    changes); tests must not see each other's entries."""
    mod._FINAL_PAIRS.clear()
    mod._FETCH_FAILED_AT.clear()
    yield
    mod._FINAL_PAIRS.clear()
    mod._FETCH_FAILED_AT.clear()


def _linescore(innings):
    """StatsAPI `/linescore` shape: `innings[].{num, away.runs, home.runs}`."""
    out = []
    for num, (away, home) in enumerate(innings, start=1):
        entry = {"num": num, "away": {"runs": away}, "home": {}}
        if home is not None:
            entry["home"]["runs"] = home
        out.append(entry)
    return {"innings": out}


NINE = [(0, 1), (2, 0), (0, 0), (1, 0), (0, 2), (0, 0), (1, 0), (0, 0), (0, None)]


def test_pairs_sum_innings_one_through_n_as_away_home():
    pairs = segment_pairs_from_linescore(_linescore(NINE))
    assert pairs == {"first1": (0.0, 1.0), "first3": (2.0, 1.0), "first5": (3.0, 3.0)}


def test_a_feed_live_payload_reads_the_same_as_the_linescore_document():
    feed = {"liveData": {"linescore": _linescore(NINE)}}
    assert segment_pairs_from_linescore(feed) == segment_pairs_from_linescore(_linescore(NINE))


def test_a_rain_shortened_final_never_answers_a_segment_it_did_not_reach():
    """Four innings played: first5 is ABSENT, never the four-inning total."""
    pairs = segment_pairs_from_linescore(_linescore(NINE[:4]))
    assert "first5" not in pairs
    assert pairs["first3"] == (2.0, 1.0)


def test_a_missing_half_inning_is_a_hole_not_a_zero():
    innings = [(0, 1), (2, 0), (1, None), (0, 0), (0, 0)]
    pairs = segment_pairs_from_linescore(_linescore(innings))
    assert pairs == {"first1": (0.0, 1.0)}


def test_the_grid_maps_the_odds_event_to_game_key():
    grid = [
        {"event_id": "ev1", "game_pk": None, "segment": "first5",
         "game": {"game_key": "822679", "state": "final"}},
        {"event_id": "ev2", "game": {"game_key": "not-a-pk"}},
        {"event_id": "ev3", "game_pk": 823000, "game": {}},
    ]
    assert event_to_game_pk_from_grid(grid) == {"ev1": "822679", "ev3": "823000"}


def _lookup(fetch, finals=("822679",), events=None):
    return MlbSegmentActuals(event_to_game=events or {"ev1": "822679"},
                             final_game_pks=set(finals), fetch=fetch)


def test_only_final_games_are_answered_and_each_is_fetched_once():
    calls = []

    def fetch(pk):
        calls.append(pk)
        return _linescore(NINE)

    lookup = _lookup(fetch)
    assert lookup("ev1", "first5") == (3.0, 3.0)
    assert lookup("822679", "FIRST3") == (2.0, 1.0)          # gamePk key, any case
    assert lookup("ev1", "first1") == (0.0, 1.0)
    assert calls == ["822679"]
    # A fresh lookup (the next board build) reuses the process cache.
    assert _lookup(fetch)("ev1", "first5") == (3.0, 3.0)
    assert calls == ["822679"]

    live = _lookup(fetch, finals=())
    assert live("ev1", "first5") is None
    assert live.diagnostics["refused_by_reason"] == {"game_not_final": 1}


def test_refusals_are_counted_by_name():
    lookup = _lookup(lambda pk: _linescore(NINE[:4]))
    assert lookup("unknown-event", "first5") is None
    assert lookup("ev1", "first7") is None
    assert lookup("ev1", "first5") is None                   # rain-shortened
    assert lookup.diagnostics["refused_by_reason"] == {
        "no_game_pk_for_key": 1,
        "unsupported_segment": 1,
        "segment_incomplete_in_final_linescore": 1,
    }


def test_a_failed_fetch_is_not_retried_inside_the_window(monkeypatch):
    calls = []

    def fetch(pk):
        calls.append(pk)
        return None

    clock = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    lookup = _lookup(fetch)
    assert lookup("ev1", "first5") is None
    assert lookup("ev1", "first5") is None
    assert calls == ["822679"]
    assert lookup.diagnostics["fetch_failed"] == 1
    assert lookup.diagnostics["fetch_deferred_retry_window"] == 1
    clock[0] += mod._RETRY_AFTER_SECONDS + 1
    assert _lookup(fetch)("ev1", "first5") is None
    assert calls == ["822679", "822679"]


# ---------------------------------------------------------------------------
# segment_score_blocks -- the block the board build attaches
# ---------------------------------------------------------------------------

def _grid(event, pk, home, away):
    """The 09-27 grid shape: event at top level, gamePk only as `game_key`."""
    return {"event_id": event, "game_pk": None, "segment": "full", "market": "h2h",
            "game": {"game_key": pk, "state": "final",
                     "home_score": str(home), "away_score": str(away)}}


def _full_h2h(event, model, market, at="2026-09-27T20:00:00Z"):
    return {"game_pk": "822679", "event_id": event, "segment": "full", "market": "h2h",
            "model_home_win_prob": model, "market_fair_prob": market,
            "priceable": False, "quote_age_seconds": 30.0, "recorded_at": at}


def _f5_obs(event, model, market, market_key="h2h", at="2026-09-27T19:00:00Z"):
    """A first5 OBSERVATION row as the ledger writes it: no game_pk, no quote
    age, withheld, the probability rounded to 2dp."""
    return {"game_pk": None, "event_id": event, "segment": "first5", "market": market_key,
            "model_home_win_prob": model, "market_fair_prob": market, "line": None,
            "priceable": False, "withheld_reason": "segment_pricing_disabled",
            "recorded_at": at}


def test_first5_h2h_is_scored_ALONE_and_the_headline_does_not_move():
    grid = [_grid("ev1", "822679", home=6, away=4)]
    finals_diag = {}
    scores = build_final_scores_index(grid, sport="mlb", diagnostics=finals_diag)
    finals = finals_from_scores(scores)
    assert set(scores) == {"ev1"}                             # event-keyed only, as in production
    records = [
        _full_h2h("ev1", 0.70, 0.60),
        _f5_obs("ev1", 0.55, 0.52),
        _f5_obs("ev1", 0.48, 0.50, at="2026-09-27T19:30:00Z"),
        _f5_obs("ev1", 0.60, 0.50, market_key="totals"),     # carries no mean -> unmeasured
    ]
    headline_before = score_ledger_records(records, finals, final_scores=scores)

    # Home led 3-1 after five.
    lookup = MlbSegmentActuals(event_to_game={"ev1": "822679"}, final_game_pks={"822679"},
                               fetch=lambda pk: _linescore([(0, 1), (1, 0), (0, 2), (0, 0), (0, 0)]))
    blocks = segment_score_blocks(records, finals, scores, grid=grid, sport="mlb",
                                  segment_actuals=lookup)
    first5 = blocks["by_segment"]["first5"]
    assert first5["games_with_outcome"] == 1
    assert first5["all_records"]["model_paired"]["n"] == 2
    assert first5["all_records"]["market"]["n"] == 2
    assert first5["unmeasured"] == {"record_carries_no_model_point_forecast": 1}
    assert blocks["lookup"]["games_answered"] == 1

    # THE HEADLINE IS UNTOUCHED: full-game h2h only, n=1, segment rows still
    # reported unmeasured there exactly as before.
    headline_after = score_ledger_records(records, finals, final_scores=scores)
    assert headline_after == headline_before
    assert headline_after["all_records"]["model"]["n"] == 1
    assert headline_after["unmeasured"]["segment_actual_unavailable"] == 3


def test_the_default_reader_is_REACHED_through_the_grid_join(monkeypatch):
    """No lookup passed -- the board build's case. The finals index is keyed by
    event only, so the reader must find the game through `game.game_key`."""
    fetched = []

    def fake_fetch(pk):
        fetched.append(pk)
        return _linescore([(0, 1), (1, 0), (0, 2), (0, 0), (0, 0)])

    monkeypatch.setattr(mod, "fetch_linescore", fake_fetch)
    grid = [_grid("ev1", "822679", home=6, away=4)]
    scores = build_final_scores_index(grid, sport="mlb")
    finals = finals_from_scores(scores)
    blocks = segment_score_blocks([_f5_obs("ev1", 0.55, 0.52)], finals, scores,
                                  grid=grid, sport="mlb")
    assert fetched == ["822679"]
    assert blocks["by_segment"]["first5"]["all_records"]["market"]["n"] == 1
    assert blocks["lookup"]["final_games"] == 1


def test_a_level_first5_is_a_push_not_a_home_loss():
    lookup = MlbSegmentActuals(event_to_game={"ev1": "822679"}, final_game_pks={"822679"},
                               fetch=lambda pk: _linescore([(1, 1)] + [(0, 0)] * 4))
    grid = [_grid("ev1", "822679", home=6, away=4)]
    scores = build_final_scores_index(grid, sport="mlb")
    blocks = segment_score_blocks([_f5_obs("ev1", 0.55, 0.52)], finals_from_scores(scores),
                                  scores, grid=grid, sport="mlb", segment_actuals=lookup)
    first5 = blocks["by_segment"]["first5"]
    assert first5["unmeasured"] == {"segment_actual_level_for_h2h": 1}
    assert first5["all_records"]["market"]["n"] == 0


def test_no_block_for_other_sports_or_a_ledger_without_segments():
    assert segment_score_blocks([_f5_obs("ev1", 0.5, 0.5)], {}, {}, sport="nfl") is None
    assert segment_score_blocks([_full_h2h("ev1", 0.5, 0.5)], {}, {}, sport="mlb") is None


def test_it_never_raises_into_the_board_build():
    def boom(_key, _seg):
        raise RuntimeError("reader exploded")

    out = segment_score_blocks([_f5_obs("ev1", 0.5, 0.5)], {}, {}, sport="mlb",
                               segment_actuals=boom)
    assert out == {"error": "RuntimeError: reader exploded"}


def test_REACHABILITY_the_board_block_carries_segments_and_the_headline_is_unchanged(monkeypatch):
    """Through `book_grid_artifact.score_block_for_grid` -- the function the
    board build calls. `off != on`: the headline keys are identical to a build
    that never computed segments, and `segments` is present and scored."""
    import syndicate.features.shared.live_gameline_ledger as ledger
    from syndicate.features.shared.book_grid_artifact import score_block_for_grid

    records = [_full_h2h("ev1", 0.70, 0.60), _f5_obs("ev1", 0.55, 0.52)]
    monkeypatch.setattr(ledger, "read_records", lambda _path: records)
    monkeypatch.setattr(mod, "fetch_linescore",
                        lambda pk: _linescore([(0, 1), (1, 0), (0, 2), (0, 0), (0, 0)]))
    grid = [_grid("ev1", "822679", home=6, away=4)]
    block = score_block_for_grid(grid, sport="mlb", date_str="2026-09-27")

    seg = block["segments"]
    assert seg["lookup"]["games_answered"] == 1
    assert seg["by_segment"]["first5"]["all_records"]["market"]["n"] == 1
    # The headline is the full-game series, untouched.
    assert block["all_records"]["model"]["n"] == 1
    assert block["segment_actuals_supplied"] is False
    assert block["unmeasured"] == {"segment_actual_unavailable": 1}


def test_the_board_block_for_another_sport_carries_no_segments(monkeypatch):
    import syndicate.features.shared.live_gameline_ledger as ledger
    from syndicate.features.shared.book_grid_artifact import score_block_for_grid

    monkeypatch.setattr(ledger, "read_records", lambda _path: [_f5_obs("ev1", 0.5, 0.5)])
    block = score_block_for_grid([_grid("ev1", "1", home=2, away=1)], sport="nfl",
                                 date_str="2026-09-27")
    assert "segments" not in block
