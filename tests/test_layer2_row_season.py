"""Season metrics on Layer 2 rows -- one explanation layer for the one list.

User 2026-10-07: "we shouldnt have seperate lists being generated". The Layer 2
board is the pick list, so its row explainer carries the season sentence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features import intelligence_season_evidence as se
from syndicate.features.shared import layer2_row_context as rc

_NBA = (
    "team,pace,off_rtg,def_rtg,efg_pct,tov_pct,orb_pct,ft_rate,fg3a_rate,fg3_pct,ts_pct,ast_per_100,games,source\n"
    "MIN,99.0,114.9,111.0,0.55,0.12,0.25,0.2,0.4,0.36,0.58,25,82,player_logs\n"
    "IND,101.0,109.2,116.5,0.53,0.13,0.25,0.2,0.4,0.36,0.56,25,82,player_logs\n"
    "BOS,97.0,120.0,108.0,0.57,0.11,0.25,0.2,0.4,0.37,0.60,25,82,player_logs\n"
)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    for sport in ("MLB", "NBA", "WNBA", "NHL", "NFL", "NCAAF", "NCAAB", "SOCCER"):
        monkeypatch.delenv(f"SYNDICATE_{sport}_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("SYNDICATE_MLB_DATA_ROOT", raising=False)
    se._CACHE.clear()
    se._TABLES_MEMO.clear()
    rc._SEASON_TEXT_MEMO.clear()
    processed = tmp_path / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "team_advanced_stats_2026_asof_20260530.csv").write_text(_NBA, encoding="utf-8")
    return tmp_path


def _nba_row(**extra):
    row = {
        "sport": "nba",
        "kind": "game",
        "market": "h2h",
        "side": "away",
        "home_team": "Indiana Pacers",
        "away_team": "Minnesota Timberwolves",
        "commence_time": "2026-10-07T23:00:00Z",
        "event_id": "401914123",
        "player_name": None,
    }
    row.update(extra)
    return row


def test_row_explainer_carries_the_season_sentence(data_root):
    text = rc.row_explainer(_nba_row(), {"price": -120, "fair_probability": 0.52, "books_quoting": 9, "bookmaker": "dk"}, {})
    assert "Season metrics, 82 games" in text
    assert "Net rating Minnesota Timberwolves +3.9 (2nd of 3) vs Indiana Pacers -7.3 (3rd of 3)" in text


def test_reachability_season_sentence_is_absent_without_a_table(tmp_path, monkeypatch):
    # off != on: the same row with no season table on the data root gets no sentence.
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NBA_SOURCE_ROOT", raising=False)
    se._CACHE.clear()
    se._TABLES_MEMO.clear()
    rc._SEASON_TEXT_MEMO.clear()
    assert rc.row_season_text(_nba_row(), {}) is None


def test_build_context_memoises_per_game_not_per_row(data_root, monkeypatch):
    calls = []
    real = se.candidate_season_signals
    monkeypatch.setattr(se, "candidate_season_signals", lambda c, t: calls.append(1) or real(c, t))
    ctx: dict = {}
    for side in ("away", "away", "away"):
        rc.row_season_text(_nba_row(side=side, market="spreads"), ctx)
    assert len(calls) == 1
    assert len(ctx["season_text_memo"]) == 1


def test_bare_caller_uses_the_module_memo(data_root, monkeypatch):
    calls = []
    real = se.candidate_season_signals
    monkeypatch.setattr(se, "candidate_season_signals", lambda c, t: calls.append(1) or real(c, t))
    rc.row_season_text(_nba_row(), None)
    rc.row_season_text(_nba_row(), None)
    assert len(calls) == 1


def test_mlb_prop_without_player_id_reads_nothing(data_root):
    row = {"sport": "mlb", "market": "batter_hits", "player_name": "Somebody", "side": "over", "projection": {}}
    assert rc.row_season_text(row, {}) is None


def test_mlb_prop_with_player_id_reads_statcast(data_root):
    payload = {
        "meta": {"season": 2026, "end_date": "2026-09-30"},
        "batters": {
            "643289": {"overall": {"xwoba": 0.319, "barrel_rate": 0.038, "pitches": 2329}},
            "1": {"overall": {"xwoba": 0.400, "barrel_rate": 0.150, "pitches": 2000}},
        },
        "pitchers": {},
    }
    path = data_root / "mlb_source" / "data" / "statcast" / "features" / "player_features_latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    row = {
        "sport": "mlb",
        "market": "batter_rbis",
        "player_name": "Mauricio Dubon",
        "side": "over",
        "commence_time": "2026-10-07T20:00:00Z",
        "projection": {"player_id": "643289"},
    }
    text = rc.row_season_text(row, {})
    assert "xwOBA Mauricio Dubon 0.319 (2nd of 2)" in text and "2,329 pitches" in text


def test_ncaaf_board_names_resolve_through_the_registry_not_word_stripping(data_root, monkeypatch):
    path = data_root / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"season": 2026, "fetched_at": "2026-10-07", "teams": {"kennesaw st": [20.1, 31.3], "jacksonville st": [26.4, 28.4], "texas": [35.0, 15.0]}}),
        encoding="utf-8",
    )
    registry = {"Kennesaw State Owls": "kennesaw state", "Jacksonville State Gamecocks": "jacksonville state", "Texas Southern Tigers": None}
    monkeypatch.setattr(se, "_canonical", lambda sport: (lambda value: registry.get(value)))
    row = {"sport": "ncaaf", "market": "h2h", "side": "home", "home_team": "Kennesaw State Owls", "away_team": "Jacksonville State Gamecocks", "commence_time": "2026-10-07T23:00:00Z", "event_id": "x"}
    assert "SP+ margin Jacksonville State Gamecocks -2.0" in rc.row_season_text(row, {})
    # An FCS opponent the registry cannot place must NOT collapse onto "texas".
    fcs = dict(row, away_team="Texas Southern Tigers")
    assert rc.row_season_text(fcs, {}) is None


def test_season_failure_never_breaks_the_explainer(data_root, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("table exploded")

    monkeypatch.setattr(se, "candidate_season_signals", boom)
    text = rc.row_explainer(_nba_row(), {"price": -120, "fair_probability": 0.52}, {})
    assert text and "Season metrics" not in text


def test_recent_matchup_budget_is_per_sport_with_a_soccer_raise():
    """Lane prop-recency-budget (user 2026-10-08): soccer kept running out of the 30 s per-sport budget.
    Raised again 2026-10-09 (lane board-history-charts, user "Raise the budget"): default 30 -> 60 s,
    soccer 45 -> 90 s -- rows past the budget get no sentence and no per-row chart values."""
    from syndicate.features.shared import layer2_row_context as rc

    assert rc._recent_matchup_budget("soccer") == 90.0
    assert rc._recent_matchup_budget("nhl") == rc._RECENT_MATCHUP_BUDGET_SECONDS_PER_SPORT == 60.0
