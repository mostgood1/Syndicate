"""Football player props that refused for want of a source (#744 H6, 2026-10-27).

Two refused groups, read on the fleet at 2026-10-27 23:15Z:

  NFL    28 rows `nfl_player_not_in_final_box`. ESPN's summary lists a player
         only in a stat group he recorded something in, so a quiet receiver is
         in NO group. ESPN's core GAME ROSTER says who played: 8 of the 11
         player-games played and recorded zero, 2 were inactive, and 1 was a
         name form ("Zonovan Knight" is ESPN's "Bam Knight").
  NCAAF  59 rows `ncaaf_props_not_gradeable_from_scoreboard`. ESPN's college
         summary box is the NFL one's shape; 43 of 44 player-games are in it.

ABSENT IS NEVER ZERO. Every test that grades a zero below grades one ESPN
STATED, behind a proof that the player played.

Hermetic: every ESPN read goes through `bet_status_nfl._default_fetch_json`
(resolved at call time) or `bet_status_nfl._fetch_box`, both replaced here, and
the clock through `bet_status_nfl._utcnow`. The payloads are trimmed to the
shapes measured on the fleet; the numbers are the real ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import bet_status_ncaaf, bet_status_nfl
from syndicate.features.shared.bet_status_ncaaf import ncaaf_status_resolver
from syndicate.features.shared.bet_status_nfl import nfl_status_resolver

NOW = datetime(2026, 10, 27, 23, 15, tzinfo=timezone.utc)
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
CORE_HTTP = "http://sports.core.api.espn.com/v2/sports/football/leagues"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football"

_GROUP_KEYS = {
    "passing": ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt", "passingTouchdowns", "interceptions"],
    "rushing": ["rushingAttempts", "rushingYards", "yardsPerRushAttempt", "rushingTouchdowns", "longRushing"],
    "receiving": ["receptions", "receivingYards", "yardsPerReception", "receivingTouchdowns", "longReception"],
    "defensive": ["totalTackles", "soloTackles"],
}


def _summary(teams):
    """`{abbr: {group: [(name, athlete_id, [cells...]), ...]}}` -> ESPN's summary shape."""
    return {
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": abbr},
                    "statistics": [
                        {
                            "name": group,
                            "keys": _GROUP_KEYS[group],
                            "athletes": [
                                {"athlete": {"id": str(aid), "displayName": name}, "stats": cells}
                                for name, aid, cells in athletes
                            ],
                        }
                        for group, athletes in groups.items()
                    ],
                }
                for abbr, groups in teams.items()
            ]
        }
    }


class FakeEspn:
    """URL -> payload. An unknown URL reads as an outage (None). Records every call."""

    def __init__(self, routes=None, *, raises=False):
        self.routes = dict(routes or {})
        self.calls: list[str] = []
        self.raises = raises

    def __call__(self, url):
        self.calls.append(url)
        if self.raises:
            raise TimeoutError("simulated ESPN timeout")
        return self.routes.get(url)

    def core_calls(self):
        return [url for url in self.calls if "sports.core.api.espn.com" in url]


@pytest.fixture(autouse=True)
def memo(monkeypatch):
    """A FRESH process-wide refusal memo for every test, restored afterwards,
    so no test can see another's refusals -- in this file or any other."""
    fresh: dict = {}
    monkeypatch.setattr(bet_status_nfl, "_SETTLEMENT_MEMO", fresh)
    return fresh


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: NOW)


def _at(monkeypatch, moment):
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: moment)


@pytest.fixture
def espn(monkeypatch):
    def install(routes=None, **kwargs):
        fake = FakeEspn(routes, **kwargs)
        monkeypatch.setattr(bet_status_nfl, "_default_fetch_json", fake)
        return fake

    return install


# ---------------------------------------------------------------------------
# NFL fixtures: DEN @ SF, ESPN 401872975, 2026-10-04 (final SF 26 - DEN 23)
# ---------------------------------------------------------------------------

NFL_EVENT = "401872975"
NFL_KICKOFF = "2026-10-04T20:25Z"


def _nfl_record(**over):
    row = {
        "event_id": NFL_EVENT,
        "home_team": "San Francisco 49ers",
        "away_team": "Denver Broncos",
        "home_abbr": "SF",
        "away_abbr": "DEN",
        "home_score": 26,
        "away_score": 23,
        "in_progress": False,
        "final": True,
        "status": "Final",
        "start_time": NFL_KICKOFF,
    }
    row.update(over)
    return row


