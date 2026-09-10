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


def test_paper_settlement_DISPATCHES_nfl_to_a_real_resolver(monkeypatch):
    """THE LOAD-BEARING TEST. `_default_resolver` had builders for mlb, wnba and
    soccer only, so this exact call returned `no_resolver_for_nfl` forever.

    The capture is stubbed unreadable so this stays offline: since props became
    gradeable (section 7), a mapped prop proceeds to the live-state read, which
    would otherwise poll ESPN's scoreboard from inside a unit test. Asserting
    the NFL resolver's OWN refusal is stronger than "not a dispatch miss" -- it
    proves this order reached `bet_status_nfl` specifically."""
    from syndicate.features.shared.paper_settlement import _default_resolver

    monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: None)
    resolve = _default_resolver("2026-08-28")
    verdict = resolve(_order(market="player_pass_yds", player_name="Brock Purdy"))

    assert verdict.get("unavailable_reason") != "no_resolver_for_nfl"
    assert verdict.get("unavailable_reason") == bet_status_nfl.REASON_NO_LIVE_STATE


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


def test_an_UNMAPPED_player_market_refuses_BY_NAME(_games):
    """Mapped props are graded since 2026-09-10 (section 7). A player market
    with no box field still refuses, by name, rather than guessing a field."""
    _games(_game())

    view = nfl_status_resolver("2026-08-28")(
        _order(market="player_longest_reception", side="over", line=25.5, player_name="Brock Purdy")
    )

    assert view["unavailable_reason"] == bet_status_nfl.REASON_PROP_MARKET


# ---------------------------------------------------------------------------
# 4. The refusals, and the ORDER they are made in
# ---------------------------------------------------------------------------


def test_the_MARKET_check_runs_BEFORE_the_artifact_read(monkeypatch):
    """"We cannot grade this market" is PERMANENT; "the capture is not there
    yet" is TRANSIENT. Checking the transient one first hides a structural gap
    behind a reason that looks like it will fix itself.

    Still true for props now that most are gradeable: an UNMAPPED player market
    is the permanent case. The absence has to be present -- this fixture makes
    the artifact unreadable, so a resolver that read first would return
    `no_nfl_live_state_for_date`.
    """
    monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: None)

    view = nfl_status_resolver("2026-08-28")(
        _order(market="player_longest_reception", player_name="Christian McCaffrey")
    )

    assert view["unavailable_reason"] == bet_status_nfl.REASON_PROP_MARKET


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


def test_a_PREGAME_game_is_NOT_STARTED_and_never_settles_a_total_as_under(_games):
    """A 0-0 on a game that has not kicked off is a schedule placeholder. The
    capture stores None; grading it would settle every pregame under. Since
    2026-09-10 it reads NOT STARTED rather than as a missing score, the answer
    props and segments already gave."""
    from syndicate.features.shared.bet_status import STATUS_NOT_STARTED, resolve_bet_status

    _games(_game(home_score=None, away_score=None, final=False, in_progress=False))

    view = nfl_status_resolver("2026-08-28")(_order(market="totals", side="over", line=44.5))

    assert view == {"current_value": None, "is_final": False, "started": False}
    status = resolve_bet_status(market="totals", side="over", line=44.5, current_value=None,
                                is_final=False, started=False)
    assert status["status"] == STATUS_NOT_STARTED


def test_a_PREGAME_spread_is_NOT_STARTED_not_no_team_scores(_games):
    # The game-line half of the same fix: `game_line_view` answers a pregame
    # spread with `no_team_scores`, which is what 172 rows read on 2026-09-10.
    _games(_game(home_score=None, away_score=None, final=False, in_progress=False))

    view = nfl_status_resolver("2026-08-28")(_order(market="spreads", side="home", line=-3.5))

    assert view == {"current_value": None, "is_final": False, "started": False}


def test_a_FINAL_game_with_no_scores_still_REFUSES(_games):
    # The fix must not eat the refusal it sits beside: a game ESPN calls final
    # (postponed and cancelled games land here) with no score is still unknown.
    _games(_game(home_score=None, away_score=None, final=True, in_progress=False))

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


