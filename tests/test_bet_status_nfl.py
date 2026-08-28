"""NFL settlement: the resolver, and the wiring that makes it reachable.

MEASURED BEFORE THIS EXISTED, refresh-worker 2026-08-28T02:50:38Z:

    SETTLED date=2026-08-28 orders=21 graded=0
      ungraded={..., 'no_resolver_for_nfl': 6, ...}

6 of 21 -- 29% of the slate -- and NFL was the ONLY sport producing orders with
no resolver at all.

REACHABILITY IS TESTED BEFORE CORRECTNESS, per `model_engine_standard.md`. A
test that only proves this module imports would pass identically with the
`paper_settlement` wiring removed, which is the state that shipped the bug.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import bet_status_nfl
from syndicate.features.shared.bet_status_nfl import nfl_status_resolver


def _order(**over):
    row = {
        "sport": "nfl",
        "market": "h2h",
        "side": "home",
        "line": None,
        "home_team": "San Francisco 49ers",
        "away_team": "Seattle Seahawks",
    }
    row.update(over)
    return row


def _game(**over):
    row = {
        "event_id": "401671800",
        "home_team": "San Francisco 49ers",
        "away_team": "Seattle Seahawks",
        "home_abbr": "SF",
        "away_abbr": "SEA",
        "home_score": 24,
        "away_score": 17,
        "in_progress": False,
        "final": True,
        "status": "Final",
    }
    row.update(over)
    return row


@pytest.fixture
def _games(monkeypatch):
    def install(*games):
        monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: list(games))
    return install


# ---------------------------------------------------------------------------
# 1. Reachability -- the half that was missing
# ---------------------------------------------------------------------------


def test_paper_settlement_DISPATCHES_nfl_to_a_real_resolver():
    """THE LOAD-BEARING TEST. `_default_resolver` had builders for mlb, wnba and
    soccer only, so this exact call returned `no_resolver_for_nfl` forever."""
    from syndicate.features.shared.paper_settlement import _default_resolver

    resolve = _default_resolver("2026-08-28")
    verdict = resolve(_order(market="player_pass_yds", player_name="Brock Purdy"))

    # A refusal is fine -- props are not gradeable from a scoreboard. What must
    # NOT come back is the dispatch miss.
    assert verdict.get("unavailable_reason") != "no_resolver_for_nfl"


def test_an_UNWIRED_sport_still_reports_the_dispatch_miss():
    """Paired with the test above deliberately, and it is what makes that one
    mean something. If the dispatch had been changed to fall through to some
    default, the NFL assertion would pass for the wrong reason -- so this pins
    that the `no_resolver_for_<sport>` branch is still live and still reachable
    for a sport that genuinely has no resolver."""
    from syndicate.features.shared.paper_settlement import _default_resolver

    resolve = _default_resolver("2026-08-28")
    verdict = resolve({"sport": "cricket", "market": "h2h"})

    assert verdict.get("unavailable_reason") == "no_resolver_for_cricket"


# ---------------------------------------------------------------------------
# 2. A tie is a PUSH -- the decision most likely to be got wrong
# ---------------------------------------------------------------------------


def test_a_TIED_game_grades_as_a_PUSH_not_a_loss(_games):
    """NFL regular-season games CAN end level and a level moneyline returns the
    stake. `game_line_view` encodes that as `line=0.0` under
    `draw_possible=False`; passing soccer's `True` would make it three-way and
    `line=0.5`, which grades a tie as a LOSS.

    The fixture contains the negative case ON PURPOSE -- a resolver tested only
    on decisive games cannot distinguish the two settings at all.
    """
    _games(_game(home_score=20, away_score=20))

    view = nfl_status_resolver("2026-08-28")(_order())

    assert view["current_value"] == 0.0
    assert view["line"] == 0.0, "0.5 here means draw_possible=True -- a tie would grade as a loss"
    assert view["is_final"] is True


def test_a_three_way_market_is_still_graded_three_way(_games):
    """`h2h_3_way` is in `_ALWAYS_THREE_WAY`, so it is decided by the MARKET
    NAME and not by the flag above. The board does emit it for NFL."""
    _games(_game(home_score=20, away_score=20))

    view = nfl_status_resolver("2026-08-28")(_order(market="h2h_3_way"))

    assert view["line"] == 0.5


# ---------------------------------------------------------------------------
# 3. Markets
# ---------------------------------------------------------------------------


def test_a_moneyline_reads_the_margin(_games):
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(_order())

    assert view["current_value"] == 7.0
    assert view["side"] == "over"


def test_a_total_is_graded_off_the_COMBINED_points_with_no_translation(_games):
    """A total already arrives in the grader's vocabulary. Routing it through
    `game_line_view` is what produced soccer's `unmapped_market` count --
    `is_game_line_market` is False for totals BY DESIGN."""
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(_order(market="totals", side="over", line=44.5))

    assert view["current_value"] == 41.0
    assert view["is_final"] is True


def test_a_TEAM_total_refuses_rather_than_using_the_combined_score(_games):
    """Grading one side's points off the scoreline roughly doubles the value and
    settles overs that lost."""
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(_order(market="team_totals", side="over", line=24.5))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_TEAM_TOTAL


def test_a_player_prop_refuses_BY_NAME(_games):
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(
        _order(market="player_pass_yds", side="over", line=250.5, player_name="Brock Purdy")
    )

    assert view["unavailable_reason"] == bet_status_nfl.REASON_PROPS


# ---------------------------------------------------------------------------
# 4. The refusals, and the ORDER they are made in
# ---------------------------------------------------------------------------


def test_the_MARKET_check_runs_BEFORE_the_artifact_read(monkeypatch):
    """"We cannot grade this market" is PERMANENT; "the capture is not there
    yet" is TRANSIENT. Checking the transient one first hides a structural gap
    behind a reason that looks like it will fix itself.

    The absence has to be present: this fixture makes the artifact unreadable,
    so a resolver that read first would return `no_nfl_live_state_for_date`.
    """
    monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: None)

    view = nfl_status_resolver("2026-08-28")(
        _order(market="player_rush_yds", player_name="Christian McCaffrey")
    )

    assert view["unavailable_reason"] == bet_status_nfl.REASON_PROPS


def test_an_unreadable_capture_and_a_missing_GAME_are_different_reasons(monkeypatch, _games):
    """One says the poller is down, the other says this fixture is not in a
    capture we DID read. They point at different jobs."""
    monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: None)
    assert nfl_status_resolver("2026-08-28")(_order())["unavailable_reason"] == (
        bet_status_nfl.REASON_NO_LIVE_STATE
    )

    _games(_game(home_team="Green Bay Packers", away_team="Chicago Bears",
                 home_abbr="GB", away_abbr="CHI"))
    assert nfl_status_resolver("2026-08-28")(_order())["unavailable_reason"] == (
        bet_status_nfl.REASON_GAME_NOT_FOUND
    )


def test_an_order_with_no_teams_refuses_rather_than_falling_back_to_event_id(_games):
    """`event_id` is the OddsAPI hash; the capture is ESPN-keyed. There is no
    fallback here that would be anything but a guess."""
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(_order(home_team=None, event_id="abc123"))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_NO_MATCHUP


def test_a_PREGAME_game_carries_no_scores_and_does_not_settle_a_total_as_under(_games):
    """A 0-0 on a game that has not kicked off is a schedule placeholder. The
    capture stores None; grading it would settle every pregame under."""
    _games(_game(home_score=None, away_score=None, final=False, in_progress=False))

    view = nfl_status_resolver("2026-08-28")(_order(market="totals", side="over", line=44.5))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_NO_SCORES


def test_a_HALF_known_score_refuses_both_together(_games):
    """A missing away total must not read as a shutout."""
    _games(_game(away_score=None))

    view = nfl_status_resolver("2026-08-28")(_order(market="totals", side="over", line=44.5))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_NO_SCORES


def test_a_non_nfl_order_is_not_reported_as_an_NFL_failure(_games):
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(_order(sport="mlb"))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_NOT_NFL


# ---------------------------------------------------------------------------
# 5. The join
# ---------------------------------------------------------------------------


def test_the_join_resolves_a_TRI_CODE_as_well_as_a_display_name(_games):
    """The capture stores both because the board may hold either, and a miss on
    one form is not a miss on the game."""
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(_order(home_team="SF", away_team="SEA"))

    assert view["current_value"] == 7.0


# ---------------------------------------------------------------------------
# 6. The capture itself
# ---------------------------------------------------------------------------


def test_the_poller_does_not_emit_a_placeholder_score_for_an_unplayed_game():
    from scripts.poll_nfl_live_state import _game_from_event

    event = {
        "id": "401671999",
        "date": "2026-09-07T17:00Z",
        "status": {"type": {"state": "pre", "completed": False, "shortDetail": "Sun 12:00 PM"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "0", "team": {"displayName": "Dallas Cowboys", "abbreviation": "DAL"}},
            {"homeAway": "away", "score": "0", "team": {"displayName": "New York Giants", "abbreviation": "NYG"}},
        ]}],
    }

    game = _game_from_event(event)

    assert game["home_score"] is None and game["away_score"] is None
    assert game["final"] is False


def test_a_state_post_game_counts_as_FINAL_even_without_the_completed_flag():
    """Both signals, not just `completed`: some payload shapes omit it, and
    reading only one leaves a finished game ungraded all night."""
    from scripts.poll_nfl_live_state import _game_from_event

    event = {
        "id": "401671800",
        "status": {"type": {"state": "post", "shortDetail": "Final"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "24", "team": {"displayName": "San Francisco 49ers", "abbreviation": "SF"}},
            {"homeAway": "away", "score": "17", "team": {"displayName": "Seattle Seahawks", "abbreviation": "SEA"}},
        ]}],
    }

    game = _game_from_event(event)

    assert game["final"] is True
    assert game["home_score"] == 24 and game["away_score"] == 17
