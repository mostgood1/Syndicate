"""Soccer prop evidence over PRODUCTION-SLICED fixtures (web disk, read 2026-09-17).

Every file under `tests/fixtures/prop_evidence/root/soccer_source` is cut from a
real production artifact, values verbatim, only rows removed:

    serie_a/api/recommendations/recommendations_2026-09-19.json   match 401874767 (Torino @ Bologna) + its players
    eredivisie/api/recommendations/recommendations_2026-09-19.json match 401875598 (Excelsior @ Ajax) + its players
    eredivisie/api/recommendations/recommendations_2026-09-20.json top level only (matches/players emptied)
    */api/live_state/live_state_<date>.json                        the boxes of those clubs' recent matches
    */players/players_2025.csv, players_2026.csv                   those clubs' rows

THE BOARD ROW SHAPE, verified in code rather than assumed. There were no soccer
prop rows on the served board on 2026-09-17, so the rows below carry the WNBA
board row's key set (`/api/board/layer2-shortlist`) with soccer values from the
real `serie_a/props/2026-09-18.csv` and `eredivisie/props/2026-09-17.csv`
captures (same OddsAPI event ids, spellings and prices). A soccer prop reaches
the board as:

    market       = the OddsAPI market key (`player_shots`, `player_shots_on_target`,
                   `player_assists`, `player_goal_scorer_anytime`, `player_first_goal_scorer`)
                   -- `odds_book_quotes.py:1277` (`"market": market_name`) -> `book_grid.py:799`
    player_name  = the outcome's `description` -- `odds_book_quotes.py:1268` -> `book_grid.py:802`
    line         = the outcome's `point`, None for the yes-priced scorer markets
                   -- `odds_book_quotes.py:1281` -> `book_grid.py:806`
    side         = `over` for shots/SOT/assists (`odds_book_quotes.py:1256`) and `yes`
                   for scorer markets (the lowered outcome name, `:1264`), carried as the
                   grid row's `sides` (`book_grid.py:826`) and set per candidate at
                   `layer2_board.py:2909`. Measured on production's
                   `soccer_source/tracking/book_quotes/2026-09-17.jsonl`: every soccer prop
                   quote is `over` with a numeric line (shots, SOT, assists) or `yes` with a
                   null line (anytime/first/last scorer, cards) -- no `under` is captured.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from syndicate.features.shared import prop_evidence, soccer_projections
from syndicate.features.shared import population_outcomes_soccer as grader
from syndicate.features.shared.prop_evidence import soccer
from syndicate.features.shared.prop_evidence.contract import LAYER_ORDER, Layer

ROOT = Path(__file__).parent / "fixtures" / "prop_evidence" / "root"
SERIE_A = ROOT / "soccer_source" / "serie_a"
EREDIVISIE = ROOT / "soccer_source" / "eredivisie"
SELECTED = "2026-09-17"


def _board_row(**overrides) -> dict:
    """A soccer prop in the served board row's shape (key set of `board_props_wnba.json`)."""
    row = {
        "sport": "soccer", "kind": "prop", "segment": "full", "board_lane": "opportunity",
        "event_id": "c7b8233ea02650f1055ae086b169b7a1", "home_team": "Bologna", "away_team": "Torino",
        "commence_time": "2026-09-19T13:00:00Z", "game_state": "pregame", "market_state": "pregame", "is_live": False,
        "game": {"away_score": None, "home_score": None, "matchup": "Torino @ Bologna",
                 "start_time_utc": "2026-09-19T13:00:00+00:00", "state": "pregame", "status_token": "8:00A CT"},
        "market": "player_shots", "player_name": "Roberto Piccoli", "line": 2.5, "side": "over",
        "ev_basis": "market_fair", "ev_pct": None, "model_edge_basis": None, "model_edge_pct": None, "model_ev_pct": None,
        "gate": {"fair_method": "consensus", "lane": "opportunity", "market_state": "pregame", "reasons": []},
        "movement": {"movement_state": "no_comparable_price"},
        "quote": {"bookmaker": "fanduel", "price": -300, "book_prices": {"fanduel": -300}, "books_quoting": 1,
                  "fair_method": "consensus", "other_sides": None, "suspect_stale": False},
        "score": {"score": None},
        "projection": None,
    }
    row.update(overrides)
    return row


PICCOLI_SHOTS = _board_row()
RODRIGUEZ_SOT = _board_row(market="player_shots_on_target", player_name="Ricardo Rodríguez", line=0.5,
                           quote={"bookmaker": "betrivers", "price": 420, "book_prices": {"betrivers": 420}, "books_quoting": 1})
