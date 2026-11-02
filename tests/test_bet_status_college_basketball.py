"""NCAAB and WNCAAB paper settlement off ESPN's Division I scoreboard.

  ESPN scoreboard (groups=50&limit=500) -> `bet_status_ncaab` / `bet_status_wncaab`
  (via `paper_settlement._default_resolver`) -> `_our_verdict` -> `grade_order`

Reachability first: before this, every NCAAB paper order read `no_resolver_for_ncaab`
(both 11-02 orders on the fleet, 2026-11-02 ~19:3xZ). The orders below are those
orders' real shape: OddsAPI hash, the odds feed's team names, `book: bovada`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import bet_status_ncaab as mod
from syndicate.features.shared import bet_status_nfl, population_outcomes_espn
from syndicate.features.shared.bet_status_wncaab import wncaab_status_resolver
from syndicate.features.shared.paper_settlement import _default_resolver, _our_verdict

DATE = "2026-11-02"
AFTER_THE_GAMES = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)
BEFORE_TIP = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)


def _side(home_away, name, periods, *, score=None):
    return {
        "homeAway": home_away,
        "team": {"id": name[:4], "displayName": name},
        "score": str(sum(periods) if score is None else score),
        "linescores": [
            {"value": float(points), "displayValue": str(points), "period": number}
            for number, points in enumerate(periods, start=1)
        ],
    }


def _event(event_id, home, away, home_periods, away_periods, *, state="post", completed=True,
           name="STATUS_FINAL", neutral=False, home_score=None):
    status = {"period": len(home_periods), "type": {"state": state, "completed": completed, "name": name,
                                                    "shortDetail": "Final" if completed else name}}
    return {
        "id": event_id,
        "date": "2026-11-03T00:00Z",
        "status": status,
        "competitions": [{
            "neutralSite": neutral,
            "status": status,
            "competitors": [
                _side("home", home, home_periods, score=home_score),
                _side("away", away, away_periods),
            ],
        }],
    }


# The two real 11-02 games, with made-up finals.
YALE_HOWARD = _event("401924743", "Yale Bulldogs", "Howard Bison", [40, 38], [30, 35])
RICHMOND_UNCA = _event("401911237", "Richmond Spiders", "UNC Asheville Bulldogs", [31, 30], [36, 34])
# Two overtimes: h2 is period 2 plus 3 and 4 under a book that counts overtime.
DUKE_UNC_2OT = _event("401900001", "Duke Blue Devils", "North Carolina Tar Heels", [35, 30, 8, 9], [33, 32, 8, 5])


_EVENTS = object()


class _Feed:
    """`fetch_json`: every URL asked for, one payload for every date (`payload=None` is a
    read that failed)."""

    def __init__(self, *events, payload=_EVENTS):
        self.urls: list[str] = []
        self.payload = {"events": list(events)} if payload is _EVENTS else payload

    def __call__(self, url):
        self.urls.append(url)
        return self.payload


@pytest.fixture(autouse=True)
def _after_the_games(monkeypatch):
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: AFTER_THE_GAMES)


def _order(**kw):
    order = {"sport": "ncaab", "mode": "paper", "venue": "paper", "status": "filled", "book": "bovada",
             "event_id": "c5189ac34ee35b759f907342dde69951", "market": "h2h", "segment": "full",
             "side": "home", "line": None, "home_team": "Yale Bulldogs", "away_team": "Howard Bison",
             "commence_time": "2026-11-03 00:00:00+00:00", "fill_price": -245.0, "fill_stake_dollars": 10.0,
             "selected_date": DATE, "idempotency_key": "k1"}
    order.update(kw)
    return order


def _grade(order, resolver):
    verdict, resolved, refusal = _our_verdict(order, resolver)
    return verdict, resolved, refusal


# ---------------------------------------------------------------------------
# Reachability: the SAME dispatcher settlement uses, and the URL it reads
# ---------------------------------------------------------------------------


def test_an_ncaab_order_reaches_espn_through_the_settlement_dispatcher(monkeypatch):
    feed = _Feed(YALE_HOWARD, RICHMOND_UNCA)
    monkeypatch.setattr(population_outcomes_espn, "_default_fetch_json", feed)

    verdict, resolved, refusal = _grade(_order(), _default_resolver(DATE))

    assert refusal == ""
    assert resolved["espn_event_id"] == "401924743"
    assert verdict["outcome"] == "won"
    # The Eastern date of a 7 PM ET tip, and the Division I filter.
    assert feed.urls == [
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        "?dates=20261102&groups=50&limit=500"
    ]


def test_wncaab_dispatches_to_its_own_resolver():
    verdict = _default_resolver(DATE)({"sport": "wncaab", "market": "h2h"})
    assert verdict.get("unavailable_reason") != "no_resolver_for_wncaab"


def test_the_womens_resolver_reads_the_womens_scoreboard(womens_map):
    feed = _Feed(SC_MD_OT)
    wncaab_status_resolver(DATE, fetch_json=feed)(
        _order(sport="wncaab", home_team="South Carolina Gamecocks", away_team="Maryland Terrapins"))
    assert feed.urls == [
        "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard"
        "?dates=20261102&groups=50&limit=500"
    ]


# ---------------------------------------------------------------------------
# Full game
# ---------------------------------------------------------------------------


def test_the_two_real_1102_orders_grade_against_the_final():
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(YALE_HOWARD, RICHMOND_UNCA))

    yale, _, _ = _grade(_order(), resolver)
    richmond, _, _ = _grade(_order(home_team="Richmond Spiders", away_team="UNC Asheville Bulldogs",
                                   event_id="0f54e76dec4ba99841b26be0dff31b52", fill_price=-750.0), resolver)

    assert yale["outcome"] == "won"  # 78-65
    assert yale["pnl_dollars"] == pytest.approx(10 * 100 / 245, abs=0.01)
    assert richmond["outcome"] == "lost"  # 61-70
    assert richmond["pnl_dollars"] == pytest.approx(-10.0)


def test_one_scoreboard_read_serves_every_order_on_the_date():
    feed = _Feed(YALE_HOWARD, RICHMOND_UNCA)
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=feed)
    resolver(_order())
    resolver(_order(side="away"))
    resolver(_order(home_team="Richmond Spiders", away_team="UNC Asheville Bulldogs"))
    assert len(feed.urls) == 1


def test_spreads_and_totals():
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(YALE_HOWARD))

    covered, _, _ = _grade(_order(market="spreads", side="Yale Bulldogs", line=-12.5), resolver)
    missed, _, _ = _grade(_order(market="spreads", side="Yale Bulldogs", line=-13.5), resolver)
    over, _, _ = _grade(_order(market="totals", side="over", line=142.5), resolver)
    push, _, _ = _grade(_order(market="totals", side="under", line=143.0), resolver)

    assert (covered["outcome"], missed["outcome"]) == ("won", "lost")  # margin 13
    assert over["outcome"] == "won"  # 143
    assert push["outcome"] == "push"


def test_a_neutral_site_game_espn_lists_the_other_way_round_grades_in_the_orders_orientation():
    """At a neutral site ESPN and OddsAPI pick different 'home' teams (6 of 119 on 11-02).
    A positional `home` bet is the ODDS FEED's home team, so the scores must be swapped."""
    flipped = _event("401924743", "Howard Bison", "Yale Bulldogs", [30, 35], [40, 38], neutral=True)
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(flipped))

    verdict, resolved, _ = _grade(_order(side="home"), resolver)

    assert resolved["matched_by"] == "espn_scoreboard:swapped"
    assert resolved["home_score"] == 78.0
    assert verdict["outcome"] == "won"  # Yale, the order's home team, won 78-65