# ---------------------------------------------------------------------------
# 7. PLAYER PROPS, graded off ESPN's per-player box (2026-09-10)
#
# Until this section existed every NFL prop refused as
# `nfl_props_not_gradeable_from_scoreboard`, which made NFL props stakeable but
# unmeasurable. The fixture is the REAL box for NE @ SEA (ESPN event 401872656,
# 2026-09-09, final NE 10 - SEA 13), captured 2026-09-10 and trimmed to the
# stat groups settlement reads. Every expected number below is ESPN's own.
# ---------------------------------------------------------------------------


def _opener_summary():
    import json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "nfl_espn_summary_401872656.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _opener_game(**over):
    row = {
        "event_id": "401872656",
        "home_team": "Seattle Seahawks",
        "away_team": "New England Patriots",
        "home_abbr": "SEA",
        "away_abbr": "NE",
        "home_score": 13,
        "away_score": 10,
        "in_progress": False,
        "final": True,
        "status": "Final",
    }
    row.update(over)
    return row


def _prop(**over):
    row = {
        "sport": "nfl",
        "home_team": "Seattle Seahawks",
        "away_team": "New England Patriots",
        "side": "over",
        "line": 0.5,
    }
    row.update(over)
    return row


@pytest.fixture
def _opener(monkeypatch):
    """The real NE @ SEA box, served offline. Returns the list of event ids
    the resolver fetched, so a test can count ESPN calls."""
    from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary

    calls: list[str] = []

    def fetch(event_id):
        calls.append(event_id)
        return player_stat_rows_from_summary(_opener_summary())

    def install(**game_over):
        monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: [_opener_game(**game_over)])
        monkeypatch.setattr(bet_status_nfl, "_fetch_box", fetch)
        return calls

    return install


@pytest.mark.parametrize(
    "market, player, expected",
    [
        ("Passing Yards", "Drake Maye", 178.0),
        ("Passing Attempts", "Drake Maye", 33.0),
        ("Passing TDs", "Drew Lock", 1.0),
        ("Interceptions", "Drake Maye", 3.0),
        ("Rushing Yards", "Rhamondre Stevenson", 51.0),
        ("Rushing Attempts", "Rhamondre Stevenson", 18.0),
        ("Receptions", "Mack Hollins", 4.0),
        ("Receiving Yards", "Jaxon Smith-Njigba", 122.0),
        # The raw OddsAPI key, which a minority of board rows still carry.
        ("player_receptions", "Rhamondre Stevenson", 5.0),
    ],
)
def test_a_player_prop_is_GRADED_off_the_real_ESPN_box(_opener, market, player, expected):
    _opener()

    view = nfl_status_resolver("2026-09-09")(_prop(market=market, player_name=player))

    assert view.get("unavailable_reason") is None, view
    assert view["current_value"] == expected
    assert view["is_final"] is True and view["started"] is True


def test_interceptions_are_THROWN_never_a_defenders_CATCH():
    """ESPN carries `interceptions` in the `passing` group (thrown) AND in a
    separate `interceptions` group (caught). Maye threw 3 on this box and the
    three SEA defenders who caught them are listed in the other group. A
    name-only key map credits each of them with a thrown interception."""
    from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary

    summary = _opener_summary()
    rows = {row["player_name"]: row for row in player_stat_rows_from_summary(summary)}
    catchers = [
        athlete["athlete"]["displayName"]
        for team in summary["boxscore"]["players"]
        for group in team["statistics"]
        if group["name"] == "interceptions"
        for athlete in group["athletes"]
    ]

    assert rows["Drake Maye"]["pass_int"] == 3.0
    assert catchers, "the fixture must contain the collision or this test proves nothing"
    assert all(rows[name]["pass_int"] == 0.0 for name in catchers)


def test_a_REAL_zero_is_graded_as_zero_not_as_an_absence(_opener):
    """Robert Spillane is in NE's box (defensive group) with no yards and no
    touchdown -- exactly the row the CARD filters out. He played, so his
    receptions are a genuine 0 and an under settles. Reading the card's
    filtered rows would turn this into `not_in_final_box` and refuse a bet that
    has an answer."""
    _opener()

    view = nfl_status_resolver("2026-09-09")(
        _prop(market="Receptions", player_name="Robert Spillane", side="under")
    )

    assert view.get("unavailable_reason") is None, view
    assert view["current_value"] == 0.0


