"""NHL / NFL props whose player is OUT (ESPN injuries via the news collector) or SCRATCHED (NHL gameinfo) are flagged on
the board and not seated on Layer 2 -- matched on team + name (lane `news-availability-gate`)."""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import news_availability as na

NOW = datetime(2026, 10, 14, 22, 0, tzinfo=timezone.utc)


def _write_state(root: Path, sport: str, athletes: list[dict]) -> Path:
    path = root / "news" / "_state" / f"{sport}_injuries.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(i): a for i, a in enumerate(athletes)}), encoding="utf-8")
    os.utime(path, (NOW.timestamp() - 300,) * 2)  # 5 min old
    return path


def _write_gameinfo(root: Path, day: str, records: list[dict]) -> None:
    path = root / "news" / "nhl" / "gameinfo" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _prop(player: str, home: str, away: str, sport: str, commence: str = "2026-10-15T00:30:00Z", **extra) -> dict:
    row = {"sport": sport, "kind": "prop", "market": "SOG", "player_name": player, "home_team": home,
           "away_team": away, "commence_time": commence, "projection": {"edge_vs_market_pct": 5.0}}
    row.update(extra)
    return row


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv(na.SWITCH_ENV, raising=False)
    return tmp_path


def _status(row: dict) -> str | None:
    return (row.get("player_availability") or {}).get("status")


def test_nfl_confirmed_out_is_flagged_and_questionable_doubtful_stay_priced(root):
    _write_state(root, "nfl", [
        {"athlete": "Rashee Rice", "team": "Kansas City Chiefs", "status": "Out"},
        {"athlete": "Puka Nacua", "team": "Los Angeles Rams", "status": "Injured Reserve"},
        {"athlete": "Justin Tucker", "team": "Baltimore Ravens", "status": "Suspension"},
        {"athlete": "CeeDee Lamb", "team": "Dallas Cowboys", "status": "Questionable"},
        {"athlete": "Tee Higgins", "team": "Cincinnati Bengals", "status": "Doubtful"},
        {"athlete": "Travis Kelce", "team": "Kansas City Chiefs", "status": "Active"},
    ])
    grid = [_prop("Rashee Rice", "Kansas City Chiefs", "Las Vegas Raiders", "nfl"),
            _prop("Puka Nacua", "Los Angeles Rams", "Arizona Cardinals", "nfl"),
            _prop("Justin Tucker", "Pittsburgh Steelers", "Baltimore Ravens", "nfl"),
            _prop("CeeDee Lamb", "Green Bay Packers", "Dallas Cowboys", "nfl"),
            _prop("Tee Higgins", "Cincinnati Bengals", "Cleveland Browns", "nfl"),
            _prop("Travis Kelce", "Kansas City Chiefs", "Las Vegas Raiders", "nfl")]
    summary = na.flag_out_player_props(grid, sport="nfl", now=NOW)["out_player_props"]
    assert [_status(r) for r in grid] == ["OUT", "OUT", "SUSPENDED", None, None, None]
    assert grid[0]["projection"]["edge_vs_market_pct"] is None and grid[3]["projection"]["edge_vs_market_pct"] == 5.0
    assert summary["feed_status"] == "ok" and summary["rows_flagged"] == 3 and summary["out_players_on_feed"] == 3


def test_same_name_on_another_team_is_not_flagged(root):
    # The basketball path keys on the name alone; here the Jaguars' Josh Allen must not flag the Bills' Josh Allen.
    _write_state(root, "nfl", [{"athlete": "Josh Allen", "team": "Jacksonville Jaguars", "status": "Out"}])
    bills = _prop("Josh Allen", "Buffalo Bills", "Miami Dolphins", "nfl")
    jags = _prop("Josh Allen", "Jacksonville Jaguars", "Tennessee Titans", "nfl")
    na.flag_out_player_props([bills, jags], sport="nfl", now=NOW)
    assert _status(bills) is None and _status(jags) == "OUT"


def test_nhl_injured_reserve_is_flagged_day_to_day_is_not_and_accents_match(root):
    _write_state(root, "nhl", [
        {"athlete": "Patrik Laine", "team": "Montreal Canadiens", "status": "Injured Reserve"},
        {"athlete": "Joel Kiviranta", "team": "Dallas Stars", "status": "Day-To-Day"},
    ])
    laine = _prop("Patrik Laine", "Washington Capitals", "Montréal Canadiens", "nhl")
    kiviranta = _prop("Joel Kiviranta", "Colorado Avalanche", "Dallas Stars", "nhl")
    na.flag_out_player_props([laine, kiviranta], sport="nhl", now=NOW)
    assert _status(laine) == "OUT" and _status(kiviranta) is None


