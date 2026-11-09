"""Live NHL / NFL prop ACTUALS on the Layer 2 board: shown, never priced (lane `nhl-nfl-live-prop-actuals`).

Measured 2026-11-09 01:31Z on the served board: live NHL props 0 of 29 and live NFL props 0 of 140 had an
Actual. These tests pin the three halves: the producers put a box on each live game, the join writes the
grader's own field onto the row and nothing the edge reads, and the gate routes NHL/NFL here (off != on).

Fixtures are RECORDED payloads, not hand-built shapes: NHL PHI @ NYR 2025020549 (box + play-by-play
rosterSpots) and NFL NE @ SEA 401872656 (ESPN summary; Drake Maye threw 3 interceptions).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import live_player_actuals as A

FIXTURES = Path(__file__).parent / "fixtures"
NHL_BASE = FIXTURES / "nhl_settlement" / "gamecenter_2025020549_"
NFL_SUMMARY = FIXTURES / "nfl_espn_summary_401872656.json"


@pytest.fixture(autouse=True)
def _clear_roster_cache():
    A._NHL_ROSTER_NAMES.clear()
    yield
    A._NHL_ROSTER_NAMES.clear()


def _nhl_fetch(calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if url.endswith("/boxscore"):
            return json.loads((Path(str(NHL_BASE) + "boxscore.json")).read_text(encoding="utf-8"))
        if url.endswith("/play-by-play"):
            return json.loads((Path(str(NHL_BASE) + "play-by-play.json")).read_text(encoding="utf-8"))
        return None
    return fetch


def _nhl_snapshot(*, as_of=None):
    block = A.nhl_live_player_stats("2025020549", fetch_json=_nhl_fetch(), game_state="LIVE")
    if as_of is not None:
        block["asOf"] = as_of
    # The re-sim names clubs by the `/v1/score` SHORT name; the board uses full names.
    return {"sport": "nhl", "games": [{"away_name": "Flyers", "home_name": "Rangers", "gameLens": [],
                                       A.BLOCK_KEY: block}]}


def _nfl_snapshot(monkeypatch, *, as_of=None):
    from syndicate.features.nfl import live_player_box
    from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary

    summary = json.loads(NFL_SUMMARY.read_text(encoding="utf-8"))
    monkeypatch.setattr(live_player_box, "fetch_player_stat_rows", lambda event_id: player_stat_rows_from_summary(summary))
    block = A.nfl_live_player_stats("401872656", game_state="in")
    if as_of is not None:
        block["asOf"] = as_of
    return {"sport": "nfl", "games": [{"away_name": "new england patriots", "home_name": "seattle seahawks",
                                       "gameLens": [], A.BLOCK_KEY: block}]}


def _row(player, market, *, away, home, state="live", line=0.5, segment=None, projection=None):
    row = {"kind": "prop", "game": {"state": state}, "player_name": player, "market": market, "line": line,
           "away_team": away, "home_team": home, "projection": dict(projection or {})}
    if segment is not None:
        row["segment"] = segment
    return row


def _nhl_row(player, market, **kw):
    return _row(player, market, away="Philadelphia Flyers", home="New York Rangers", **kw)


def _nfl_row(player, market, **kw):
    return _row(player, market, away="New England Patriots", home="Seattle Seahawks", **kw)


# --- the producers -------------------------------------------------------------------------------


def test_nhl_block_carries_full_names_and_the_graders_fields():
    calls = []
    block = A.nhl_live_player_stats("2025020549", fetch_json=_nhl_fetch(calls), game_state="LIVE")
    by_name = {p["playerName"]: p for p in block["players"]}
    assert block["source"] == A.SOURCE_NHL_BOX and block["gameId"] == "2025020549"
    assert len(block["players"]) == 40, "every dressed player, zeros included"
    assert by_name["Artemi Panarin"]["stats"] == {"goals": 2, "assists": 0, "points": 2, "sog": 7, "blocked_shots": 0}
    assert by_name["Igor Shesterkin"]["role"] == "goalie"
    assert by_name["Igor Shesterkin"]["stats"] == {"saves": 28, "shots_against": 32}
    # The roster is read once per game; the next tick reads the box alone.
    A.nhl_live_player_stats("2025020549", fetch_json=_nhl_fetch(calls), game_state="LIVE")
    assert sum(url.endswith("/play-by-play") for url in calls) == 1
    assert sum(url.endswith("/boxscore") for url in calls) == 2


def test_nhl_block_falls_back_to_the_box_abbreviation_without_a_roster():
    def fetch(url):
        return _nhl_fetch()(url) if url.endswith("/boxscore") else None
    block = A.nhl_live_player_stats("2025020549", fetch_json=fetch)
    names = {p["playerName"] for p in block["players"]}
    assert "A. Panarin" in names and "Artemi Panarin" not in names


def test_nhl_unreadable_box_is_none_not_an_empty_block():
    assert A.nhl_live_player_stats("2025020549", fetch_json=lambda url: None) is None


def test_nfl_block_is_the_settlement_read_with_real_zeros(monkeypatch):
    snap = _nfl_snapshot(monkeypatch)
    players = {p["playerName"]: p for p in snap["games"][0][A.BLOCK_KEY]["players"]}
    maye = players["Drake Maye"]["stats"]
    assert maye["pass_int"] == 3.0 and maye["completions"] == 23.0 and maye["receptions"] == 0.0


# --- the join ------------------------------------------------------------------------------------


def test_nhl_rows_get_the_box_count_and_nothing_the_edge_reads():
    pregame = {"projected": 0.41, "model_prob_over": 0.33, "basis": "game_simulation", "source": "hockeysim"}
    grid = [
        _nhl_row("Artemi Panarin", "GOALS", projection=pregame),
        _nhl_row("Artemi Panarin", "SOG", line=3.5),
        _nhl_row("Mika Zibanejad", "POINTS"),
        _nhl_row("Igor Shesterkin", "SAVES", line=27.5),
        _nhl_row("Vincent Trocheck", "player_goal_scorer_anytime", line=None),
    ]
    cov = A.attach_live_player_actuals(grid, _nhl_snapshot(), sport="nhl")
    assert [r["projection"].get("actual_so_far") for r in grid] == [2.0, 7.0, 2.0, 28.0, 1.0]
    assert cov["rows_live_actual"] == 5 and cov["rows_live_display_only"] == 5
    assert cov["rows_live_projected"] == 0 and cov["rows_live_edged"] == 0
    first = grid[0]["projection"]
    # The pregame projection survives untouched; nothing live-priced is written.
    assert first["projected"] == 0.41 and first["model_prob_over"] == 0.33 and first["basis"] == "game_simulation"
    for row in grid:
        p = row["projection"]
        assert p["live_display_only"] is True
        assert "live_aware" not in p and "live_projected" not in p and "live_prob_over" not in p
        assert "edge_vs_market_pct" not in p


def test_nfl_rows_read_the_graders_field_per_market(monkeypatch):
    grid = [
        _nfl_row("Drake Maye", "Interceptions"),
        _nfl_row("Drake Maye", "Passing Attempts", line=32.5),
        _nfl_row("Drake Maye", "player_pass_yds", line=210.5),
        _nfl_row("Rhamondre Stevenson", "Receptions", line=3.5),
        _nfl_row("Rhamondre Stevenson", "Anytime TD", line=None),
    ]
    cov = A.attach_live_player_actuals(grid, _nfl_snapshot(monkeypatch), sport="nfl")
    fields = [r["projection"].get("live_actual_field") for r in grid]
    assert fields == ["pass_int", "pass_attempts", "pass_yards", "receptions", "td_scored"]
    assert [r["projection"].get("actual_so_far") for r in grid][:4] == [3.0, 33.0, 178.0, 5.0]
    assert cov["rows_live_actual"] == 5


def test_the_column_reads_the_actual_and_shows_no_live_projection():
    from syndicate.features.shared.layer2_board import _live_projection_columns

    grid = [_nhl_row("Artemi Panarin", "SOG", line=3.5)]
    A.attach_live_player_actuals(grid, _nhl_snapshot(), sport="nhl")
    cols = _live_projection_columns(grid[0])
    assert cols.get("actual") == 7.0
    assert "live_projection" not in cols and "live_model_probability" not in cols and "live_aware" not in cols


def test_refusals_are_named_never_a_zero(monkeypatch):
    grid = [
        _nhl_row("Connor McDavid", "GOALS"),                      # not dressed in this game
        _nhl_row("Artemi Panarin", "SAVES"),                      # a skater has no saves
        _nhl_row("Artemi Panarin", "GOALS", segment="p1"),        # a period prop: the box is whole-game
        _nhl_row("Artemi Panarin", "player_hits"),                # a market the grader cannot settle
        _row("Artemi Panarin", "GOALS", away="Boston Bruins", home="Florida Panthers"),  # no box for that game
    ]
    cov = A.attach_live_player_actuals(grid, _nhl_snapshot(), sport="nhl")
    assert all(r["projection"].get("actual_so_far") is None for r in grid)
    assert (cov["miss_player_absent"], cov["miss_stat_unavailable"], cov["miss_segment"],
            cov["miss_no_market_field"], cov["miss_no_game"]) == (1, 1, 1, 1, 1)


def test_a_stale_block_is_refused():
    old = (datetime.now(timezone.utc) - timedelta(seconds=A.MAX_BLOCK_AGE_SECONDS + 60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    grid = [_nhl_row("Artemi Panarin", "GOALS")]
    cov = A.attach_live_player_actuals(grid, _nhl_snapshot(as_of=old), sport="nhl")
    assert cov["miss_stale_block"] == 1 and grid[0]["projection"].get("actual_so_far") is None


def test_only_live_prop_rows_are_touched():
    grid = [
        _nhl_row("Artemi Panarin", "GOALS", state="scheduled"),
        _nhl_row("Artemi Panarin", "GOALS", state="final"),
        {**_nhl_row("Artemi Panarin", "GOALS"), "kind": "game"},
    ]
    cov = A.attach_live_player_actuals(grid, _nhl_snapshot(), sport="nhl")
    assert cov["rows_live_considered"] == 0
    assert all("actual_so_far" not in r["projection"] for r in grid)


def test_two_live_games_under_one_club_pair_trust_neither():
    snap = _nhl_snapshot()
    snap["games"].append(dict(snap["games"][0]))
    grid = [_nhl_row("Artemi Panarin", "GOALS")]
    cov = A.attach_live_player_actuals(grid, snap, sport="nhl")
    assert cov["games_ambiguous"] == 1 and cov["miss_no_game"] == 1


# --- the gate: off != on -------------------------------------------------------------------------


def _patch_snapshot(monkeypatch, tmp_path, snapshots):
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "data_root", lambda: tmp_path)
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda path: snapshots.get(Path(path).name))


def test_the_board_gate_routes_nhl_and_nfl_here(monkeypatch, tmp_path):
    from syndicate.features.shared.board_enrichment import attach_live_projections_for_sport

    nfl = _nfl_snapshot(monkeypatch)
    _patch_snapshot(monkeypatch, tmp_path, {"nhl_live_lens.json": _nhl_snapshot(), "nfl_live_resim.json": nfl})
    nhl_grid = [_nhl_row("Artemi Panarin", "GOALS")]
    nfl_grid = [_nfl_row("Drake Maye", "Interceptions")]
    nhl_cov = attach_live_projections_for_sport(nhl_grid, sport="nhl", selected_date="2026-11-08")
    nfl_cov = attach_live_projections_for_sport(nfl_grid, sport="nfl", selected_date="2026-11-08")
    assert nhl_cov["supported"] is True and nhl_cov["join"] == "live_player_actuals"
    assert nhl_grid[0]["projection"]["actual_so_far"] == 2.0
    assert nfl_grid[0]["projection"]["actual_so_far"] == 3.0
    assert nfl_cov["rows_live_display_only"] == 1


def test_without_the_producers_block_the_rows_stay_blank_and_say_why(monkeypatch, tmp_path):
    """OFF: a snapshot from a producer that predates this change carries no block."""
    from syndicate.features.shared.board_enrichment import attach_live_projections_for_sport

    bare = _nhl_snapshot()
    bare["games"][0].pop(A.BLOCK_KEY)
    _patch_snapshot(monkeypatch, tmp_path, {"nhl_live_lens.json": bare})
    grid = [_nhl_row("Artemi Panarin", "GOALS")]
    cov = attach_live_projections_for_sport(grid, sport="nhl", selected_date="2026-11-08")
    assert "actual_so_far" not in grid[0]["projection"]
    assert cov["rows_live_display_only"] == 0 and "livePlayerStats" in cov["reason"]


def test_an_absent_snapshot_is_named(monkeypatch, tmp_path):
    from syndicate.features.shared.board_enrichment import attach_live_projections_for_sport

    _patch_snapshot(monkeypatch, tmp_path, {})
    cov = attach_live_projections_for_sport([_nhl_row("Artemi Panarin", "GOALS")], sport="nhl", selected_date="2026-11-08")
    assert cov["supported"] is True and "no published live snapshot" in cov["reason"]


# --- the producers inside their ticks -----------------------------------------------------------


def _score_row(state, pk="2025020549"):
    return {"id": pk, "gameState": state, "awayTeam": {"name": {"default": "Flyers"}, "score": 1},
            "homeTeam": {"name": {"default": "Rangers"}, "score": 2}, "periodDescriptor": {"number": 2},
            "clock": {"timeRemaining": "10:00", "inIntermission": False}}


def test_the_nhl_tick_attaches_a_box_to_live_games_only():
    from syndicate.features.nhl import live_resim as LR

    snap = LR.build_live_lens_snapshot(
        "2026-11-08", sims=2, score_rows=[_score_row("LIVE"), _score_row("FUT", pk="2025020550")],
        slate_features=[], player_stats_fetch_json=_nhl_fetch())
    live, future = snap["games"]
    assert A.BLOCK_KEY in live and A.BLOCK_KEY not in future
    # The re-sim refused (no slate features); the box is attached regardless.
    assert live["gameLens"][0]["liveResimRefusal"] == "no_slate_features"
    tally = snap["coverage"]["livePlayerStats"]
    assert (tally["liveGames"], tally["attached"]) == (1, 1)


def test_an_injected_nhl_slate_without_a_seam_reads_no_box():
    from syndicate.features.nhl import live_resim as LR

    snap = LR.build_live_lens_snapshot("2026-11-08", sims=2, score_rows=[_score_row("LIVE")], slate_features=[])
    assert A.BLOCK_KEY not in snap["games"][0]
    assert snap["coverage"]["livePlayerStats"]["enabled"] is False


def test_the_nfl_tick_attaches_a_box_to_in_progress_games(monkeypatch):
    from syndicate.features.nfl import live_player_box
    from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary
    from syndicate.features.nfl.live_resim import build_live_lens_snapshot

    summary = json.loads(NFL_SUMMARY.read_text(encoding="utf-8"))
    asked = []
    monkeypatch.setattr(live_player_box, "fetch_player_stat_rows",
                        lambda event_id: asked.append(event_id) or player_stat_rows_from_summary(summary))
    games = [{"away_team": "ne", "home_team": "sea", "live_key": "a"},
             {"away_team": "dal", "home_team": "phi", "live_key": "b"},
             {"away_team": "kc", "home_team": "buf", "live_key": "c"}]
    live_index = {
        "a": {"state": "in", "period": 3, "clock_seconds": 600, "home_score": 10, "away_score": 7, "event_id": "401872656"},
        "b": {"state": "final", "period": 4, "clock_seconds": 0, "home_score": 20, "away_score": 17, "event_id": "2"},
        "c": {"state": "in", "period": 1, "clock_seconds": 900, "home_score": 0, "away_score": 0},
    }
    snap = build_live_lens_snapshot("2026-11-08", games=games, live_index=live_index, ratings={}, env={})
    by_code = {g["away_code"]: g for g in snap["games"]}
    assert A.BLOCK_KEY in by_code["ne"] and A.BLOCK_KEY not in by_code["dal"] and A.BLOCK_KEY not in by_code["kc"]
    assert asked == ["401872656"]
    tally = snap["coverage"]["live_player_stats"]
    assert (tally["live_games"], tally["attached"], tally["no_event_id"]) == (2, 1, 1)
