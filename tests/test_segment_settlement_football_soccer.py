"""NFL, NCAAF and soccer resolvers GRADE segment orders off per-period actuals.

THE PROPERTY `test_segment_settlement_guard.py` ASSERTS IS KEPT, AND MOVED.
That file pins that a segment order is never graded off the whole-game score.
These three resolvers no longer refuse every segment; they grade `q1..q4`,
`h1`, `h2` (football) and `h1`, `h2` (soccer) off the linescores their pollers
now persist -- and when a record has NO linescores they refuse BY NAME,
`segment_actual_unavailable:<seg>`, never falling back to `home + away`. The
pair `test_..._grades_WITH_linescores` / `test_..._refuses_WITHOUT` is the
mutation check: same order, one field removed, opposite outcome.

Every full-game case is still here too, for the same reason the guard file
gives: every order ever written carries no `segment` key at all, and a false
positive here would refuse the entire book.

NCAAF's team join is stubbed. `resolve_ncaaf_team_id` reads a 684-team CSV
under `data/`, which a session worktree does not carry; the join itself is
pinned by `test_bet_status_ncaaf.py` and is not what these tests are about.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import bet_status_ncaaf, bet_status_nfl
from syndicate.features.shared import bet_status_soccer as soccer
from syndicate.features.shared.bet_status import (
    STATUS_LIVE_TIED,
    STATUS_LOST,
    STATUS_NOT_STARTED,
    STATUS_WON,
    resolve_bet_status,
)
from syndicate.features.shared.bet_status_ncaaf import ncaaf_status_resolver
from syndicate.features.shared.bet_status_nfl import nfl_status_resolver

HOME_LS = [7, 10, 3, 4]     # 24
AWAY_LS = [0, 7, 7, 3]      # 17


def _graded(order, view):
    """The verdict `paper_settlement` would reach from this resolver output."""
    return resolve_bet_status(
        market=order.get("market"),
        side=view.get("side", order.get("side")),
        line=view.get("line", order.get("line")),
        current_value=view.get("current_value"),
        is_final=bool(view.get("is_final")),
        started=bool(view.get("started", True)),
    )


# ===========================================================================
# NFL
# ===========================================================================


def _nfl_order(**over):
    row = {"sport": "nfl", "market": "h2h", "side": "home", "line": None,
           "home_team": "San Francisco 49ers", "away_team": "Seattle Seahawks"}
    row.update(over)
    return row


def _nfl_game(**over):
    row = {"event_id": "401671800", "home_team": "San Francisco 49ers", "away_team": "Seattle Seahawks",
           "home_abbr": "SF", "away_abbr": "SEA", "home_score": 24, "away_score": 17,
           "home_linescores": list(HOME_LS), "away_linescores": list(AWAY_LS),
           "period": 4, "in_progress": False, "final": True, "status": "Final"}
    row.update(over)
    return row


@pytest.fixture
def nfl_games(monkeypatch):
    def install(*games):
        monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: list(games))
    return install


def test_nfl_a_full_game_order_is_UNCHANGED(nfl_games):
    nfl_games(_nfl_game())
    resolve = nfl_status_resolver("2026-09-08")
    assert resolve(_nfl_order(market="totals", side="over", line=40.5))["current_value"] == 41.0
    assert resolve(_nfl_order())["current_value"] == 7.0


@pytest.mark.parametrize("segment", [None, "", "  ", "full", "FULL"])
def test_nfl_an_absent_or_full_segment_grades_as_the_whole_game(nfl_games, segment):
    nfl_games(_nfl_game())
    order = _nfl_order(market="totals", side="over", line=40.5)
    if segment is not None:
        order["segment"] = segment
    assert nfl_status_resolver("2026-09-08")(order)["current_value"] == 41.0


def test_nfl_h1_total_over_and_under(nfl_games):
    nfl_games(_nfl_game())
    resolve = nfl_status_resolver("2026-09-08")
    over = _nfl_order(market="totals", segment="h1", side="over", line=23.5)
    under = _nfl_order(market="totals", segment="h1", side="under", line=23.5)

    view = resolve(over)
    assert view["current_value"] == 24.0 and view["is_final"] is True
    assert _graded(over, view)["status"] == STATUS_WON
    assert _graded(under, resolve(under))["status"] == STATUS_LOST


def test_nfl_q1_spread(nfl_games):
    nfl_games(_nfl_game())
    order = _nfl_order(market="spreads", segment="q1", side="home", line=-3.5)

    view = nfl_status_resolver("2026-09-08")(order)

    assert view["current_value"] == 7.0 and view["line"] == 3.5 and view["side"] == "over"
    assert _graded(order, view)["status"] == STATUS_WON


def test_nfl_h1_moneyline_win_loss_and_PUSH(nfl_games):
    """A level half is a PUSH under `draw_possible=False`, exactly as a level
    game is -- `line == 0.0`, and `resolve_bet_status` reports the tie."""
    nfl_games(_nfl_game())
    resolve = nfl_status_resolver("2026-09-08")
    win = _nfl_order(market="h2h", segment="h1", side="home")
    loss = _nfl_order(market="h2h", segment="h1", side="away")
    assert _graded(win, resolve(win))["status"] == STATUS_WON
    assert _graded(loss, resolve(loss))["status"] == STATUS_LOST

    nfl_games(_nfl_game(home_linescores=[7, 10, 3, 4], away_linescores=[10, 7, 0, 0]))
    view = nfl_status_resolver("2026-09-08")(win)
    assert view["current_value"] == 0.0 and view["line"] == 0.0
    assert _graded(win, view)["status"] == STATUS_LIVE_TIED


def test_nfl_a_segment_order_refuses_BY_NAME_without_linescores(nfl_games):
    """The mutation half of the pair above: same order, linescores removed,
    and the answer is a named refusal -- NOT the 41-point game total."""
    nfl_games(_nfl_game(home_linescores=None, away_linescores=None))

    view = nfl_status_resolver("2026-09-08")(_nfl_order(market="totals", segment="h1", side="over", line=23.5))

    assert view == {"unavailable_reason": "segment_actual_unavailable:h1"}


def test_nfl_a_segment_the_sport_does_not_play_refuses_by_its_own_name(nfl_games):
    nfl_games(_nfl_game())
    view = nfl_status_resolver("2026-09-08")(_nfl_order(market="totals", segment="first5", side="over", line=3.5))
    assert view == {"unavailable_reason": "unsupported_segment:first5"}


def test_nfl_h2_includes_overtime(nfl_games):
    nfl_games(_nfl_game(home_linescores=[7, 10, 3, 4, 6], away_linescores=[0, 7, 7, 3, 0], period=5, home_score=30))
    resolve = nfl_status_resolver("2026-09-08")
    assert resolve(_nfl_order(market="totals", segment="h2", side="over", line=20.5))["current_value"] == 23.0
    assert resolve(_nfl_order(market="totals", segment="q4", side="over", line=6.5))["current_value"] == 7.0


def test_nfl_in_play_segments_are_not_final_until_their_clock_runs_out(nfl_games):
    nfl_games(_nfl_game(home_linescores=[7, 3], away_linescores=[0, 7], home_score=10, away_score=7,
                        period=2, in_progress=True, final=False, status="Q2 3:12"))
    resolve = nfl_status_resolver("2026-09-08")

    h1 = resolve(_nfl_order(market="totals", segment="h1", side="over", line=23.5))
    assert h1["current_value"] == 17.0 and h1["is_final"] is False

    q1 = resolve(_nfl_order(market="totals", segment="q1", side="under", line=10.5))
    assert q1["current_value"] == 7.0 and q1["is_final"] is True

    q4 = resolve(_nfl_order(market="totals", segment="q4", side="over", line=10.5))
    assert q4["started"] is False
    assert _graded(_nfl_order(market="totals", segment="q4", side="over", line=10.5), q4)["status"] == STATUS_NOT_STARTED


def test_nfl_halftime_closes_the_first_half(nfl_games):
    nfl_games(_nfl_game(home_linescores=[7, 3], away_linescores=[0, 7], home_score=10, away_score=7,
                        period=2, in_progress=True, final=False, status="Halftime"))
    view = nfl_status_resolver("2026-09-08")(_nfl_order(market="totals", segment="h1", side="over", line=15.5))
    assert view["is_final"] is True


def test_nfl_a_segment_order_REACHES_the_resolver_through_paper_settlement(monkeypatch):
    """Reachability before correctness: the real dispatch, a real segment
    order, and a graded value rather than either refusal."""
    from syndicate.features.shared.paper_settlement import _default_resolver

    monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: [_nfl_game()])
    view = _default_resolver("2026-09-08")(_nfl_order(market="totals", segment="h1", side="over", line=23.5))

    assert view.get("unavailable_reason") is None
    assert view["current_value"] == 24.0


# ===========================================================================
# NCAAF
# ===========================================================================

_REGISTRY = {"tcu horned frogs": "1", "tcu": "1", "north carolina tar heels": "2", "unc": "2"}


@pytest.fixture
def ncaaf_games(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.ncaaf_team_registry.resolve_ncaaf_team_id",
        lambda name: _REGISTRY.get(" ".join(str(name or "").strip().lower().split())),
    )

    def install(*games):
        monkeypatch.setattr(bet_status_ncaaf, "_load_games", lambda _d: list(games))
    return install


def _ncaaf_order(**over):
    row = {"sport": "ncaaf", "market": "h2h", "side": "home", "line": None,
           "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"}
    row.update(over)
    return row


def _ncaaf_game(**over):
    row = {"event_id": "401752000", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels",
           "home_abbr": "TCU", "away_abbr": "UNC", "home_score": 24, "away_score": 17,
           "home_linescores": list(HOME_LS), "away_linescores": list(AWAY_LS),
           "period": 4, "in_progress": False, "final": True, "status": "Final"}
    row.update(over)
    return row


def test_ncaaf_a_full_game_order_is_UNCHANGED(ncaaf_games):
    ncaaf_games(_ncaaf_game())
    resolve = ncaaf_status_resolver("2026-09-08")
    assert resolve(_ncaaf_order(market="totals", side="over", line=40.5))["current_value"] == 41.0
    assert resolve(_ncaaf_order())["current_value"] == 7.0
    assert resolve({**_ncaaf_order(), "segment": "full"})["current_value"] == 7.0


def test_ncaaf_h1_total_over_under(ncaaf_games):
    ncaaf_games(_ncaaf_game())
    resolve = ncaaf_status_resolver("2026-09-08")
    over = _ncaaf_order(market="totals", segment="h1", side="over", line=23.5)
    under = _ncaaf_order(market="totals", segment="h1", side="under", line=23.5)
    assert _graded(over, resolve(over))["status"] == STATUS_WON
    assert _graded(under, resolve(under))["status"] == STATUS_LOST


def test_ncaaf_q1_spread(ncaaf_games):
    ncaaf_games(_ncaaf_game())
    order = _ncaaf_order(market="spreads", segment="q1", side="home", line=-7.5)
    view = ncaaf_status_resolver("2026-09-08")(order)
    assert view["current_value"] == 7.0 and view["line"] == 7.5
    assert _graded(order, view)["status"] == STATUS_LOST


def test_ncaaf_h1_moneyline_win_loss_push(ncaaf_games):
    ncaaf_games(_ncaaf_game())
    resolve = ncaaf_status_resolver("2026-09-08")
    win = _ncaaf_order(market="h2h", segment="h1", side="home")
    loss = _ncaaf_order(market="h2h", segment="h1", side="away")
    assert _graded(win, resolve(win))["status"] == STATUS_WON
    assert _graded(loss, resolve(loss))["status"] == STATUS_LOST

    ncaaf_games(_ncaaf_game(away_linescores=[10, 7, 0, 0]))
    assert _graded(win, ncaaf_status_resolver("2026-09-08")(win))["status"] == STATUS_LIVE_TIED


def test_ncaaf_a_segment_order_refuses_BY_NAME_without_linescores(ncaaf_games):
    ncaaf_games(_ncaaf_game(home_linescores=None, away_linescores=None))
    view = ncaaf_status_resolver("2026-09-08")(_ncaaf_order(market="totals", segment="h1", side="over", line=23.5))
    assert view == {"unavailable_reason": "segment_actual_unavailable:h1"}


def test_ncaaf_unsupported_segment_refuses_before_the_join(ncaaf_games):
    ncaaf_games(_ncaaf_game())
    view = ncaaf_status_resolver("2026-09-08")(_ncaaf_order(market="totals", segment="p1", side="over", line=3.5))
    assert view == {"unavailable_reason": "unsupported_segment:p1"}


# ===========================================================================
# Soccer
# ===========================================================================


def _soccer_order(**over):
    row = {"sport": "soccer", "market": "h2h", "side": "home", "line": None,
           "home_team": "Chelsea", "away_team": "Fulham", "event_id": "oddsapi-hash"}
    row.update(over)
    return row


def _match(**over):
    row = {"home_team": "Chelsea", "away_team": "Fulham", "home_score": 3, "away_score": 1,
           "home_linescores": [2, 1], "away_linescores": [1, 0], "period": 2,
           "final": True, "in_progress": False, "status_detail": "FT"}
    row.update(over)
    return row


def _patch_matches(monkeypatch, records):
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: records)


def test_soccer_a_full_match_order_is_UNCHANGED(monkeypatch):
    _patch_matches(monkeypatch, [_match()])
    resolve = soccer.soccer_status_resolver("2026-09-08")
    assert resolve(_soccer_order(market="totals", side="over", line=2.5))["current_value"] == 4.0
    view = resolve(_soccer_order())
    assert view["current_value"] == 2 and view["line"] == 0.5


def test_soccer_h1_total_over_under(monkeypatch):
    _patch_matches(monkeypatch, [_match()])
    resolve = soccer.soccer_status_resolver("2026-09-08")
    over = _soccer_order(market="totals", segment="h1", side="over", line=2.5)
    under = _soccer_order(market="totals", segment="h1", side="under", line=2.5)
    view = resolve(over)
    assert view["current_value"] == 3.0 and view["is_final"] is True
    assert _graded(over, view)["status"] == STATUS_WON
    assert _graded(under, resolve(under))["status"] == STATUS_LOST


def test_soccer_h1_result_is_THREE_WAY_a_level_half_is_the_draw_not_a_push(monkeypatch):
    """The prompt's own rule: a first-half draw is an OUTCOME. The home side
    LOSES on 1-1 at the half (margin 0 against a 0.5 line) and the draw side
    WINS (|margin| under 0.5) -- `game_line_view`'s half-point trick, applied
    to the half's scores."""
    _patch_matches(monkeypatch, [_match(home_linescores=[1, 2], away_linescores=[1, 0])])
    resolve = soccer.soccer_status_resolver("2026-09-08")
    home = _soccer_order(market="h2h", segment="h1", side="home")
    draw = _soccer_order(market="h2h", segment="h1", side="draw")
    away = _soccer_order(market="h2h", segment="h1", side="away")

    assert _graded(home, resolve(home))["status"] == STATUS_LOST
    assert _graded(draw, resolve(draw))["status"] == STATUS_WON
    assert _graded(away, resolve(away))["status"] == STATUS_LOST
    # And the full-match result on the same record is a home win, so the
    # segment is being read and not the game.
    assert _graded(_soccer_order(), resolve(_soccer_order()))["status"] == STATUS_WON


