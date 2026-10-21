"""NBA current rosters (lane nba-current-rosters): the ESPN producer, the as-of re-key of the props features, the
player-priors fallback for a moved player, and the sim-reuse pool check -- each shown reachable (off != on).

Measured motivation (2026-10-20, fleet): 179 of 460 simulated players in the 10-20/10-21 NBA sims were not on the team
they were simulated for, every one on his 2025-26 team (scripts/nba_sim_roster_audit.py)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.shared import nba_current_rosters as ncr
from syndicate.features.shared import basketball_props_features as features_module
from syndicate.features.shared.basketball_props_onnx import PlayerPriors, PlayerPriorsConfig

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
TRI_TO_ESPN = {tri: espn for espn, tri in ncr.ESPN_TO_TRI.items()}


def _rosters(overrides: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    teams = {tri: [f"Filler {tri} {i}" for i in range(9)] for tri in ncr.STATS_TEAM_ID}
    for tri, names in (overrides or {}).items():
        teams[tri] = list(names) + [f"Filler {tri} {i}" for i in range(9 - len(names))]
    return teams


class FakeEspn:
    """site.api.espn.com stand-in: /teams lists 30 teams, /teams/{id}/roster serves `rosters`."""

    def __init__(self, rosters: dict[str, list[str]], *, fail: set[str] = frozenset(), season: str = "2026-27"):
        self.rosters, self.fail, self.season, self.calls = rosters, set(fail), season, 0
        self.ids = {tri: str(100 + i) for i, tri in enumerate(sorted(rosters))}

    def __call__(self, url: str) -> dict:
        self.calls += 1
        if url.endswith("/teams"):
            teams = [{"team": {"id": self.ids[tri], "abbreviation": TRI_TO_ESPN.get(tri, tri)}} for tri in self.rosters]
            return {"sports": [{"leagues": [{"teams": teams}]}]}
        espn_id = url.rstrip("/").split("/")[-2]
        tri = next(t for t, i in self.ids.items() if i == espn_id)
        if tri in self.fail:
            raise TimeoutError("espn timeout")
        athletes = [{"displayName": n, "id": f"e{abs(hash(n)) % 10**6}", "position": {"abbreviation": "G"},
                     "status": {"type": "active"}} for n in self.rosters[tri]]
        return {"season": {"displayName": self.season}, "team": {"displayName": tri}, "athletes": athletes}


def _write_roster(processed: Path, rosters: dict[str, list[str]], *, fetched_at: datetime = NOW) -> Path:
    path = ncr.roster_path(processed, "2026-27")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ncr.COLUMNS)
        w.writeheader()
        for tri, names in rosters.items():
            for n in names:
                w.writerow({"PLAYER": n, "TEAM_ABBREVIATION": tri, "ROSTER_SOURCE": "espn", "FETCHED_AT": fetched_at.isoformat()})
    return path


# ---------------------------------------------------------------------------------------------------- producer


def test_name_key_matches_stats_and_espn_spellings():
    assert ncr.name_key("Nikola Vučević") == ncr.name_key("Nikola Vucevic")
    assert ncr.name_key("Kelly Oubre Jr.") == ncr.name_key("Kelly Oubre")
    assert ncr.name_key("Kentavious Caldwell-Pope") == "kentavious caldwell pope"
    assert ncr.name_key("A.J. Green") == ncr.name_key("AJ Green")
    assert ncr.name_key("Jimmy Butler III") == "jimmy butler"
    assert ncr.name_key(None) == "" and ncr.name_key("nan") == ""


def test_refresh_writes_a_complete_roster_with_stats_ids_and_spelling(tmp_path):
    (tmp_path / "player_logs.csv").write_text(
        "PLAYER_ID,PLAYER_NAME,TEAM_ABBREVIATION,GAME_DATE\n2544,LeBron James,LAL,2026-04-12\n1629008,A.J. Green,MIL,2026-04-12\n",
        encoding="utf-8",
    )
    fake = FakeEspn(_rosters({"PHI": ["LeBron James", "Joel Embiid"], "MIL": ["AJ Green"]}))
    out = ncr.refresh_current_rosters(tmp_path, "2026-10-20", http_get=fake, now=NOW, env={})
    assert out["wrote"] is True and out["failed"] == [] and out["players"] == 30 * 9
    rows = list(csv.DictReader(ncr.roster_path(tmp_path, "2026-27").open(encoding="utf-8")))
    by = {r["ESPN_NAME"]: r for r in rows}
    assert by["LeBron James"]["TEAM_ABBREVIATION"] == "PHI" and by["LeBron James"]["PLAYER_ID"] == "2544"
    # stats.nba spelling wins (the sim's roster filter keeps periods), ESPN's is kept beside it
    assert by["AJ Green"]["PLAYER"] == "A.J. Green" and by["AJ Green"]["PLAYER_ID"] == "1629008"
    assert by["Joel Embiid"]["PLAYER_ID"] == ""  # no stats.nba history in the fixture: blank, never guessed
    assert {r["SEASON"] for r in rows} == {"2026-27"} and {r["ROSTER_SOURCE"] for r in rows} == {"espn"}
    assert {r["TEAM_ABBREVIATION"] for r in rows} == set(ncr.STATS_TEAM_ID)  # ESPN GS/NY/SA/... mapped to tricodes
    assert not list(tmp_path.glob("*.tmp"))


def test_a_failed_team_keeps_its_previous_rows_or_nothing_is_written(tmp_path):
    first = ncr.refresh_current_rosters(tmp_path, "2026-10-20", http_get=FakeEspn(_rosters()), now=NOW, env={})
    assert first["wrote"]
    before = ncr.roster_path(tmp_path, "2026-27").read_bytes()
    later = NOW.replace(hour=21)
    carried = ncr.refresh_current_rosters(tmp_path, "2026-10-20", http_get=FakeEspn(_rosters(), fail={"BOS"}), now=later, env={})
    assert carried["wrote"] and carried["carried_over"] == ["BOS"]
    # no previous ESPN file for the team -> a team short -> NOTHING written (a partial file would hide the old season's)
    other = tmp_path / "fresh"
    other.mkdir()
    refused = ncr.refresh_current_rosters(other, "2026-10-20", http_get=FakeEspn(_rosters(), fail={"BOS"}), now=NOW, env={})
    assert refused["wrote"] is False and refused["failed"] == ["BOS"] and "incomplete" in refused["reason"]
    assert not ncr.roster_path(other, "2026-27").exists()
    assert before  # the first file existed before the carry-over rewrite


def test_throttle_kill_switch_and_wrong_season(tmp_path):
    fake = FakeEspn(_rosters())
    assert ncr.refresh_current_rosters(tmp_path, "2026-10-20", http_get=fake, now=NOW, env={})["wrote"]
    calls = fake.calls
    again = ncr.refresh_current_rosters(tmp_path, "2026-10-20", http_get=fake, now=NOW.replace(minute=30), env={})
    assert "skipped" in again and fake.calls == calls
    off = ncr.refresh_current_rosters(tmp_path, "2026-10-20", http_get=fake, now=NOW, env={ncr.FLAG: "0"}, force=True)
    assert off["skipped"] == f"{ncr.FLAG} off" and fake.calls == calls
    wrong = ncr.refresh_current_rosters(tmp_path / "x", "2026-10-20", http_get=FakeEspn(_rosters(), season="2025-26"), now=NOW, env={})
    assert wrong["wrote"] is False and "ESPN serves season 2025-26" in wrong["reason"]


def test_index_refuses_future_knowledge_incomplete_files_and_ambiguity(tmp_path):
    _write_roster(tmp_path, _rosters({"PHI": ["LeBron James"]}))
    idx = ncr.current_roster_index(tmp_path, "2026-10-21", env={})
    assert idx is not None and idx.team_for(player_name="LEBRON JAMES") == "PHI"
    assert ncr.current_roster_index(tmp_path, "2026-10-19", env={}) is not None  # fetched the day after: allowed
    # an as-of replay of a past date must not see moves made after it
    assert ncr.current_roster_index(tmp_path, "2026-03-10", env={}) is None
    assert ncr.current_roster_index(tmp_path, "2026-10-21", env={ncr.FLAG: "off"}) is None
    short = _rosters()
    short["BOS"] = short["BOS"][:3]
    _write_roster(tmp_path, short)
    assert ncr.current_roster_index(tmp_path, "2026-10-21", env={}) is None
    _write_roster(tmp_path, _rosters({"PHI": ["Jalen Williams"], "OKC": ["Jalen Williams"]}))
    idx = ncr.current_roster_index(tmp_path, "2026-10-21", env={})
    assert idx is not None and idx.team_for(player_name="Jalen Williams") is None  # two current players, never guess


# --------------------------------------------------------------------------------- props features re-key (off != on)

HEADER = "GAME_DATE,PLAYER_ID,PLAYER_NAME,TEAM_ABBREVIATION,MATCHUP,MIN,PTS,REB,AST,FG3M,FG3A,STL,BLK,TOV,FGM,FGA,FTA,FTM,OREB,DREB,PF,PLUS_MINUS\n"


def _seed_nba(root: Path) -> Path:
    processed = root / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "player_logs.csv").write_text(
        HEADER
        + "2026-04-10,2544,LeBron James,LAL,LAL vs. DEN,34,25,8,8,2,6,1,1,3,10,20,5,4,1,7,2,5\n"
        + "2026-04-12,2544,LeBron James,LAL,LAL vs. UTA,33,22,7,9,1,5,1,0,4,9,19,4,3,1,6,2,3\n"
        + "2026-04-12,202331,Paul George,PHI,PHI @ BOS,30,18,5,4,3,7,2,0,2,7,15,2,2,0,5,3,-4\n"
        + "2026-04-12,1630178,Tyrese Maxey,PHI,PHI @ BOS,36,28,4,6,4,9,1,0,2,10,21,5,4,0,4,1,-2\n",
        encoding="utf-8",
    )
    (processed / "game_odds_2026-10-20.csv").write_text("home_team,visitor_team\nPHI,NYK\n", encoding="utf-8")
    return processed


def _teams(features) -> dict[str, str]:
    return {str(r["player_name"]): str(r["team"]) for _, r in features.iterrows()}


def test_features_rekey_to_the_current_roster_and_drop_departed(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(ncr.FLAG, raising=False)
    processed = _seed_nba(tmp_path)
    _write_roster(processed, _rosters({"PHI": ["LeBron James", "Tyrese Maxey"]}))  # Paul George on no roster
    feats = features_module.build_features_for_date_local(processed_root=processed, date="2026-10-20")
    assert _teams(feats) == {"LeBron James": "PHI", "Tyrese Maxey": "PHI"}
    lebron = feats[feats["player_name"] == "LeBron James"].iloc[0]
    assert float(lebron["is_home"]) == 1.0 and float(lebron["lag1_pts"]) == 22.0  # his own history, his new team's game
    line = next(l for l in capsys.readouterr().out.splitlines() if "NBA_CURRENT_ROSTER_REKEY" in l)
    rekey = json.loads(line.split("NBA_CURRENT_ROSTER_REKEY ", 1)[1])
    assert (rekey["moved"], rekey["departed"], rekey["kept"]) == (1, 1, 1)


def test_features_rekey_off_is_the_pre_fix_team(tmp_path, monkeypatch, capsys):
    processed = _seed_nba(tmp_path)
    _write_roster(processed, _rosters({"PHI": ["LeBron James", "Tyrese Maxey"]}))
    monkeypatch.setenv(ncr.FLAG, "0")
    off = _teams(features_module.build_features_for_date_local(processed_root=processed, date="2026-10-20"))
    assert off == {"LeBron James": "LAL", "Paul George": "PHI", "Tyrese Maxey": "PHI"}
    assert "NBA_CURRENT_ROSTER_REKEY" not in capsys.readouterr().out
    monkeypatch.delenv(ncr.FLAG)
    on = _teams(features_module.build_features_for_date_local(processed_root=processed, date="2026-10-20"))
    assert on != off


def test_features_replay_date_and_other_league_untouched(tmp_path, monkeypatch):
    monkeypatch.delenv(ncr.FLAG, raising=False)
    processed = _seed_nba(tmp_path)
    _write_roster(processed, _rosters({"PHI": ["LeBron James", "Tyrese Maxey"]}))
    replay = _teams(features_module.build_features_for_date_local(processed_root=processed, date="2026-04-13"))
    assert replay["LeBron James"] == "LAL" and "Paul George" in replay
    wnba = tmp_path / "wnba_source" / "data" / "processed"
    wnba.mkdir(parents=True)
    (wnba / "player_logs.csv").write_text((processed / "player_logs.csv").read_text(encoding="utf-8"), encoding="utf-8")
    _write_roster(wnba, _rosters({"PHI": ["LeBron James"]}))
    assert _teams(features_module.build_features_for_date_local(processed_root=wnba, date="2026-10-20"))["LeBron James"] == "LAL"


# ----------------------------------------------------------------------------------------- priors fallback


def test_priors_fall_back_to_the_players_most_recent_team():
    rates = {("LAL", "LEBRON JAMES"): {"min_mu": 34.0, "pts_pm": 0.7}, ("PHI", "TYRESE MAXEY"): {"min_mu": 36.0}}
    priors = PlayerPriors(config=PlayerPriorsConfig(), rates=rates, games={}, latest_team={"LEBRON JAMES": "LAL"})
    assert priors.rate("PHI", "LeBron James", "LEBRON JAMES") == {"min_mu": 34.0, "pts_pm": 0.7}
    assert priors.rate("PHI", "Tyrese Maxey", "TYRESE MAXEY") == {"min_mu": 36.0}
    legacy = PlayerPriors(config=PlayerPriorsConfig(), rates=rates, games={})  # no map = the pre-fix lookup
    assert legacy.rate("PHI", "LeBron James", "LEBRON JAMES") == {}

    from syndicate.features.shared.basketball_props_smart_sim import _prior_rates_for_player_local

    assert _prior_rates_for_player_local(priors=priors, team_tri="PHI", pkey="LEBRON JAMES", player_name="LeBron James")["pts_pm"] == 0.7
    assert _prior_rates_for_player_local(priors=legacy, team_tri="PHI", pkey="LEBRON JAMES", player_name="LeBron James") == {}


def test_compute_priors_records_the_latest_team(tmp_path):
    from syndicate.features.shared.basketball_props_onnx import compute_player_priors_local

    processed = _seed_nba(tmp_path)
    priors = compute_player_priors_local(processed_root=processed, date_str="2026-10-20")
    assert priors.latest_team.get("LEBRON JAMES") == "LAL"
    assert priors.rate("PHI", "LeBron James", "")  # found through the fallback
    assert priors.rate("PHI", "LeBron James", "") == priors.rate("LAL", "LeBron James", "")


# -------------------------------------------------------------------------- sim reuse pool check (real branch)

DATE = "2026-10-21"


def _seed_sim(root: Path, *, pool_stamp: dict | None, props: str) -> tuple[Path, Path]:
    processed, raw = root / "nba_source" / "data" / "processed", root / "nba_source" / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text("home_team,visitor_team,totals,spread_margin\nNYK,PHI,225,3\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text("player_name,team\n" + props, encoding="utf-8")
    payload: dict = {"home": "NYK", "away": "PHI", "players": {"home": [{"player_name": "Jalen Brunson"}], "away": [{"player_name": "Paul George"}]},
                     "context": {}}
    if pool_stamp is not None:
        payload["context"]["props_pool"] = pool_stamp
    (processed / f"smart_sim_{DATE}_NYK_PHI.json").write_text(json.dumps(payload), encoding="utf-8")
    return processed, raw


def _run(processed: Path, raw: Path) -> dict:
    from syndicate.features.shared.basketball_props_smart_sim import _smart_sim_run_date_local

    with patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local",
               side_effect=lambda job: {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}), \
         patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local", return_value=None), \
         patch("syndicate.features.shared.nba_prop_calibration.sim_is_stale", return_value=False):
        return _smart_sim_run_date_local(processed_root=processed, raw_root=raw, date_str=DATE, n_sims=10, seed=None,
                                         max_games=None, overwrite=False, workers=1, league_code="nba")


OLD_PROPS = "Jalen Brunson,NYK\nPaul George,PHI\n"
NEW_PROPS = "Jalen Brunson,NYK\nLeBron James,PHI\n"


def test_unstamped_sim_is_rebuilt_only_while_the_current_roster_is_active(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(ncr.FLAG, raising=False)
    monkeypatch.delenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", raising=False)
    processed, raw = _seed_sim(tmp_path / "a", pool_stamp=None, props=NEW_PROPS)
    _write_roster(processed, _rosters({"PHI": ["LeBron James"], "NYK": ["Jalen Brunson"]}))
    assert _run(processed, raw)["wrote"] == 1
    assert "reason=no_pool_stamp_current_roster_active" in capsys.readouterr().out
    # reachability: the same unstamped file with the switch OFF is reused, as before this lane
    processed, raw = _seed_sim(tmp_path / "b", pool_stamp=None, props=NEW_PROPS)
    _write_roster(processed, _rosters({"PHI": ["LeBron James"], "NYK": ["Jalen Brunson"]}))
    monkeypatch.setenv(ncr.FLAG, "0")
    result = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (0, 1)


def test_stamped_sim_rebuilds_on_pool_change_and_reuses_otherwise(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(ncr.FLAG, raising=False)
    monkeypatch.delenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", raising=False)
    processed, raw = _seed_sim(tmp_path / "a", pool_stamp={"NYK": ["JALEN BRUNSON"], "PHI": ["PAUL GEORGE"]}, props=NEW_PROPS)
    assert _run(processed, raw)["wrote"] == 1
    assert "SMART_SIM_REUSE_STALE_POOL" in capsys.readouterr().out
    processed, raw = _seed_sim(tmp_path / "b", pool_stamp={"NYK": ["JALEN BRUNSON"], "PHI": ["LEBRON JAMES"]}, props=NEW_PROPS)
    result = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (0, 1)


def test_pool_helper_maps_teams_and_keys():
    import pandas as pd
    from syndicate.features.shared.basketball_props_smart_sim import _props_pool_for_teams_local

    df = pd.DataFrame({"player_name": ["LeBron James", "Kelly Oubre Jr.", "Jalen Brunson"], "team": ["PHI", "Philadelphia 76ers", "NYK"]})
    assert _props_pool_for_teams_local(df, ("PHI", "NYK")) == {"PHI": ["KELLY OUBRE JR.", "LEBRON JAMES"], "NYK": ["JALEN BRUNSON"]}
    assert _props_pool_for_teams_local(None, ("PHI",)) == {"PHI": []}
