"""`population_outcomes_mlb.MlbPopulationSettler` -- the MLB rows `bucket_search` skipped.

FIXTURES ARE REAL (`tests/fixtures/population_outcomes/mlb/`), fetched 2026-09-17:
- `records_2026-09-16__mlb.jsonl`: production recorder rows (`opportunity_population_ledger`)
  for three 2026-09-16 games, unmodified -- NYY @ MIN (13 innings), CWS @ CLE (home did not bat
  in the 9th), SF @ STL (10 innings) -- plus DET @ TOR's full-game h2h rows;
- statsapi schedules for 2026-09-16 and 2026-09-04 (a split doubleheader, DET @ CLE), linescores
  and box scores, trimmed to the fields read; `linescore_823655_timecode_20260916_185719.json` is
  statsapi's own linescore AT that timecode (NYY @ MIN, middle of the 5th), and
  `feed_status_...` is the live feed's `gameData.status` at the same timecode.
The two sides of every join come from different sources: team and player names from the odds
feed's recorder rows, games and players from statsapi. Where a test edits a real row (a market
swapped, a commence time moved), it says so.

Every expected result below was read off the linescore by hand, not computed by the code.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import pathlib

import pytest

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared import population_outcomes_mlb as pom
from syndicate.features.shared.population_outcomes_mlb import MlbPopulationSettler

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "population_outcomes" / "mlb"
STATSAPI = "https://statsapi.mlb.com/api/v1"

_spec = importlib.util.spec_from_file_location("bucket_search", ROOT / "scripts" / "bucket_search.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

NYY_MIN = "d2d5b9cc47ff975b91780b6cb7753dae"  # gamePk 823655
CWS_CLE = "97eacfe4e498d0be4c1fb28f0dccad61"  # gamePk 824382
SF_STL = "6e2eb2cc19ebcdb2b0405dff792ab529"  # gamePk 823004
DET_TOR = "fa74757372f1d4cb43bd1510e5ed1213"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


RECORDS = bs.parse_records_text((FIXTURES / "records_2026-09-16__mlb.jsonl").read_text(encoding="utf-8"))


class FakeStatsapi:
    """URL -> fixture payload; anything else is None (a failed fetch). Counts every call."""

    def __init__(self, overrides=None):
        self.routes = {
            f"{STATSAPI}/schedule?sportId=1&date=2026-09-16": "schedule_2026-09-16.json",
            f"{STATSAPI}/schedule?sportId=1&date=2026-09-04": "schedule_2026-09-04.json",
            f"{STATSAPI}/game/823655/boxscore": "boxscore_823655.json",
            f"{STATSAPI}/game/824382/boxscore": "boxscore_824382.json",
        }
        for pk in (823655, 824382, 823004, 824424, 824387):
            self.routes[f"{STATSAPI}/game/{pk}/linescore"] = f"linescore_{pk}.json"
        self.overrides = dict(overrides or {})
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.overrides:
            return copy.deepcopy(self.overrides[url])
        name = self.routes.get(url)
        return _load(name) if name else None


def _row(event, market, segment, side, line=None, player=""):
    """The one real recorder row with this identity, shaped the way `grade_population` shapes it."""
    for record in RECORDS:
        shaped, _ = bs.scorecard_record(record)
        if (shaped["event_id"], shaped["market"], shaped["segment"], shaped["side"], shaped["line"],
                shaped["player_name"]) == (event, market, segment, side, line, player):
            return shaped, mbs.view_from_record(record), record
    raise AssertionError(f"no real row {event} {market} {segment} {side} {line} {player!r}")


def _settle(settler, event, market, segment, side, line=None, player=""):
    shaped, view, _ = _row(event, market, segment, side, line, player)
    return settler(shaped, view)


@pytest.fixture()
def api():
    return FakeStatsapi()


@pytest.fixture()
def settler(api):
    return MlbPopulationSettler(fetch_json=api)


# --------------------------------------------------------------------------
# segments, read off the real linescores
# --------------------------------------------------------------------------
# NYY @ MIN 823655  away [0,0,0,0,0,0,0,0,2,1,1,0,0]  home [1,0,0,0,1,0,0,0,0,1,1,0,1]
#   first1 0-1, first3 0-1, first5 0-2, through 9 2-2, final 4-5
# CWS @ CLE 824382  away [0,0,0,0,3,0,0,0,0]          home [0,0,2,0,0,4,0,0,x]
#   first1 0-0, first5 3-2, final 3-6
# SF @ STL 823004   away [0,0,1,0,0,0,2,1,0,2]        home [0,0,0,0,0,0,2,0,2,1]
#   first1 0-0, through 9 4-4, final 6-5


@pytest.mark.parametrize("event, market, side, line, expected", [
    (NYY_MIN, "totals", "under", 4.0, "win"),        # 2 runs
    (NYY_MIN, "totals", "over", 4.0, "loss"),
    (NYY_MIN, "totals_alt", "over", 2.0, "push"),    # 2 runs on 2.0
    (NYY_MIN, "totals_alt", "under", 2.0, "push"),
    (CWS_CLE, "totals", "over", 3.0, "win"),         # 5 runs
    (CWS_CLE, "totals_alt", "over", 5.0, "push"),
    (CWS_CLE, "totals_alt", "under", 5.0, "push"),
])
def test_first5_totals(settler, event, market, side, line, expected):
    assert _settle(settler, event, market, "first5", side, line) == (expected, None)


@pytest.mark.parametrize("event, market, side, line, expected", [
    (NYY_MIN, "spreads", "away", 1.0, "loss"),       # 0 - 2 + 1 = -1
    (NYY_MIN, "spreads", "home", -1.0, "win"),       # 2 - 0 - 1 = +1
    (NYY_MIN, "spreads_alt", "away", 2.0, "push"),   # 0 - 2 + 2 = 0
    (NYY_MIN, "spreads_alt", "home", -2.0, "push"),
    (CWS_CLE, "spreads_alt", "away", 1.0, "win"),    # 3 - 2 + 1 = +2
    (CWS_CLE, "spreads_alt", "home", -1.0, "loss"),  # 2 - 3 - 1 = -2
    (CWS_CLE, "spreads_alt", "away", -1.0, "push"),  # 3 - 2 - 1 = 0
    (CWS_CLE, "spreads_alt", "home", 1.0, "push"),   # 2 - 3 + 1 = 0
])
def test_first5_run_line_both_sides(settler, event, market, side, line, expected):
    assert _settle(settler, event, market, "first5", side, line) == (expected, None)


@pytest.mark.parametrize("event, side, expected", [
    (CWS_CLE, "draw", "win"), (CWS_CLE, "home", "loss"), (CWS_CLE, "away", "loss"),  # 0-0
    (SF_STL, "draw", "win"), (SF_STL, "home", "loss"), (SF_STL, "away", "loss"),     # 0-0
    (NYY_MIN, "draw", "loss"), (NYY_MIN, "home", "win"), (NYY_MIN, "away", "loss"),  # 0-1
])
def test_first1_three_way_draw_is_a_result(settler, event, side, expected):
    assert _settle(settler, event, "h2h_3_way", "first1", side) == (expected, None)


def test_first1_two_way_tie_is_a_push_and_first5_three_way_has_a_winner(settler):
    assert _settle(settler, CWS_CLE, "h2h", "first1", "home") == ("push", None)
    assert _settle(settler, CWS_CLE, "h2h", "first1", "away") == ("push", None)
    assert _settle(settler, NYY_MIN, "h2h_3_way", "first5", "home") == ("win", None)
    assert _settle(settler, NYY_MIN, "h2h_3_way", "first5", "draw") == ("loss", None)


# --------------------------------------------------------------------------
# full-game rows bucket_search does not grade
# --------------------------------------------------------------------------


def _swap_market(event, market, side, line=None):
    """A real full-game row with its market swapped: none of these markets was recorded full-game on 09-16."""
    shaped, view, _ = _row(event, "h2h" if market == "h2h_3_way" else market.replace("_alt", ""), "full", side, line)
    shaped, view = dict(shaped), dict(view)
    shaped["market"] = view["market"] = market
    return shaped, view


def test_full_game_three_way_settles_on_regulation_not_the_final(settler):
    # NYY @ MIN: 2-2 after nine, MIN won 5-4 in the 13th.
    assert settler(*_swap_market(NYY_MIN, "h2h_3_way", "home")) == ("loss", None)
    draw = dict(_swap_market(NYY_MIN, "h2h_3_way", "home")[0], side="draw")
    assert settler(draw, {}) == ("win", None)
    # SF @ STL: 4-4 after nine, SF won 6-5 in the 10th.
    draw = dict(_swap_market(SF_STL, "h2h_3_way", "away")[0], side="draw")
    assert settler(draw, {}) == ("win", None)


def test_full_game_three_way_when_the_home_team_did_not_bat_in_the_ninth(settler):
    # CWS @ CLE: the home 9th is absent from the linescore; 3-6 through regulation.
    assert settler(*_swap_market(CWS_CLE, "h2h_3_way", "home")) == ("win", None)


def test_full_game_alt_lines_settle_on_the_final_score(settler):
    # Real full-game rows with the market swapped to its alt key (and, for a push, the line moved).
    shaped, view, _ = _row(NYY_MIN, "totals", "full", "over", 8.0)  # final 4-5 = 9
    alt = dict(shaped, market="totals_alt")
    assert settler(alt, dict(view, market="totals_alt")) == ("win", None)
    assert settler(dict(alt, side="under"), {}) == ("loss", None)
    assert settler(dict(alt, line=9.0), {}) == ("push", None)
    shaped, view, _ = _row(NYY_MIN, "spreads", "full", "home", 1.5)  # 5 - 4 + 1.5
    assert settler(dict(shaped, market="spreads_alt"), {}) == ("win", None)
    assert settler(dict(shaped, market="spreads_alt", line=-1.0), {}) == ("push", None)  # 5 - 4 - 1
    assert settler(dict(shaped, market="spreads_alt", side="away", line=-1.5), {}) == ("loss", None)


def test_rules_match_the_scorecards_grade_on_the_base_markets():
    """ONE DEFINITION: `settle_runs` on h2h / spreads / totals IS `layer2_live_scorecard.grade`."""
    grid = [(a, h) for a in range(0, 7) for h in range(0, 7)]
    bets = [("h2h", s, None) for s in ("home", "away", "draw", "over")]
    bets += [("spreads", s, x) for s in ("home", "away", "over") for x in (-2.5, -1.0, 0.0, 1.0, 1.5)]
    bets += [("totals", s, x) for s in ("over", "under", "home") for x in (0.5, 3.0, 6.5)]
    for market, side, line in bets:
        record = {"sport": "mlb", "market": market, "side": side, "line": line}
        for away, home in grid:
            expected = bs.SCORECARD.grade(record, away, home)
            assert pom.settle_runs(market, side, line, away, home) == expected
            assert pom.settle_runs(f"{market}_alt", side, line, away, home) == expected


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------


def _live_at_timecode():
    """statsapi AT 2026-09-16 18:57:19Z: the schedule's NYY @ MIN status set to the live feed's
    status at that timecode, and the linescore endpoint's own reply for that timecode."""
    schedule = _load("schedule_2026-09-16.json")
    status = _load("feed_status_823655_timecode_20260916_185719.json")["gameData"]["status"]
    for game in schedule["dates"][0]["games"]:
        if game["gamePk"] == 823655:
            game["status"] = status
            game["teams"]["away"]["score"] = 0
            game["teams"]["home"]["score"] = 1
    return FakeStatsapi(overrides={
        f"{STATSAPI}/schedule?sportId=1&date=2026-09-16": schedule,
        f"{STATSAPI}/game/823655/linescore": _load("linescore_823655_timecode_20260916_185719.json"),
    })


