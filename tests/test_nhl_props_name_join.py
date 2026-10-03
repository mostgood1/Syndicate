"""NHL props: the producer's name join and the board's prop projection join.

2026-10-02, lane nhl-player-props-projection: the lineup feed carried the
boxscore's abbreviated names ("A. Copp") while every book line carries the full
name ("Andrew Copp"), so `build_props_for_date` matched 0 of 339 lines and
`props_recommendations` was header-only on every date; and the board had no NHL
prop join at all.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_nhl_artifacts as producer  # noqa: E402
from syndicate.features.nhl import prop_projections as npp  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient  # noqa: E402


def _game(home_players, away_players):
    return SimpleNamespace(
        home=SimpleNamespace(name="Detroit Red Wings"),
        away=SimpleNamespace(name="New York Rangers"),
        home_players=[SimpleNamespace(player_id=pid, full_name=n) for pid, n in home_players],
        away_players=[SimpleNamespace(player_id=pid, full_name=n) for pid, n in away_players],
    )


def _line(name, home="Detroit Red Wings", away="New York Rangers", market="SOG"):
    from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import normalize_name

    return {"name_key": normalize_name(name), "player_name": name, "market": market, "line": 1.5,
            "home_team": home, "away_team": away}


def test_abbreviated_lineup_name_matches_full_book_name():
    game = _game([(1, "A. Copp"), (2, "J. Bernard-Docker")], [(3, "A. Fox")])
    lines = [_line("Andrew Copp"), _line("Jacob Bernard-Docker"), _line("Adam Fox")]
    assert producer._match_lines_to_game(game, lines) == {0: 1, 1: 2, 2: 3}


def test_abbreviation_never_crosses_into_another_game():
    game = _game([(1, "A. Copp")], [])
    other_game_line = _line("Adam Copp", home="Winnipeg Jets", away="Boston Bruins")
    assert producer._match_lines_to_game(game, [other_game_line]) == {}


def test_ambiguous_abbreviation_is_refused():
    # Two players in the game share "e lindholm": the abbreviation cannot pick one.
    game = _game([(1, "E. Lindholm")], [(2, "E. Lindholm")])
    assert producer._match_lines_to_game(game, [_line("Elias Lindholm")]) == {}


def test_exact_full_name_wins_and_needs_no_team_names():
    game = _game([(1, "Andrew Copp")], [])
    assert producer._match_lines_to_game(game, [_line("Andrew Copp", home="", away="")]) == {0: 1}
    # ...but an abbreviation without team names is never trusted.
    game_abbr = _game([(1, "A. Copp")], [])
    assert producer._match_lines_to_game(game_abbr, [_line("Andrew Copp", home="", away="")]) == {}


def test_roster_full_names_parses_api_web_roster(monkeypatch):
    client = NhlWebIngestClient(cache_dir=Path("."), rate_limit_per_sec=0)
    payload = {
        "forwards": [{"id": 8477429, "firstName": {"default": "Andrew"}, "lastName": {"default": "Copp"}}],
        "defensemen": [{"id": 8476459, "firstName": {"default": "Adam"}, "lastName": {"default": "Fox"}}],
        "goalies": [{"id": 1, "firstName": {"default": ""}, "lastName": {"default": ""}}],
    }
    monkeypatch.setattr(client, "_get", lambda url: payload)
    assert client.roster_full_names("DET", "20262027") == {8477429: "Andrew Copp", 8476459: "Adam Fox"}


def test_roster_full_names_unreachable_is_empty(monkeypatch):
    client = NhlWebIngestClient(cache_dir=Path("."), rate_limit_per_sec=0)

    def boom(url):
        raise OSError("offline")

    monkeypatch.setattr(client, "_get", boom)
    assert client.roster_full_names("DET", "20262027") == {}


# --- board join -------------------------------------------------------------


_REG = {"line_slot": "L1", "proj_toi": "18.0", "sim_starter": "", "game_type": "regular"}


def _index(rows, context=None):
    idx = npp.NhlPropProjectionIndex(date="2026-10-02")
    for player, code, team, opp, lam in rows:
        idx.by_key[(npp._norm(player), code)] = (npp._norm(team), npp._norm(opp), lam)
        idx.context[(npp._norm(player), code)] = dict(_REG if context is None else context)
    return idx


def _row(player="Andrew Copp", market="player_shots_on_goal", line=1.5, **kw):
    row = {"kind": "prop", "sport": "nhl", "market": market, "player_name": player, "line": line,
           "home_team": "Detroit Red Wings", "away_team": "New York Rangers",
           "commence_time": "2026-10-02T23:00:00Z", "side": "over"}
    row.update(kw)
    return row


def test_every_fit_line_gets_probability_and_edge():
    # User decision 2026-10-02: no market-level withhold; every line is its own decision.
    grid = [_row(), _row(market="player_goals_alternate", line=0.5)]
    cov = npp.attach_nhl_prop_projections(
        grid, _index([("Andrew Copp", "SOG", "Detroit Red Wings", "New York Rangers", 2.0),
                      ("Andrew Copp", "GOALS", "Detroit Red Wings", "New York Rangers", 0.3)]),
        selected_date="2026-10-02",
    )
    assert cov["rows_with_projection"] == 2 and cov["rows_with_probability"] == 2
    assert cov["probability_refused_by_line"] == {}
    p = grid[0]["projection"]
    assert p["projected"] == 2.0 and p["edge_vs_line"] == pytest.approx(0.5)
    # P(X > 1.5 | Poisson 2) = 1 - e^-2 (1 + 2)
    assert p["model_prob_over"] == pytest.approx(0.594, abs=1e-3)


@pytest.mark.parametrize("context,code,reason", [
    ({"line_slot": "", "game_type": "regular"}, "SOG", npp.REFUSE_NO_SLOT),
    ({"line_slot": "L2", "game_type": "preseason"}, "SOG", npp.REFUSE_PRESEASON),
    ({}, "SOG", npp.REFUSE_NO_CONTEXT),
    ({"sim_starter": "0", "game_type": "regular"}, "SAVES", npp.REFUSE_NOT_STARTER),
])
def test_unfit_line_is_refused_on_its_own_facts(context, code, reason):
    market = {"SOG": "SOG", "SAVES": "SAVES"}[code]
    grid = [_row(market=market, line=1.5 if code == "SOG" else 25.5)]
    cov = npp.attach_nhl_prop_projections(
        grid, _index([("Andrew Copp", code, "Detroit Red Wings", "New York Rangers", 2.0)], context=context),
        selected_date="2026-10-02",
    )
    p = grid[0]["projection"]
    assert p["projected"] == 2.0                    # the mean is still shown
    assert p["model_prob_over"] is None and p["edge_vs_market_pct"] is None
    assert p["edge_unavailable_reason"].endswith(reason)
    assert cov["probability_refused_by_line"] == {reason: 1}


def test_starting_goalie_saves_are_priced():
    grid = [_row(market="SAVES", line=25.5)]
    npp.attach_nhl_prop_projections(
        grid, _index([("Andrew Copp", "SAVES", "Detroit Red Wings", "New York Rangers", 27.0)],
                     context={"sim_starter": "1", "game_type": "regular"}),
        selected_date="2026-10-02")
    assert grid[0]["projection"]["model_prob_over"] is not None


def test_same_name_in_another_game_does_not_price_the_row():
    grid = [_row()]
    cov = npp.attach_nhl_prop_projections(
        grid, _index([("Andrew Copp", "SOG", "Winnipeg Jets", "Boston Bruins", 2.0)]), selected_date="2026-10-02"
    )
    assert "projection" not in grid[0] and cov["unmatched_player_rows"] == 1


def test_other_date_rows_are_out_of_the_denominator():
    grid = [_row(commence_time="2026-10-04T23:00:00Z")]
    cov = npp.attach_nhl_prop_projections(grid, _index([]), selected_date="2026-10-02")
    assert cov["rows_considered"] == 0


def test_empty_artifact_reports_a_reason():
    cov = npp.attach_nhl_prop_projections([_row()], _index([]), selected_date="2026-10-02")
    assert cov["rows_with_projection"] == 0 and "props_recommendations" in cov["reason"]


def test_poisson_matches_producer():
    for line, lam in ((0.5, 0.3), (1.5, 2.2), (2.5, 3.1), (24.5, 27.0)):
        assert npp.poisson_p_over(line, lam) == pytest.approx(producer._poisson_p_over(line, lam), abs=1e-9)


def test_grid_market_codes_are_supported():
    # The fleet's NHL book grid stores the code, not the OddsAPI key (all 339 rows on 2026-10-02).
    assert [npp.market_code(m) for m in ("SOG", "GOALS", "ASSISTS", "POINTS", "SAVES", "BLOCKS")] == [
        "SOG", "GOALS", "ASSISTS", "POINTS", "SAVES", "BLOCKS"]
    assert npp.market_code("player_points_alternate") == "POINTS"
    assert npp.market_code("h2h") is None
    grid = [_row(market="SOG")]
    npp.attach_nhl_prop_projections(
        grid, _index([("Andrew Copp", "SOG", "Detroit Red Wings", "New York Rangers", 2.2)]), selected_date="2026-10-02")
    assert grid[0]["projection"]["projected"] == 2.2


def test_loader_falls_back_to_the_all_markets_file(tmp_path, monkeypatch):
    import syndicate.features.nhl.sources as src

    proc = tmp_path
    (proc / "props_recommendations_2026-10-03.csv").write_text(
        "date,player,team,opp,market,line,proj_lambda,line_slot,proj_toi,sim_starter,game_type\n"
        "2026-10-03,John Carlson,Washington Capitals,Tampa Bay Lightning,SOG,1.5,2.0,D1,23.7,,regular\n",
        encoding="utf-8")
    (proc / "props_recommendations_all_markets_2026-10-03.csv").write_text(
        "date,player,team,opp,market,proj_lambda,line_slot,proj_toi,sim_starter,game_type\n"
        "2026-10-03,John Carlson,Washington Capitals,Tampa Bay Lightning,SOG,9.9,D1,23.7,,regular\n"
        "2026-10-03,John Carlson,Washington Capitals,Tampa Bay Lightning,ASSISTS,0.55,D1,23.7,,regular\n",
        encoding="utf-8")
    monkeypatch.setattr(src, "processed_path", lambda name: proc / name)
    idx = npp.load_nhl_prop_projections("2026-10-03")
    assert idx.by_key[(npp._norm("John Carlson"), "SOG")][2] == 2.0       # primary file wins
    assert idx.by_key[(npp._norm("John Carlson"), "ASSISTS")][2] == 0.55  # filled from all-markets
    assert idx.from_all_markets == 1