DOVBYK_ASSISTS = _board_row(market="player_assists", player_name="Artem Dovbyk", line=0.5,
                            quote={"bookmaker": "fanduel", "price": 390, "book_prices": {"fanduel": 390}, "books_quoting": 1})
ENEM_ANYTIME = _board_row(market="player_goal_scorer_anytime", player_name="Jay Enem", line=None, side="yes",
                          quote={"bookmaker": "draftkings", "price": 240, "book_prices": {"draftkings": 240, "fanduel": 230}, "books_quoting": 2})
ORSOLINI_SOT = _board_row(market="player_shots_on_target", player_name="Riccardo Orsolini", line=0.5,
                          quote={"bookmaker": "betrivers", "price": -177, "book_prices": {"fanduel": -380, "betrivers": -177}, "books_quoting": 2})
SIMEONE_SHOTS_45 = _board_row(market="player_shots", player_name="Giovanni Simeone", line=4.5,
                              quote={"bookmaker": "fanduel", "price": 450, "book_prices": {"fanduel": 450}, "books_quoting": 1})
ODGAARD_FIRST = _board_row(market="player_first_goal_scorer", player_name="Jens Odgaard", line=None, side="yes",
                           quote={"bookmaker": "betrivers", "price": 950, "book_prices": {"draftkings": 750, "betrivers": 950}, "books_quoting": 4})
AJAX = {"event_id": "c63f2e2e69298e7e1ac986f01316a389", "home_team": "Ajax", "away_team": "Excelsior",
        "commence_time": "2026-09-19T18:00:00Z",
        "game": {"away_score": None, "home_score": None, "matchup": "Excelsior @ Ajax",
                 "start_time_utc": "2026-09-19T18:00:00+00:00", "state": "pregame", "status_token": "1:00P CT"}}
GLOUKH_ANYTIME = _board_row(**AJAX, market="player_goal_scorer_anytime", player_name="Oscar Gloukh", line=None, side="yes",
                            quote={"bookmaker": "betrivers", "price": 130, "book_prices": {"betrivers": 130}, "books_quoting": 1})
GAAEI_SOT = _board_row(**AJAX, market="player_shots_on_target", player_name="Anton Gaaei", line=0.5,
                       quote={"bookmaker": "betrivers", "price": 195, "book_prices": {"betrivers": 195}, "books_quoting": 1})


@pytest.fixture(autouse=True)
def _data_root(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))
    # Hermetic: without this `preferred_artifact_roots` appends the repo's own
    # `data/soccer_source` mirror after the fixture root.
    monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "1")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("SYNDICATE_SOCCER_SOURCE_ROOT", raising=False)


def _build(row: dict):
    return prop_evidence.build_prop_evidence(row, selected_date=SELECTED)


def _sim_player(league_dir: Path, name: str) -> dict:
    payload = json.loads((league_dir / "api" / "recommendations" / "recommendations_2026-09-19.json").read_text(encoding="utf-8"))
    hits = [p for p in payload["player_props"] if p["player_name"] == name]
    assert len(hits) == 1, name
    return hits[0]


def _tables(evidence, layer: Layer) -> list[dict]:
    return [t for t in evidence.to_section()["tables"] if t.get("layer") == layer.value]


def _rows(evidence, layer: Layer) -> list[list]:
    return [row for t in _tables(evidence, layer) for row in t["rows"]]


# --- (a) all seven layers ----------------------------------------------------


def test_every_layer_is_declared_and_a_shots_prop_fills_all_seven():
    evidence = _build(PICCOLI_SHOTS)
    coverage = evidence.coverage()
    assert list(coverage) == [layer.value for layer in LAYER_ORDER]
    assert all(status == "filled" for status in coverage.values()), coverage
    assert evidence.provider == "soccer"
    assert all(t["layer"] in {layer.value for layer in LAYER_ORDER} for t in evidence.to_section()["tables"])


@pytest.mark.parametrize("row", [RODRIGUEZ_SOT, DOVBYK_ASSISTS, ENEM_ANYTIME, GLOUKH_ANYTIME, GAAEI_SOT, ODGAARD_FIRST])
def test_every_modelled_market_declares_all_seven_and_never_an_undeclared_one(row):
    coverage = _build(row).coverage()
    assert list(coverage) == [layer.value for layer in LAYER_ORDER]
    assert not any(status.endswith(":undeclared") for status in coverage.values()), coverage
    for layer in ("player_sim", "matchup", "advanced", "game_sim", "environment", "track_record"):
        assert coverage[layer] == "filled", (row["player_name"], layer, coverage[layer])


# --- (b) filled values asserted against the fixture files ------------------