def test_an_nhl_scratch_flags_only_that_game(root):
    _write_state(root, "nhl", [])
    # 2026-10-14 00:30Z is 7:30 PM CT on 10-13: the scratch belongs to the 10-13 game only.
    _write_gameinfo(root, "2026-10-14", [
        {"game_id": "2026020100", "captured_at": "2026-10-14T00:01:16Z", "start_utc": "2026-10-14T00:30:00Z",
         "away": "COL", "home": "DAL", "away_scratches": [], "home_scratches": []},
        {"game_id": "2026020100", "captured_at": "2026-10-14T00:11:16Z", "start_utc": "2026-10-14T00:30:00Z",
         "away": "COL", "home": "DAL", "away_scratches": [{"id": 1, "name": "Cale Makar"}], "home_scratches": []},
    ])
    that_game = _prop("Cale Makar", "Dallas Stars", "Colorado Avalanche", "nhl", commence="2026-10-14T00:40:00Z")
    next_game = _prop("Cale Makar", "Colorado Avalanche", "Dallas Stars", "nhl", commence="2026-10-15T00:40:00Z")
    summary = na.flag_out_player_props([that_game, next_game], sport="nhl", now=NOW)["out_player_props"]
    assert _status(that_game) == "INACTIVE" and that_game["player_availability"]["source"] == "nhl_gameinfo"
    assert _status(next_game) is None
    assert summary["scratches_on_feed"] == 1 and summary["rows_flagged_by_source"]["nhl_gameinfo"] == 1


def test_the_latest_gameinfo_record_wins(root):
    # A player scratched at 00:01 and back in the lineup by 00:11 is not flagged.
    _write_state(root, "nhl", [])
    _write_gameinfo(root, "2026-10-14", [
        {"game_id": "9", "captured_at": "2026-10-14T00:01:16Z", "start_utc": "2026-10-14T00:30:00Z", "away": "COL",
         "home": "DAL", "away_scratches": [{"id": 1, "name": "Cale Makar"}], "home_scratches": []},
        {"game_id": "9", "captured_at": "2026-10-14T00:11:16Z", "start_utc": "2026-10-14T00:30:00Z", "away": "COL",
         "home": "DAL", "away_scratches": [{"id": 2, "name": "Ross Colton"}], "home_scratches": []},
    ])
    makar = _prop("Cale Makar", "Dallas Stars", "Colorado Avalanche", "nhl", commence="2026-10-14T00:40:00Z")
    colton = _prop("Ross Colton", "Dallas Stars", "Colorado Avalanche", "nhl", commence="2026-10-14T00:40:00Z")
    na.flag_out_player_props([makar, colton], sport="nhl", now=NOW)
    assert _status(makar) is None and _status(colton) == "INACTIVE"


def test_absent_stale_and_disabled_flag_nothing_and_say_so(root, monkeypatch):
    row = _prop("Rashee Rice", "Kansas City Chiefs", "Las Vegas Raiders", "nfl")
    assert na.flag_out_player_props([row], sport="nfl", now=NOW)["out_player_props"]["feed_status"] == "absent"
    path = _write_state(root, "nfl", [{"athlete": "Rashee Rice", "team": "Kansas City Chiefs", "status": "Out"}])
    os.utime(path, (NOW.timestamp() - 25 * 3600,) * 2)
    stale = na.flag_out_player_props([row], sport="nfl", now=NOW)["out_player_props"]
    assert stale["feed_status"] == "stale" and stale["rows_flagged"] == 0 and _status(row) is None
    os.utime(path, (NOW.timestamp() - 60,) * 2)
    monkeypatch.setenv(na.SWITCH_ENV, "off")
    assert na.flag_out_player_props([row], sport="nfl", now=NOW)["out_player_props"]["feed_status"] == "disabled"
    assert _status(row) is None
    monkeypatch.delenv(na.SWITCH_ENV)
    assert na.flag_out_player_props([row], sport="nfl", now=NOW)["out_player_props"]["rows_flagged"] == 1