def test_soccer_h1_result_win_and_loss(monkeypatch):
    """Positional sides on purpose: club-name sides resolve through the
    data-backed `team_aliases` map, which a session worktree does not carry,
    and that resolver is pinned by `test_bet_status_soccer.py` already."""
    _patch_matches(monkeypatch, [_match()])
    resolve = soccer.soccer_status_resolver("2026-09-08")
    win = _soccer_order(market="h2h", segment="h1", side="home")
    loss = _soccer_order(market="h2h", segment="h1", side="away")
    assert _graded(win, resolve(win))["status"] == STATUS_WON
    assert _graded(loss, resolve(loss))["status"] == STATUS_LOST


def test_soccer_h1_handicap(monkeypatch):
    _patch_matches(monkeypatch, [_match()])
    order = _soccer_order(market="spreads", segment="h1", side="home", line=-0.5)
    view = soccer.soccer_status_resolver("2026-09-08")(order)
    assert view["current_value"] == 1 and view["line"] == 0.5
    assert _graded(order, view)["status"] == STATUS_WON


def test_soccer_a_segment_order_refuses_BY_NAME_without_linescores(monkeypatch):
    _patch_matches(monkeypatch, [_match(home_linescores=None, away_linescores=None)])
    view = soccer.soccer_status_resolver("2026-09-08")(_soccer_order(market="totals", segment="h1", side="over", line=1.5))
    assert view == {"unavailable_reason": "segment_actual_unavailable:h1"}


