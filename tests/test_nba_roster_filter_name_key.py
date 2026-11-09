"""One player, one key in the NBA pregame pool build (lane nba-roster-filter-name-key).

Measured on the fleet, 2026-11-08 slate (fleet code e2558013c, fleet data):
  * The roster filter dropped exactly one priced player: "Bobby Portis Jr." (the 2026-27 player_logs spelling),
    because `_norm_name_key` keeps periods and so never strips " JR.", while rosters_2026-27.csv says "Bobby Portis".
    Both rows carry PLAYER_ID 1626171. He played 20 min (ESPN box), and his 6-7 served live prop rows had no Live
    proj., because the live re-sim resumes from the pregame frames and he was not in them.
  * The NBA recency rule's prop-line readmit missed "Terrence Shannon Jr" (logs) against the books' "Terrence Shannon
    Jr.". The MIN @ UTA sim left him out, and he played 18 min.
  * The expected-minutes merge missed both players in the same way.

Fixture shapes are production's: rosters_<season>.csv carries the commonteamroster columns, pregame_expected_minutes
carries no player_id, and the props snapshot carries `market`/`player_name`. Each test drives the function the sim
calls, through the orchestrator hook where one exists, and an OFF arm shows that the widened match is what keeps the
player in.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.basketball_engine.orchestrator import hooks as orch_hooks
from syndicate.features.basketball_engine.orchestrator import player_names
from syndicate.features.basketball_engine.orchestrator.runtime import OrchestratorEnv
from syndicate.features.shared import basketball_props_smart_sim as bps
from syndicate.features.shared import nba_season_phase as ph
from syndicate.features.shared import nba_sim_availability as av
from syndicate.features.shared import nba_team_inputs
from tests.test_nba_prop_calibration import write_season_types

D = "2026-11-08"
MIA = [  # (PLAYER_ID, roster PLAYER) -- rosters_2026-27.csv, as the fleet's ESPN roster writer spells them
    (1626171, "Bobby Portis"), (1628389, "Bam Adebayo"), (1627741, "Andrew Wiggins"), (202691, "Klay Thompson"),
    (1630558, "Davion Mitchell"), (1631216, "Pelle Larsson"),
]


def _processed(tmp_path: Path) -> Path:
    p = tmp_path / "nba_source" / "data" / "processed"
    p.mkdir(parents=True)
    with (p / "rosters_2026-27.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["TeamID", "SEASON", "PLAYER", "PLAYER_ID", "POSITION", "TEAM_ABBREVIATION", "ROSTER_SOURCE"])
        for pid, name in MIA:
            w.writerow([1610612748, "2026-27", name, pid, "F", "MIA", "espn"])
        w.writerow([1610612758, "2026-27", "Zach LaVine", 203897, "G", "SAC", "espn"])
    return p


def _pool(*extra) -> pd.DataFrame:
    """The props_df pool for MIA: player_logs spellings, as props_predictions carries them."""
    rows = [{"player_id": pid, "player_name": name, "team": "MIA"} for pid, name in MIA[1:]]
    rows.insert(0, {"player_id": 1626171, "player_name": "Bobby Portis Jr.", "team": "MIA"})
    rows.extend(extra)
    return pd.DataFrame(rows)


def _filter(processed: Path, df: pd.DataFrame) -> pd.DataFrame:
    # The call smart_sim.py's _augment_team_players makes (orchestrator/hooks.py -> the bridge's _local port).
    orch = OrchestratorEnv.for_processed_root(processed, "nba")
    return orch_hooks._filter_team_players_against_processed_roster(df, D, "SAC", "MIA", "MIA", orch=orch)


def _break_canonical_key(monkeypatch):
    """OFF arm: the widened match cannot run (its import raises), so only the old `_norm_name_key` match is left."""
    def boom(*_a, **_k):
        raise RuntimeError("canonical key disabled for the OFF arm")

    monkeypatch.setattr(player_names, "normalize_player_name_key", boom)


def test_suffix_period_split_is_kept_by_player_id_and_canonical_key(tmp_path, monkeypatch, capsys):
    processed = _processed(tmp_path)
    departed = {"player_id": 1629639, "player_name": "Tyler Herro", "team": "MIA"}   # on no current MIA roster row
    on = _filter(processed, _pool(departed))
    assert "Bobby Portis Jr." in set(on["player_name"])
    assert "Tyler Herro" not in set(on["player_name"])            # the filter still filters
    assert len(on) == len(MIA)
    out = capsys.readouterr().out
    assert "ROSTER_FILTER_DROPPED" in out and "Tyler Herro" in out and "Portis" not in out

    _break_canonical_key(monkeypatch)
    off = _filter(processed, _pool(departed))
    assert "Bobby Portis Jr." not in set(off["player_name"])      # the 2026-11-08 production behaviour
    assert set(on["player_name"]) - set(off["player_name"]) == {"Bobby Portis Jr."}


def test_player_id_alone_keeps_a_differently_spelled_name(tmp_path):
    processed = _processed(tmp_path)
    df = _pool()
    df.loc[df["player_id"] == 1626171, "player_name"] = "Robert Portis"   # no name key can match; the id does
    assert "Robert Portis" in set(_filter(processed, df)["player_name"])


def test_canonical_key_alone_keeps_a_row_with_no_id(tmp_path):
    processed = _processed(tmp_path)
    df = _pool()
    df.loc[df["player_id"] == 1626171, "player_id"] = None             # no id: the name must carry it
    assert "Bobby Portis Jr." in set(_filter(processed, df)["player_name"])


def test_expected_minutes_merge_matches_the_split_spelling(tmp_path, monkeypatch):
    processed = _processed(tmp_path)
    # The production file (fleet 2026-11-08): no player_id, the ESPN spelling, the starters producer's source tag.
    pd.DataFrame([
        {"date": D, "team_tri": "MIA", "player_name": "Bobby Portis", "starter_prob": 0.0, "is_starter": False,
         "exp_min_source": "nba_starters_v1:2027_regular:last5"},
        {"date": D, "team_tri": "MIA", "player_name": "Bam Adebayo", "starter_prob": 1.0, "is_starter": True,
         "exp_min_source": "nba_starters_v1:2027_regular:last5"},
    ]).to_csv(processed / f"pregame_expected_minutes_{D}.csv", index=False)
    monkeypatch.setattr(nba_team_inputs, "enabled", lambda: True)          # production: team inputs on (default)
    monkeypatch.setattr(nba_team_inputs, "ensure_starters", lambda **_k: None)
    bps._PREGAME_EXPECTED_MINUTES_CACHE_LOCAL.clear()
    orch = OrchestratorEnv.for_processed_root(processed, "nba")
    merged, diag = orch_hooks._merge_pregame_expected_minutes_for_team(_pool(), D, "MIA", orch=orch)
    row = merged[merged["player_name"] == "Bobby Portis Jr."].iloc[0]
    assert diag["applied"] and row["starter_prob"] == 0.0              # was NaN: no key met "Bobby Portis"
    assert merged[merged["player_name"] == "Bam Adebayo"].iloc[0]["starter_prob"] == 1.0

    _break_canonical_key(monkeypatch)
    bps._PREGAME_EXPECTED_MINUTES_CACHE_LOCAL.clear()
    merged_off, _ = orch_hooks._merge_pregame_expected_minutes_for_team(_pool(), D, "MIA", orch=orch)
    assert pd.isna(merged_off[merged_off["player_name"] == "Bobby Portis Jr."].iloc[0]["starter_prob"])


@pytest.fixture
def recency_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "_fetch_types", lambda year, timeout=10.0: None)
    write_season_types(tmp_path)
    with (tmp_path / av.HISTORY).open("w", encoding="utf-8") as fh:
        fh.write("PLAYER_NAME,TEAM_ABBREVIATION,GAME_ID,GAME_DATE,MIN\n")
        # MIN this season; Shannon (stats.nba spelling, no period) played 10-20, then missed 10-22 and 10-24.
        for gid, d in (("0022600001", "2026-10-20"), ("0022600010", "2026-10-22"), ("0022600020", "2026-10-24")):
            fh.write(f"Anthony Edwards,MIN,{gid},{d},36\n")
        fh.write("Terrence Shannon Jr,MIN,0022600001,2026-10-20,18\n")
        fh.write("Hurt Guy,MIN,0022600001,2026-10-20,12\n")
    # The books' spelling, with the period. Hurt Guy has no line.
    (tmp_path / "oddsapi_player_props_2026-10-26.csv").write_text(
        "market,player_name,point,price\nplayer_points,Terrence Shannon Jr.,8.5,-110\n", encoding="utf-8")
    (tmp_path / av.FILE).write_text(json.dumps({"enabled": True}), encoding="utf-8")
    return tmp_path


def test_recency_readmit_meets_the_books_spelling(recency_root, monkeypatch):
    def run():
        ex: dict = {}
        s = av.add_nba_recency_exclusions(ex, processed_root=recency_root, date_str="2026-10-26", league_code="nba",
                                          name_key=bps._norm_name_key, env={})   # production passes _norm_name_key
        return ex, s

    on, s_on = run()
    assert s_on["applied"] and s_on["readmitted_with_prop_line"] == 1
    assert on == {"MIN": {"HURT GUY"}}                                  # the rule still excludes the unpriced absentee

    monkeypatch.setattr(av, "_canon", lambda _n: "")                     # OFF arm: the old key match only
    off, s_off = run()
    assert s_off["readmitted_with_prop_line"] == 0
    assert off["MIN"] - on["MIN"] == {"TERRENCE SHANNON"}               # the 2026-11-08 production exclusion