def _nfl_order(**over):
    row = {
        "sport": "nfl",
        "market": "Receptions",
        "player_name": "Troy Franklin",
        "side": "over",
        "line": 0.5,
        "segment": "full",
        "home_team": "San Francisco 49ers",
        "away_team": "Denver Broncos",
        "commence_time": "2026-10-04T20:25:00Z",
        "selected_date": "2026-10-02",
    }
    row.update(over)
    return row


# Troy Franklin is in NO group: no catch, no carry. Courtland Sutton is.
NFL_BOX = _summary(
    {
        "DEN": {
            "receiving": [("Courtland Sutton", 3128429, ["6", "71", "11.8", "1", "24"])],
            "rushing": [("RJ Harvey", 4568490, ["14", "52", "3.7", "0", "11"])],
        },
        "SF": {"receiving": [("George Kittle", 3040151, ["5", "48", "9.6", "0", "17"])]},
    }
)


def _entry(team_id, player_id, surname, *, did_not_play=False, stats=True):
    row = {
        "playerId": player_id,
        "displayName": surname,
        "didNotPlay": did_not_play,
        "athlete": {"$ref": f"{CORE_HTTP}/nfl/seasons/2026/athletes/{player_id}?lang=en&region=us"},
    }
    if stats:
        row["statistics"] = {
            "$ref": f"{CORE_HTTP}/nfl/events/{NFL_EVENT}/competitions/{NFL_EVENT}/competitors/{team_id}"
            f"/roster/{player_id}/statistics/0?lang=en&region=us"
        }
    return row


def _athlete_url(player_id):
    return f"{CORE}/nfl/seasons/2026/athletes/{player_id}?lang=en&region=us"


def _stats_url(team_id, player_id):
    return (
        f"{CORE}/nfl/events/{NFL_EVENT}/competitions/{NFL_EVENT}/competitors/{team_id}"
        f"/roster/{player_id}/statistics/0?lang=en&region=us"
    )


def _game_stats(games_played=1.0, **values):
    """`receiving_receptions=0.0` -> the core API's categories shape."""
    categories: dict[str, list] = {"general": [{"name": "gamesPlayed", "value": games_played}]}
    for key, value in values.items():
        category, _, name = key.partition("_")
        categories.setdefault(category, []).append({"name": name, "value": value})
    return {"splits": {"categories": [{"name": name, "stats": stats} for name, stats in categories.items()]}}


FRANKLIN_ZEROS = _game_stats(
    receiving_receptions=0.0,
    receiving_receivingYards=0.0,
    receiving_receivingTouchdowns=0.0,
    rushing_rushingAttempts=0.0,
    rushing_rushingTouchdowns=0.0,
)


def _nfl_routes(den_entries, sf_entries=None, *, extra=None):
    base = f"{CORE}/nfl/events/{NFL_EVENT}/competitions/{NFL_EVENT}/competitors"
    routes = {
        base: {"items": [{"id": "25"}, {"id": "7"}]},
        f"{base}/7/roster": {"entries": den_entries},
        f"{base}/25/roster": {"entries": sf_entries if sf_entries is not None else [_entry("25", 3040151, "Kittle")]},
        _athlete_url(4431280): {"fullName": "Troy Franklin", "displayName": "Troy Franklin", "firstName": "Troy", "lastName": "Franklin"},
        _athlete_url(3040151): {"fullName": "George Kittle", "displayName": "George Kittle", "firstName": "George", "lastName": "Kittle"},
    }
    routes.update(extra or {})
    return routes


@pytest.fixture
def nfl_game(monkeypatch):
    """The capture and the summary box, offline. Returns the box fetch log."""
    from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary

    box_calls: list[str] = []

    def install(record=None, box=NFL_BOX):
        def fetch_box(event_id):
            box_calls.append(event_id)
            return player_stat_rows_from_summary(box)

        monkeypatch.setattr(bet_status_nfl, "_load_games", lambda _d: [record or _nfl_record()])
        monkeypatch.setattr(bet_status_nfl, "_fetch_box", fetch_box)
        return box_calls

    return install


# ---------------------------------------------------------------------------
# 0. OFF != ON -- the new branches are REACHED, from the settlement wiring
# ---------------------------------------------------------------------------


