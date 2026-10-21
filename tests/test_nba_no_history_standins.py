"""Lane nba-no-history-admit: market-implied stand-ins for priced NBA players with no player_logs history.

Reachability first (model_engine_standard.md): every switch state is exercised and off != on is asserted on the
production hook (the sim worker's pool), not only on the module.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.shared import nba_no_history_standins as nhs

DATE = "2026-10-21"


def _write_csv(path: Path, rows, fields=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _roster_row(name, tri, espn_id, pid=""):
    return {"PLAYER": name, "TEAM_ABBREVIATION": tri, "PLAYER_ID": pid, "POSITION": "G", "ESPN_ID": espn_id,
            "ESPN_NAME": name, "ROSTER_SOURCE": "espn", "FETCHED_AT": "2026-10-21T01:28:24+00:00", "SEASON": "2026-27"}


def _odds_row(name, market, point, book="draftkings", snap="2026-10-21T18:00:00+00:00", side="Over"):
    return {"snapshot_ts": snap, "event_id": "e1", "commence_time": "2026-10-22T00:30:00Z", "bookmaker": book,
            "bookmaker_title": book, "market": market, "outcome_name": side, "player_name": name, "point": point,
            "price": -110, "last_update": snap, "home_team": "Houston Rockets", "away_team": "Dallas Mavericks"}


def _check_row(name, tri, espn_id, day, minutes, starter, season_type="preseason", season="2027"):
    return {"league": "nba", "season": season, "season_type": season_type, "date": day, "event_id": "x", "team": tri,
            "player_id": espn_id, "player_name": name, "starter": starter, "box_minutes": minutes,
            "stint_minutes": minutes, "minutes_diff": 0, "within_1": 1, "box_pf": 0, "pbp_pf": 0}


def _to_tri(value):
    return {"houston rockets": "HOU", "dallas mavericks": "DAL"}.get(str(value or "").strip().lower(),
                                                                     str(value or "").strip().upper())


@pytest.fixture()
def processed(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv(nhs.FLAG, raising=False)
    monkeypatch.delenv("SYNDICATE_NBA_CURRENT_ROSTERS", raising=False)
    p = tmp_path / "nba_source" / "data" / "processed"
    roster = [_roster_row("Cooper Flagg", "DAL", "100", "1642843"), _roster_row("Kyrie Irving", "DAL", "6442"),
              _roster_row("Unpriced Rookie", "DAL", "777"), _roster_row("One Game Rookie", "DAL", "888"),
              _roster_row("Amen Thompson", "HOU", "200", "1641708")]
    from syndicate.features.shared.nba_current_rosters import STATS_TEAM_ID

    # the roster index refuses an incomplete file: all 30 teams, >= 8 players each
    roster += [_roster_row(f"Filler {t} {i}", t, f"9{t}{i}") for t in sorted(STATS_TEAM_ID) for i in range(8)]
    _write_csv(p / "rosters_2026-27.csv", roster)
    _write_csv(p / f"oddsapi_player_props_{DATE}.csv", [
        _odds_row("Kyrie Irving", "player_points", 20.5),
        _odds_row("Kyrie Irving", "player_points", 21.5, book="fanduel"),
        _odds_row("Kyrie Irving", "player_points", 19.5, book="fanduel", snap="2026-10-21T12:00:00+00:00"),  # older
        _odds_row("Kyrie Irving", "player_points", 30.5, book="betmgm", snap="2026-10-22T01:00:00+00:00"),  # post-tip
        _odds_row("Kyrie Irving", "player_points_alternate", 25.5),
        _odds_row("Kyrie Irving", "player_points", 20.5, side="Under"),
        _odds_row("Kyrie Irving", "player_assists", 4.5),
        _odds_row("One Game Rookie", "player_points", 8.5),
        _odds_row("Cooper Flagg", "player_points", 21.5),
    ])
    _write_csv(p / "rotation_stints" / "player_checks_2026-10-11.csv", [
        _check_row("Kyrie Irving", "DAL", "6442", "2026-10-11", 22.0, 1),
        _check_row("One Game Rookie", "DAL", "888", "2026-10-11", 15.0, 0),
        _check_row("Unpriced Rookie", "DAL", "777", "2026-10-11", 12.0, 0),
    ])
    _write_csv(p / "rotation_stints" / "player_checks_2026-10-16.csv", [
        _check_row("Kyrie Irving", "DAL", "6442", "2026-10-16", 25.0, 1),
        _check_row("Unpriced Rookie", "DAL", "777", "2026-10-16", 14.0, 0),
    ])
    # a regular-season game ON the slate date must not count as preseason
    _write_csv(p / "rotation_stints" / f"player_checks_{DATE}.csv", [
        _check_row("One Game Rookie", "DAL", "888", DATE, 30.0, 1),
    ])
    _write_csv(p / "player_logs.csv", [
        {"SEASON_ID": "22025", "PLAYER_NAME": "Cooper Flagg", "MIN": 30, "PTS": 15, "REB": 6, "AST": 3, "FG3M": 1,
         "STL": 1, "BLK": 1, "TOV": 2},
    ])
    return p


def _props_df():
    return pd.DataFrame([
        {"player_id": 1642843, "player_name": "Cooper Flagg", "team": "DAL", "opponent": "HOU", "is_home": 0.0,
         "roll10_min": 34.0, "pred_pts": 21.0},
        {"player_id": 1641708, "player_name": "Amen Thompson", "team": "HOU", "opponent": "DAL", "is_home": 1.0,
         "roll10_min": 33.0, "pred_pts": 17.0},
    ])


def test_mode_is_off_unless_set():
    assert nhs.mode({}) == "off"
    assert nhs.mode({nhs.FLAG: "off"}) == "off"
    assert nhs.mode({nhs.FLAG: "garbage"}) == "off"
    assert nhs.mode({nhs.FLAG: "shadow"}) == "shadow"
    assert nhs.mode({nhs.FLAG: "on"}) == "on"
    assert nhs.mode({nhs.FLAG: "1"}) == "on"


def test_minutes_prior_is_the_fitted_line_and_clamped():
    assert nhs.minutes_prior(23.5, 1.0) == pytest.approx(2.012 + 0.577 * 23.5 + 15.148)
    assert nhs.minutes_prior(27.0, 1 / 3) == pytest.approx(2.012 + 0.577 * 27.0 + 15.148 / 3)
    assert nhs.minutes_prior(2.0, 0.0) == nhs.MINUTES_FLOOR
    assert nhs.minutes_prior(48.0, 1.0) == nhs.MINUTES_CAP


def test_posted_lines_latest_pretip_over_per_book_then_median(processed):
    from syndicate.features.shared.nba_current_rosters import name_key

    lines = nhs.posted_lines(processed, DATE, to_tri=_to_tri, name_key=name_key)
    kyrie = lines[(frozenset(("HOU", "DAL")), "kyrie irving")]
    # draftkings 20.5 and fanduel's LATEST 21.5 (not its older 19.5); betmgm posted after tip; alternate and Under ignored
    assert kyrie["pts"] == pytest.approx(21.0)
    assert kyrie["ast"] == pytest.approx(4.5)


def test_build_admits_only_priced_no_history_players_with_preseason_minutes(processed):
    from syndicate.features.shared.nba_current_rosters import name_key

    standins, diag = nhs.build_standins(processed_root=processed, date_str=DATE, props_df=_props_df(),
                                        name_key=name_key, to_tri=_to_tri)
    assert [s.player_name for s in standins] == ["Kyrie Irving"]
    k = standins[0]
    assert (k.team, k.opponent, k.is_home) == ("DAL", "HOU", False)
    assert k.preseason_games == 2 and k.preseason_mean_minutes == pytest.approx(23.5) and k.start_share == 1.0
    assert k.minutes == pytest.approx(nhs.minutes_prior(23.5, 1.0), abs=0.005)
    assert k.rates_pm["pts"] == pytest.approx(21.0 / k.minutes)
    assert k.rate_source["pts"] == "line" and k.rate_source["reb"] == "league_pm"
    assert k.rates_pm["reb"] == pytest.approx(6 / 30)  # league rate from player_logs.csv
    # priced but one preseason game (the slate-day regular-season row does not count): skipped with the reason
    assert diag["skipped"] == {"One Game Rookie (DAL)": "preseason_games=1<2"}
    # Cooper Flagg is priced but already in the pool; Unpriced Rookie has no line -- neither is considered


def test_add_standins_off_and_shadow_return_the_pool_untouched(processed, capsys):
    pool = _props_df()
    out_off = nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="nba", to_tri=_to_tri,
                               env={})
    assert out_off is pool
    assert "NBA_NO_HISTORY_STANDINS" not in capsys.readouterr().out
    out_shadow = nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="nba", to_tri=_to_tri,
                                  env={nhs.FLAG: "shadow"})
    assert out_shadow is pool
    line = [ln for ln in capsys.readouterr().out.splitlines() if "NBA_NO_HISTORY_STANDINS" in ln][0]
    assert json.loads(line.split("NBA_NO_HISTORY_STANDINS ", 1)[1])["admitted"] == ["Kyrie Irving (DAL)"]


def test_add_standins_on_appends_a_consistent_row_and_off_differs(processed):
    pool = _props_df()
    on = nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="nba", to_tri=_to_tri,
                          env={nhs.FLAG: "on"})
    off = nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="nba", to_tri=_to_tri, env={})
    assert len(on) == len(off) + 1  # off != on
    row = on.iloc[-1]
    assert row["player_name"] == "Kyrie Irving" and row["pool_source"] == nhs.SOURCE
    mins = round(nhs.minutes_prior(23.5, 1.0), 2)
    assert row["roll5_min"] == pytest.approx(mins) and row["roll10_min"] == pytest.approx(mins)
    assert row["pred_pts"] == pytest.approx(21.0) and row["roll10_pts"] == pytest.approx(21.0)
    assert row["pred_pra"] == pytest.approx(row["pred_pts"] + row["pred_reb"] + row["pred_ast"])
    # the original rows are untouched and carry no pool_source
    assert on.iloc[: len(pool)]["pool_source"].isna().all()


def test_add_standins_is_nba_only_and_never_raises(processed, monkeypatch):
    pool = _props_df()
    assert nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="wnba", to_tri=_to_tri,
                            env={nhs.FLAG: "on"}) is pool

    def boom(**_kw):
        raise RuntimeError("x")

    monkeypatch.setattr(nhs, "build_standins", boom)
    assert nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="nba", to_tri=_to_tri,
                            env={nhs.FLAG: "on"}) is pool


def test_no_current_roster_admits_nobody(processed, monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_CURRENT_ROSTERS", "0")
    pool = _props_df()
    assert len(nhs.add_standins(pool, processed_root=processed, date_str=DATE, league_code="nba", to_tri=_to_tri,
                                env={nhs.FLAG: "on"})) == len(pool)


def test_tag_sim_output_takes_standins_out_of_players(processed):
    pool = nhs.add_standins(_props_df(), processed_root=processed, date_str=DATE, league_code="nba",
                            to_tri=_to_tri, env={nhs.FLAG: "on"})
    out = {"home": "HOU", "away": "DAL", "context": {"props_pool": {}},
           "players": {"home": [{"player_name": "Amen Thompson", "min_mean": 33.0}],
                       "away": [{"player_name": "Cooper Flagg", "min_mean": 33.0, "pts_mean": 20.0},
                                {"player_name": "Kyrie Irving", "min_mean": 30.1, "pts_mean": 20.2,
                                 "prop_ladders": {"pts": {}}}]}}
    rec = nhs.tag_sim_output(out, pool, ("HOU", "DAL"))
    assert [r["player_name"] for r in out["players"]["away"]] == ["Cooper Flagg"]
    assert out["context"]["no_history_standins"] == rec
    entry = rec["DAL"][0]
    assert entry["player_name"] == "Kyrie Irving" and entry["min_mean"] == 30.1 and "prop_ladders" not in entry
    assert entry["minutes_prior"] == pytest.approx(nhs.minutes_prior(23.5, 1.0), abs=0.005)
    assert nhs.is_standin(entry) and not nhs.is_standin(out["players"]["away"][0])


def test_tag_sim_output_without_standins_changes_nothing():
    out = {"home": "HOU", "away": "DAL", "players": {"home": [{"player_name": "A"}], "away": []}, "context": {}}
    before = json.dumps(out, sort_keys=True)
    assert nhs.tag_sim_output(out, _props_df(), ("HOU", "DAL")) == {}
    assert json.dumps(out, sort_keys=True) == before


def test_sim_worker_pool_reachability_off_vs_on(processed, monkeypatch):
    """The production hook: the sim worker re-reads the pool from disk and must add the same stand-ins."""
    from syndicate.features.shared import basketball_props_smart_sim as bpss

    props_path = processed / f"props_predictions_{DATE}.csv"
    _props_df().to_csv(props_path, index=False)
    monkeypatch.setattr(bpss, "_to_tricode_local", _to_tri, raising=False)

    def worker_pool(mode):
        monkeypatch.setenv(nhs.FLAG, mode)
        bpss._smart_sim_worker_init_local(DATE, 100, 1, False, str(props_path), "historical", "nba", {}, {}, {}, {}, {})
        return bpss._SMARTSIM_WORKER_STATE["props_df"]

    off, on = worker_pool("off"), worker_pool("on")
    assert "Kyrie Irving" not in set(off["player_name"])
    assert "Kyrie Irving" in set(on["player_name"])  # off != on through the real hook
    assert len(on) == len(off) + 1


# ------------------------------------------------------------------------------------------- live re-sim

def _live_inputs(flag: bool):
    home = pd.DataFrame({"player_name": ["Amen Thompson", "Fred VanVleet"]})
    away = pd.DataFrame({"player_name": ["Cooper Flagg", "Kyrie Irving"]})
    if flag:
        home["pool_source"] = [None, nhs.SOURCE]
        away["pool_source"] = [None, nhs.SOURCE]
    return {"home_players": home, "away_players": away}


def _box_sim(rng, gs):
    hb = {"players": [{"player_name": "Amen Thompson", "pts": 10}, {"player_name": "Fred VanVleet", "pts": 8}]}
    ab = {"players": [{"player_name": "Cooper Flagg", "pts": 12}, {"player_name": "Kyrie Irving", "pts": 9}]}
    return hb, ab, [100, 0, 0, 0], [98, 0, 0, 0]


def test_live_resim_hides_standin_remainders_and_off_differs():
    from syndicate.features.nba import live_resim as lr

    on = lr.resim_live_game(_live_inputs(True), None, sims=100, simulate=_box_sim)
    off = lr.resim_live_game(_live_inputs(False), None, sims=100, simulate=_box_sim)
    assert set(on["player_remainders"]["home"]) == {"Amen Thompson"}
    assert set(on["player_remainders"]["away"]) == {"Cooper Flagg"}
    assert on["no_history_standins_hidden"] == ["Fred VanVleet", "Kyrie Irving"]
    # without the flag (every pool before this lane): every player published, no new key
    assert set(off["player_remainders"]["away"]) == {"Cooper Flagg", "Kyrie Irving"}
    assert "no_history_standins_hidden" not in off
    # the game itself is the same either way: hiding is output-only
    assert on["total_dist"] == off["total_dist"] and on["home_win_prob"] == off["home_win_prob"]


def test_live_props_never_price_a_hidden_standin():
    from syndicate.features.nba import live_resim as lr

    on = lr.resim_live_game(_live_inputs(True), None, sims=100, simulate=_box_sim)
    actuals = {lr.normalize_name("Kyrie Irving"): {"pts": 4}, lr.normalize_name("Cooper Flagg"): {"pts": 6}}
    lines = {(lr.normalize_name("Kyrie Irving"), "pts"): 20.5, (lr.normalize_name("Cooper Flagg"), "pts"): 21.5}
    rows, _counts = lr.build_live_props(on, actuals, lines)
    assert {r["playerName"] for r in rows} == {"Cooper Flagg"}


def test_preseason_minutes_reads_only_this_seasons_preseason_before_the_slate(processed):
    # a 2025-26 preseason file (season label 2026) and a file dated before this season's September are ignored
    _write_csv(processed / "rotation_stints" / "player_checks_2025-10-10.csv", [
        _check_row("Kyrie Irving", "DAL", "6442", "2025-10-10", 40.0, 1, season="2026"),
    ])
    _write_csv(processed / "rotation_stints" / "player_checks_2026-08-30.csv", [
        _check_row("Kyrie Irving", "DAL", "6442", "2026-08-30", 40.0, 1),
    ])
    got = nhs.preseason_minutes(processed, DATE)
    assert sorted(got["6442"]) == [(22.0, 1), (25.0, 1)]
    assert "888" in got and got["888"] == [(15.0, 0)]  # the slate-day regular-season game is not counted


def test_worker_stamp_equals_the_reuse_expectation_even_if_the_odds_file_moves(processed, monkeypatch):
    """The reuse branch expects `_props_pool_for_teams_local(parent props_df)`; each worker stamps the same function of
    ITS props_df. They must agree or every reused sim reads as stale on every refresh. The worker appends the parent's
    rows, so an odds file rewritten between the two reads changes nothing."""
    from syndicate.features.shared import basketball_props_smart_sim as bpss

    monkeypatch.setenv(nhs.FLAG, "on")
    monkeypatch.setattr(bpss, "_to_tricode_local", _to_tri, raising=False)
    props_path = processed / f"props_predictions_{DATE}.csv"
    _props_df().to_csv(props_path, index=False)
    parent = nhs.add_standins(pd.read_csv(props_path), processed_root=processed, date_str=DATE, league_code="nba",
                              to_tri=_to_tri)
    # the odds file is rewritten mid-run: Kyrie's line is gone
    (processed / f"oddsapi_player_props_{DATE}.csv").write_text("snapshot_ts,market\n", encoding="utf-8")
    bpss._smart_sim_worker_init_local(DATE, 100, 1, False, str(props_path), "historical", "nba", {}, {}, {}, {}, {})
    worker = bpss._SMARTSIM_WORKER_STATE["props_df"]
    teams = ("HOU", "DAL")
    assert "Kyrie Irving" in set(worker["player_name"])
    assert bpss._props_pool_for_teams_local(worker, teams) == bpss._props_pool_for_teams_local(parent, teams)
    # and a worker with no parent rows (spawn) rebuilds from what it sees -- logged as such
    nhs._BUILT.clear()
    rebuilt = nhs.add_standins(pd.read_csv(props_path), processed_root=processed, date_str=DATE, league_code="nba",
                               to_tri=_to_tri, reuse_built=True)
    assert "Kyrie Irving" not in set(rebuilt["player_name"])
