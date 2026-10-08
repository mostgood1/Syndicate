"""NHL this-season display table + its readers (lane intelligence-evidence-coverage, user 2026-10-08)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_nhl_season_to_date", Path(__file__).resolve().parents[1] / "scripts" / "build_nhl_season_to_date.py"
)
std = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(std)


def _rec(gid, home, away, hg, ag, hs, as_):
    return SimpleNamespace(game_id=gid, home_abbr=home, away_abbr=away, home_goals=hg, away_goals=ag, home_sog=hs, away_sog=as_)


def test_team_table_sums_per_game_and_ranks(monkeypatch):
    import syndicate.features.nhl.inseason_season_inputs as I
    import syndicate.features.nhl.inseason_team_xg as X

    records = [_rec("1", "BOS", "BUF", 2, 4, 25, 30), _rec("2", "BUF", "TOR", 3, 1, 28, 20)]
    team = {"BOS": {"pp_pct": [1.0, 4.0], "pk_ga_rate": [1.0, 2.0], "faceoff_pct": [30.0, 60.0]}}
    monkeypatch.setattr(I, "current_counts", lambda payloads: {"team": team, "player": {}, "records": records})
    xg = {"1": ("BOS", "BUF", 2.0, 3.0), "2": ("BUF", "TOR", 2.5, 1.5)}
    monkeypatch.setattr(X, "game_xg", lambda pbp: xg[pbp["id"]])
    out = std.team_table([{"pbp": {"id": "1"}}, {"pbp": {"id": "2"}}, {"pbp": {"id": "999"}}])
    assert out["BUF"]["games"] == 2 and out["BUF"]["gf_pg"] == 3.5 and out["BUF"]["xgf_pg"] == 2.75
    assert out["BUF"]["xg_share"] == pytest.approx(5.5 / 9.0)
    assert out["BOS"]["pp_pct"] == 0.25 and out["BOS"]["pk_pct"] == 0.5 and out["BOS"]["faceoff_win_pct"] == 0.5
    assert out["BUF"]["gf_pg_rank"] == 1 and out["TOR"]["ga_pg_rank"] == 2 and out["BUF"]["xga_pg_rank"] == 1


def _write(path: Path, text: str, mtime: dt.date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = dt.datetime(mtime.year, mtime.month, mtime.day, 12).timestamp()
    os.utime(path, (stamp, stamp))


def test_explanation_prefers_this_season_and_tags_last_season(tmp_path, monkeypatch):
    from syndicate.features import intelligence_season_evidence as se

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    proc = tmp_path / "nhl_source" / "data" / "processed"
    today = dt.date(2026, 10, 8)
    _write(proc / "team_xg_latest.csv", "abbr,xgf60,xga60,games\nBOS,1,9,82\nBUF,9,1,82\n", dt.date(2026, 8, 18))
    _write(proc / "team_xg_2026-2027.csv", "abbr,xgf60,xga60,games\nBOS,2.9,3.4,4\nBUF,3.4,3.0,3\n", today)
    _write(proc / "team_elo_latest.csv", "abbr,elo\nBOS,1535\nBUF,1604\n", dt.date(2026, 8, 18))
    _write(proc / "nhl_team_season_to_date_2026-2027.csv",
           "abbr,games,gf_pg,ga_pg,xgf_pg,xga_pg,xg_share,pp_pct,pk_pct\nBOS,4,2.25,2.75,3,3.2,0.48,0.1,0.75\nBUF,3,3.3,3.7,3.7,2.1,0.64,0.2,0.66\n", today)
    se._TABLES_MEMO.clear()
    signals = se.candidate_season_signals({"sport": "nhl", "matchup": "BOS @ BUF", "team": "BUF"}, today)
    text = se.season_evidence_text(signals, limit_metrics=4)
    assert text.startswith("Season metrics, this season 3-4 games: xG share this season BOS 48.0% (2nd of 2) vs BUF 64.0% (1st of 2); "
                           "xG share blended with this season BOS 46.0%")
    assert "(1st of 2)" in text and "1.0%" not in text  # the frozen _latest xG (1 vs 9) is not read
    assert se.season_evidence_text(signals, limit_metrics=9).count("(last season)") == 1  # Elo, tagged; no global caveat
    assert "last season's numbers" not in se.season_evidence_text(signals, limit_metrics=9)


def test_nhl_board_sentence_names_the_blend_and_this_season():
    from syndicate.features import intelligence_recent_matchup as rm

    facts = {"opponent": "BOS", "opponent_profile": {"xg": {"xga60": 3.38}, "xg_blended": True},
             "opponent_this_season": {"games": 4, "xga_pg": 3.19, "xga_pg_rank": 17}}
    assert rm.matchup_text(facts) == (
        "Matchup: BOS allows 3.38 xG/60 (blended with this season); this season 3.19 xG a game, 17 of 32 (1 = stingiest), 4 GP.")
