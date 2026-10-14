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


def test_every_status_written_is_one_layer2_refuses():
    assert set(na.OUT_STATUS.values()) | {na.SCRATCH_STATUS} <= {"OUT", "SUSPENDED", "INACTIVE"}


def test_reached_through_attach_projections(root):
    # REACHABILITY: the real call site, not the module. attach_projections runs the NFL / NHL joins first; with no
    # artifacts they report unsupported / empty and still return a dict, which is what lets the flag run.
    from syndicate.features.shared import board_enrichment

    _write_state(root, "nfl", [{"athlete": "Rashee Rice", "team": "Kansas City Chiefs", "status": "Out"}])
    row = _prop("Rashee Rice", "Kansas City Chiefs", "Las Vegas Raiders", "nfl", market="Receptions")
    coverage = board_enrichment.attach_projections([row], sport="nfl", selected_date="2026-10-14")
    assert coverage["out_player_props"]["source"] == "news" and coverage["out_player_props"]["rows_flagged"] == 1
    assert _status(row) == "OUT"


# --- END TO END through the rebuild production uses: grid -> flag -> build_layer2_rows -> select_shortlist ----------

def _grid_prop(player: str, home: str, away: str, sport: str = "nhl") -> dict:
    return {
        "sport": sport, "event_id": f"evt-{player}", "kind": "prop", "market": "SOG", "segment": "full", "line": 2.5,
        "player_name": player, "home_team": home, "away_team": away, "commence_time": "2026-10-15T00:30:00Z",
        "sides": ["over", "under"], "books_quoting": 4, "cells": {},
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