def test_FIRST_the_nfl_roster_path_is_REACHED_from_settlement_and_only_after_the_window(nfl_game, espn, monkeypatch):
    """`value_source` is set by the roster path and nothing else. Reached
    through `paper_settlement`'s own dispatch and `_our_verdict` -- the call
    settlement grades with -- so a resolver that was correct but unwired fails.

    OFF: the same order inside the settlement window refuses as it always did
    and touches nothing on the core API. ON: past it, Franklin's stated zero
    grades, and his over 0.5 LOSES."""
    from syndicate.features.shared.paper_settlement import OUTCOME_LOST, _default_resolver, _our_verdict

    nfl_game()
    fake = espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS}))
    order = {**_nfl_order(), "status": "filled", "fill_stake_dollars": 3.08, "fill_price": -156}

    # OFF: two hours after kickoff, final -- inside the window.
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: datetime(2026, 10, 4, 22, 25, tzinfo=timezone.utc))
    verdict, resolved, refusal = _our_verdict(dict(order), _default_resolver("2026-10-02"))
    assert verdict is None and refusal == bet_status_nfl.REASON_PLAYER_NOT_IN_BOX
    assert "value_source" not in resolved
    assert fake.calls == []

    # ON: the 23:15Z reading's clock.
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: NOW)
    verdict, resolved, refusal = _our_verdict(dict(order), _default_resolver("2026-10-02"))
    assert refusal == "", refusal
    assert resolved["value_source"] == bet_status_nfl.VALUE_SOURCE_CORE_GAME_STATS
    assert resolved["current_value"] == 0.0 and resolved["is_final"] is True
    assert verdict["outcome"] == OUTCOME_LOST


def test_FIRST_the_ncaaf_box_path_is_REACHED_from_settlement(ncaaf_game, espn, clock):
    """`value_source` is set by the NCAAF prop path only. Before it existed
    this exact order read `ncaaf_props_not_gradeable_from_scoreboard`."""
    from syndicate.features.shared.paper_settlement import OUTCOME_WON, _default_resolver, _our_verdict

    ncaaf_game()
    espn({NCAAF_SUMMARY_URL: NCAAF_BOX})
    order = {
        **_ncaaf_order(player_name="Zacharyus Williams", market="Receptions", side="under", line=2.5),
        "status": "filled",
        "fill_stake_dollars": 5.0,
        "fill_price": -110,
    }

    verdict, resolved, refusal = _our_verdict(order, _default_resolver("2026-10-24"))

    assert refusal == "", refusal
    assert resolved["value_source"] == bet_status_ncaaf.VALUE_SOURCE_SUMMARY_BOX
    assert resolved["current_value"] == 2.0
    assert verdict["outcome"] == OUTCOME_WON


# ---------------------------------------------------------------------------
# 1. NFL: who played, who did not, and what is never a zero
# ---------------------------------------------------------------------------


def test_an_INACTIVE_player_refuses_as_dnp_void_and_is_never_graded_zero(nfl_game, espn, clock):
    """Tyler Warren / Tyjae Spears, 2026-10-18 and 10-25: `didNotPlay: true`,
    no statistics. Books void; this refuses BY NAME, as NHL and soccer do."""
    nfl_game()
    espn(_nfl_routes([_entry("7", 4431280, "Franklin", did_not_play=True, stats=False)]))

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_DNP_VOID}


@pytest.mark.parametrize(
    "did_not_play, stats",
    [
        # Measured: 2 roster rows on 11 games (Clark Phillips III, Jamaal
        # Pritchett) carry `didNotPlay: true` WITH `gamesPlayed: 1`.
        (True, True),
        # 49 rows carry `didNotPlay: false` and no statistics at all.
        (False, False),
        # The flag absent proves nothing either way.
        (None, True),
    ],
)
def test_flags_that_DISAGREE_or_are_missing_refuse_rather_than_pick_one(nfl_game, espn, clock, did_not_play, stats):
    nfl_game()
    entry = _entry("7", 4431280, "Franklin", did_not_play=did_not_play, stats=stats)
    if did_not_play is None:
        entry.pop("didNotPlay")
    espn(_nfl_routes([entry], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS}))

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_PARTICIPATION_UNKNOWN}


def test_games_played_ZERO_is_not_proof_of_playing(nfl_game, espn, clock):
    nfl_game()
    espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): _game_stats(0.0, receiving_receptions=0.0)}))

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_PARTICIPATION_UNKNOWN}