def test_mlb_is_flagged_only_inside_the_2027_regular_season(root):
    # User 2026-10-14: "collect MLB injuries now, flag in 2027". Injured lists are OUT, Day-To-Day stays priced, and
    # nothing moves during the 2026 postseason, 2027 spring training or the 2027 postseason.
    _write_state(root, "mlb", [
        {"athlete": "Mookie Betts", "team": "Los Angeles Dodgers", "status": "10-Day-IL"},
        {"athlete": "Aaron Judge", "team": "New York Yankees", "status": "7-Day IL"},
        {"athlete": "Juan Soto", "team": "New York Mets", "status": "Day-To-Day"},
    ])
    def mlb(player, home, away, commence):
        return _prop(player, home, away, "mlb", commence=commence, market="batter_hits")
    april = [mlb("Mookie Betts", "Los Angeles Dodgers", "San Diego Padres", "2027-04-10T02:10:00Z"),
             mlb("Aaron Judge", "Boston Red Sox", "New York Yankees", "2027-04-10T23:05:00Z"),
             mlb("Juan Soto", "New York Mets", "Atlanta Braves", "2027-04-10T23:10:00Z")]
    postseason_now = mlb("Mookie Betts", "Los Angeles Dodgers", "Philadelphia Phillies", "2026-10-15T00:08:00Z")
    spring = mlb("Mookie Betts", "Los Angeles Dodgers", "Chicago Cubs", "2027-03-10T20:05:00Z")
    postseason_2027 = mlb("Mookie Betts", "Los Angeles Dodgers", "Chicago Cubs", "2027-10-05T00:08:00Z")
    unlisted = mlb("Mookie Betts", "Los Angeles Dodgers", "Chicago Cubs", "2028-04-10T23:05:00Z")
    grid = april + [postseason_now, spring, postseason_2027, unlisted]
    summary = na.flag_out_player_props(grid, sport="mlb", now=NOW)["out_player_props"]
    assert [_status(r) for r in april] == ["OUT", "OUT", None]
    assert all(_status(r) is None for r in (postseason_now, spring, postseason_2027, unlisted))
    assert postseason_now["projection"]["edge_vs_market_pct"] == 5.0          # untouched, not just unflagged
    # 2026 is not a listed season at all (unknown); 2027 spring and postseason are outside its window; 2028 unknown.
    assert summary["season_gate"]["prop_rows_by_gate"] == {"open": 3, "outside": 2, "unknown": 2}
    assert summary["season_gate"]["windows"] == {"2027": ["2027-03-25", "2027-09-26"]}


def test_il_statuses_map_to_out_and_others_stay_priced():
    for status in ("10-Day-IL", "15-Day-IL", "60-Day-IL", "7-Day IL", "paternity", "Bereavement List", "restricted"):
        assert na.availability_status(status) == "OUT"
    assert na.availability_status("suspension") == "SUSPENDED"   # ESPN MLB sends it lower-case
    for status in ("Day-To-Day", "Questionable", "Doubtful", "Active", "", None):
        assert na.availability_status(status) is None


def test_every_status_written_is_one_layer2_refuses():
    assert set(na.OUT_STATUS.values()) | {na.SCRATCH_STATUS} <= {"OUT", "SUSPENDED", "INACTIVE"}


def test_reached_through_attach_projections(root):
    # REACHABILITY: the real call site, not the module. attach_projections runs the NFL / NHL joins first; with no
    # artifacts they report unsupported / empty and still return a dict, which is what lets the flag run.
    from syndicate.features.shared import board_enrichment

    state = _write_state(root, "nfl", [{"athlete": "Rashee Rice", "team": "Kansas City Chiefs", "status": "Out"}])
    # The real call site passes no `now`: the flag judges freshness against the WALL CLOCK, so the state must be fresh
    # NOW. Stamped at the fixed NOW above, this test passed the day it was written and read `feed=stale` from then on
    # (ci-suite 10-16 08:00Z, age 2,339 min, rows_flagged 0; todo #697, found by lane ci-suite-red-1015).
    os.utime(state, None)
    row = _prop("Rashee Rice", "Kansas City Chiefs", "Las Vegas Raiders", "nfl", market="Receptions")
    coverage = board_enrichment.attach_projections([row], sport="nfl", selected_date="2026-10-14")
    assert coverage["out_player_props"]["source"] == "news" and coverage["out_player_props"]["rows_flagged"] == 1
    assert _status(row) == "OUT"


# --- END TO END through the rebuild production uses: grid -> flag -> build_layer2_rows -> select_shortlist ----------