def test_a_live_game_does_not_decide_a_moneyline():
    live = _event("401924743", "Yale Bulldogs", "Howard Bison", [40], [30], state="in", completed=False,
                  name="STATUS_IN_PROGRESS")
    verdict, resolved, refusal = _grade(_order(), mod.ncaab_status_resolver(DATE, fetch_json=_Feed(live)))
    assert verdict is None and refusal == "not_decided_yet"
    assert resolved["is_final"] is False and resolved["started"] is True


def test_a_game_that_has_not_tipped_reads_not_started_without_a_read(monkeypatch):
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: BEFORE_TIP)
    feed = _Feed(YALE_HOWARD)
    resolved = mod.ncaab_status_resolver(DATE, fetch_json=feed)(_order())
    assert resolved == {"current_value": None, "is_final": False, "started": False}
    assert feed.urls == []


def test_a_postponed_game_never_grades_off_its_zero_score():
    postponed = _event("401924743", "Yale Bulldogs", "Howard Bison", [], [], state="post", completed=False,
                       name="STATUS_POSTPONED")
    resolved = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(postponed))(_order())
    assert resolved["unavailable_reason"] == "ncaab_game_not_completed:STATUS_POSTPONED"


# ---------------------------------------------------------------------------
# Halves (men)
# ---------------------------------------------------------------------------


def test_a_first_half_is_period_one_alone():
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(YALE_HOWARD))
    verdict, resolved, _ = _grade(_order(market="totals", segment="h1", side="under", line=70.5), resolver)
    assert (resolved["home_score"], resolved["away_score"]) == (40.0, 30.0)
    assert resolved["segment_periods"] == [1]
    assert verdict["outcome"] == "won"


def test_a_second_half_takes_overtime_under_a_book_that_counts_it():
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(DUKE_UNC_2OT))
    order = _order(home_team="Duke Blue Devils", away_team="North Carolina Tar Heels", market="totals",
                   segment="h2", side="over", line=70.5, book="draftkings")
    verdict, resolved, _ = _grade(order, resolver)
    assert resolved["segment_periods"] == [2, 3, 4]
    assert resolved["current_value"] == 30 + 8 + 9 + 32 + 8 + 5
    assert verdict["outcome"] == "won"