def test_a_stat_ESPN_did_not_state_is_refused_not_read_as_zero(nfl_game, espn, clock):
    """He played (gamesPlayed 1) but the receiving category is missing: the
    receptions number was never stated, so it is not 0."""
    nfl_game()
    espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): _game_stats(rushing_rushingAttempts=0.0)}))

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_STAT_NOT_IN_GAME_STATS}


def test_a_shared_SURNAME_never_stands_in_for_the_player(nfl_game, espn, clock):
    """The roster row carries a surname only. A different Franklin on the
    roster is not Troy Franklin, and nothing grades off him."""
    nfl_game()
    espn(
        _nfl_routes(
            [_entry("7", 9999, "Franklin")],
            extra={
                _athlete_url(9999): {"fullName": "Zach Franklin", "displayName": "Zach Franklin"},
                _stats_url("7", 9999): _game_stats(receiving_receptions=4.0),
            },
        )
    )

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_NOT_ON_GAME_ROSTER}


def test_the_right_player_is_picked_from_two_SAME_SURNAME_candidates(nfl_game, espn, clock):
    nfl_game()
    espn(
        _nfl_routes(
            [_entry("7", 4431280, "Franklin")],
            [_entry("25", 9999, "Franklin")],
            extra={
                _athlete_url(9999): {"fullName": "Zach Franklin", "displayName": "Zach Franklin"},
                _stats_url("7", 4431280): FRANKLIN_ZEROS,
            },
        )
    )

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view["current_value"] == 0.0
    assert view["value_source"] == bet_status_nfl.VALUE_SOURCE_CORE_GAME_STATS


def test_an_UNREADABLE_candidate_refuses_rather_than_claiming_absence(nfl_game, espn, clock):
    nfl_game()
    routes = _nfl_routes([_entry("7", 4431280, "Franklin")])
    routes.pop(_athlete_url(4431280))
    espn(routes)

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_ROSTER_UNAVAILABLE}


def test_HALF_a_roster_is_not_a_roster(nfl_game, espn, clock):
    nfl_game()
    routes = _nfl_routes([_entry("7", 4431280, "Franklin")])
    routes.pop(f"{CORE}/nfl/events/{NFL_EVENT}/competitions/{NFL_EVENT}/competitors/25/roster")
    espn(routes)

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_ROSTER_UNAVAILABLE}


def test_a_link_to_ANY_OTHER_HOST_is_not_followed(nfl_game, espn, clock):
    nfl_game()
    entry = _entry("7", 4431280, "Franklin")
    entry["athlete"] = {"$ref": "https://example.com/athletes/4431280"}
    fake = espn(_nfl_routes([entry]))

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_ROSTER_UNAVAILABLE}
    assert not any("example.com" in url for url in fake.calls)


def test_a_RAISING_fetch_degrades_to_a_named_refusal(nfl_game, espn, clock):
    nfl_game()
    espn(raises=True)
    assert nfl_status_resolver("2026-10-02")(_nfl_order()) == {
        "unavailable_reason": bet_status_nfl.REASON_ROSTER_UNAVAILABLE
    }


def test_a_RAISING_roster_reader_degrades_to_a_named_refusal(nfl_game, espn, clock, monkeypatch):
    nfl_game()
    espn({})

    def boom(*_a, **_k):
        raise RuntimeError("parser bug")

    monkeypatch.setattr(bet_status_nfl, "roster_participation", boom)
    assert nfl_status_resolver("2026-10-02")(_nfl_order()) == {
        "unavailable_reason": bet_status_nfl.REASON_PARTICIPATION_READ_FAILED
    }


@pytest.mark.parametrize(
    "record_start, commence",
    [
        ("2026-10-27T19:00Z", "2026-10-27T19:00:00Z"),  # 4h15m ago: inside the window
        (None, None),  # no kickoff anywhere: unknown must not open it
        ("", "2026-10-04"),  # a bare date carries no hour
    ],
)
def test_NO_core_read_until_a_readable_kickoff_is_six_hours_old(nfl_game, espn, clock, memo, record_start, commence):
    nfl_game(_nfl_record(start_time=record_start))
    fake = espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS}))

    view = nfl_status_resolver("2026-10-02")(_nfl_order(commence_time=commence))

    assert view == {"unavailable_reason": bet_status_nfl.REASON_PLAYER_NOT_IN_BOX}
    assert fake.calls == []
    assert memo == {}  # inside the window nothing is remembered either