def test_a_player_ABSENT_from_the_box_refuses_rather_than_grading_zero(_opener):
    """Absent from a final box can mean inactive (books VOID) or active with no
    touch; they settle differently, so it refuses. Live, it is only 'not yet'."""
    _opener()
    final_view = nfl_status_resolver("2026-09-09")(
        _prop(market="Receiving Yards", player_name="Nobody Played")
    )
    assert final_view["unavailable_reason"] == bet_status_nfl.REASON_PLAYER_NOT_IN_BOX

    _opener(final=False, in_progress=True)
    live_view = nfl_status_resolver("2026-09-09")(
        _prop(market="Receiving Yards", player_name="Nobody Played")
    )
    assert live_view["unavailable_reason"] == bet_status_nfl.REASON_PLAYER_NOT_IN_BOX_YET


def test_the_name_fold_joins_INITIALS_and_SUFFIXES(_opener):
    """ESPN writes 'A.J. Brown'; the board writes 'AJ Brown'. `_norm_name` alone
    turns those into 'a j brown' and 'aj brown' and they never join."""
    key = bet_status_nfl._player_key
    assert key("A.J. Brown") == key("AJ Brown")
    assert key("Travis Etienne Jr.") == key("Travis Etienne")
    assert key("Kenneth Walker III") == key("Kenneth Walker")
    assert key("Amon-Ra St. Brown") == key("Amon-Ra St Brown")

    _opener()
    view = nfl_status_resolver("2026-09-09")(_prop(market="Receiving Yards", player_name="AJ Brown"))
    assert view["current_value"] == 26.0


def test_a_PREGAME_prop_is_NOT_STARTED_and_fetches_nothing(_opener):
    calls = _opener(final=False, in_progress=False)

    view = nfl_status_resolver("2026-09-09")(_prop(market="Receiving Yards", player_name="Mack Hollins"))

    assert view == {"current_value": None, "is_final": False, "started": False}
    assert calls == []


def test_a_QUARTER_prop_refuses_before_any_read(_opener):
    """ESPN's box is whole-game; a first-quarter prop graded off it would be
    graded off the wrong quantity."""
    calls = _opener()

    view = nfl_status_resolver("2026-09-09")(
        _prop(market="Receiving Yards", player_name="Mack Hollins", segment="q1")
    )

    assert view["unavailable_reason"] == bet_status_nfl.REASON_PROP_SEGMENT
    assert calls == []


def test_the_box_is_fetched_ONCE_per_game_not_once_per_order(_opener):
    calls = _opener()
    resolve = nfl_status_resolver("2026-09-09")

    for player in ("Drake Maye", "Mack Hollins", "Jaxon Smith-Njigba"):
        resolve(_prop(market="Receiving Yards", player_name=player))

    assert calls == ["401872656"]


def test_anytime_TD_supplies_the_implicit_line(_opener):
    """A yes/no market with no line on the board. 'Scored' is td_scored > 0.5,
    and `paper_settlement` honours a line the resolver supplies."""
    _opener()

    view = nfl_status_resolver("2026-09-09")(
        _prop(market="Anytime TD", player_name="Jaxon Smith-Njigba", side="yes", line=None)
    )

    assert view["current_value"] == 1.0
    assert view["line"] == 0.5


def test_an_unreadable_box_refuses_TRANSIENTLY(monkeypatch, _opener):
    _opener()
    monkeypatch.setattr(bet_status_nfl, "_fetch_box", lambda _e: None)

    view = nfl_status_resolver("2026-09-09")(_prop(market="Receiving Yards", player_name="Mack Hollins"))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_NO_BOX


def test_a_game_with_no_ESPN_event_id_refuses(_opener):
    _opener(event_id="")

    view = nfl_status_resolver("2026-09-09")(_prop(market="Receiving Yards", player_name="Mack Hollins"))

    assert view["unavailable_reason"] == bet_status_nfl.REASON_NO_EVENT_ID