def test_player_sim_reads_the_published_ladder_at_the_board_line():
    evidence = _build(PICCOLI_SHOTS)
    published = _sim_player(SERIE_A, "Roberto Piccoli")["shots_over_probabilities"]["2.5"]
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_over"] == published
    assert evidence.layers[Layer.PLAYER_SIM].charts[0]["marker"]["x"] == "2.5"


def test_evidence_and_board_price_the_same_number_through_the_same_join():
    """The board's own `attach_soccer_projections`, over the same roots and window, lands on the same probability."""
    row = dict(PICCOLI_SHOTS)
    index = soccer.load_index(soccer.artifact_roots(), SELECTED, soccer.slate_window(SELECTED))
    soccer_projections.attach_soccer_projections([row], index)
    assert row["projection"]["basis"] == "shots_over_probabilities"
    evidence = _build(row)
    assert evidence.layers[Layer.PLAYER_SIM].facts["prob_over"] == row["projection"]["model_prob_over"]


def test_hit_rate_uses_the_board_line_and_side_and_a_did_not_play_is_not_a_miss():
    evidence = _build(GAAEI_SOT)
    facts = evidence.layers[Layer.RECENT_FORM].facts
    boxes = {}
    for date in ("2026-09-12", "2026-09-15"):
        payload = json.loads((EREDIVISIE / "api" / "live_state" / f"live_state_{date}.json").read_text(encoding="utf-8"))
        for box in payload["match_box"].values():
            for side in ("home", "away"):
                for player in box["players"][side]["players"]:
                    if player["player_name"] == "Anton Gaaei":
                        boxes[date] = player
    assert boxes["2026-09-15"]["appeared"] is False           # listed, unused
    assert facts["values"] == [boxes["2026-09-12"]["shots_on_target"]]
    assert facts["hit_rate"]["line"] == 0.5 and facts["hit_rate"]["side"] == "over"
    assert facts["unused_dates"] == ["2026-09-15"]
    assert facts["games"] == 1 and facts["small_sample"] is True
    assert any(str(r[0]).startswith("SMALL SAMPLE: 1 appearance") for r in _rows(evidence, Layer.RECENT_FORM))


def test_first_scorer_form_uses_the_settlement_graders_goal_order():
    evidence = _build(ODGAARD_FIRST)
    payload = json.loads((SERIE_A / "api" / "live_state" / "live_state_2026-09-13.json").read_text(encoding="utf-8"))
    box = payload["match_box"]["401874792"]
    goals, _ = grader.qualifying_goals(box)
    scorer, _ = grader.deciding_scorer(goals, "first")
    assert scorer == "stanislav lobotka"
    facts = evidence.layers[Layer.RECENT_FORM].facts
    assert facts["values"] == [0.0]
    assert "scored the first goal in 0 of 1 appearances" in [r[-1] for r in _rows(evidence, Layer.RECENT_FORM)]


def test_matchup_reads_the_opponents_rating_and_recent_concessions():
    evidence = _build(PICCOLI_SHOTS)
    recs = json.loads((SERIE_A / "api" / "recommendations" / "recommendations_2026-09-19.json").read_text(encoding="utf-8"))
    match = recs["matches"][0]
    facts = evidence.layers[Layer.MATCHUP].facts
    assert facts["opponent"] == "Torino"
    assert facts["opponent_rating"] == match["adapter_metadata"]["away_rating_detail"]
    box = json.loads((SERIE_A / "api" / "live_state" / "live_state_2026-09-14.json").read_text(encoding="utf-8"))["match_box"]["401874950"]
    assert box["home_team"] == "Torino"
    assert facts["opponent_recent_conceded"]["shots"] == float(box["teams"]["away"]["stats"]["Shots"])


def test_game_sim_is_the_match_entry():
    evidence = _build(PICCOLI_SHOTS)
    recs = json.loads((SERIE_A / "api" / "recommendations" / "recommendations_2026-09-19.json").read_text(encoding="utf-8"))
    facts = evidence.layers[Layer.GAME_SIM].facts
    assert facts["win_probability"] == recs["matches"][0]["win_probability"]
    assert facts["simulations"] == 400


# --- (c) reachability ---------------------------------------------------------


def test_removing_the_live_state_reader_names_the_recent_form_absence(monkeypatch):
    """The layer is filled BY the live_state reader, not by something beside it."""
    assert _build(PICCOLI_SHOTS).layers[Layer.RECENT_FORM].filled
    monkeypatch.setattr(soccer, "live_state_files", lambda roots, league, before: [])
    evidence = _build(PICCOLI_SHOTS)
    assert evidence.layers[Layer.RECENT_FORM].status().startswith("artifact_missing:no serie_a live_state")
    assert "opponent_recent_conceded" not in evidence.layers[Layer.MATCHUP].facts


