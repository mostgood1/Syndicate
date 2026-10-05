"""Tests for the owned NHL ingestion (roster/lineup/goalie collection).

Pure logic (infer_lines/project_lineup/_toi_to_min) + a cache-backed build_team_usage run entirely
offline; a tolerant live smoke exercises the full collector when the network + mirror are available.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.ingestion import lineups as lu
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient, season_code_for_date


def test_toi_to_min():
    assert lu._toi_to_min("18:30") == pytest.approx(18.5)
    assert lu._toi_to_min("00:00") == 0.0
    assert lu._toi_to_min(None) == 0.0
    assert lu._toi_to_min("bad") == 0.0


def test_season_code_for_date():
    assert season_code_for_date("2026-01-15") == "20252026"
    assert season_code_for_date("2025-10-10") == "20252026"
    assert season_code_for_date("2026-08-01") == "20262027"


def _usage(n_f=13, n_d=7, n_g=2):
    """Synthetic usage with descending TOI so ranks are deterministic."""
    rows = []
    for i in range(n_f):
        rows.append({"player_id": 100 + i, "full_name": f"F{i}", "position": "F", "games_played": 5, "toi_avg": 20.0 - i})
    for i in range(n_d):
        rows.append({"player_id": 200 + i, "full_name": f"D{i}", "position": "D", "games_played": 5, "toi_avg": 24.0 - i})
    for i in range(n_g):
        rows.append({"player_id": 300 + i, "full_name": f"G{i}", "position": "G", "games_played": 3, "toi_avg": 60.0 - 30 * i})
    return rows


def test_infer_lines_slots():
    usage = lu.infer_lines(_usage())
    by_id = {r["player_id"]: r for r in usage}
    # top-3 forwards -> L1, next 3 -> L2 ...
    assert by_id[100]["line_slot"] == "L1" and by_id[102]["line_slot"] == "L1"
    assert by_id[103]["line_slot"] == "L2"
    assert by_id[109]["line_slot"] == "L4"
    assert by_id[112]["line_slot"] is None      # 13th forward, no slot
    # top-2 D -> D1
    assert by_id[200]["line_slot"] == "D1" and by_id[201]["line_slot"] == "D1"
    assert by_id[202]["line_slot"] == "D2"
    assert by_id[206]["line_slot"] is None      # 7th D
    # goalies never get a skater slot
    assert by_id[300]["line_slot"] is None


def test_infer_lines_pp_pk_units():
    usage = lu.infer_lines(_usage())
    by_id = {r["player_id"]: r for r in usage}
    # highest-TOI skaters are the D-men (24 > 20); PP1 = top 5 skaters overall
    pp1 = [r["player_id"] for r in usage if r.get("pp_unit") == 1]
    assert len(pp1) == 5
    assert all(r.get("pp_unit") is None for r in usage if r["position"] == "G")


def test_project_lineup_flags_starter_goalie():
    usage = lu.project_lineup(lu.infer_lines(_usage()))
    starters = [r for r in usage if r.get("is_starter_goalie")]
    assert len(starters) == 1
    assert starters[0]["player_id"] == 300      # higher-TOI goalie
    assert all("proj_toi" in r for r in usage)


def _boxscore(home_abbr, away_abbr, home_players):
    return {
        "homeTeam": {"abbrev": home_abbr}, "awayTeam": {"abbrev": away_abbr},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [p for p in home_players if p["position"] == "C"],
                "defense": [p for p in home_players if p["position"] == "D"],
                "goalies": [p for p in home_players if p["position"] == "G"],
            },
            "awayTeam": {"forwards": [], "defense": [], "goalies": []},
        },
    }


def test_build_team_usage_from_cache(tmp_path):
    client = NhlWebIngestClient(cache_dir=tmp_path, offline=True)
    players = [
        {"playerId": 1, "name": {"default": "Top C"}, "position": "C", "toi": "20:00"},
        {"playerId": 2, "name": {"default": "Top D"}, "position": "D", "toi": "24:00"},
        {"playerId": 3, "name": {"default": "Starter G"}, "position": "G", "toi": "60:00"},
    ]
    for gid in ("1", "2"):
        (tmp_path / f"boxscore_{gid}.json").write_text(json.dumps(_boxscore("BUF", "MTL", players)), encoding="utf-8")
    # stub the schedule lookup (offline) to return our two cached games
    client.recent_finished_game_ids = lambda *a, **k: ["1", "2"]  # type: ignore[assignment]

    usage = lu.build_team_usage(client, "BUF", date="2026-01-16", n_games=5)
    by_id = {r["player_id"]: r for r in usage}
    assert by_id[1]["toi_avg"] == pytest.approx(20.0)     # averaged over 2 games
    assert by_id[2]["games_played"] == 2
    assert by_id[3]["position"] == "G"
    assert usage[0]["toi_avg"] >= usage[-1]["toi_avg"]    # sorted desc


def test_collect_slate_inputs_offline_empty(tmp_path):
    # No scoreboard under this root -> no teams -> zero rows, files still written with headers.
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs
    client = NhlWebIngestClient(cache_dir=tmp_path, offline=True)
    summary = collect_slate_inputs("2026-01-16", root=tmp_path, client=client, out_dir=tmp_path)
    assert summary["teams"] == 0
    assert summary["lineup_rows"] == 0
    assert Path(summary["lineups_path"]).exists()


def test_collect_live_smoke(tmp_path):
    """Full collector against the real mirror + network (skipped if unavailable)."""
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs
    try:
        summary = collect_slate_inputs("2026-06-14", out_dir=tmp_path, n_games=4)
    except Exception as exc:  # network/offline environments
        pytest.skip(f"live NHL API unavailable: {exc}")
    if summary["teams"] == 0:
        pytest.skip("no mirrored scoreboard for 2026-06-14")
    assert summary["lineup_rows"] > 0
    assert summary["goalies"] >= 1


def test_dress_selection_uses_total_ice_time_not_average():
    # 13 forwards: F12 played ONE long game (22 min avg) while F0..F11 are every-night regulars
    # (avg 10-20 over 8 games). Ranked by average, F12 dressed and a regular lost his slot --
    # the 2026-10-02 backtest's 10% of skaters who played with no slot (projected ~0).
    rows = [{"player_id": 100 + i, "position": "F", "games_played": 8, "toi_avg": 20.0 - i,
             "toi_total": 8 * (20.0 - i)} for i in range(12)]
    rows.append({"player_id": 112, "position": "F", "games_played": 1, "toi_avg": 22.0, "toi_total": 22.0})
    by_id = {r["player_id"]: r for r in lu.infer_lines(rows)}
    assert by_id[112]["line_slot"] is None
    assert all(by_id[100 + i]["line_slot"] for i in range(12))
    # lines are still ordered by AVERAGE usage within the dressed set
    assert by_id[100]["line_slot"] == "L1" and by_id[111]["line_slot"] == "L4"


def test_special_teams_units_have_positional_shape():
    # D log the most minutes (24 > 20), which used to make PP1 / PK1 mostly defensemen.
    usage = lu.infer_lines(_usage())
    for unit, (nf, nd) in ((1, (3, 2)), (2, (3, 2))):
        members = [r for r in usage if r.get("pp_unit") == unit]
        assert (sum(r["position"] == "F" for r in members), sum(r["position"] == "D" for r in members)) == (nf, nd)
    for unit in (1, 2):
        members = [r for r in usage if r.get("pk_unit") == unit]
        assert (sum(r["position"] == "F" for r in members), sum(r["position"] == "D" for r in members)) == (2, 2)
    assert all(r.get("line_slot") for r in usage if r.get("pp_unit") or r.get("pk_unit"))


def _goalies(**rows):
    out = []
    for pid, (starts, last, avg, team_last) in rows.items():
        out.append({"player_id": int(pid[1:]), "position": "G", "games_played": starts, "toi_avg": avg,
                    "starts": starts, "last_start_date": last, "team_last_game_date": team_last})
    return out


def test_starter_is_most_starts_not_highest_average():
    # The backup's one full start averages 60 min -- the same as the starter's. Old rule: a coin toss.
    usage = _goalies(g1=(6, "2026-01-10", 59.0, "2026-01-12"), g2=(1, "2026-01-12", 60.0, "2026-01-12"))
    usage = lu.project_lineup(usage, date="2026-01-15")
    assert [r["player_id"] for r in usage if r["is_starter_goalie"]] == [1]


def test_back_to_back_swaps_to_the_other_goalie():
    usage = _goalies(g1=(6, "2026-01-14", 59.0, "2026-01-14"), g2=(2, "2026-01-08", 58.0, "2026-01-14"))
    usage = lu.project_lineup(usage, date="2026-01-15")
    assert [r["player_id"] for r in usage if r["is_starter_goalie"]] == [2]
    # not a back-to-back: the regular starter
    usage = lu.project_lineup(_goalies(g1=(6, "2026-01-12", 59.0, "2026-01-12"), g2=(2, "2026-01-08", 58.0, "2026-01-12")),
                              date="2026-01-15")
    assert [r["player_id"] for r in usage if r["is_starter_goalie"]] == [1]


def test_window_skips_preseason_and_tops_up_from_last_season(monkeypatch):
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient

    sched = {
        "20262027": {"games": [
            {"id": 1, "gameType": 1, "gameState": "OFF", "gameDate": "2026-09-28"},
            {"id": 2, "gameType": 1, "gameState": "OFF", "gameDate": "2026-09-30"},
            {"id": 3, "gameType": 2, "gameState": "OFF", "gameDate": "2026-10-02"},
            {"id": 4, "gameType": 2, "gameState": "FUT", "gameDate": "2026-10-05"},
        ]},
        "20252026": {"games": [
            {"id": 90 + i, "gameType": 2, "gameState": "OFF", "gameDate": f"2026-04-{10 + i:02d}"} for i in range(5)
        ] + [{"id": 99, "gameType": 3, "gameState": "OFF", "gameDate": "2026-04-20"}]},
    }
    client = NhlWebIngestClient(rate_limit_per_sec=0)
    monkeypatch.setattr(client, "_get", lambda url: sched[url.rsplit("/", 1)[-1]])
    ids = client.recent_finished_game_ids("MTL", "20262027", before_date="2026-10-03", n=4)
    # preseason 1, 2 never; the one regular-season game, topped up with last season's latest three
    assert ids == ["93", "94", "99", "3"]


def test_book_listed_player_is_dressed_first():
    # 7 D: D6 ranks 7th by total ice time (missed late games last season) but has a book line.
    rows = [{"player_id": 200 + i, "position": "D", "games_played": 8, "toi_avg": 24.0 - i,
             "toi_total": 8 * (24.0 - i)} for i in range(6)]
    rows.append({"player_id": 206, "position": "D", "games_played": 3, "toi_avg": 23.7, "toi_total": 71.1})
    assert {r["player_id"]: r for r in lu.infer_lines([dict(r) for r in rows])}[206]["line_slot"] is None
    by_id = {r["player_id"]: r for r in lu.infer_lines([dict(r) for r in rows], must_dress={206})}
    assert by_id[206]["line_slot"] == "D1"            # dressed, and slotted by his AVERAGE usage
    assert sum(1 for r in by_id.values() if r["line_slot"]) == 6


def test_book_listed_ids_match_full_and_unique_abbreviated_names():
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import _book_listed_ids

    usage = [{"player_id": 1, "full_name": "John Carlson", "position": "D"},
             {"player_id": 2, "full_name": "A. Ovechkin", "position": "F"},
             {"player_id": 3, "full_name": "L. Hughes", "position": "D"},
             {"player_id": 4, "full_name": "L. Hughes", "position": "F"},
             {"player_id": 5, "full_name": "Logan Thompson", "position": "G"}]
    line = lambda n, h="Tampa Bay Lightning", a="Washington Capitals": {"player_name": n, "home_team": h, "away_team": a}
    lines = [line("John Carlson"), line("Alex Ovechkin"), line("Luke Hughes"), line("Logan Thompson"),
             line("Someone Else", h="Boston Bruins", a="Winnipeg Jets")]
    # Carlson exact, Ovechkin by unique abbreviation; the two "L. Hughes" are ambiguous; goalies never
    assert _book_listed_ids(usage, "Washington Capitals", lines) == {1, 2}
    assert _book_listed_ids(usage, "Boston Bruins", [line("John Carlson", h="Winnipeg Jets", a="Calgary Flames")]) == set()


def _usage_with_st():
    rows = []
    for i in range(12):   # forwards: F4 (index 4) is a PP1 specialist despite lower total TOI
        rows.append({"player_id": 100 + i, "position": "F", "games_played": 8, "toi_avg": 20.0 - i,
                     "toi_total": 8 * (20.0 - i), "pp_toi_total": {0: 25, 1: 24, 2: 2, 3: 23, 4: 22}.get(i, 1.0),
                     "sh_toi_total": {5: 15, 6: 14}.get(i, 0.5)})
    for i in range(6):    # defense: D0 quarterbacks PP1, D1/D2 kill penalties
        rows.append({"player_id": 200 + i, "position": "D", "games_played": 8, "toi_avg": 24.0 - i,
                     "toi_total": 8 * (24.0 - i), "pp_toi_total": 26 if i == 0 else 3.0,
                     "sh_toi_total": {1: 18, 2: 17}.get(i, 1.0)})
    return rows


def test_real_special_teams_minutes_build_the_units():
    by_id = {r["player_id"]: r for r in lu.infer_lines(_usage_with_st())}
    pp1 = sorted(pid for pid, r in by_id.items() if r.get("pp_unit") == 1)
    assert pp1 == [100, 101, 103, 104, 200]          # 4F + 1D, as the minutes say -- not 3F+2D
    assert by_id[102]["pp_unit"] != 1                # big total TOI, little PP time -> not PP1
    pk1 = sorted(pid for pid, r in by_id.items() if r.get("pk_unit") == 1)
    assert pk1 == [105, 106, 201, 202]


def test_special_teams_toi_parses_the_stats_report(monkeypatch):
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient

    client = NhlWebIngestClient(rate_limit_per_sec=0)
    seen = []

    def fake_get(url):
        seen.append(url)
        if "gameTypeId%3D2" in url:
            return {"data": [{"gameId": 2025020500, "playerId": 8480018, "ppTimeOnIce": 212, "shTimeOnIce": 0},
                             {"gameId": 2025020500, "playerId": 8478851, "ppTimeOnIce": 0, "shTimeOnIce": 73}]}
        return {"data": []}

    monkeypatch.setattr(client, "_get", fake_get)
    st = client.special_teams_toi("MTL", "20252026")
    assert st == {"2025020500": {8480018: (212.0, 0.0), 8478851: (0.0, 73.0)}}
    assert len(seen) == 2 and all("seasonId%3D20252026" in u for u in seen)


def test_projected_ev_minutes_are_total_minus_special_teams():
    rows = [{"player_id": 1, "position": "F", "games_played": 4, "toi_avg": 20.0, "pp_toi_total": 12.0, "sh_toi_total": 4.0},
            {"player_id": 2, "position": "F", "games_played": 4, "toi_avg": 12.0}]
    by_id = {r["player_id"]: r for r in lu.project_lineup(rows)}
    assert by_id[1]["proj_ev_toi"] == 16.0          # 20 - (12 + 4) / 4
    assert by_id[2]["proj_ev_toi"] is None          # no special-teams data: unknown, not total


def test_onice_goals_parses_the_stats_report(monkeypatch):
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient

    client = NhlWebIngestClient(rate_limit_per_sec=0)

    def fake_get(url):
        assert "skater/goalsForAgainst" in url
        if "gameTypeId%3D2" in url:
            return {"data": [{"gameId": 2025020500, "gameDate": "2025-12-01", "playerId": 7, "goals": 1, "assists": 2,
                              "evenStrengthGoalsFor": 3, "powerPlayGoalFor": 1, "shortHandedGoalsFor": None}]}
        return {"data": []}

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.onice_goals("TBL", "20252026") == {"2025020500": ("2025-12-01", {7: (3, 2)})}  # 4 on ice - 1 own


def test_assist_share_is_as_of_and_shrunk_to_the_position_prior():
    """Games ON or after the slate date never count; a share is pulled toward its position prior by
    ASSIST_SHARE_K teammate goals; a previous season counts at its weight; no report at all -> None."""
    from syndicate.features.nhl.sim_engine.hockeysim.state import ASSIST_SHARE_PRIOR

    cur = {"g1": ("2025-12-01", {1: (30, 24), 2: (30, 6)}),
           "g2": ("2025-12-05", {1: (100, 0)})}              # the slate date itself: must be ignored
    prev = {"p1": ("2025-03-01", {1: (60, 30)})}
    rows = [{"player_id": 1, "position": "F"}, {"player_id": 2, "position": "D"}, {"player_id": 3, "position": "F"},
            {"player_id": 9, "position": "G"}]
    by_id = {r["player_id"]: r for r in lu.attach_assist_share(rows, [(cur, 1.0), (prev, 0.5)], "2025-12-05")}
    kf, kd = lu.ASSIST_SHARE_K["F"], lu.ASSIST_SHARE_K["D"]
    assert by_id[1]["assist_share"] == round((24 + 15 + kf * ASSIST_SHARE_PRIOR["F"]) / (30 + 30 + kf), 4)
    assert by_id[2]["assist_share"] == round((6 + kd * ASSIST_SHARE_PRIOR["D"]) / (30 + kd), 4)
    assert by_id[3]["assist_share"] == ASSIST_SHARE_PRIOR["F"]          # no games: exactly the prior
    assert by_id[9]["assist_share"] is None                             # goalies carry none
    empty = lu.attach_assist_share([{"player_id": 1, "position": "F"}], [({}, 1.0), ({}, 0.5)], "2025-12-05")
    assert empty[0]["assist_share"] is None                             # outage reads as missing, not as prior


def test_dressing_prefers_players_from_the_teams_last_game():
    """`[lane nhl-scratch-dilution]`: a regular who missed the team's previous game loses his slot to a
    skater who played it, even with far more total ice time; a book-listed player still dresses first."""
    fwd = [{"player_id": 100 + i, "position": "F", "games_played": 8, "toi_avg": 18.0 - i * 0.5,
            "toi_total": (18.0 - i * 0.5) * 8, "played_last_game": True} for i in range(12)]
    injured = {"player_id": 99, "position": "F", "games_played": 7, "toi_avg": 21.0, "toi_total": 147.0,
               "played_last_game": False}
    callup = {"player_id": 150, "position": "F", "games_played": 1, "toi_avg": 9.0, "toi_total": 9.0,
              "played_last_game": True}
    dmen = [{"player_id": 200 + i, "position": "D", "games_played": 8, "toi_avg": 20.0 - i, "toi_total": (20.0 - i) * 8,
             "played_last_game": True} for i in range(6)]
    fwd[11]["played_last_game"] = False          # the 12th forward also sat out last game
    usage = fwd + [injured, callup] + dmen
    slotted = {r["player_id"] for r in lu.infer_lines([dict(r) for r in usage]) if r.get("line_slot")}
    assert 99 not in slotted and 150 in slotted   # the injured star sits; the call-up who played dresses
    assert 111 not in slotted                     # 12th F missed last game too; the call-up outranks him
    forced = {r["player_id"] for r in lu.infer_lines([dict(r) for r in usage], must_dress={99}) if r.get("line_slot")}
    assert 99 in forced                           # a posted book line still wins