def test_the_CARD_rows_are_unchanged_by_the_settlement_fields():
    """The game card read this same parser before counting stats existed. Its
    rows must carry exactly the old ten fields -- and the same 19 players the
    production card showed for this game on 2026-09-10."""
    from syndicate.features.nfl.live_player_box import _DISPLAY_FIELDS, player_rows_from_summary

    rows = player_rows_from_summary(_opener_summary())

    assert len(rows) == 19
    assert all(tuple(row) == _DISPLAY_FIELDS for row in rows)
    assert not any("receptions" in row for row in rows)


def test_paper_settlement_SETTLES_an_nfl_prop_WON_and_LOST(_opener):
    """END TO END through the function settlement actually grades with.
    Reachability before correctness: a resolver test alone would pass with the
    settlement path still refusing."""
    from syndicate.features.shared.paper_settlement import OUTCOME_LOST, OUTCOME_WON, _our_verdict

    _opener()
    resolve = nfl_status_resolver("2026-09-09")

    def outcome_of(order):
        # A SETTLED order is a FILLED one: `grade_order` refuses anything else
        # as `order_not_filled`, and needs a stake and a price to compute P&L.
        order = {**order, "status": "filled", "fill_stake_dollars": 10.0, "fill_price": -110}
        verdict, _resolved, refusal = _our_verdict(order, resolve)
        assert not refusal, refusal
        # `_our_verdict` returns `grade_order`'s dict: `graded`, `outcome`, P&L.
        assert verdict["graded"] is True
        return verdict["outcome"]

    # Maye threw for 178.
    assert outcome_of(_prop(market="Passing Yards", player_name="Drake Maye", side="over", line=250.5)) == OUTCOME_LOST
    assert outcome_of(_prop(market="Passing Yards", player_name="Drake Maye", side="under", line=250.5)) == OUTCOME_WON
    # Smith-Njigba scored; the order carries no line and the resolver supplies it.
    assert outcome_of(
        _prop(market="Anytime TD", player_name="Jaxon Smith-Njigba", side="yes", line=None)
    ) == OUTCOME_WON


# ---------------------------------------------------------------------------
# 8. THE GAME IS FOUND UNDER ITS KICKOFF DATE, NOT THE PLAN DATE (2026-09-10)
# ---------------------------------------------------------------------------
# An order carries the PLAN's date, and a plan commits games days ahead.
# Measured 2026-09-10: the one NFL prop order dated 09-10 read
# `game_not_in_nfl_live_state` against a 09-10 capture holding only SF @ LAR.


def _captures(monkeypatch, by_date):
    """`_load_games` keyed by capture date. Returns the dates read, in order."""
    calls: list[str] = []

    def load(capture_date):
        calls.append(capture_date)
        games = by_date.get(capture_date)
        return None if games is None else list(games)

    monkeypatch.setattr(bet_status_nfl, "_load_games", load)
    return calls


def _sf_lar_pregame():
    return {
        "event_id": "401872657",
        "home_team": "Los Angeles Rams",
        "away_team": "San Francisco 49ers",
        "home_abbr": "LAR",
        "away_abbr": "SF",
        "home_score": None,
        "away_score": None,
        "in_progress": False,
        "final": False,
        "status": "Scheduled",
    }


def _det_no_final():
    return {
        "event_id": "401900001",
        "home_team": "Detroit Lions",
        "away_team": "New Orleans Saints",
        "home_abbr": "DET",
        "away_abbr": "NO",
        "home_score": 27,
        "away_score": 20,
        "in_progress": False,
        "final": True,
        "status": "Final",
    }


def _sunday_total(**over):
    row = {
        "sport": "nfl",
        "home_team": "Detroit Lions",
        "away_team": "New Orleans Saints",
        "market": "totals",
        "side": "over",
        "line": 44.5,
        "selected_date": "2026-09-10",
        "commence_time": "2026-09-13T17:00:00Z",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    "commence_time, expected",
    [
        # The three real games the mapping was read off (ESPN `?dates=`).
        ("2026-09-10T00:20:00Z", "2026-09-09"),  # NE @ SEA, listed under 20260909
        ("2026-09-11T00:35:00Z", "2026-09-10"),  # SF @ LAR, listed under 20260910
        ("2026-09-13T17:00:00Z", "2026-09-13"),  # a Sunday 1 PM ET kickoff
        ("2026-09-13T17:00:00+00:00", "2026-09-13"),
        ("2026-09-13T17:00:00", "2026-09-13"),  # naive is read as UTC
        ("2026-09-13", "2026-09-13"),  # a bare date is already the game's date
        (None, None),
        ("", None),
        ("not a time", None),
    ],
)
def test_the_kickoff_capture_date_is_the_ESPN_eastern_date(commence_time, expected):
    assert bet_status_nfl.kickoff_capture_date(commence_time) == expected