def test_an_unfinished_segment_is_refused_and_a_finished_one_settles_mid_game():
    settler = MlbPopulationSettler(fetch_json=_live_at_timecode())
    # Middle of the 5th: the bottom of the 5th has not been played.
    assert _settle(settler, NYY_MIN, "totals", "first5", "under", 4.0) == (None, "segment_not_complete")
    assert _settle(settler, NYY_MIN, "h2h_3_way", "first5", "home") == (None, "segment_not_complete")
    # ...but the first three innings are over: 0-1.
    assert _settle(settler, NYY_MIN, "h2h", "first3", "home") == ("win", None)
    # Full-game alt lines wait for the final.
    shaped, _, _ = _row(NYY_MIN, "totals", "full", "over", 8.0)
    assert settler(dict(shaped, market="totals_alt"), {}) == (None, "game_not_final")


def test_runs_through_a_final_game_that_never_reached_the_segment():
    shortened = {"scheduledInnings": 9, "innings": [
        {"num": n, "away": {"runs": 0}, "home": {"runs": 1}} for n in (1, 2, 3, 4)]}
    assert pom.runs_through(shortened, 5, final=True) == (None, "segment_not_played")
    # An absent home half short of regulation is not "did not need to bat".
    no_bottom = copy.deepcopy(_load("linescore_824382.json"))
    no_bottom["innings"] = no_bottom["innings"][:5]
    no_bottom["innings"][4]["home"] = {}
    assert pom.runs_through(no_bottom, 5, final=True) == (None, "segment_not_played")


