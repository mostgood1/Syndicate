"""WNBA prop evidence over PRODUCTION-SLICED fixtures (web disk, 2026-09-17).

The fixture files under `tests/fixtures/prop_evidence/root` are cut from the
real production artifacts -- `cards_sim_detail_2026-09-17.json`, the two
`smart_sim_*` game files, `boxscores_history.csv`, `boxscores_2026-08-25.csv`,
`team_advanced_stats_2026.csv`, `model_scorecard_latest.json` -- not typed by
hand, and the board rows below are the served `/api/board/layer2-shortlist`
rows for the same slate. A fixture that invents both sides of a join proves
nothing (`learnings.md` 2026-09-05), which is how Ask's old reader asked for
`minutes` against an engine that writes `min_mean` and every test stayed green.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syndicate.features.shared import prop_evidence
from syndicate.features.shared.prop_evidence import basketball
from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence.contract import LAYER_ORDER, Layer

ROOT = Path(__file__).parent / "fixtures" / "prop_evidence" / "root"
SIM_DETAIL = ROOT / "wnba_source" / "data" / "processed" / "cards_sim_detail_2026-09-17.json"

RIVERS_POINTS = {
    "sport": "wnba", "event_id": "0fd1d4ee6d6e720e030e8cefb6a5a591", "market": "player_points",
    "player_name": "Saniya Rivers", "line": 9.5, "side": "over", "segment": "full",
    "home_team": "Atlanta Dream", "away_team": "Connecticut Sun", "commence_time": "2026-09-17T23:30:00Z",
    "kind": "prop",
    "projection": {"basis": "empirical_sim_ladder", "market_fair_prob_over": 0.5074, "model_prob_over": 0.34,
                   "model_skill": {"correlation": None, "sample_games": 0, "status": "unmeasured",
                                   "verdict": "model never backtested -- projection is unvalidated"},
                   "projected": 8.04, "source": "wnba_props_recommendations"},
}
AUSTIN_POINTS_UNDER = {
    "sport": "wnba", "event_id": "e1345bc3242e9236f8524205bb759ad3", "market": "player_points",
    "player_name": "Shakira Austin", "line": 17.5, "side": "under", "segment": "full",
    "home_team": "Chicago Sky", "away_team": "Washington Mystics", "commence_time": "2026-09-18T00:00:00Z",
    "kind": "prop", "projection": None,
}
AUSTIN_REB_AST = {**AUSTIN_POINTS_UNDER, "market": "player_rebounds_assists", "line": 12.5, "side": "over"}
CARDOSO_DOUBLE_DOUBLE = {
    "sport": "wnba", "event_id": "e1345bc3242e9236f8524205bb759ad3", "market": "player_double_double",
    "player_name": "Kamilla Cardoso", "line": None, "side": "Yes", "segment": "full",
    "home_team": "Chicago Sky", "away_team": "Washington Mystics", "commence_time": "2026-09-18T00:00:00Z",
    "kind": "prop", "projection": None,
}


@pytest.fixture(autouse=True)
def _data_root(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))


def _sim_player(name: str) -> dict:
    payload = json.loads(SIM_DETAIL.read_text(encoding="utf-8"))
    for game in payload["games"]:
        for side in ("home", "away"):
            for player in game["sim"]["players"][side]:
                if player["player_name"] == name:
                    return player
    raise AssertionError(name)


def _table(section: dict, layer: Layer) -> list[dict]:
    return [t for t in section["tables"] if t.get("layer") == layer.value]


def test_every_layer_is_declared_and_a_full_prop_fills_all_seven():
    evidence = prop_evidence.build_prop_evidence(RIVERS_POINTS, selected_date="2026-09-17")
    coverage = evidence.coverage()
    assert list(coverage) == [layer.value for layer in LAYER_ORDER]
    assert all(status == "filled" for status in coverage.values()), coverage


def test_player_sim_probability_is_read_off_the_published_draws_not_a_fitted_normal():
    evidence = prop_evidence.build_prop_evidence(RIVERS_POINTS, selected_date="2026-09-17")
    player = _sim_player("Saniya Rivers")
    draws = player["prop_distributions"]["pts"]["distribution"]
    expected = sum(c for x, c in draws.items() if float(x) > 9.5) / sum(draws.values())
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_over"] == pytest.approx(expected)
    # The board row carried model_prob_over 0.34 from the same ladder; both readers agree.
    assert facts["prob_over"] == pytest.approx(0.34)
    chart = evidence.layers[Layer.PLAYER_SIM].charts[0]
    assert chart["marker"]["x"] == "9.5"


def test_minutes_come_from_min_mean_the_key_the_engine_writes():
    evidence = prop_evidence.build_prop_evidence(RIVERS_POINTS, selected_date="2026-09-17")
    player = _sim_player("Saniya Rivers")
    assert "minutes" not in player  # the stub-only key the old reader asked for
    assert evidence.layers[Layer.PLAYER_SIM].facts["min_mean"] == pytest.approx(player["min_mean"])
    rows = _table(evidence.to_section(), Layer.ADVANCED)[0]["rows"]
    assert ["Sim minutes", f"{player['min_mean']:.1f}"] in rows


def test_hit_rate_uses_the_board_line_and_side_and_skips_dnp_games():
    evidence = prop_evidence.build_prop_evidence(AUSTIN_POINTS_UNDER, selected_date="2026-09-17")
    facts = evidence.layers[Layer.RECENT_FORM].facts
    rate = facts["hit_rate"]
    assert rate["line"] == 17.5 and rate["side"] == "under"
    assert rate["hits"] == rate["under"]
    assert all(value is not None for value in facts["values"])
    # Every counted game had minutes: a 0-minute DNP is voided by books, never a miss.
    games, _ = basketball._box_games("wnba", "Shakira Austin", "2026-09-17")
    assert games and all(g["MIN"] for g in games)


def test_dated_daily_box_scores_extend_the_stale_history_file():
    history = ROOT / "wnba_source" / "data" / "processed" / "boxscores_history.csv"
    newest_in_history = max(r["date"] for r in csv.DictReader(history.open(encoding="utf-8"))
                            if r["PLAYER_NAME"] == "Shakira Austin")
    evidence = prop_evidence.build_prop_evidence(AUSTIN_POINTS_UNDER, selected_date="2026-09-17")
    facts = evidence.layers[Layer.RECENT_FORM].facts
    assert facts["newest_game"] == "2026-08-25" > newest_in_history
    # And what staleness remains is stated on the table, not hidden.
    rows = _table(evidence.to_section(), Layer.RECENT_FORM)[0]["rows"]
    assert any(str(r[0]).startswith("STALE: newest box score is 23 days") for r in rows)


def test_removing_the_box_score_reader_empties_recent_form(monkeypatch):
    """Reachability: the layer is filled BY the reader, not by something beside it."""
    monkeypatch.setattr(basketball, "_box_sources", lambda sport, as_of: [])
    evidence = prop_evidence.build_prop_evidence(RIVERS_POINTS, selected_date="2026-09-17")
    assert evidence.layers[Layer.RECENT_FORM].status().startswith("artifact_missing")


def test_combo_market_uses_the_published_mean_and_declares_no_probability():
    evidence = prop_evidence.build_prop_evidence(AUSTIN_REB_AST, selected_date="2026-09-17")
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_over"] is None
    assert facts["mean"] == pytest.approx(14.14)
    assert evidence.layers[Layer.RECENT_FORM].facts["hit_rate"]["line"] == 12.5


def test_joint_market_declares_its_absences_by_name():
    evidence = prop_evidence.build_prop_evidence(CARDOSO_DOUBLE_DOUBLE, selected_date="2026-09-17")
    coverage = evidence.coverage()
    assert coverage["player_sim"].startswith("no_producer:")
    assert coverage["recent_form"].startswith("not_applicable:")
    assert coverage["game_sim"] == "filled"


def test_game_sim_and_environment_read_the_smart_sim_file_for_that_game():
    evidence = prop_evidence.build_prop_evidence(RIVERS_POINTS, selected_date="2026-09-17")
    smart = json.loads((ROOT / "wnba_source/data/processed/smart_sim_2026-09-17_ATL_CON.json").read_text(encoding="utf-8"))
    assert evidence.layers[Layer.GAME_SIM].facts["p_home_win"] == smart["score"]["p_home_win"]
    env = evidence.layers[Layer.ENVIRONMENT].facts
    assert env["pace"] == {"own": smart["context"]["away_pace"], "opp": smart["context"]["home_pace"]}
    assert env["side"] == "away"


def test_evening_tip_resolves_the_slate_date_not_the_utc_date():
    row = {**AUSTIN_POINTS_UNDER}
    subject = prop_evidence.PropSubject.from_board_row(row, selected_date="")
    # 2026-09-18T00:00:00Z is 8 PM ET on the 17th: the slate date, not the UTC date.
    assert subject.selected_date == "2026-09-17"
    assert basketball.candidate_dates(subject) == ["2026-09-17", "2026-09-18"]
    evidence = basketball.build(subject)
    assert evidence.layers[Layer.PLAYER_SIM].filled


def test_track_record_states_the_row_skill_note_when_the_scorecard_has_no_cell():
    evidence = prop_evidence.build_prop_evidence(RIVERS_POINTS, selected_date="2026-09-17")
    layer = evidence.layers[Layer.TRACK_RECORD]
    assert layer.filled
    assert layer.facts["cells"] == {}
    assert ["Model skill note (this row)", "unmeasured", "model never backtested -- projection is unvalidated"] in layer.tables[0]["rows"]


def test_unknown_player_is_a_named_absence_not_an_empty_answer():
    row = {**RIVERS_POINTS, "player_name": "Nobody Atall", "projection": None}
    evidence = prop_evidence.build_prop_evidence(row, selected_date="2026-09-17")
    assert evidence.coverage()["player_sim"].startswith("player_not_found:")
    assert evidence.coverage()["recent_form"].startswith("player_not_found:")


def test_names_join_through_accents_and_suffixes():
    assert C.names_match("Kenneth Walker III", "Kenneth Walker")
    assert C.names_match("Nneka Ogwumike", "nneka  ogwumike")
    assert not C.names_match("Chennedy Carter", "Chennedy Cartier")