def _grid_prop(player: str, home: str, away: str, sport: str = "nhl") -> dict:
    return {
        "sport": sport, "event_id": f"evt-{player}", "kind": "prop", "market": "SOG", "segment": "full", "line": 2.5,
        "player_name": player, "home_team": home, "away_team": away, "commence_time": "2026-10-15T00:30:00Z",
        # Two books' prices, so the row has a market fair. Since dd499146 a row with a model edge and NO market price is
        # refused at selection (`rows_no_market_price`), and an empty `cells` here made this test seat nobody at all --
        # gate or no gate (seen 2026-10-20: rows_no_market_price 4 nhl|SOG, `seated` empty).
        "sides": ["over", "under"], "books_quoting": 4,
        "cells": {book: {"over": {"price": over, "age_seconds": 30.0, "stale": False},
                         "under": {"price": under, "age_seconds": 30.0, "stale": False}}
                  # over fair ~47% (the books' median); FanDuel's +125 beats it, so the over is a value row
                  for book, over, under in (("caesars", 105, -125), ("betmgm", 100, -120), ("fanduel", 125, -155))},
        "best": {"over": {"price": 118, "bookmaker": "fanduel", "books_quoting": 4, "age_seconds": 30.0},
                 "under": {"price": -140, "bookmaker": "draftkings", "books_quoting": 4, "age_seconds": 30.0}},
        "projection": {"edge_vs_market_pct": 6.0, "model_skill": {"status": "measured", "sample_games": 120}},
        "game": {"game_key": "2026_10_DAL_COL", "matchup": "DAL @ COL", "state": "pregame",
                 "start_time_utc": "2026-10-15T00:30:00+00:00", "home_score": None, "away_score": None},
    }


def _seated(grid: list[dict]) -> tuple[set, dict]:
    from syndicate.features.shared.layer2_board import build_layer2_rows, select_shortlist

    opportunities = build_layer2_rows([dict(r) for r in grid])["opportunities"]
    result = select_shortlist(opportunities, now=NOW)
    return {row.get("player_name") for row in result["rows"]}, result


def test_end_to_end_an_out_nhl_player_is_not_seated_and_off_is_not_on(root):
    _write_state(root, "nhl", [{"athlete": "Cale Makar", "team": "Colorado Avalanche", "status": "Out"}])
    grid = [_grid_prop("Cale Makar", "Colorado Avalanche", "Dallas Stars"),
            _grid_prop("Nathan MacKinnon", "Colorado Avalanche", "Dallas Stars")]
    flagged = copy.deepcopy(grid)  # deep: the flag clears the nested projection edge
    na.flag_out_player_props(flagged, sport="nhl", now=NOW)
    seated, _ = _seated(flagged)
    assert "Nathan MacKinnon" in seated and "Cale Makar" not in seated
    seated_off, result_off = _seated(grid)  # the same grid, never flagged
    assert "Cale Makar" in seated_off and result_off["rows_player_out_on_feed"] == 0


def test_flagged_rows_are_counted_per_sport_by_the_layer2_gate(root):
    # This fixture has no book cells, so once the flag clears the model edge an end-to-end row has nothing to score on
    # and leaves before the gate (`build_layer2_rows` keeps scored rows only). Production rows score on market EV, so
    # here the flagged row carries its market score, as the basketball gate test does, to prove the COUNT per sport.
    from syndicate.features.shared.layer2_board import select_shortlist

    _write_state(root, "nhl", [{"athlete": "Cale Makar", "team": "Colorado Avalanche", "status": "Out"}])
    _write_state(root, "nfl", [{"athlete": "Rashee Rice", "team": "Kansas City Chiefs", "status": "Out"}])

    def scored(player: str, home: str, away: str, sport: str) -> dict:
        return _prop(player, home, away, sport, side="over", event_id=f"evt-{player}", ev_pct=2.5, model_edge_pct=4.1,
                     quote={"price": 118, "fair_probability": 0.44, "fair_method": "consensus_no_vig", "books_quoting": 4},
                     score={"score": 2.5, "value_pct": 2.5})

    nhl = [scored("Cale Makar", "Colorado Avalanche", "Dallas Stars", "nhl"),
           scored("Nathan MacKinnon", "Colorado Avalanche", "Dallas Stars", "nhl")]
    nfl = [scored("Rashee Rice", "Kansas City Chiefs", "Las Vegas Raiders", "nfl"),
           scored("Travis Kelce", "Kansas City Chiefs", "Las Vegas Raiders", "nfl")]
    na.flag_out_player_props(nhl, sport="nhl", now=NOW)
    na.flag_out_player_props(nfl, sport="nfl", now=NOW)
    result = select_shortlist(nhl + nfl, now=NOW)
    seated = {row.get("player_name") for row in result["rows"]}
    assert {"Nathan MacKinnon", "Travis Kelce"} <= seated and not {"Cale Makar", "Rashee Rice"} & seated
    assert result["rows_player_out_on_feed_by_sport"] == {"nfl": 1, "nhl": 1}
    sample = {row["player_name"]: row["availability"] for row in result["rows_player_out_on_feed_sample"]}
    assert sample["Cale Makar"]["status"] == "OUT" and sample["Rashee Rice"]["feed_team"] == "Kansas City Chiefs"