def test_a_LIVE_game_absence_is_only_not_yet_and_reads_nothing(nfl_game, espn, clock):
    nfl_game(_nfl_record(final=False, in_progress=True))
    fake = espn(_nfl_routes([_entry("7", 4431280, "Franklin")]))

    view = nfl_status_resolver("2026-10-02")(_nfl_order())

    assert view == {"unavailable_reason": bet_status_nfl.REASON_PLAYER_NOT_IN_BOX_YET}
    assert fake.calls == []


def test_the_roster_is_read_ONCE_per_game_per_resolver(nfl_game, espn, clock):
    nfl_game()
    fake = espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS}))
    resolve = nfl_status_resolver("2026-10-02")

    for line in (0.5, 1.5, 2.5):
        assert resolve(_nfl_order(line=line))["current_value"] == 0.0
    assert resolve(_nfl_order(market="Rushing Attempts"))["current_value"] == 0.0

    assert len(fake.calls) == len(set(fake.calls)) == 5  # competitors, 2 rosters, athlete, stats


def test_anytime_TD_off_the_roster_path_keeps_the_implicit_line(nfl_game, espn, clock):
    """Jonnu Smith, CHI @ GB 2026-10-11: played, no touch -- a 'yes' loses."""
    nfl_game()
    espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS}))

    view = nfl_status_resolver("2026-10-02")(_nfl_order(market="Anytime TD", side="yes", line=None))

    assert view["current_value"] == 0.0 and view["line"] == 0.5


def test_a_player_IN_the_box_never_reaches_the_roster(nfl_game, espn, clock):
    nfl_game()
    fake = espn({})

    view = nfl_status_resolver("2026-10-02")(_nfl_order(player_name="Courtland Sutton"))

    assert view["current_value"] == 6.0 and "value_source" not in view
    assert fake.calls == []


def test_the_board_name_ZONOVAN_Knight_joins_ESPNs_BAM_Knight(nfl_game, espn, clock):
    """ARI @ DEN 2026-10-25: ESPN's athlete 4427728 is "Bam Knight" in every
    name field; the board sends "Zonovan Knight". 7 rushes, per the box."""
    box = _summary({"ARI": {"rushing": [("Bam Knight", 4427728, ["7", "48", "6.9", "0", "29"])]}})
    nfl_game(_nfl_record(home_team="Arizona Cardinals", away_team="Denver Broncos", home_abbr="ARI"), box=box)
    fake = espn({})

    view = nfl_status_resolver("2026-10-23")(
        _nfl_order(
            player_name="Zonovan Knight",
            market="Rushing Attempts",
            line=10.5,
            home_team="Arizona Cardinals",
            away_team="Denver Broncos",
        )
    )

    assert view["current_value"] == 7.0
    assert fake.calls == []


# ---------------------------------------------------------------------------
# 2. NCAAF: the college summary box, graded under the same rules
# ---------------------------------------------------------------------------

NCAAF_EVENT = "401858500"
NCAAF_SUMMARY_URL = f"{SITE}/college-football/summary?event={NCAAF_EVENT}"
# The real USC @ Wisconsin lines (2026-10-24), filed under the fixture's teams.
NCAAF_BOX = _summary(
    {
        "TCU": {
            "passing": [("Josh Hoover", 4685541, ["31/50", "258", "5.2", "1", "2"])],
            "receiving": [
                ("Zacharyus Williams", 5141547, ["2", "14", "7.0", "0", "9"]),
                ("Taniela Tupou", 4880264, ["6", "46", "7.7", "1", "10"]),
            ],
        },
        "UNC": {"defensive": [("Kaimon Rucker", 4426483, ["0", "0"])]},
    }
)


def _ncaaf_record(**over):
    row = {
        "event_id": NCAAF_EVENT,
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
        "home_abbr": "TCU",
        "away_abbr": "UNC",
        "home_score": 27,
        "away_score": 20,
        "in_progress": False,
        "final": True,
        "status": "Final",
        "start_time": "2026-10-24T23:30Z",
    }
    row.update(over)
    return row


def _ncaaf_order(**over):
    row = {
        "sport": "ncaaf",
        "market": "Receptions",
        "player_name": "Zacharyus Williams",
        "side": "under",
        "line": 2.5,
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
        "commence_time": "2026-10-24T23:30:00Z",
        "selected_date": "2026-10-24",
    }
    row.update(over)
    return row