def test_soccer_an_absent_segment_key_grades_as_the_whole_match(monkeypatch):
    _patch_matches(monkeypatch, [_match(home_linescores=None, away_linescores=None)])
    view = soccer.soccer_status_resolver("2026-09-08")(_soccer_order(market="totals", side="over", line=2.5))
    assert view["current_value"] == 4.0


def test_soccer_in_play_first_half_is_a_value_and_second_half_not_started(monkeypatch):
    _patch_matches(monkeypatch, [_match(home_linescores=[1], away_linescores=[0], home_score=1, away_score=0,
                                        period=1, final=False, in_progress=True, status_detail="23'")])
    resolve = soccer.soccer_status_resolver("2026-09-08")
    h1 = resolve(_soccer_order(market="totals", segment="h1", side="over", line=0.5))
    assert h1["current_value"] == 1.0 and h1["is_final"] is False
    assert resolve(_soccer_order(market="totals", segment="h2", side="over", line=0.5))["started"] is False


def test_soccer_the_second_half_closes_the_first(monkeypatch):
    _patch_matches(monkeypatch, [_match(home_linescores=[1, 0], away_linescores=[0, 0], home_score=1, away_score=0,
                                        period=2, final=False, in_progress=True, status_detail="61'")])
    view = soccer.soccer_status_resolver("2026-09-08")(_soccer_order(market="totals", segment="h1", side="under", line=1.5))
    assert view["is_final"] is True