def test_a_doubleheader_matches_by_start_and_refuses_an_ambiguous_start(settler):
    """2026-09-04 DET @ CLE split doubleheader: G1 18:10Z first5 6-6, G2 23:15Z first5 3-0.

    Built from a REAL CWS @ CLE first5 row: its away team replaced by DET @ TOR's recorded away
    team, its commence time moved onto 09-04. Team names still come from the recorder."""
    detroit = _row(DET_TOR, "h2h", "full", "away")[0]["away_team"]
    shaped, _, _ = _row(CWS_CLE, "h2h_3_way", "first5", "draw")
    game1 = dict(shaped, away_team=detroit, commence_time="2026-09-04T18:11:00Z")
    game2 = dict(shaped, away_team=detroit, commence_time="2026-09-04T23:16:00Z")
    between = dict(shaped, away_team=detroit, commence_time="2026-09-04T20:42:00Z")
    assert settler(game1, {}) == ("win", None)
    assert settler(game2, {}) == ("loss", None)
    assert settler(between, {}) == (None, "ambiguous_game")


def test_failed_fetches_and_unknown_games_are_reasons_not_results():
    shaped, view, _ = _row(NYY_MIN, "totals", "first5", "under", 4.0)
    assert MlbPopulationSettler(fetch_json=lambda url: None)(shaped, view) == (None, "schedule_unavailable")
    no_linescore = FakeStatsapi(overrides={f"{STATSAPI}/game/823655/linescore": None})
    assert MlbPopulationSettler(fetch_json=no_linescore)(shaped, view) == (None, "linescore_unavailable")
    settler = MlbPopulationSettler(fetch_json=FakeStatsapi())
    assert settler(dict(shaped, commence_time="2026-09-04T18:10:00Z"), view) == (None, "game_not_found")
    assert settler(dict(shaped, home_team=None), view) == (None, "no_team_names")