@pytest.fixture
def ncaaf_game(monkeypatch):
    """Install the capture. Returns the capture dates read."""
    reads: list[str] = []

    def install(record=None):
        def load(capture_date):
            reads.append(capture_date)
            return [record or _ncaaf_record()]

        monkeypatch.setattr(bet_status_ncaaf, "_load_games", load)
        return reads

    return install


@pytest.mark.parametrize(
    "market, player, expected",
    [
        ("Receptions", "Taniela Tupou", 6.0),
        ("Receiving Yards", "Taniela Tupou", 46.0),
        ("Passing TDs", "Josh Hoover", 1.0),
        ("player_receptions", "Zacharyus Williams", 2.0),
        # A defender in the box played: his receptions are a stated zero.
        ("Receptions", "Kaimon Rucker", 0.0),
    ],
)
def test_ncaaf_props_grade_off_the_college_box(ncaaf_game, espn, clock, market, player, expected):
    ncaaf_game()
    espn({NCAAF_SUMMARY_URL: NCAAF_BOX})

    view = ncaaf_status_resolver("2026-10-24")(_ncaaf_order(market=market, player_name=player))

    assert view.get("unavailable_reason") is None, view
    assert view["current_value"] == expected
    assert view["is_final"] is True and view["started"] is True


def test_ncaaf_ABSENT_from_the_box_refuses_and_is_never_zero(ncaaf_game, espn, clock):
    """Mark Bowman, USC @ Wisconsin: in no group. The college roster cannot say
    whether he played (every row `didNotPlay: false`), so it is not asked."""
    ncaaf_game()
    fake = espn({NCAAF_SUMMARY_URL: NCAAF_BOX})

    view = ncaaf_status_resolver("2026-10-24")(_ncaaf_order(player_name="Mark Bowman", side="over", line=3.5))

    assert view == {"unavailable_reason": bet_status_ncaaf.REASON_PLAYER_NOT_IN_BOX}
    assert fake.core_calls() == []


def test_ncaaf_NO_read_inside_the_settlement_window(ncaaf_game, espn, monkeypatch):
    monkeypatch.setattr(bet_status_nfl, "_utcnow", lambda: datetime(2026, 10, 25, 2, 30, tzinfo=timezone.utc))
    ncaaf_game()
    fake = espn({NCAAF_SUMMARY_URL: NCAAF_BOX})

    view = ncaaf_status_resolver("2026-10-24")(_ncaaf_order())

    assert view == {"unavailable_reason": bet_status_ncaaf.REASON_BOX_NOT_YET}
    assert fake.calls == []


def test_ncaaf_PREGAME_is_not_started_and_reads_nothing(ncaaf_game, espn, clock):
    ncaaf_game(_ncaaf_record(final=False, in_progress=False, home_score=None, away_score=None))
    fake = espn({NCAAF_SUMMARY_URL: NCAAF_BOX})

    view = ncaaf_status_resolver("2026-10-24")(_ncaaf_order())

    assert view == {"current_value": None, "is_final": False, "started": False}
    assert fake.calls == []


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"market": "Tackles"}, bet_status_ncaaf.REASON_PROP_MARKET),
        ({"segment": "q1"}, bet_status_ncaaf.REASON_PROP_SEGMENT),
    ],
)
def test_ncaaf_PERMANENT_prop_refusals_come_before_any_read(ncaaf_game, espn, clock, over, reason):
    reads = ncaaf_game()
    fake = espn({NCAAF_SUMMARY_URL: NCAAF_BOX})

    view = ncaaf_status_resolver("2026-10-24")(_ncaaf_order(**over))

    assert view == {"unavailable_reason": reason}
    assert reads == [] and fake.calls == []


def test_ncaaf_props_still_join_through_the_REGISTRY(ncaaf_game, espn, clock):
    """An ambiguous mascot cannot stand in for a school on the prop path either."""
    reads = ncaaf_game()
    espn({NCAAF_SUMMARY_URL: NCAAF_BOX})

    view = ncaaf_status_resolver("2026-10-24")(_ncaaf_order(home_team="Tigers"))

    assert view == {"unavailable_reason": bet_status_ncaaf.REASON_TEAM_UNRESOLVED}
    assert reads == []