# ---------------------------------------------------------------------------
# The soccer sidecar: the fields reach `_load_matches` from the aggregate
# refresh-worker can read, with no per-league tree on disk.
# ---------------------------------------------------------------------------


def test_soccer_load_matches_carries_linescores_from_the_cross_service_aggregate(tmp_path, monkeypatch):
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path)
    (tmp_path / "live").mkdir(parents=True)
    (tmp_path / "live" / "soccer_live_lens.json").write_text(json.dumps({
        "date": "2026-09-08",
        "games": [{"league": "epl", "event_id": "e2", "home_team": "Leeds", "away_team": "Brentford",
                   "score_home": 1, "score_away": 0, "status_period": 1, "status_detail": "30'",
                   "home_linescores": [1], "away_linescores": [0]}],
        "finals": [{"league": "epl", "event_id": "e1", "home_team": "Chelsea", "away_team": "Fulham",
                    "score_home": "3", "score_away": "1", "status_state": "post", "final": True,
                    "home_linescores": [2, 1], "away_linescores": [1, 0]}],
    }), encoding="utf-8")

    records = {(r["home_team"], r["away_team"]): r for r in soccer._load_matches("2026-09-08")}

    final = records[("Chelsea", "Fulham")]
    assert final["final"] is True and final["home_linescores"] == [2, 1] and final["away_linescores"] == [1, 0]
    live = records[("Leeds", "Brentford")]
    assert live["in_progress"] is True and live["home_linescores"] == [1] and live["period"] == 1

    # And the resolver grades the half off exactly this read.
    view = soccer.soccer_status_resolver("2026-09-08")(_soccer_order(market="totals", segment="h1", side="over", line=2.5))
    assert view["current_value"] == 3.0 and view["is_final"] is True