def test_a_bad_side_fetches_nothing(api, settler):
    shaped, view, _ = _row(NYY_MIN, "totals", "first5", "under", 4.0)
    assert settler(dict(shaped, side="home"), view) == (None, "unsettleable_side_or_line")
    assert settler(dict(shaped, line=None), view) == (None, "unsettleable_side_or_line")
    assert api.calls == []


# --------------------------------------------------------------------------
# batter_strikeouts
# --------------------------------------------------------------------------


@pytest.mark.parametrize("event, player, side, line, expected", [
    (CWS_CLE, "anthony kay", "over", 3.5, "loss"),       # 3 K in 4.0 IP
    (CWS_CLE, "anthony kay", "under", 3.5, "win"),
    (CWS_CLE, "parker messick", "over", 6.5, "win"),     # 8 K
    (NYY_MIN, "carlos rodon", "under", 5.5, "win"),      # 5 K, box score spells Rodón
    (NYY_MIN, "zebby matthews", "over", 4.5, "win"),     # 8 K
])
def test_batter_strikeouts_naming_a_starter_settle_on_his_pitching(settler, event, player, side, line, expected):
    assert _settle(settler, event, "batter_strikeouts", "full", side, line, player) == (expected, None)


def test_batter_strikeouts_naming_a_batter_settle_on_his_batting(settler):
    # A real batter_hits row (Ryan McMahon, 6 PA, 4 K) with the market swapped.
    shaped, view, _ = _row(NYY_MIN, "batter_hits", "full", "over", 0.5, "ryan mcmahon")
    swapped = dict(shaped, market="batter_strikeouts")
    assert settler(swapped, dict(view, market="batter_strikeouts")) == ("win", None)
    assert settler(dict(swapped, line=4.0), {}) == ("push", None)
    assert settler(dict(swapped, player_name="nobody at all"), {}) == (None, "player_not_in_boxscore")