@pytest.mark.parametrize("raises", [False, True])
def test_ncaaf_unreadable_or_raising_box_is_a_named_refusal(ncaaf_game, espn, clock, raises):
    ncaaf_game()
    espn({}, raises=raises)
    assert ncaaf_status_resolver("2026-10-24")(_ncaaf_order()) == {
        "unavailable_reason": bet_status_ncaaf.REASON_NO_BOX
    }


def test_ncaaf_the_box_is_read_ONCE_per_game_per_resolver(ncaaf_game, espn, clock):
    ncaaf_game()
    fake = espn({NCAAF_SUMMARY_URL: NCAAF_BOX})
    resolve = ncaaf_status_resolver("2026-10-24")

    for player in ("Zacharyus Williams", "Taniela Tupou", "Josh Hoover", "Mark Bowman"):
        resolve(_ncaaf_order(player_name=player))

    assert fake.calls == [NCAAF_SUMMARY_URL]


def test_ncaaf_game_lines_are_untouched_by_the_prop_path(ncaaf_game, espn, clock):
    ncaaf_game()
    fake = espn({})

    view = ncaaf_status_resolver("2026-10-24")(
        {"sport": "ncaaf", "market": "totals", "side": "over", "line": 44.5,
         "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels",
         "commence_time": "2026-10-24T23:30:00Z"}
    )

    assert view == {"current_value": 47.0, "is_final": True, "started": True}
    assert fake.calls == []


# ---------------------------------------------------------------------------
# 3. The process-wide refusal memo: a refused row is re-asked every settlement
#    tick (then hourly for 14 days once archived), each time by a NEW resolver.
# ---------------------------------------------------------------------------

DNP_ROUTES = [_entry("7", 4431280, "Franklin", did_not_play=True, stats=False)]


def test_a_memoised_DNP_is_NOT_re_read_by_the_next_resolver(nfl_game, espn, clock, memo):
    box_calls = nfl_game()
    fake = espn(_nfl_routes(DNP_ROUTES))

    first = nfl_status_resolver("2026-10-02")(_nfl_order())
    reads = len(fake.calls)
    assert first == {"unavailable_reason": bet_status_nfl.REASON_DNP_VOID}
    assert reads == 4 and box_calls == [NFL_EVENT]  # competitors, 2 rosters, athlete; the box once
    assert list(memo) == [("nfl", NFL_EVENT, "troy franklin")]

    # The next tick: a NEW resolver, and another market on the same player.
    for order in (_nfl_order(), _nfl_order(market="Rushing Attempts", line=1.5)):
        assert nfl_status_resolver("2026-10-02")(order) == first
    assert len(fake.calls) == reads, "a memoised refusal re-read ESPN"
    assert box_calls == [NFL_EVENT], "a memoised refusal re-read the summary box"


def test_a_DEFINITIVE_refusal_is_re_read_only_after_SIX_hours(nfl_game, espn, monkeypatch):
    _at(monkeypatch, NOW)
    nfl_game()
    fake = espn(_nfl_routes(DNP_ROUTES))
    nfl_status_resolver("2026-10-02")(_nfl_order())
    reads = len(fake.calls)

    _at(monkeypatch, NOW + timedelta(hours=5, minutes=59))
    nfl_status_resolver("2026-10-02")(_nfl_order())
    assert len(fake.calls) == reads

    _at(monkeypatch, NOW + timedelta(hours=6, minutes=1))
    assert nfl_status_resolver("2026-10-02")(_nfl_order()) == {"unavailable_reason": bet_status_nfl.REASON_DNP_VOID}
    assert len(fake.calls) == 2 * reads


def test_a_READ_FAILURE_is_retried_after_ONE_hour_and_then_grades(nfl_game, espn, monkeypatch, memo):
    _at(monkeypatch, NOW)
    nfl_game()
    routes = _nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS})
    roster_url = f"{CORE}/nfl/events/{NFL_EVENT}/competitions/{NFL_EVENT}/competitors/7/roster"
    den_roster = routes.pop(roster_url)
    fake = espn(routes)

    assert nfl_status_resolver("2026-10-02")(_nfl_order()) == {
        "unavailable_reason": bet_status_nfl.REASON_ROSTER_UNAVAILABLE
    }
    reads = len(fake.calls)
    fake.routes[roster_url] = den_roster  # ESPN recovers

    _at(monkeypatch, NOW + timedelta(minutes=59))
    assert nfl_status_resolver("2026-10-02")(_nfl_order()) == {
        "unavailable_reason": bet_status_nfl.REASON_ROSTER_UNAVAILABLE
    }
    assert len(fake.calls) == reads

    _at(monkeypatch, NOW + timedelta(minutes=61))
    view = nfl_status_resolver("2026-10-02")(_nfl_order())
    assert view["current_value"] == 0.0
    assert view["value_source"] == bet_status_nfl.VALUE_SOURCE_CORE_GAME_STATS
    assert memo == {}, "a PLAYED answer must not be remembered"