def test_soccer_a_record_WITHOUT_the_fields_never_overwrites_one_WITH_them(tmp_path, monkeypatch):
    """The aggregate's `finals` carries the halves; the per-league `match_box`
    for the same fixture is a box cached before the field existed. The join
    must keep the halves, whichever source is walked last."""
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path)
    (tmp_path / "live").mkdir(parents=True)
    (tmp_path / "live" / "soccer_live_lens.json").write_text(json.dumps({
        "date": "2026-09-08", "games": [],
        "finals": [{"home_team": "Chelsea", "away_team": "Fulham", "score_home": "3", "score_away": "1",
                    "status_state": "post", "final": True, "home_linescores": [2, 1], "away_linescores": [1, 0]}],
    }), encoding="utf-8")
    league = tmp_path / "soccer_source" / "epl" / "api" / "live_state"
    league.mkdir(parents=True)
    (league / "live_state_2026-09-08.json").write_text(json.dumps({
        "league": "epl", "date": "2026-09-08",
        "match_box": {"e1": {"home_team": "Chelsea", "away_team": "Fulham", "score_home": "3", "score_away": "1",
                             "status_state": "post", "final": True}},
    }), encoding="utf-8")

    fields = soccer._segment_fields_by_matchup("2026-09-08")

    assert fields[("chelsea", "fulham")]["home_linescores"] == [2, 1]
    assert fields[("chelsea", "fulham")]["away_linescores"] == [1, 0]