def test_removing_the_players_reader_drops_season_rates_and_says_so(monkeypatch):
    assert any(t["title"].startswith("Season rates") for t in _tables(_build(PICCOLI_SHOTS), Layer.ADVANCED))
    monkeypatch.setattr(soccer, "season_rates", lambda roots, league, entry, match_date: [])
    evidence = _build(PICCOLI_SHOTS)
    assert not any(t["title"].startswith("Season rates") for t in _tables(evidence, Layer.ADVANCED))
    assert evidence.layers[Layer.ADVANCED].facts["season_rates"].startswith("artifact_missing:")


def test_no_recommendations_in_the_window_is_artifact_missing_on_every_match_layer():
    evidence = prop_evidence.build_prop_evidence(PICCOLI_SHOTS, selected_date="2026-10-10")
    coverage = evidence.coverage()
    for layer in ("player_sim", "recent_form", "matchup", "advanced", "game_sim", "environment"):
        assert coverage[layer].startswith("artifact_missing:no soccer recommendations"), (layer, coverage[layer])


# --- (d) conditional-on-playing labelling --------------------------------------


def test_a_bench_players_shots_ladder_is_labelled_if_he_plays_beside_his_minutes_share():
    sim = _sim_player(SERIE_A, "Ricardo Rodríguez")
    published = sim["shots_on_target_over_probabilities"]["0.5"]
    # The measurement behind the label: the ladder is the if-playing quantity, not the unconditional one.
    assert abs(published - (1 - math.exp(-sim["expected_shots_on_target_if_playing"]))) < 0.01
    assert published > 2 * (1 - math.exp(-sim["expected_shots_on_target"]))
    evidence = _build(RODRIGUEZ_SOT)
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_over"] == published and facts["ladder_basis"] == "if_playing"
    rows = _rows(evidence, Layer.PLAYER_SIM)
    labels = {str(r[0]): r[1] for r in rows}
    assert labels["Sim P(over 0.5 shots on target) — IF HE PLAYS (start/sub mixture; books void on a DNP)"] == "14.5%"
    assert labels["Expected minutes share (sim)"] == f"{100 * sim['expected_minutes_share']:.1f}%"
    assert "if he plays" in evidence.layers[Layer.PLAYER_SIM].charts[0]["title"]


def test_the_assists_ladder_is_labelled_unconditional():
    sim = _sim_player(SERIE_A, "Artem Dovbyk")
    assert abs(sim["assists_over_probabilities"]["0.5"] - (1 - math.exp(-sim["expected_assists"]))) <= 1e-4
    evidence = _build(DOVBYK_ASSISTS)
    assert evidence.layers[Layer.PLAYER_SIM].facts["ladder_basis"] == "unconditional"
    assert any("UNCONDITIONAL (includes the chance he does not play)" in str(r[0]) for r in _rows(evidence, Layer.PLAYER_SIM))


def test_anytime_scorer_shows_the_unconditional_price_the_board_uses_and_the_if_plays_one():
    sim = _sim_player(SERIE_A, "Jay Enem")
    evidence = _build(ENEM_ANYTIME)
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_yes"] == sim["anytime_scorer_probability"]
    assert facts["prob_yes_if_playing"] == sim["anytime_scorer_probability_if_playing"]
    assert facts["probability_basis"] == "unconditional"
    labels = [str(r[0]) for r in _rows(evidence, Layer.PLAYER_SIM)]
    assert any(label.startswith("Sim P(scores) — UNCONDITIONAL") and "board prices this field" in label for label in labels)
    assert "Sim P(scores) — IF HE PLAYS (start/sub mixture)" in labels
    assert facts["caveats"][0]["source"].startswith(".syndicate/state_soccer.md")


def test_ladder_basis_catches_an_unconditional_shots_ladder_under_the_same_key():
    """Artifacts built before `b33ef901` (2026-09-15) priced shots on the unconditional mean."""
    sim = dict(_sim_player(SERIE_A, "Ricardo Rodríguez"))
    spec = soccer.MARKETS["player_shots"]
    assert soccer.ladder_basis(sim, spec) == "if_playing"
    sim["shots_over_probabilities"] = {"0.5": round(1 - math.exp(-sim["expected_shots"]), 4)}
    assert soccer.ladder_basis(sim, spec) == "unconditional"


# --- (e) ESPN-league relabel ---------------------------------------------------