def test_scratches_do_not_wait_on_the_injury_feed(root):
    # 2026-10-25: an absent, stale or unreadable `_state/nhl_injuries.json` dropped every NHL scratch with it, silently.
    _write_gameinfo(root, "2026-10-14", [
        {"game_id": "2026020100", "captured_at": "2026-10-14T00:11:16Z", "start_utc": "2026-10-14T00:30:00Z",
         "away": "COL", "home": "DAL", "away_scratches": [{"id": 1, "name": "Cale Makar"}], "home_scratches": []}])
    row = _prop("Cale Makar", "Dallas Stars", "Colorado Avalanche", "nhl", commence="2026-10-14T00:40:00Z")
    absent = na.flag_out_player_props([row], sport="nhl", now=NOW)["out_player_props"]
    assert absent["feed_status"] == "absent" and absent["rows_flagged"] == 1 and _status(row) == "INACTIVE"
    path = _write_state(root, "nhl", [])
    os.utime(path, (NOW.timestamp() - 25 * 3600,) * 2)
    assert len(na.out_index("nhl", now=NOW)["scratches"]) == 1                      # stale injuries, scratch kept


def test_restamp_at_select_flags_a_scratch_posted_after_the_first_read(root, monkeypatch):
    # 10-23: a 7:41 PM COL scratch missed the 7:46 PM shortlist because the build had read news at 7:40:25.
    _write_state(root, "nhl", [])
    late = _prop("Cale Makar", "Dallas Stars", "Colorado Avalanche", "nhl", commence="2026-10-14T00:40:00Z")
    other = _prop("Nathan MacKinnon", "Dallas Stars", "Colorado Avalanche", "nhl", commence="2026-10-14T00:40:00Z")
    already = _prop("Rashee Rice", "Kansas City Chiefs", "Las Vegas Raiders", "nfl",
                    player_availability={"status": "OUT", "source": "espn_injuries"})
    assert na.restamp_out_players([late, other, already], now=NOW) == {}          # nothing posted yet: nothing stamped
    _write_gameinfo(root, "2026-10-14", [
        {"game_id": "2026020100", "captured_at": "2026-10-14T00:11:16Z", "start_utc": "2026-10-14T00:30:00Z",
         "away": "COL", "home": "DAL", "away_scratches": [{"id": 1, "name": "Cale Makar"}], "home_scratches": []}])
    assert na.restamp_out_players([late, other, already], now=NOW) == {"nhl": 1}
    assert _status(late) == "INACTIVE" and late["player_availability"]["stamped_at"] == "select"
    assert _status(other) is None and late["projection"] == {"edge_vs_market_pct": 5.0}   # the stamp only
    assert already["player_availability"] == {"status": "OUT", "source": "espn_injuries"}
    monkeypatch.setenv(na.SWITCH_ENV, "off")
    assert na.restamp_out_players([_prop("Cale Makar", "Dallas Stars", "Colorado Avalanche", "nhl",
                                         commence="2026-10-14T00:40:00Z")], now=NOW) == {}


def test_the_pool_count_shows_flagged_rows_an_earlier_rule_removed(root):
    # 10-23: six flagged NHL rows left before the gate (quote age, uninformative EV) and the gate's count read no nhl.
    from syndicate.features.shared.layer2_board import select_shortlist

    def scored(player: str, age_s: float) -> dict:
        return _prop(player, "Colorado Avalanche", "Dallas Stars", "nhl", side="over", event_id=f"evt-{player}",
                     ev_pct=2.5, model_edge_pct=4.1, score={"score": 2.5, "value_pct": 2.5},
                     player_availability={"status": "INACTIVE", "source": "nhl_gameinfo"},
                     quote={"price": 118, "fair_probability": 0.44, "fair_method": "consensus_no_vig", "books_quoting": 4,
                            "quote_seen_age_seconds": age_s})

    result = select_shortlist([scored("Cale Makar", 60.0), scored("Devon Toews", 50_000.0)], now=NOW)
    assert result["rows_player_out_in_pool_by_sport"] == {"nhl": 2}
    assert result["rows_player_out_on_feed_by_sport"] == {"nhl": 1}                 # the stale one went to quote age first
