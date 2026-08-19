"""Unit tests for the hockeysim feature loaders.

Two lanes:
  * synthetic — a self-contained temp ``data/nhl_source`` tree exercises every reader + assembler
    deterministically (no dependence on the checked-in mirror).
  * fixture-backed — a tolerant smoke against the real mirrored ``2026-06-14`` slate to prove the
    end-to-end path (scoreboard -> features -> projection -> adapter) runs on shipped data.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.adapters import build_game_prediction
from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyMarketLines
from syndicate.features.nhl.sim_engine.hockeysim.features import loaders


# ---------------------------------------------------------------------------
# Synthetic mirror fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def synth_root(tmp_path: Path) -> Path:
    """Build a minimal ``data/nhl_source`` tree for date 2026-03-15."""
    date = "2026-03-15"
    proc = tmp_path / "data" / "processed"
    games = tmp_path / "data" / "odds" / "games" / f"date={date}"
    proc.mkdir(parents=True)
    games.mkdir(parents=True)

    # season code for 2026-03-15 is 2025-2026
    (proc / "team_xg_2025-2026.csv").write_text(
        "abbr,xgf60,xga60\n"
        "BOS,3.60,2.50\n"   # strong both ways
        "CHI,2.40,3.60\n",  # weak both ways
        encoding="utf-8",
    )
    (proc / "team_elo_2025-2026.csv").write_text(
        "abbr,elo\n"
        "BOS,1560\n"
        "CHI,1470\n",
        encoding="utf-8",
    )
    (proc / "team_special_teams_2025-2026.csv").write_text(
        "abbr,pp_pct,pk_pct,committed_per_game\n"
        "BOS,0.23,0.83,2.9\n"
        "CHI,0.14,0.79,3.3\n",
        encoding="utf-8",
    )
    (proc / f"lineups_{date}.csv").write_text(
        "player_id,full_name,position,line_slot,pp_unit,pk_unit,proj_toi,confidence,team\n"
        "101,Star Center,C,L1,1,,19.5,0.9,Boston Bruins\n"
        "102,Top Dman,D,D1,1,1,22.0,0.9,Boston Bruins\n"
        "103,Bruins Starter,G,,,,60.0,0.9,Boston Bruins\n"
        "201,Hawk Winger,LW,L1,1,,18.0,0.8,Chicago Blackhawks\n"
        "202,Hawk Goalie,G,,,,60.0,0.8,Chicago Blackhawks\n",
        encoding="utf-8",
    )
    (proc / f"starting_goalies_{date}.csv").write_text(
        "team,goalie,status,confidence,source\n"
        "Boston Bruins,Bruins Starter,confirmed,0.9,test\n"
        "Chicago Blackhawks,Hawk Goalie,confirmed,0.8,test\n",
        encoding="utf-8",
    )
    (games / "scoreboard.csv").write_text(
        "gamePk,gameDate,home,away,home_goals,away_goals,gameState\n"
        f"9001,{date}T23:00:00Z,Boston Bruins,Chicago Blackhawks,,,FUT\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "date,expected",
    [("2026-03-15", "2025-2026"), ("2026-07-01", "2026-2027"), ("2026-10-14", "2026-2027"),
     ("2026-06-30", "2025-2026")],
)
def test_season_code_boundary(date, expected):
    assert loaders._season_code_for_date(date) == expected


def test_load_team_xg_map(synth_root):
    m = loaders.load_team_xg_map("2026-03-15", root=synth_root)
    assert m["BOS"] == {"xgf60": 3.60, "xga60": 2.50}
    assert m["CHI"]["xgf60"] == 2.40


def test_load_team_xg_map_missing_is_empty(tmp_path):
    assert loaders.load_team_xg_map("2026-03-15", root=tmp_path) == {}


def test_build_team_features_uses_xg_map(synth_root):
    m = loaders.load_team_xg_map("2026-03-15", root=synth_root)
    bos = loaders.build_team_features("Boston Bruins", xg_map=m)
    assert bos.abbrev == "BOS"
    assert bos.xgf_per_60 == 3.60 and bos.xga_per_60 == 2.50


def test_build_team_features_without_xg_is_league_average(synth_root):
    bos = loaders.build_team_features("Boston Bruins", xg_map={})
    assert bos.xgf_per_60 is None and bos.xga_per_60 is None


def test_build_game_features_populates_xg_end_to_end(synth_root):
    """The full loader path (what `build_slate_features` drives in production) actually reaches
    `xgf_per_60`/`xga_per_60` -- mirrors `test_build_game_features_populates_elo_end_to_end` below,
    now that `scripts/build_nhl_xg_artifact.py` is a real producer for this CSV, not just a shape
    the reader was written against with no writer (`hockeysim_engine_reference.md` §5/§2i)."""
    game = loaders.build_game_features(
        "9001", "2026-03-15", "Boston Bruins", "Chicago Blackhawks", root=synth_root,
    )
    assert game.home.xgf_per_60 == 3.60 and game.home.xga_per_60 == 2.50
    assert game.away.xgf_per_60 == 2.40 and game.away.xga_per_60 == 3.60


# ---------------------------------------------------------------------------
# Elo — `docs/ai_context/hockeysim_engine_reference.md`: `elo_rating` was CONSUMED
# (projection.py's `_elo_win_prob`) with no producer anywhere; these are the
# reachability tests for the fix (`load_team_elo_map` + the wiring below), mirroring
# the xG tests above exactly so the two inputs are held to the same bar.
# ---------------------------------------------------------------------------


def test_load_team_elo_map(synth_root):
    m = loaders.load_team_elo_map("2026-03-15", root=synth_root)
    assert m["BOS"] == 1560.0
    assert m["CHI"] == 1470.0


def test_load_team_elo_map_missing_is_empty(tmp_path):
    assert loaders.load_team_elo_map("2026-03-15", root=tmp_path) == {}


def test_build_team_features_uses_elo_map(synth_root):
    m = loaders.load_team_elo_map("2026-03-15", root=synth_root)
    bos = loaders.build_team_features("Boston Bruins", elo_map=m)
    assert bos.abbrev == "BOS"
    assert bos.elo_rating == 1560.0


def test_build_team_features_without_elo_is_none(synth_root):
    bos = loaders.build_team_features("Boston Bruins", elo_map={})
    assert bos.elo_rating is None


def test_build_game_features_populates_elo_end_to_end(synth_root):
    """The full loader path (what `build_slate_features` drives in production) actually reaches
    `elo_rating` -- population alone, not just the map/dataclass-level wiring above."""
    game = loaders.build_game_features(
        "9001", "2026-03-15", "Boston Bruins", "Chicago Blackhawks", root=synth_root,
    )
    assert game.home.elo_rating == 1560.0
    assert game.away.elo_rating == 1470.0


# ---------------------------------------------------------------------------
# special_teams -- `docs/ai_context/hockeysim_engine_reference.md`: `pp_pct`/`pk_pct`/
# `committed_per_game` are CONSUMED (via `st_home`/`st_away` in `engine.py`) and had no producer;
# same reachability-test discipline as elo/xG above.
# ---------------------------------------------------------------------------


def test_load_team_special_teams_map(synth_root):
    m = loaders.load_team_special_teams_map("2026-03-15", root=synth_root)
    assert m["BOS"] == {"pp_pct": 0.23, "pk_pct": 0.83, "committed_per_game": 2.9}
    assert m["CHI"]["pp_pct"] == 0.14


def test_load_team_special_teams_map_missing_is_empty(tmp_path):
    assert loaders.load_team_special_teams_map("2026-03-15", root=tmp_path) == {}


def test_build_team_features_uses_special_teams_map(synth_root):
    m = loaders.load_team_special_teams_map("2026-03-15", root=synth_root)
    bos = loaders.build_team_features("Boston Bruins", special_teams_map=m)
    assert bos.special_teams == {"pp_pct": 0.23, "pk_pct": 0.83, "committed_per_game": 2.9}


def test_build_team_features_without_special_teams_is_empty_dict(synth_root):
    bos = loaders.build_team_features("Boston Bruins", special_teams_map={})
    assert bos.special_teams == {}


def test_build_game_features_populates_special_teams_end_to_end(synth_root):
    game = loaders.build_game_features(
        "9001", "2026-03-15", "Boston Bruins", "Chicago Blackhawks", root=synth_root,
    )
    assert game.home.special_teams == {"pp_pct": 0.23, "pk_pct": 0.83, "committed_per_game": 2.9}
    assert game.away.special_teams["pp_pct"] == 0.14


def test_load_team_special_teams_map_reads_shot_index_when_present(tmp_path):
    """`pp_shot_index`/`pk_shot_index_allowed` (`docs/ai_context/hockeysim_engine_reference.md`
    §2f) -- a SEPARATE test fixture from `synth_root` above, so the backward-compat case (an
    artifact written before this session, with no shot-index columns) stays covered by the
    existing tests rather than silently changing what they assert."""
    date = "2026-03-15"
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    (proc / "team_special_teams_2025-2026.csv").write_text(
        "abbr,pp_pct,pk_pct,committed_per_game,pp_shot_index,pk_shot_index_allowed\n"
        "BOS,0.23,0.83,2.9,1.24,0.91\n"
        "CHI,0.14,0.79,3.3,0.88,1.15\n",
        encoding="utf-8",
    )
    m = loaders.load_team_special_teams_map(date, root=tmp_path)
    assert m["BOS"] == {"pp_pct": 0.23, "pk_pct": 0.83, "committed_per_game": 2.9,
                         "pp_shot_index": 1.24, "pk_shot_index_allowed": 0.91}
    assert m["CHI"]["pp_shot_index"] == 0.88


def test_load_team_special_teams_map_reads_block_rate_index_when_present(tmp_path):
    """`block_rate_index` (`docs/ai_context/hockeysim_engine_reference.md` §2g) -- again a
    separate fixture, so backward compat (an artifact predating this column) stays covered
    elsewhere without silently changing what those tests assert."""
    date = "2026-03-15"
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    (proc / "team_special_teams_2025-2026.csv").write_text(
        "abbr,pp_pct,pk_pct,committed_per_game,pp_shot_index,pk_shot_index_allowed,block_rate_index\n"
        "BOS,0.23,0.83,2.9,1.24,0.91,1.10\n"
        "CHI,0.14,0.79,3.3,0.88,1.15,0.87\n",
        encoding="utf-8",
    )
    m = loaders.load_team_special_teams_map(date, root=tmp_path)
    assert m["BOS"]["block_rate_index"] == 1.10
    assert m["CHI"]["block_rate_index"] == 0.87


def test_build_player_features_flags_starting_goalie(synth_root):
    lineups = loaders.load_lineups("2026-03-15", root=synth_root)
    goalies = loaders.load_starting_goalies("2026-03-15", root=synth_root)
    players = loaders.build_player_features(lineups["BOS"], starting_goalie=goalies["BOS"])
    by_name = {p.full_name: p for p in players}
    assert by_name["Bruins Starter"].is_starting_goalie is True
    assert by_name["Bruins Starter"].position == "G"
    # skater positions normalized to F/D, never flagged as goalie
    assert by_name["Star Center"].position == "F"
    assert by_name["Star Center"].is_starting_goalie is False
    assert by_name["Top Dman"].position == "D"


# ---------------------------------------------------------------------------
# Game / slate assembly
# ---------------------------------------------------------------------------


def test_build_game_features_wires_projection_into_period_lambdas(synth_root):
    game = loaders.build_game_features(
        "9001", "2026-03-15", "Boston Bruins", "Chicago Blackhawks", root=synth_root
    )
    # Projection ran: default contract lambdas (0.9,0.95,1.05) must have been replaced.
    assert game.home.period_goal_lambdas != (0.9, 0.95, 1.05)
    # Strong home (BOS 3.6/2.5) vs weak away (CHI 2.4/3.6): home outscores away.
    assert sum(game.home.period_goal_lambdas) > sum(game.away.period_goal_lambdas)
    # Players assembled + starter flagged.
    assert len(game.home_players) == 3 and len(game.away_players) == 2
    assert any(p.is_starting_goalie for p in game.home_players)


def test_build_game_features_project_false_keeps_defaults(synth_root):
    game = loaders.build_game_features(
        "9001", "2026-03-15", "Boston Bruins", "Chicago Blackhawks",
        root=synth_root, project=False,
    )
    assert game.home.period_goal_lambdas == (0.9, 0.95, 1.05)


def test_build_slate_features(synth_root):
    slate = loaders.build_slate_features("2026-03-15", root=synth_root)
    assert len(slate) == 1
    g = slate[0]
    assert g.home.name == "Boston Bruins" and g.away.name == "Chicago Blackhawks"
    assert g.home.xgf_per_60 == 3.60  # xG map shared + applied


def test_build_slate_features_missing_scoreboard_is_empty(tmp_path):
    assert loaders.build_slate_features("2026-03-15", root=tmp_path) == []


def test_slate_feeds_adapter_end_to_end(synth_root):
    g = loaders.build_slate_features("2026-03-15", root=synth_root)[0]
    pred = build_game_prediction(g)
    # Strong home team should be the moneyline favorite with a positive projected margin.
    assert pred.p_home_ml > pred.p_away_ml
    assert pred.model_spread > 0
    # No market line supplied -> over/under degrade to finite 0.0 (never NaN).
    assert pred.p_over == 0.0 and pred.p_under == 0.0


def test_adapter_with_market_line_has_finite_ou_and_ev(synth_root):
    import dataclasses

    g = loaders.build_slate_features("2026-03-15", root=synth_root)[0]
    g = dataclasses.replace(
        g, market=HockeyMarketLines(total_line=6.0, home_ml_odds=-140, away_ml_odds=120,
                                    over_odds=-105, under_odds=-115)
    )
    pred = build_game_prediction(g)
    assert 0.0 < pred.p_over < 1.0 and 0.0 < pred.p_under < 1.0
    assert "home_ml" in pred.ev and "over" in pred.ev


# ---------------------------------------------------------------------------
# Fixture-backed smoke against the shipped mirror (tolerant)
# ---------------------------------------------------------------------------


def test_real_mirror_slate_smoke():
    """The checked-in 2026-06-14 mirror should assemble + project without error."""
    slate = loaders.build_slate_features("2026-06-14")
    if not slate:  # mirror may be pruned in some checkouts; don't hard-fail
        pytest.skip("no mirrored scoreboard for 2026-06-14 in this checkout")
    g = slate[0]
    assert g.home.name and g.away.name
    # projection wired -> lambdas sum to a believable regulation total
    total = sum(g.home.period_goal_lambdas) + sum(g.away.period_goal_lambdas)
    assert 4.0 <= total <= 9.0
    pred = build_game_prediction(g)
    assert 0.0 < pred.p_home_ml < 1.0