def test_espn_league_xg_columns_are_labelled_goals_and_assists():
    evidence = _build(GLOUKH_ANYTIME)
    with (EREDIVISIE / "players" / "players_2026.csv").open(encoding="utf-8") as handle:
        row = next(r for r in csv.DictReader(handle) if r["player_name"] == "Oscar Gloukh")
    assert row["source"] == "espn_true_per90"
    season_table = next(t for t in _tables(evidence, Layer.ADVANCED) if t["title"].startswith("Season rates"))
    labels = {str(r[0]): r[1] for r in season_table["rows"]}
    assert not any(label.startswith(("xG per 90", "xA per 90")) for label in labels)
    assert labels["Goals per 90 (ESPN: `xg_per90` holds GOALS, no xG exists)"] == f"{float(row['xg_per90']):.2f}"
    assert labels["Assists per 90 (ESPN: `xa_per90` holds ASSISTS, no xA exists)"] == f"{float(row['xa_per90']):.2f}"
    assert evidence.layers[Layer.ADVANCED].facts["season_rates"]["2026"]["xg_column_meaning"] == "goals_per90"
    # Team ratings on that path use goals as the xG stand-in too, and PPDA's 0.0 is a sentinel.
    matchup = {str(r[0]): r for r in _rows(evidence, Layer.MATCHUP)}
    assert "Goals (xG stand-in) for / match" in matchup and "xG for / match" not in matchup
    assert matchup["PPDA (lower = more pressing)"][1] == "not measured (0.0 sentinel)"


def test_understat_league_keeps_the_xg_labels():
    evidence = _build(PICCOLI_SHOTS)
    season_table = next(t for t in _tables(evidence, Layer.ADVANCED) if t["title"].startswith("Season rates"))
    labels = [str(r[0]) for r in season_table["rows"]]
    assert "xG per 90" in labels and "Goals per 90" in labels
    assert evidence.layers[Layer.ADVANCED].facts["season_rates"]["2026"]["xg_column_meaning"] == "xg_per90"
    assert "xG for / match" in {str(r[0]) for r in _rows(evidence, Layer.MATCHUP)}


# --- named absences and refusals ---------------------------------------------------


def test_a_player_absent_from_his_teams_box_roster_is_a_small_sample_not_a_miss():
    evidence = _build(ORSOLINI_SOT)
    assert evidence.coverage()["recent_form"].startswith("insufficient_sample:Riccardo Orsolini has no appearance")
    assert evidence.layers[Layer.ENVIRONMENT].facts["last_team_match_status"].startswith("not in the box roster")


def test_a_line_the_sim_did_not_price_is_refused_not_substituted():
    evidence = _build(SIMEONE_SHOTS_45)
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_over"] is None
    assert any(str(r[1]).startswith("not priced at 4.5") for r in _rows(evidence, Layer.PLAYER_SIM))
    assert evidence.layers[Layer.RECENT_FORM].facts["hit_rate"]["line"] == 4.5


def test_card_market_declares_no_producer_by_name():
    row = _board_row(market="player_to_receive_card", player_name="Jens Odgaard", line=None, side="yes")
    coverage = _build(row).coverage()
    assert coverage["player_sim"].startswith("no_producer:")
    assert coverage["recent_form"].startswith("no_producer:")
    assert coverage["game_sim"] == "filled"


def test_unknown_player_and_unknown_fixture_are_named_absences():
    nobody = _build(_board_row(player_name="Nobody Atall"))
    assert nobody.coverage()["player_sim"].startswith("player_not_found:Nobody Atall not in the sim's player list")
    assert nobody.coverage()["game_sim"] == "filled"
    wrong_fixture = _build(_board_row(away_team="Juventus"))
    for layer in ("player_sim", "matchup", "game_sim", "environment"):
        assert wrong_fixture.coverage()[layer].startswith("player_not_found:fixture Juventus @ Bologna"), layer


def test_sim_age_comes_from_the_matchs_own_file_not_the_league_map():
    """`generated_at_by_league` is a per-league plain write across the window: the LAST date read wins."""
    index = soccer.load_index(soccer.artifact_roots(), SELECTED, soccer.slate_window(SELECTED))
    later = json.loads((EREDIVISIE / "api" / "recommendations" / "recommendations_2026-09-20.json").read_text(encoding="utf-8"))
    own = json.loads((EREDIVISIE / "api" / "recommendations" / "recommendations_2026-09-19.json").read_text(encoding="utf-8"))
    assert index.generated_at_by_league["eredivisie"] == later["generated_at"] != own["generated_at"]
    evidence = _build(GLOUKH_ANYTIME)
    assert evidence.layers[Layer.ENVIRONMENT].facts["generated_at"] == own["generated_at"]
