"""NBA projections onto the Layer 2 board `[2026-10-03, lane nba-layer2-projections]`.

Baseline on the served board 2026-10-04T03:29Z: `per_sport_ingest.nba.enrichment
.projections` = `supported: false`, "no projection source wired for nba". These
tests build the producer's REAL file shapes (copied from the fleet's 2026-10-04
artifacts) on disk under a temp NBA source root and drive the same entry point
the board calls, so a passing test means the files a fleet run writes are read.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared.nba_game_projections import (
    attach_nba_game_projections,
    load_nba_game_projections,
)
from syndicate.features.shared.nba_projections import (
    attach_nba_prop_projections,
    load_nba_prop_projections,
)

D = "2026-10-04"
HOME, AWAY = "Denver Nuggets", "Utah Jazz"
HOME2, AWAY2 = "Los Angeles Clippers", "Golden State Warriors"
# 6:10 PM CT on D.
COMMENCE = f"{D}T23:10:00Z"
# 9:30 PM CT on D is 02:30Z on D+1 -- the UTC prefix lies about the slate.
LATE_COMMENCE = "2026-10-05T02:30:00Z"


def _ladder(counts: dict[int, int]) -> dict:
    n = sum(counts.values())
    totals = sorted(counts)
    ladder = []
    for t in totals:
        hit = sum(c for v, c in counts.items() if v >= t)
        ladder.append({"total": t, "hitCount": hit, "hitProb": round(hit / n, 4), "exactCount": counts[t], "exactProb": round(counts[t] / n, 4)})
    mean = sum(v * c for v, c in counts.items()) / n
    return {"simCount": n, "mean": round(mean, 3), "ladder": ladder, "ladderShape": "exact"}


# 10 draws of points: P(>= 21) = 0.4, P(>= 18) = 0.8, mean 19.9
_PTS = {14: 1, 17: 1, 18: 2, 20: 2, 21: 2, 24: 1, 26: 1}
_PTS_LADDER = _ladder(_PTS)


def _player(name: str, pid: str, *, pts: dict | None = None) -> dict:
    ladder = _ladder(pts or _PTS)
    return {
        "player_name": name,
        "player_id": pid,
        "min_mean": 30.0,
        "pts_mean": ladder["mean"],
        "prop_ladders": {"pts": ladder, "reb": _ladder({4: 3, 6: 4, 9: 3})},
    }


def _write_game_cards(root: Path, date: str, rows: list[dict]) -> None:
    path = root / "data" / "processed" / f"game_cards_{date}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["date", "game_id", "home_team", "visitor_team", "commence_time", "home_tri", "away_tri", "pred_margin", "pred_total"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in cols})


def _dist(margins: dict[int, int], totals: dict[int, int]) -> dict:
    return {"total": {str(k): v for k, v in totals.items()}, "margin": {str(k): v for k, v in margins.items()}}


def _write_smart_sim(root: Path, date: str, home_tri: str, away_tri: str, *, frame: str = "home_minus_away", with_h1: bool = True) -> None:
    # 10 full-game draws: margins (home - away) -3,-1,2,4,5,6,8,9,10,12 ; totals 220..238
    full = _dist(
        {-3: 1, -1: 1, 2: 1, 4: 1, 5: 1, 6: 1, 8: 1, 9: 1, 10: 1, 12: 1},
        {220: 1, 222: 1, 226: 1, 228: 1, 230: 1, 231: 1, 233: 1, 235: 1, 236: 1, 238: 1},
    )
    segments = {"full": full}
    if with_h1:
        segments["h1"] = _dist({-2: 2, 1: 2, 3: 3, 5: 3}, {108: 3, 112: 4, 118: 3})
    payload = {
        "home": home_tri,
        "away": away_tri,
        "date": date,
        "score": {
            "p_home_win": 0.8,
            "dist": {"n": 10, "margin_frame": frame, "segments": segments, "source": "syndicate_recorded_draws"},
        },
    }
    path = root / "data" / "processed" / f"smart_sim_{date}_{home_tri}_{away_tri}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_cards_sim_detail(root: Path, date: str, games: list[dict]) -> None:
    path = root / "data" / "processed" / f"cards_sim_detail_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date, "games": games}), encoding="utf-8")


@pytest.fixture
def nba_root(tmp_path, monkeypatch):
    root = tmp_path / "nba_source"
    (root / "data" / "processed").mkdir(parents=True)
    monkeypatch.setenv("SYNDICATE_NBA_SOURCE_ROOT", str(root))
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "unused_data_root"))
    _write_game_cards(
        root,
        D,
        [
            # ESPN game ids -- deliberately NOT what a board row carries.
            {"date": D, "game_id": "401914127", "home_team": HOME, "visitor_team": AWAY, "commence_time": COMMENCE, "home_tri": "DEN", "away_tri": "UTA", "pred_margin": 6.216, "pred_total": 240.412},
            {"date": D, "game_id": "401918010", "home_team": HOME2, "visitor_team": AWAY2, "commence_time": LATE_COMMENCE, "home_tri": "LAC", "away_tri": "GSW", "pred_margin": -2.9, "pred_total": 231.6},
        ],
    )
    _write_smart_sim(root, D, "DEN", "UTA")
    _write_cards_sim_detail(
        root,
        D,
        [
            {
                "home_tri": "DEN",
                "away_tri": "UTA",
                "sim": {
                    "players": {
                        # NBA stats ids -- also never on a board row.
                        "home": [_player("Jonas Valančiūnas", "202685"), _player("Jalen Williams", "1631114")],
                        "away": [_player("Lauri Markkanen", "1628374")],
                    },
                    "missing_prop_players": {"home": ["Injured Guy"], "away": []},
                },
            },
            {
                "home_tri": "LAC",
                "away_tri": "GSW",
                "sim": {
                    "players": {
                        # Same NAME as a DEN player, different game, different numbers.
                        "home": [_player("Jalen Williams", "9999999", pts={4: 5, 6: 5})],
                        "away": [_player("Stephen Curry", "201939")],
                    },
                    "missing_prop_players": {"home": [], "away": []},
                },
            },
        ],
    )
    return root


def _game_row(market: str, *, line=None, segment: str = "full", home: str = HOME, away: str = AWAY, commence: str = COMMENCE, state: str | None = None) -> dict:
    sides = ["over", "under"] if market.startswith("totals") else ["away", "home"]
    consensus = {"over": -110, "under": -110} if market.startswith("totals") else {"home": -110, "away": -110}
    row = {
        "sport": "nba",
        "kind": "game",
        "event_id": "bfe913a081d4591852a3a26d938da96d",  # OddsAPI id space
        "market": market,
        "segment": segment,
        "line": line,
        "home_team": home,
        "away_team": away,
        "commence_time": commence,
        "sides": sides,
        "consensus": consensus,
    }
    if state:
        row["game"] = {"state": state}
    return row


def _prop_row(player: str, market: str = "player_points", *, line=19.5, home: str = HOME, away: str = AWAY, commence: str = COMMENCE, over: int = -110, under: int = -110, state: str | None = None) -> dict:
    row = {
        "sport": "nba",
        "kind": "prop",
        "event_id": "bfe913a081d4591852a3a26d938da96d",
        "market": market,
        "segment": "full",
        "player_name": player,
        "line": line,
        "home_team": home,
        "away_team": away,
        "commence_time": commence,
        "sides": ["over", "under"],
        "consensus": {"over": over, "under": under},
    }
    if state:
        row["game"] = {"state": state}
    return row


# ---------------------------------------------------------------- game lines


def test_spread_and_total_are_priced_at_lines_the_sim_never_used(nba_root):
    index = load_nba_game_projections(D)
    rows = [_game_row("spreads", line=-4.5), _game_row("spreads_alt", line=-7.5), _game_row("totals_alt", line=229.5)]
    cov = attach_nba_game_projections(rows, index)
    spread, alt_spread, alt_total = (r["projection"] for r in rows)
    # Away frame: line -4.5 means home +4.5 -> P(home covers) = P(margin > -4.5) = 10/10 -> refused as a certainty.
    assert spread["model_prob_over"] is None and "draws" in spread["probability_unavailable_reason"]
    # P(margin > -7.5) is also 10/10; use the total for a real number.
    assert alt_total["model_prob_over"] == pytest.approx(0.6)  # 230..238 = 6 of 10 above 229.5
    assert alt_total["market_fair_prob_over"] == pytest.approx(0.5)
    assert alt_total["edge_vs_market_pct"] == pytest.approx(10.0)
    assert alt_total["source"] == "nba_smart_sim_draws"
    assert cov["rows_with_projection"] == 3 and cov["rows_with_probability"] == 1


def test_spread_probability_follows_the_home_minus_away_frame(nba_root):
    index = load_nba_game_projections(D)
    row = _game_row("spreads", line=5.5)  # away +5.5 -> home -5.5 covers iff margin > 5.5
    attach_nba_game_projections([row], index)
    p = row["projection"]
    assert p["model_prob_over"] == pytest.approx(0.5)  # 6,8,9,10,12 of 10
    assert p["side"] == HOME
    assert p["edge_vs_line"] == pytest.approx(round(5.2 - 5.5, 3))  # dist margin mean 5.2


def test_moneyline_edge_is_priced_not_withheld(nba_root):
    # WNBA withholds this edge on a market-level judgement; the NBA directive is
    # every line is its own decision.
    index = load_nba_game_projections(D)
    row = _game_row("h2h")
    attach_nba_game_projections([row], index)
    p = row["projection"]
    assert p["model_prob_over"] == pytest.approx(0.8)  # 8 of 10 margins > 0, no ties
    assert p["edge_vs_market_pct"] == pytest.approx(30.0)
    assert "edge_unavailable_reason" not in p


def test_period_rows_use_their_own_histogram_and_refuse_without_one(nba_root):
    index = load_nba_game_projections(D)
    h1 = _game_row("totals", line=111.5, segment="h1")
    q1 = _game_row("totals", line=57.5, segment="q1")
    cov = attach_nba_game_projections([h1, q1], index)
    assert h1["projection"]["model_prob_over"] == pytest.approx(0.7)  # 112 x4 + 118 x3
    assert h1["projection"]["basis"] == "sim_total_dist/h1"
    assert "projection" not in q1
    assert cov["unprojected_by_reason"] == {"no sim histogram for segment q1": 1}


def test_a_game_without_draws_keeps_its_mean_and_says_why(nba_root):
    index = load_nba_game_projections(D)
    row = _game_row("totals", line=230.5, home=HOME2, away=AWAY2, commence=LATE_COMMENCE)
    attach_nba_game_projections([row], index)
    p = row["projection"]
    assert p["projected"] == pytest.approx(231.6)
    assert p["model_prob_over"] is None
    assert p["probability_unavailable_reason"] == "no smart-sim draws for this game"
    assert p["edge_unavailable_reason"].startswith("no probability to price")


def test_live_row_keeps_the_probability_and_loses_the_edge(nba_root):
    index = load_nba_game_projections(D)
    row = _game_row("totals", line=229.5, state="live")
    attach_nba_game_projections([row], index)
    p = row["projection"]
    assert p["model_prob_over"] == pytest.approx(0.6)
    assert p["edge_vs_market_pct"] is None
    assert p["edge_unavailable_reason"]


def test_an_unknown_game_is_refused_not_guessed(nba_root):
    index = load_nba_game_projections(D)
    row = _game_row("h2h", home="Boston Celtics", away="New York Knicks")
    cov = attach_nba_game_projections([row], index)
    assert "projection" not in row
    assert cov["unprojected_by_reason"] == {"no NBA sim for this game": 1}


def test_a_histogram_in_another_frame_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "nba_source"
    (root / "data" / "processed").mkdir(parents=True)
    monkeypatch.setenv("SYNDICATE_NBA_SOURCE_ROOT", str(root))
    _write_game_cards(root, D, [{"home_team": HOME, "visitor_team": AWAY, "home_tri": "DEN", "away_tri": "UTA", "pred_margin": 6.2, "pred_total": 240.4}])
    _write_smart_sim(root, D, "DEN", "UTA", frame="away_minus_home")
    index = load_nba_game_projections(D)
    assert index.games == 1 and index.games_with_dist == 0


def test_the_slate_is_the_central_date_not_the_utc_prefix(nba_root):
    # The LAC@GSW tip is 02:30Z on D+1 but is D's slate; asking for D+1 must
    # still find it through the D file, and asking for D finds it directly.
    for anchor in (D, "2026-10-05"):
        index = load_nba_game_projections(anchor)
        assert index.lookup(HOME2, AWAY2, LATE_COMMENCE) is not None
    # A game on a different slate between the same clubs is not this one.
    index = load_nba_game_projections(D)
    assert index.lookup(HOME, AWAY, "2026-10-09T23:00:00Z") is None


# --------------------------------------------------------------------- props


def _props(rows: list[dict]) -> dict:
    games = load_nba_game_projections(D)
    return attach_nba_prop_projections(rows, load_nba_prop_projections(D, games))


def test_prop_probability_comes_from_the_ladder_at_the_rows_line(nba_root):
    row = _prop_row("Lauri Markkanen", line=20.5, away=AWAY)
    cov = _props([row])
    p = row["projection"]
    assert p["projected"] == pytest.approx(_PTS_LADDER["mean"])
    assert p["model_prob_over"] == pytest.approx(0.4)  # >= 21: 21x2, 24, 26
    assert p["market_fair_prob_over"] == pytest.approx(0.5)
    assert p["edge_vs_market_pct"] == pytest.approx(-10.0)
    assert p["basis"] == "empirical_sim_ladder" and p["source"] == "nba_smart_sim_ladder"
    assert cov["edge_sign_by_side"] == {"favours_under": 1}
    assert cov["rows_with_probability"] == 1


def test_accented_sim_name_joins_the_books_plain_spelling(nba_root):
    row = _prop_row("Jonas Valanciunas", line=17.5)
    _props([row])
    assert row["projection"]["model_prob_over"] == pytest.approx(0.8)


def test_a_shared_name_is_resolved_by_the_rows_game(nba_root):
    den = _prop_row("Jalen Williams", line=19.5)
    lac = _prop_row("Jalen Williams", line=4.5, home=HOME2, away=AWAY2, commence=LATE_COMMENCE)
    _props([den, lac])
    assert den["projection"]["projected"] == pytest.approx(_PTS_LADDER["mean"])
    assert lac["projection"]["projected"] == pytest.approx(5.0)
    assert lac["projection"]["model_prob_over"] == pytest.approx(0.5)


def test_ids_are_never_the_join(nba_root):
    # A board row carries an OddsAPI event_id; the sim carries NBA stats player
    # ids and game_cards ESPN game ids. A row with a nonsense id still joins on
    # name + game, and a row whose NAME is wrong never joins on any id.
    good = _prop_row("Stephen Curry", line=19.5, home=HOME2, away=AWAY2, commence=LATE_COMMENCE)
    good["event_id"] = "401918010"
    good["player_id"] = "201939"
    bad = _prop_row("201939", line=19.5, home=HOME2, away=AWAY2, commence=LATE_COMMENCE)
    _props([good, bad])
    assert "projection" in good
    assert "projection" not in bad


def test_per_line_refusals_are_counted_by_reason(nba_root):
    rows = [
        _prop_row("Injured Guy"),
        _prop_row("Nobody Atall"),
        _prop_row("Lauri Markkanen", market="player_double_double", line=None),
        _prop_row("Stephen Curry"),  # wrong game: Curry's sim is LAC@GSW
        _prop_row("Lauri Markkanen", market="player_steals", line=0.5),  # no stl ladder in fixture
    ]
    cov = _props(rows)
    assert all("projection" not in r for r in rows)
    reasons = cov["unprojected_by_reason"]
    assert reasons["player not in this game's sim (missing_prop_players)"] == 1
    assert reasons["player not in the NBA sim for this game"] == 1
    assert reasons["player's sim game is not this row's game"] == 1
    assert reasons["sim has no stl ladder for this player"] == 1
    assert any("double-double" in key for key in reasons)
    assert cov["rows_considered"] == 5 and cov["rows_with_projection"] == 0


def test_a_row_without_a_line_keeps_the_mean_and_says_why(nba_root):
    row = _prop_row("Lauri Markkanen", line=None)
    _props([row])
    p = row["projection"]
    assert p["projected"] == pytest.approx(_PTS_LADDER["mean"])
    assert p["model_prob_over"] is None
    assert p["probability_unavailable_reason"] == "row has no line to price"
    assert p["edge_unavailable_reason"].startswith("no probability to price")


def test_a_line_past_every_draw_is_null_with_a_reason_not_zero(nba_root):
    row = _prop_row("Lauri Markkanen", line=40.5)
    _props([row])
    p = row["projection"]
    assert p["model_prob_over"] is None
    assert p["edge_vs_market_pct"] is None
    assert p["projected"] == pytest.approx(_PTS_LADDER["mean"])


def test_live_prop_keeps_the_probability_and_loses_the_edge(nba_root):
    row = _prop_row("Lauri Markkanen", line=20.5, state="live")
    _props([row])
    p = row["projection"]
    assert p["model_prob_over"] == pytest.approx(0.4)
    assert p["edge_vs_market_pct"] is None and p["edge_vs_line"] is None
    assert p["edge_unavailable_reason"]


# ------------------------------------------------------------ reachability


def test_board_branch_is_reachable_off_differs_from_on(nba_root, tmp_path, monkeypatch):
    """OFF: no NBA artifacts -> the branch reports, but projects nothing.
    ON: the producer's files -> rows carry projections. The old state was
    `supported: False, "no projection source wired for nba"`; neither may
    return it now."""
    grid_on = [_game_row("totals", line=229.5), _prop_row("Lauri Markkanen", line=20.5)]
    on = board_enrichment._attach_projections_by_sport(grid_on, sport="nba", selected_date=D)

    empty = tmp_path / "empty_nba"
    (empty / "data" / "processed").mkdir(parents=True)
    monkeypatch.setenv("SYNDICATE_NBA_SOURCE_ROOT", str(empty))
    grid_off = [_game_row("totals", line=229.5), _prop_row("Lauri Markkanen", line=20.5)]
    off = board_enrichment._attach_projections_by_sport(grid_off, sport="nba", selected_date=D)

    for cov in (on, off):
        assert cov["supported"] is True
        assert cov.get("reason") != "no projection source wired for nba"
    assert on["game_rows_with_projection"] == 1 and on["prop_rows_with_projection"] == 1
    assert on["rows_with_probability"] == 2 and on["rows_with_edge"] == 2
    assert off["rows_with_projection"] == 0
    assert all("projection" in r for r in grid_on)
    assert not any("projection" in r for r in grid_off)
    assert on["rows_considered"] == on["game_rows_considered"] + on["prop_rows_considered"] == 2
