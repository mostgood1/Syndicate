"""Level 4 of scripts/basketball_sim_input_checklist.py (todo #821 F0): the pregame quarter model's team inputs.

Structural half: TeamContextLocal fields over dataclasses.fields(), consumed (AST of the quarter model) vs passed (AST of
the pregame builder's TeamContextLocal(...) calls). Data half: a replay of the job build's own game-model read over the
newest predictions files, plus market_anchor.game_model_fed on the sims of the same dates. Each half must be able to
fail: a positive control for the structure, NBA-named fixtures for the data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import basketball_sim_input_checklist as chk  # noqa: E402

BRIDGE_SOURCE = chk.BRIDGE_PATH.read_text(encoding="utf-8")


# --- structural ----------------------------------------------------------------------------------------------------

def test_quarter_model_reads_off_rating_and_the_builder_passes_it():
    consumed = chk.consumed_team_context_fields(BRIDGE_SOURCE)
    populated, n_calls = chk.populated_team_context_fields(BRIDGE_SOURCE)
    assert n_calls == 2  # home_ctx + away_ctx
    for name in ("off_rating", "def_rating", "pace", "injuries_out", "back_to_back", "off_rating_from_points"):
        assert name in consumed and name in populated, name
    assert consumed["off_rating"] == ["_simulate_quarters_local"]


def test_form_terms_are_consumed_and_never_passed_today():
    """Pinned on purpose (a lead from todo #821): form_7/form_30 move the quarter means (_adjustments_local) and the
    quarter sigma (the stress term in _simulate_quarters_local), and the pregame builder passes neither, so both are
    always None. Wiring them is a behaviour change: update this pin when that is decided."""
    data, alarms = chk.team_context_structural_alarms(BRIDGE_SOURCE)
    assert data["consumed_not_populated"] == ["form_30", "form_7"]
    assert data["populated_not_consumed"] == ["rest_days"]
    assert sorted(data["consumed"]["form_7"]) == ["_adjustments_local", "_simulate_quarters_local"]
    assert [a.split(" is read")[0] for a in alarms] == [
        "STRUCTURALLY UNFED: TeamContextLocal.form_30", "STRUCTURALLY UNFED: TeamContextLocal.form_7"]


def test_positive_control_a_builder_that_drops_off_rating_alarms():
    blinded = BRIDGE_SOURCE.replace("off_rating=home_off_rtg, ", "", 1)
    assert blinded != BRIDGE_SOURCE
    data, alarms = chk.team_context_structural_alarms(blinded)
    assert "off_rating" in data["consumed_not_populated"]
    assert any("TeamContextLocal.off_rating is read" in a for a in alarms)


def test_a_renamed_consumer_reads_nothing_and_says_so():
    data, alarms = chk.team_context_structural_alarms(BRIDGE_SOURCE.replace("def _adjustments_local(", "def _adj_renamed(")
                                                      .replace("def _simulate_quarters_local(", "def _sq_renamed("))
    assert data["consumed"] == {}
    assert any(a.startswith("LEVEL 4 READ NOTHING") for a in alarms)


def test_level4_is_not_blind_on_the_real_source(monkeypatch, tmp_path):
    for cfg in chk.LEAGUES.values():
        monkeypatch.setitem(cfg, "sim_root", tmp_path / "absent")
    data, alarms, notes = chk.level4_quarter_model_inputs()
    assert not [a for a in alarms if a.startswith("LEVEL 4 BLIND")]
    assert len([n for n in notes if "UNMEASURED" in n]) == len(chk.LEAGUES)


# --- the game-model feed -------------------------------------------------------------------------------------------

def _predictions(root: Path, date: str, header: str, rows: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"predictions_{date}.csv").write_text(
        f"home_team,visitor_team,{header}\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _sim(root: Path, date: str, game: str, anchor: dict) -> None:
    (root / f"smart_sim_{date}_{game}.json").write_text(json.dumps({"market_anchor": anchor}), encoding="utf-8")


def test_nba_named_predictions_alarm_unfed(tmp_path):
    for i, date in enumerate(("2026-11-14", "2026-11-15")):
        _predictions(tmp_path, date, "pred_total,pred_margin,elo_diff",
                     [f"BOS,NYK,22{i}.5,2.0,10", "LAL,GSW,231.0,-1.5,-3", "MIA,ORL,214.0,4.0,7"])
        _sim(tmp_path, date, "BOS_NYK", {"model_margin_raw": 0.0})
    census = chk.game_model_feed_census(tmp_path)
    assert (census["prediction_rows"], census["prediction_rows_fed"]) == (6, 0)
    assert census["columns_present"] == {"totals": 0, "spread_margin": 0, "pred_total": 6, "pred_margin": 6}
    assert (census["sims"], census["sims_with_field"]) == (2, 0)
    alarms, notes = chk.game_model_feed_alarms("nba", census)
    assert len(alarms) == 1 and alarms[0].startswith("UNFED: nba quarter-model off_rating")
    assert "0.0% of 6 predictions rows over 2 dates (2026-11-14..2026-11-15)" in alarms[0]
    assert any("absent on all 2 sims" in n for n in notes)


def test_wnba_named_predictions_pass(tmp_path):
    _predictions(tmp_path, "2026-10-31", "totals,spread_margin",
                 [f"LVA,NYL,16{i}.0,{i}.5" for i in range(6)])
    census = chk.game_model_feed_census(tmp_path)
    assert (census["prediction_rows"], census["prediction_rows_fed"]) == (6, 6)
    assert chk.game_model_feed_alarms("wnba", census)[0] == []


def test_artifacts_carrying_fed_false_alarm_on_their_own(tmp_path):
    _predictions(tmp_path, "2026-11-20", "totals,spread_margin", [f"BOS,NYK,22{i}.0,1.0" for i in range(6)])
    for i in range(5):
        _sim(tmp_path, "2026-11-20", f"G{i}_H{i}", {"game_model_fed": False, "game_model_columns": ["pred_total"]})
    census = chk.game_model_feed_census(tmp_path)
    assert (census["sims_with_field"], census["sims_fed"]) == (5, 0)
    alarms, _ = chk.game_model_feed_alarms("nba", census)
    assert [a.split(" --")[0] for a in alarms] == ["UNFED: nba smart_sim artifacts"]


def test_only_the_newest_files_and_only_dated_names_count(tmp_path):
    for day in range(1, 17):
        _predictions(tmp_path, f"2026-11-{day:02d}", "pred_total,pred_margin", ["BOS,NYK,220.0,1.0"])
    (tmp_path / "props_predictions_2026-11-16.csv").write_text("totals,spread_margin\n1,2\n", encoding="utf-8")
    (tmp_path / "predictions_latest.csv").write_text("totals,spread_margin\n1,2\n", encoding="utf-8")
    census = chk.game_model_feed_census(tmp_path)
    assert census["dates"][0] == "2026-11-03" and census["dates"][-1] == "2026-11-16"
    assert len(census["dates"]) == chk.GAME_MODEL_RECENT_FILES and census["prediction_rows"] == 14


def test_too_few_rows_is_unmeasured_not_unfed(tmp_path):
    _predictions(tmp_path, "2026-11-16", "pred_total,pred_margin", ["BOS,NYK,220.0,1.0"])
    alarms, notes = chk.game_model_feed_alarms("nba", chk.game_model_feed_census(tmp_path))
    assert alarms == [] and any("UNMEASURED" in n for n in notes)