def test_overtime_under_an_unread_book_refuses_rather_than_guesses():
    resolver = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(DUKE_UNC_2OT))
    order = _order(home_team="Duke Blue Devils", away_team="North Carolina Tar Heels", market="totals",
                   segment="h2", side="over", line=70.5)
    assert resolver(order)["unavailable_reason"] == "ncaab_overtime_rule_unread:bovada"
    # ...but a game with no overtime grades for any book: every rule agrees there.
    assert _grade(_order(market="spreads", segment="h2", side="home", line=-1.5),
                  mod.ncaab_status_resolver(DATE, fetch_json=_Feed(YALE_HOWARD)))[0]["outcome"] == "won"  # 38-35


def test_a_segment_waits_for_the_final():
    live = _event("401924743", "Yale Bulldogs", "Howard Bison", [40, 10], [30, 12], state="in", completed=False,
                  name="STATUS_IN_PROGRESS")
    resolved = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(live))(_order(market="totals", segment="h1",
                                                                              side="over", line=60.5))
    assert resolved["unavailable_reason"] == "ncaab_segment_waits_for_final"


def test_a_linescore_that_does_not_sum_to_the_final_refuses():
    short = _event("401924743", "Yale Bulldogs", "Howard Bison", [40, 38], [30, 35], home_score=81)
    resolved = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(short))(_order(market="totals", segment="h1",
                                                                               side="over", line=60.5))
    assert resolved["unavailable_reason"] == "ncaab_linescore_disagrees_with_final"


# ---------------------------------------------------------------------------
# Quarters (women)
# ---------------------------------------------------------------------------

SC_MD_OT = _event("401918849", "South Carolina Gamecocks", "Maryland Terrapins", [33, 28, 17, 23, 9],
                  [14, 19, 26, 42, 5])


@pytest.fixture
def womens_map(monkeypatch):
    """The women's map lands with lane `wncaab-module`; these schools are named alike in both."""
    real = mod._school
    monkeypatch.setattr(mod, "_school", lambda sport, names: real("ncaab", names))


@pytest.mark.parametrize("segment,periods,home,away", [
    ("q1", [1], 33, 14), ("q3", [3], 17, 26), ("h1", [1, 2], 61, 33),
])
def test_womens_quarters_and_halves(womens_map, segment, periods, home, away):
    order = _order(sport="wncaab", home_team="South Carolina Gamecocks", away_team="Maryland Terrapins",
                   market="totals", segment=segment, side="over", line=1.5)
    resolved = wncaab_status_resolver(DATE, fetch_json=_Feed(SC_MD_OT))(order)
    assert resolved["segment_periods"] == periods
    assert (resolved["home_score"], resolved["away_score"]) == (home, away)


@pytest.mark.parametrize("book,periods,margin", [("fanduel", [4], -19.0), ("draftkings", [4, 5], -15.0)])
def test_a_womens_fourth_quarter_takes_overtime_by_the_books_rule(womens_map, book, periods, margin):
    order = _order(sport="wncaab", home_team="South Carolina Gamecocks", away_team="Maryland Terrapins",
                   market="spreads", segment="q4", side="home", line=0.0, book=book)
    resolved = wncaab_status_resolver(DATE, fetch_json=_Feed(SC_MD_OT))(order)
    assert resolved["segment_periods"] == periods
    assert resolved["current_value"] == margin


def test_a_womens_name_the_map_cannot_pin_refuses_by_the_womens_name():
    feed = _Feed(SC_MD_OT)
    resolved = wncaab_status_resolver(DATE, fetch_json=feed)(_order(sport="wncaab", home_team="Bulldogs"))
    assert resolved["unavailable_reason"] == "wncaab_team_not_in_registry_or_ambiguous"
    assert feed.urls == []


# ---------------------------------------------------------------------------
# Permanent refusals come before any read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("change,reason", [
    ({"segment": "q1"}, "unsupported_segment:q1"),
    ({"player_name": "Some Guard", "market": "player_points"}, "ncaab_props_not_graded"),
    ({"market": "h2h_3_way"}, "ncaab_three_way_needs_regulation_score"),
    ({"market": "team_totals"}, "unmapped_market"),
    ({"home_team": "Bulldogs"}, "ncaab_team_not_in_registry_or_ambiguous"),
    ({"home_team": None}, "no_home_away_teams_on_order"),
    ({"sport": "nba"}, "not_an_ncaab_order"),
])
def test_permanent_refusals_never_read_the_feed(change, reason):
    feed = _Feed(YALE_HOWARD)
    assert mod.ncaab_status_resolver(DATE, fetch_json=feed)(_order(**change))["unavailable_reason"] == reason
    assert feed.urls == []


def test_an_unreadable_scoreboard_is_named_apart_from_a_missing_game():
    unreadable = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(payload=None))(_order())
    missing = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(RICHMOND_UNCA))(_order())
    assert unreadable["unavailable_reason"] == "no_ncaab_scoreboard_for_date"
    assert missing["unavailable_reason"] == "game_not_in_ncaab_scoreboard"


def test_the_same_pair_twice_on_a_date_refuses_both():
    again = _event("401999999", "Yale Bulldogs", "Howard Bison", [1, 1], [2, 2])
    resolved = mod.ncaab_status_resolver(DATE, fetch_json=_Feed(YALE_HOWARD, again))(_order())
    assert resolved["unavailable_reason"] == "matchup_twice_in_ncaab_scoreboard"