def test_a_player_who_pitched_and_batted_is_refused():
    box = _load("boxscore_823655.json")
    for player in box["teams"]["home"]["players"].values():
        if player["person"]["fullName"] == "Zebby Matthews":
            player["stats"]["batting"] = {"plateAppearances": 3, "atBats": 3, "hits": 0, "strikeOuts": 1}
    settler = MlbPopulationSettler(fetch_json=FakeStatsapi(overrides={f"{STATSAPI}/game/823655/boxscore": box}))
    result = _settle(settler, NYY_MIN, "batter_strikeouts", "full", "over", 4.5, "zebby matthews")
    assert result == (None, "ambiguous_strikeout_subject")


# --------------------------------------------------------------------------
# routing: not double-graded, and reachable
# --------------------------------------------------------------------------


def test_rows_bucket_search_already_grades_are_not_handled(api, settler):
    for market, side, line, player in [("h2h", "home", None, ""), ("spreads", "away", -1.5, ""),
                                       ("totals", "over", 8.0, ""), ("strikeouts", "over", 4.5, "zebby matthews"),
                                       ("batter_hits", "over", 0.5, "ryan mcmahon")]:
        shaped, view, _ = _row(NYY_MIN, market, "full", side, line, player)
        assert settler.handles(shaped, view) is False
        assert settler(shaped, view) is None
    shaped, view, _ = _row(NYY_MIN, "totals", "first5", "under", 4.0)
    assert settler(dict(shaped, sport="nfl"), dict(view, sport="nfl")) is None
    assert settler(dict(shaped, market="team_totals"), {}) is None
    assert api.calls == []


def test_every_real_segment_row_is_handled_and_every_one_settles(settler):
    """No real segment row of a finished game falls through or goes ungraded."""
    seen = 0
    for record in RECORDS:
        shaped, _ = bs.scorecard_record(record)
        if shaped["segment"] == "full":
            continue
        view = mbs.view_from_record(record)
        assert settler.handles(shaped, view), shaped
        result, reason = settler(shaped, view)
        assert result in {"win", "loss", "push"} and reason is None, (shaped, reason)
        seen += 1
    assert seen > 200
    # One schedule and one linescore per game, however many rows.
    assert settler.fetches == 4


def _population(record):
    return bs.grade_population([record], {}, today="2026-09-17")


def test_reachability_off_is_ungraded_on_is_graded(settler):
    """off != on: without the settler this real row is `segment_not_full_game`; the settler grades it."""
    _, _, record = _row(NYY_MIN, "totals", "first5", "under", 4.0)
    graded, ungraded = _population(record)
    assert graded == [] and ungraded == {"segment_not_full_game": 1}

    shaped, reason = bs.scorecard_record(record)
    assert reason is None
    assert settler(shaped, mbs.view_from_record(record)) == ("win", None)


def test_reachability_through_grade_population_once_the_hook_exists(settler):
    if "extra_settler" not in inspect.signature(bs.grade_population).parameters:
        pytest.skip("bucket_search.grade_population has no extra_settler hook on this branch yet")
    _, _, record = _row(NYY_MIN, "totals", "first5", "under", 4.0)
    graded, ungraded = bs.grade_population([record], {}, today="2026-09-17", extra_settler=settler)
    assert len(graded) == 1 and graded[0]["y"] == 1.0 and ungraded == {}


def test_grader_version():
    assert pom.GRADER_VERSION == "mlb/1"
    assert MlbPopulationSettler.grader_version == "mlb/1"


def test_final_payloads_are_cached_to_disk(tmp_path):
    first = FakeStatsapi()
    settler = MlbPopulationSettler(fetch_json=first, cache_dir=tmp_path)
    assert _settle(settler, NYY_MIN, "totals", "first5", "under", 4.0) == ("win", None)
    assert len(first.calls) == 2
    second = FakeStatsapi()
    again = MlbPopulationSettler(fetch_json=second, cache_dir=tmp_path)
    assert _settle(again, NYY_MIN, "totals", "first5", "under", 4.0) == ("win", None)
    assert second.calls == []


def test_an_unfinished_linescore_is_not_cached(tmp_path):
    settler = MlbPopulationSettler(fetch_json=_live_at_timecode(), cache_dir=tmp_path)
    assert _settle(settler, NYY_MIN, "h2h", "first3", "home") == ("win", None)
    assert not (tmp_path / "linescore_823655.json").exists()