def test_a_PLAYED_answer_is_never_memoised(nfl_game, espn, clock, memo):
    nfl_game()
    espn(_nfl_routes([_entry("7", 4431280, "Franklin")], extra={_stats_url("7", 4431280): FRANKLIN_ZEROS}))

    assert nfl_status_resolver("2026-10-02")(_nfl_order())["current_value"] == 0.0
    assert memo == {}


def test_an_INJECTED_fetch_never_reads_or_writes_the_process_memo(clock, memo):
    feed = bet_status_nfl.EspnSettlementFeed("nfl", fetch_json=lambda _url: None)
    key = bet_status_nfl.settlement_memo_key("nfl", NFL_EVENT, "Troy Franklin")

    bet_status_nfl.settlement_memo_put(feed, key, {"unavailable_reason": "x"}, definitive=True)
    assert memo == {}

    memo[key] = (NOW + timedelta(hours=1), {"unavailable_reason": "x"})
    assert bet_status_nfl.settlement_memo_get(feed, key) is None


def test_the_memo_is_BOUNDED_and_evicts_the_OLDEST_written_first(clock, memo):
    feed = bet_status_nfl.EspnSettlementFeed("nfl")
    limit = bet_status_nfl.SETTLEMENT_MEMO_MAX
    put = bet_status_nfl.settlement_memo_put

    for n in range(limit + 88):
        put(feed, ("nfl", str(n), "p"), {"unavailable_reason": "x"}, definitive=True)
        if n == limit - 1:
            # Rewriting the very first key makes it the NEWEST.
            put(feed, ("nfl", "0", "p"), {"unavailable_reason": "x"}, definitive=True)

    assert len(memo) == limit
    assert ("nfl", "0", "p") in memo
    assert ("nfl", "1", "p") not in memo and ("nfl", "88", "p") not in memo
    assert ("nfl", "89", "p") in memo and ("nfl", str(limit + 87), "p") in memo


def test_ncaaf_NOT_IN_FINAL_BOX_is_not_re_read_by_the_next_resolver(ncaaf_game, espn, clock, memo):
    ncaaf_game()
    fake = espn({NCAAF_SUMMARY_URL: NCAAF_BOX})
    bowman = _ncaaf_order(player_name="Mark Bowman", side="over", line=3.5)

    for _tick in range(3):
        assert ncaaf_status_resolver("2026-10-24")(bowman) == {
            "unavailable_reason": bet_status_ncaaf.REASON_PLAYER_NOT_IN_BOX
        }

    assert fake.calls == [NCAAF_SUMMARY_URL]
    assert list(memo) == [("ncaaf", NCAAF_EVENT, "mark bowman")]


def test_ncaaf_an_UNREAD_summary_is_retried_after_ONE_hour(ncaaf_game, espn, monkeypatch):
    _at(monkeypatch, NOW)
    ncaaf_game()
    fake = espn({})

    assert ncaaf_status_resolver("2026-10-24")(_ncaaf_order()) == {
        "unavailable_reason": bet_status_ncaaf.REASON_NO_BOX
    }
    fake.routes[NCAAF_SUMMARY_URL] = NCAAF_BOX

    _at(monkeypatch, NOW + timedelta(minutes=59))
    assert ncaaf_status_resolver("2026-10-24")(_ncaaf_order())["unavailable_reason"] == bet_status_ncaaf.REASON_NO_BOX
    assert fake.calls == [NCAAF_SUMMARY_URL]

    _at(monkeypatch, NOW + timedelta(minutes=61))
    assert ncaaf_status_resolver("2026-10-24")(_ncaaf_order())["current_value"] == 2.0
    assert fake.calls == [NCAAF_SUMMARY_URL, NCAAF_SUMMARY_URL]
