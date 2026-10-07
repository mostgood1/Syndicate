"""Season-metric evidence for intelligence explanations (lane intelligence-evidence-coverage)."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from syndicate.features import intelligence_season_evidence as se

TODAY = dt.date(2026, 10, 7)

_NBA_HEADER = "team,pace,off_rtg,def_rtg,efg_pct,tov_pct,orb_pct,ft_rate,fg3a_rate,fg3_pct,ts_pct,ast_per_100,games,source\n"


def _nba_rows(values: dict[str, tuple[float, float, float]], games: int = 82) -> str:
    lines = [_NBA_HEADER]
    for team, (pace, off, deff) in values.items():
        lines.append(f"{team},{pace},{off},{deff},0.55,0.12,0.25,0.2,0.4,0.36,0.58,25,{games},player_logs\n")
    return "".join(lines)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    for sport in ("MLB", "NBA", "WNBA", "NHL", "NFL", "NCAAF", "NCAAB", "SOCCER"):
        monkeypatch.delenv(f"SYNDICATE_{sport}_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("SYNDICATE_MLB_DATA_ROOT", raising=False)
    se._CACHE.clear()
    se._TABLES_MEMO.clear()
    return tmp_path


def _write(path: Path, text: str, mtime: dt.date | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        stamp = dt.datetime(mtime.year, mtime.month, mtime.day, 12, tzinfo=dt.timezone.utc).timestamp()
        os.utime(path, (stamp, stamp))
    return path


# --------------------------------------------------------------------------- season calendar

def test_in_season_table_built_before_opening_day_is_prior_season():
    # NHL opened 2026-10-07; the fleet's team_xg_latest.csv was built 2026-08-19.
    assert se.season_status("nhl", dt.date(2026, 8, 19), TODAY) == "prior_season"


def test_preseason_reads_last_complete_season_as_expected_prior():
    # NBA 2026-27 opens 10-20: the 2025-26 table (as of 05-30) is the right prior.
    assert se.season_status("nba", dt.date(2026, 5, 30), TODAY) == "prior_season_expected"


def test_preseason_table_two_seasons_old_is_still_stale():
    assert se.season_status("nba", dt.date(2025, 5, 30), TODAY) == "prior_season"


def test_in_season_current_table_is_current():
    assert se.season_status("wnba", dt.date(2026, 10, 7), TODAY) == "current"


def test_unknown_age_is_not_permissive():
    assert se.season_status("nfl", None, TODAY) == "prior_season"


# --------------------------------------------------------------------------- table selection

def test_newest_season_asof_outranks_stale_plain_seed_and_older_season_rebuild(data_root):
    processed = data_root / "nba_source" / "data" / "processed"
    # The plain season file is a stale seed (5 games) -- must not be chosen.
    _write(processed / "team_advanced_stats_2026.csv", _nba_rows({"ATL": (100, 110, 112), "BOS": (98, 120, 108)}, games=5))
    # A LATER-DATED rebuild of an OLDER season -- must not outrank the newer season.
    _write(processed / "team_advanced_stats_2025_asof_2026-06-03.csv", _nba_rows({"ATL": (1, 1, 1), "BOS": (1, 1, 1)}))
    chosen = _write(processed / "team_advanced_stats_2026_asof_20260530.csv", _nba_rows({"ATL": (100, 110, 112), "BOS": (98, 120, 108)}))
    (table,) = se.season_tables("nba", TODAY)
    assert table.path == chosen


# --------------------------------------------------------------------------- readiness rows

def test_missing_season_table_is_a_required_missing_row(data_root):
    (row,) = se.readiness_rows("ncaab", TODAY)
    assert row["required"] is True
    assert row["exists"] is False
    assert row["season_status"] == "missing"


def test_present_table_row_reports_status_and_count(data_root):
    _write(
        data_root / "nhl_source" / "data" / "processed" / "team_xg_latest.csv",
        "abbr,xgf60,xga60,games\nPIT,3.34,3.21,82\nWSH,3.38,3.40,82\n",
        mtime=dt.date(2026, 8, 19),
    )
    rows = {r["family"]: r for r in se.readiness_rows("nhl", TODAY)}
    assert rows["team_xg"]["exists"] is True
    assert rows["team_xg"]["season_status"] == "prior_season"
    assert rows["team_xg"]["row_count"] == 2
    # The other NHL families are absent in this fixture and must say so.
    assert rows["team_elo"]["exists"] is False


# --------------------------------------------------------------------------- signals

def test_basketball_signals_carry_values_ranks_and_pick_side(data_root):
    _write(
        data_root / "nba_source" / "data" / "processed" / "team_advanced_stats_2026_asof_20260530.csv",
        _nba_rows({"MIN": (99.0, 114.9, 111.0), "IND": (101.0, 109.2, 116.5), "BOS": (97.0, 120.0, 108.0)}),
    )
    signals = se.candidate_season_signals({"sport_slug": "nba", "matchup": "MIN @ IND", "team": "MIN"}, TODAY)
    net = {s["side"]: s for s in signals if s["key"] == "nba_net_rtg"}
    assert net["away"]["display"] == "+3.9"
    assert net["away"]["is_pick_side"] is True
    assert net["home"]["is_pick_side"] is False
    assert net["away"]["rank"] == 2 and net["home"]["rank"] == 3 and net["away"]["of"] == 3
    assert net["away"]["season_status"] == "prior_season_expected"
    text = se.season_evidence_text(signals)
    assert "MIN +3.9 (2nd of 3) vs IND -7.3 (3rd of 3)" in text
    assert "the new season has not started" in text


def test_zero_variance_column_is_not_ranked(data_root):
    _write(
        data_root / "nba_source" / "data" / "processed" / "team_advanced_stats_2026_asof_20260530.csv",
        _nba_rows({"MIN": (100, 114.5, 114.5), "IND": (100, 114.5, 114.5)}),
    )
    signals = se.candidate_season_signals({"sport_slug": "nba", "matchup": "MIN @ IND", "team": "MIN"}, TODAY)
    assert signals == []


def test_ncaaf_event_id_split_uses_rated_team_names(data_root):
    _write(
        data_root / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json",
        json.dumps({"season": 2026, "fetched_at": "2026-09-30T23:40:12Z", "teams": {"alabama": [39.6, 16.6], "georgia": [41.6, 11.8], "texas a m": [30.0, 20.0]}}),
    )
    signals = se.candidate_season_signals(
        {"sport_slug": "ncaaf", "matchup": "BAMA @ UGA", "event_id": "6_Alabama_Georgia", "team": "UGA"}, TODAY
    )
    margin = {s["side"]: s for s in signals if s["key"] == "ncaaf_sp_overall"}
    assert margin["away"]["display"] == "+23.0"
    assert margin["home"]["is_pick_side"] is True
    assert margin["home"]["rank"] == 1


def test_ncaaf_unrated_teams_give_no_signals(data_root):
    _write(
        data_root / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json",
        json.dumps({"season": 2026, "fetched_at": "2026-09-30", "teams": {"alabama": [39.6, 16.6]}}),
    )
    assert se.candidate_season_signals({"sport_slug": "ncaaf", "matchup": "JS @ KS", "event_id": "6_Jacksonville_State_Kennesaw_State"}, TODAY) == []


def test_mlb_pitcher_market_reads_pitcher_pool(data_root):
    payload = {
        "meta": {"season": 2026, "end_date": "2026-09-30"},
        "batters": {"607259": {"overall": {"xwoba": 0.4, "pitches": 300}}},
        "pitchers": {
            "607259": {"overall": {"whiff_rate": 0.156, "csw_rate": 0.25, "xwoba": 0.345, "pitches": 2679}},
            "1": {"overall": {"whiff_rate": 0.30, "csw_rate": 0.31, "xwoba": 0.290, "pitches": 2000}},
        },
    }
    _write(data_root / "mlb_source" / "data" / "statcast" / "features" / "player_features_latest.json", json.dumps(payload))
    signals = se.candidate_season_signals(
        {"sport_slug": "mlb", "player_id": 607259, "market": "Pitcher Outs", "player_name": "Nick Martinez"}, TODAY
    )
    whiff = next(s for s in signals if s["key"] == "mlb_pitcher_whiff_rate")
    assert whiff["display"] == "15.6%" and whiff["rank"] == 2 and whiff["sample_pitches"] == 2679
    assert "2,679 pitches" in se.season_evidence_text(signals)


def test_soccer_player_signals_from_current_players_file(data_root):
    _write(
        data_root / "soccer_source" / "epl" / "players" / "players_2026.csv",
        "league,season,player_id,player_name,team,position,minutes,games,shots_per90,xg_per90,xa_per90,goals_per90\n"
        "epl,2026,1,Erling Haaland,Manchester City,F,450,5,3.57,0.81,0.13,0.81\n"
        "epl,2026,2,Someone Else,Arsenal,F,400,5,2.0,0.30,0.20,0.20\n",
    )
    signals = se.candidate_season_signals({"sport_slug": "soccer", "player_name": "Erling Haaland", "league": "epl"}, TODAY)
    xg = next(s for s in signals if s["key"] == "soccer_xg_per90")
    assert xg["display"] == "0.81" and xg["rank"] == 1


def test_signals_never_raise_on_garbage(data_root):
    _write(data_root / "nba_source" / "data" / "processed" / "team_advanced_stats_2026_asof_20260530.csv", "not,a\ncsv")
    assert se.candidate_season_signals({"sport_slug": "nba", "matchup": "MIN @ IND"}, TODAY) == []
    assert se.candidate_season_signals({"sport_slug": "curling"}, TODAY) == []


# --------------------------------------------------------------------------- intelligence integration

def test_readiness_summary_counts_required_data_root_rows():
    from syndicate.features.intelligence import _advanced_readiness_summary

    rows = [
        {"label": "live pbp", "exists": False, "inside_repo": False, "tracked": False},  # legacy, outside repo: not required
        {"label": "SP+", "exists": False, "inside_repo": False, "required": True, "season_input": True},
    ]
    summary = _advanced_readiness_summary(rows)
    assert summary["ready"] is False
    assert summary["required_total"] == 1
    assert [m["label"] for m in summary["missing_inputs"]] == ["SP+"]


def test_readiness_summary_ready_but_flags_prior_season():
    from syndicate.features.intelligence import _advanced_readiness_summary

    rows = [{"label": "xG", "exists": True, "inside_repo": False, "required": True, "season_status": "prior_season", "as_of": "2026-08-19"}]
    summary = _advanced_readiness_summary(rows)
    assert summary["ready"] is True
    assert summary["stale_inputs"][0]["as_of"] == "2026-08-19"


def test_price_in_confidence_is_not_a_probability():
    from syndicate.features.intelligence import _market_context

    context = _market_context({"confidence": "+700", "odds": "700", "model_probability": 0.47})
    assert context["model_probability"] == 47.0
    assert context["price_edge_pct"] == pytest.approx(34.5, abs=0.01)
    assert _market_context({"confidence": "+700", "odds": "700"})["model_probability"] is None
    assert _market_context({"confidence": "71.3%", "odds": "-121"})["model_probability"] == 71.3


def test_rationale_states_season_numbers_instead_of_metric_names():
    from syndicate.features.intelligence import _candidate_rationale

    candidate = {
        "candidate_type": "game",
        "advanced_context": [{"label": "Team advanced stats", "metrics": ["Pace", "Offensive rating"], "exists": True}],
        "season_evidence": "Season metrics, 82 games: Net rating MIN +3.9 (9th of 30) vs IND -7.3 (26th of 30).",
    }
    text = _candidate_rationale(candidate)
    assert "Advanced drivers in play -- Season metrics, 82 games: Net rating MIN +3.9" in text
    assert "Offensive rating" not in text


def test_driver_text_never_names_absent_inputs():
    from syndicate.features.intelligence import _advanced_driver_text

    rows = [
        {"label": "Weekly recommendation summary", "metrics": ["Model spread"], "exists": False},
        {"label": "SP+ ratings", "metrics": ["SP+ overall"], "exists": True},
    ]
    assert _advanced_driver_text(rows) == "SP+ ratings: SP+ overall"
    assert _advanced_driver_text([rows[0]]) == ""


def test_rationale_does_not_print_a_price_as_confidence():
    from syndicate.features.intelligence import _candidate_rationale

    text = _candidate_rationale({"candidate_type": "prop", "confidence": "+700", "model_probability": 0.47})
    assert "+700" not in text
    assert "Sim confidence is 47.0%." in text


def test_ncaaf_state_abbreviation_matches_event_id(data_root):
    _write(
        data_root / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json",
        json.dumps({"season": 2026, "fetched_at": "2026-09-30", "teams": {"jacksonville st": [26.4, 28.4], "kennesaw st": [20.1, 31.3]}}),
    )
    signals = se.candidate_season_signals(
        {"sport_slug": "ncaaf", "matchup": "JS @ KS", "event_id": "6_Jacksonville_State_Kennesaw_State", "team": "KS"}, TODAY
    )
    margin = {s["side"]: s for s in signals if s["key"] == "ncaaf_sp_overall"}
    assert margin["away"]["display"] == "-2.0" and margin["home"]["is_pick_side"] is True