def test_a_SUNDAY_order_on_a_THURSDAY_plan_finds_its_game(monkeypatch):
    calls = _captures(
        monkeypatch, {"2026-09-10": [_sf_lar_pregame()], "2026-09-13": [_det_no_final()]}
    )
    resolved = nfl_status_resolver("2026-09-10")(_sunday_total())
    assert resolved == {"current_value": 47.0, "is_final": True, "started": True}
    # Found under Sunday; the plan date's capture was never needed.
    assert calls == ["2026-09-13"]


def test_WITHOUT_a_kickoff_stamp_the_same_order_still_cannot_find_it(monkeypatch):
    # The falsifier: this is exactly the pre-fix behaviour, and it is what an
    # order with no readable `commence_time` still gets.
    _captures(monkeypatch, {"2026-09-10": [_sf_lar_pregame()], "2026-09-13": [_det_no_final()]})
    resolved = nfl_status_resolver("2026-09-10")(_sunday_total(commence_time=None))
    assert resolved == {"unavailable_reason": bet_status_nfl.REASON_GAME_NOT_FOUND}


def test_WITHOUT_a_kickoff_stamp_the_plan_date_still_grades(monkeypatch):
    # The fallback: a same-day order with no stamp grades exactly as before.
    _captures(monkeypatch, {"2026-09-13": [_det_no_final()]})
    resolved = nfl_status_resolver("2026-09-13")(_sunday_total(selected_date="2026-09-13", commence_time=None))
    assert resolved["current_value"] == 47.0


def test_a_PROP_on_a_night_game_is_found_under_its_EASTERN_date(_opener, monkeypatch):
    # NE @ SEA kicked off 2026-09-10T00:20Z and ESPN files it under 09-09. An
    # order on the 09-10 plan must still find it, and grade off the real box.
    _opener()
    _captures(monkeypatch, {"2026-09-09": [_opener_game()], "2026-09-10": [_sf_lar_pregame()]})
    order = _prop(
        market="Passing Yards",
        player_name="Drake Maye",
        selected_date="2026-09-10",
        commence_time="2026-09-10T00:20:00Z",
    )
    resolved = nfl_status_resolver("2026-09-10")(order)
    assert resolved["current_value"] == 178.0
    assert resolved["is_final"] is True


def test_an_UNREADABLE_kickoff_capture_is_no_live_state_NOT_game_not_found(monkeypatch):
    # The plan date's capture is readable and lacks the game, but the capture
    # that SHOULD hold it could not be read. That is transient, and must say so.
    _captures(monkeypatch, {"2026-09-10": [_sf_lar_pregame()]})
    resolved = nfl_status_resolver("2026-09-10")(_sunday_total())
    assert resolved == {"unavailable_reason": bet_status_nfl.REASON_NO_LIVE_STATE}


def test_a_game_in_NEITHER_capture_is_game_not_found(monkeypatch):
    _captures(monkeypatch, {"2026-09-10": [_sf_lar_pregame()], "2026-09-13": [_sf_lar_pregame()]})
    resolved = nfl_status_resolver("2026-09-10")(_sunday_total())
    assert resolved == {"unavailable_reason": bet_status_nfl.REASON_GAME_NOT_FOUND}


def test_ONE_capture_read_per_date_per_resolver(monkeypatch):
    calls = _captures(
        monkeypatch, {"2026-09-10": [_sf_lar_pregame()], "2026-09-13": [_det_no_final()]}
    )
    resolve = nfl_status_resolver("2026-09-10")
    for side in ("over", "under", "over"):
        resolve(_sunday_total(side=side))
    # A miss reads both dates, once each, and nothing is re-read after.
    resolve(_sunday_total(home_team="Chicago Bears", away_team="Green Bay Packers"))
    resolve(_sunday_total(home_team="Chicago Bears", away_team="Green Bay Packers"))
    assert calls == ["2026-09-13", "2026-09-10"]
