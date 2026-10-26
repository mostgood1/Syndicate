"""DecisionRecord (`#709` step 2, lane `decision-record-shadow`): shadow record + agreement."""

from __future__ import annotations

import ast
import gzip
import json
from pathlib import Path

import pytest

from syndicate.features.shared import decision_agreement as da
from syndicate.features.shared import decision_record as dr

REPO = Path(__file__).resolve().parents[1]
DATE = "2026-10-23"


def _row(**over):
    row = {
        "sport": "nba", "event_id": "ev1", "kind": "game", "market": "totals", "segment": "full",
        "player_name": None, "side": "over", "line": 220.5, "commence_time": "2099-10-24T00:00:00Z",
        "home_team": "Home", "away_team": "Away", "game_state": "pregame", "suggested": True,
        "suggested_reasons": [], "ev_pct": 3.0, "model_edge_pct": 4.0,
        "model_probability_cal": 0.56,
        "projection": {"model_prob_over": 0.56, "source": "sim", "basis": "b",
                       "model_skill": {"status": "measured", "verdict": "beats the close"}},
        "quote": {"fair_probability": 0.50, "fair_devig_method": "shin", "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 30.0, "quote_seen_age_seconds": 5.0,
                  "suspect_stale": False, "bookmaker": "draftkings", "price": 105,
                  "book_prices": {"draftkings": 105, "kalshi": 100, "polymarket": -110}},
    }
    for key, value in over.items():
        if key == "quote":
            row["quote"] = {**row["quote"], **value}
        else:
            row[key] = value
    return row


def _ctx(**over):
    ctx = dr.RecordContext(selected_date=DATE)
    ctx.paper_bankroll = 1000.0
    ctx.live_capital = {"kalshi": 200.0, "polymarket": 200.0}
    ctx.settled_sample_by_sport = {"nba": 500}
    ctx.max_order_dollars = {"kalshi": 10.0, "polymarket": 10.0}
    ctx.live_net_floor = {"kalshi": None, "polymarket": None}
    for key, value in over.items():
        setattr(ctx, key, value)
    return ctx


def _verdict(rec, dest):
    return next(v for v in rec.verdicts if v.destination == dest)


def _gate(rec, dest, name):
    return next(g for g in rec.gates if g.destination == dest and g.name == name)


# ----------------------------------------------------------------------------- reachability


def test_reachability_off_writes_nothing_shadow_writes_the_record(tmp_path, monkeypatch):
    shortlist = {"rows": [_row()], "written_at": "t"}
    monkeypatch.setenv(dr.MODE_ENV, "off")
    off = dr.run_shadow(DATE, shortlist, root=tmp_path, plans={}, live_orders=[])
    assert off == {"status": "off"}
    assert not dr.records_path(DATE, tmp_path).exists()
    monkeypatch.delenv(dr.MODE_ENV)
    on = dr.run_shadow(DATE, shortlist, root=tmp_path, plans={}, live_orders=[])
    assert on["status"] == "ok" and on["records"] == 1
    payload = dr.read_records(DATE, tmp_path)
    assert payload["records_count"] == 1 and payload["version"] == dr.RECORD_VERSION
    assert da.agreement_jsonl_path(DATE, tmp_path).exists()
    assert da.report_paths(DATE, tmp_path)[1].read_text(encoding="utf-8").startswith("# DecisionRecord agreement")


def test_worker_hook_calls_run_shadow_after_the_portfolio_commit_with_the_shortlist():
    """The hook is in `_build_candidate_pool`, after the commit's try, with the same shortlist."""
    source = (REPO / "pipeline" / "intelligence_state.py").read_text(encoding="utf-8")
    commit = source.index('PORTFOLIO_COMMIT_FAILED error=')
    hook = source.index("run_shadow(str(selected_date or \"\"), layer2_shortlist)")
    assert commit < hook < source.index('"source_fingerprint": source_fingerprint', commit)
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_build_candidate_pool")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "run_shadow"]
    assert len(calls) == 1


def test_nothing_outside_the_lane_reads_the_record():
    """SHADOW means no reader: no placement, sizing or board module imports it."""
    readers = []
    for path in list((REPO / "pipeline").glob("*.py")) + list((REPO / "syndicate").rglob("*.py")):
        if path.name in {"decision_record.py", "decision_agreement.py", "intelligence_state.py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "shared.decision_record" in text or "shared.decision_agreement" in text or "import decision_record" in text:
            readers.append(str(path))
    assert readers == []


# ----------------------------------------------------------------------------- the probability


def test_blend_anchors_on_market_and_uses_measured_w_star():
    row = _row()
    ctx = _ctx()
    cell = dr._calibration_cell(row, ctx.now)
    ctx.calibration = {cell: {"cell": cell, "w": 0.5, "ci95": [0.3, 0.7], "verdict": "overconfident", "games": 90}}
    rec = dr.build_record(row, ctx)
    assert rec.blend.w_model == 0.5 and rec.blend.w_model_source == "optimizer_w:overconfident"
    assert rec.blend.p_decision == pytest.approx(0.50 + 0.5 * (0.56 - 0.50), abs=1e-6)


def test_blend_default_weight_and_zero_when_skill_loses_to_market():
    rec = dr.build_record(_row(), _ctx())
    # D3 (user 2026-10-26, plan #736): an unmeasured cell's model moves nothing.
    assert dr.DEFAULT_MODEL_WEIGHT == 0.0
    assert rec.blend.w_model == 0.0 and rec.blend.w_model_source == "default_unmeasured"
    assert rec.blend.model_shift_pp == 0.0 and rec.blend.p_decision == pytest.approx(0.50, abs=1e-6)
    loses = _row(projection={"model_prob_over": 0.70, "model_skill": {"status": "measured", "verdict": "loses to the closing line"}},
                 model_probability_cal=0.70)
    rec = dr.build_record(loses, _ctx())
    assert rec.blend.w_model == 0.0 and rec.blend.p_decision == pytest.approx(0.50, abs=1e-6)


@pytest.mark.parametrize("verdict", ["not_proven", "overconfident"])
def test_fitted_w_star_whose_ci_reaches_zero_moves_nothing(verdict):
    # D3: a fit only earns weight when its ci95 LOWER bound is above 0.
    row = _row()
    ctx = _ctx()
    cell = dr._calibration_cell(row, ctx.now)
    ctx.calibration = {cell: {"cell": cell, "w": 0.4, "ci95": [-0.12, 0.81], "verdict": verdict, "games": 120}}
    rec = dr.build_record(row, ctx)
    assert rec.model.w_star == 0.4 and rec.model.w_star_ci_lower == -0.12 and rec.model.w_star_ci_upper == 0.81
    assert rec.blend.w_model == 0.0 and rec.blend.w_model_source == f"optimizer_w_ci_spans_0:{verdict}"
    assert rec.blend.p_decision == pytest.approx(0.50, abs=1e-6)


def test_insufficient_fit_is_not_a_fit_even_with_a_positive_ci():
    row = _row()
    ctx = _ctx()
    cell = dr._calibration_cell(row, ctx.now)
    ctx.calibration = {cell: {"cell": cell, "w": 0.6, "ci95": [0.2, 0.9], "verdict": "insufficient", "games": 12}}
    rec = dr.build_record(row, ctx)
    assert rec.blend.w_model == 0.0 and rec.blend.w_model_source == "default_unmeasured"


def test_w_star_ci_lower_survives_the_on_disk_round_trip():
    row = _row()
    ctx = _ctx()
    cell = dr._calibration_cell(row, ctx.now)
    ctx.calibration = {cell: {"cell": cell, "w": 0.5, "ci95": [0.3, 0.7], "verdict": "overconfident", "games": 90}}
    rec = dr.build_record(row, ctx)
    back = dr.expand_record(json.loads(json.dumps(dr._compact(rec))))
    assert back.model.w_star_ci_lower == 0.3 and back.blend.w_model == 0.5


def test_form_posterior_recorded_but_moves_nothing_until_measured():
    row = _row(kind="prop", market="player_points", player_name="A Player", line=20.5)
    ctx = _ctx(form_index={dr.line_key(row): {"form5": {"games": 5, "hits": 5}, "form10": {"games": 10, "hits": 9}, "sheet": "x"}})
    rec = dr.build_record(row, ctx)
    assert rec.form.p_posterior == pytest.approx((40 * 0.50 + 9) / 50, abs=1e-4)
    assert rec.form.provisional is True and rec.blend.w_form == 0.0 and rec.blend.form_shift_pp == 0.0


def test_p_model_is_side_adjusted_from_projection_when_no_row_probability():
    row = _row(side="under", model_probability_cal=None)
    rec = dr.build_record(row, _ctx())
    assert rec.model.p_model == pytest.approx(0.44) and rec.model.source_field == "projection.model_prob_over"


# ----------------------------------------------------------------------------- price, fee, gates


def test_one_ev_formula_net_of_the_venue_fee():
    rec = dr.build_record(_row(), _ctx())
    kalshi = next(p for p in rec.prices if p.book == "kalshi")
    assert kalshi.fee_per_contract == pytest.approx(0.07 * 0.5 * 0.5, abs=1e-6)
    assert kalshi.ev_net_pct == pytest.approx((rec.blend.p_decision / (0.5 + kalshi.fee_per_contract) - 1) * 100, abs=1e-3)
    poly = next(p for p in rec.prices if p.book == "polymarket")
    prob = 110 / 210
    assert poly.fee_basis == "polymarket_filed_quadratic"
    assert poly.fee_per_contract == pytest.approx(0.0695 * prob * (1 - prob), abs=1e-6)


def test_price_band_gate_reads_the_executors_env(monkeypatch):
    row = _row(quote={"book_prices": {"draftkings": 105, "kalshi": 250}})
    rec = dr.build_record(row, dr.load_context(DATE, [row]) if False else _ctx())
    gate = _gate(rec, "live:kalshi", "price_band")
    assert gate.passed is False and gate.enforced_live is False
    monkeypatch.setenv("SYNDICATE_LIVE_PRICE_BAND", "0.20,0.75")
    band, configured = dr._live_price_band()
    assert band == (0.20, 0.75) and configured
    rec = dr.build_record(row, _ctx(price_band=band, price_band_configured=configured))
    assert _gate(rec, "live:kalshi", "price_band").passed is True


def test_in_play_and_wrong_date_contract_block_live():
    row = _row(commence_time="2000-01-01T00:00:00Z")
    rec = dr.build_record(row, _ctx())
    assert _gate(rec, "live:kalshi", "pregame").passed is False
    assert not _verdict(rec, "live:kalshi").bet
    wrong = _row(price_source="kalshi", venue_ref="KXNBAGAME-99OCT29AWYHOM-HOM")
    rec = dr.build_record(wrong, _ctx())
    contract = next(c for c in rec.contracts if c.venue == "kalshi")
    assert contract.identity == "wrong_date"
    assert "venue_contract_identity" in _verdict(rec, "live:kalshi").failed_gates


def test_concentration_keeps_one_bet_per_game_axis():
    # Both rungs are +EV at the MARKET fair (no model weight since D3), so only concentration separates them.
    a = _row(line=220.5, quote={"book_prices": {"draftkings": 105, "kalshi": 112}})
    b = _row(line=221.5, quote={"book_prices": {"draftkings": 105, "kalshi": 115}})
    recs = dr.build_records([a, b], _ctx())
    bets = [r for r in recs if _verdict(r, "live:kalshi").bet]
    assert len(bets) == 1 and bets[0].identity.line == 221.5
    loser = next(r for r in recs if r is not bets[0])
    assert "concentration" in _verdict(loser, "live:kalshi").failed_gates


# ----------------------------------------------------------------------------- size


def test_size_layers_band_reads_full_kelly_and_is_not_applied():
    row = _row(quote={"book_prices": {"draftkings": 105, "kalshi": 110}})
    ctx = _ctx(band_config={"on": True, "min_dollars": 5.0, "max_dollars": 10.0, "kelly_at_max": 0.05,
                            "small_edge_fraction": None}, favourite_cap={"on": False})
    rec = dr.build_records([row], ctx)[0]
    size = next(s for s in rec.sizes if s.destination == "live:kalshi")
    names = [l.name for l in size.layers]
    assert names[:4] == ["kelly_full", "kelly_multiplier", "credibility", "skill_and_optimizer"]
    band = next(l for l in size.layers if l.name == "stake_band")
    assert band.applied is False and band.live_applies is True
    assert size.stake_dollars == pytest.approx(size.stake_fraction * 200.0, abs=0.01)
    assert size.stake_dollars_live_equivalent == pytest.approx(band.value)
    assert size.stake_dollars < size.stake_dollars_live_equivalent  # the full-Kelly band inflates


def test_order_cap_binds():
    row = _row(model_probability_cal=0.95, quote={"book_prices": {"draftkings": 105, "kalshi": 110}})
    ctx = _ctx(live_capital={"kalshi": 100000.0, "polymarket": 0.0}, calibration={})
    rec = dr.build_records([row], ctx)[0]
    size = next(s for s in rec.sizes if s.destination == "live:kalshi")
    assert size.binding_layer == "order_cap" and size.stake_dollars == 10.0


# ----------------------------------------------------------------------------- storage + allowlist


def test_compact_round_trip_is_exact():
    row = _row(kind="prop", market="player_points", player_name="P", price_source="polymarket_us",
               venue_ref="aec-nba-a-h-2099-10-23-points")
    rec = dr.build_records([row], _ctx())[0]
    assert dr.expand_record(json.loads(json.dumps(dr._compact(rec)))) == rec


def test_records_file_is_gzip_json_and_export_allowlisted(tmp_path):
    path = dr.write_records(DATE, dr.build_records([_row()], _ctx()), build_id="b", root=tmp_path)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        assert json.load(fh)["records_count"] == 1
    from syndicate.features.shared.artifact_publisher import (
        is_exportable_artifact_relative_path,
        is_hot_artifact_relative_path,
    )

    rel = f"reports/intelligence/decision_records/{path.name}"
    assert is_exportable_artifact_relative_path(rel)
    assert not is_hot_artifact_relative_path(rel)


# ----------------------------------------------------------------------------- agreement


def _sim_opposes_row():
    return _row(model_probability_cal=0.40, ev_pct=2.5,
                projection={"model_prob_over": 0.40, "model_skill": {"status": "measured", "verdict": "beats"}},
                quote={"price": 110, "book_prices": {"draftkings": 110, "kalshi": -110}})


def test_board_disagreement_names_sim_opposes_and_venue_negative():
    # The sim only moves the record where its weight is EARNED (D3), so give the cell an earned w*.
    row = _sim_opposes_row()
    ctx = _ctx()
    cell = dr._calibration_cell(row, ctx.now)
    ctx.calibration = {cell: {"cell": cell, "w": 0.5, "ci95": [0.3, 0.7], "verdict": "overconfident", "games": 90}}
    recs = dr.build_records([row], ctx)
    result = da.build_agreement(recs, [row], {}, [])
    board = result["by_destination"]["board"]
    assert board["disagree"] == 1 and board["causes"].get("sim_opposes") == 1
    assert result["forks"]["F3_suggested_sim_opposes"]["count"] == 1
    assert result["forks"]["F1_suggested_negative_at_venue_price"]["kalshi"]["count"] == 1


def test_unearned_sim_no_longer_overrules_the_board_but_the_fork_is_still_counted():
    # D3: with no earned weight the record follows the market and agrees with the board's
    # Suggested; the F3 fork (a Suggested side the sim opposes) is still counted as information.
    row = _sim_opposes_row()
    recs = dr.build_records([row], _ctx())
    assert recs[0].blend.w_model == 0.0 and recs[0].blend.w_model_source == "default_unmeasured"
    result = da.build_agreement(recs, [row], {}, [])
    assert result["by_destination"]["board"]["disagree"] == 0
    assert result["forks"]["F3_suggested_sim_opposes"]["count"] == 1


def test_live_plan_size_disagreement_names_full_kelly_band():
    row = _row(quote={"book_prices": {"draftkings": 105, "kalshi": 110}})
    recs = dr.build_records([row], _ctx())
    position = {**{k: row[k] for k in ("sport", "event_id", "market", "segment", "side", "line")},
                "player_name": None, "stake_dollars": 9.37,
                "stake_band": {"band_stake_dollars": 9.37, "full_kelly": 0.04}, "sizing": {}}
    plans = {"live:kalshi": {"positions": [position]}}
    result = da.build_agreement(recs, [row], plans, [])
    live = result["by_destination"]["live:kalshi"]
    assert live["agree"] == 1 and live["size_compared"] == 1 and live["size_agree"] == 0
    assert "full_kelly_band" in live["size_causes"]


def test_live_orders_judged_against_the_record():
    good = _row(quote={"book_prices": {"draftkings": 105, "kalshi": 110}})
    bad = _row(event_id="ev2", quote={"book_prices": {"draftkings": 105, "kalshi": -300}})
    recs = dr.build_records([good, bad], _ctx())
    orders = [{"venue": "kalshi", "mode": "live", "idempotency_key": k, **{f: r[f] for f in ("sport", "event_id", "market", "segment", "side", "line")}}
              for k, r in (("o1", good), ("o2", bad))]
    out = {o["order_key"]: o for o in da.compare_orders({r.key: r for r in recs}, orders)}
    assert out["o1"]["agree"] is True
    assert out["o2"]["agree"] is False and "gate:price_band" in out["o2"]["causes"]


def test_daily_report_judges_each_order_once(tmp_path):
    rows = [_row()]
    recs = dr.build_records(rows, _ctx())
    order = {"venue": "kalshi", "idempotency_key": "o1", "submitted_at": "2026-10-23T12:00:00Z",
             **{f: rows[0][f] for f in ("sport", "event_id", "market", "segment", "side", "line")}}
    for _ in range(3):
        da.record_build_agreement(DATE, recs, rows, {}, [order], build_id="b", root=tmp_path)
    summary = json.loads(da.report_paths(DATE, tmp_path)[0].read_text(encoding="utf-8"))
    assert summary["builds"] == 3 and summary["live_orders"]["count"] == 1


# ----------------------------------------------------------------------------- the checklist gates


def test_checklist_alarms_when_an_input_is_unfed_and_passes_when_fed(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("drc", REPO / "scripts" / "decision_record_checklist.py")
    drc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drc)
    rows = [_row(event_id=f"e{i}", line=200.5 + i) for i in range(6)]
    rows += [_row(event_id="p", kind="prop", market="player_points", player_name="P", line=20.5,
                  price_source="kalshi", venue_ref="KXNBAPTS-99OCT23AWYHOM-P20")]
    rows += [_row(event_id="n", model_probability_cal=None, projection=None, model_edge_pct=None)]
    ctx = _ctx()
    cell = dr._calibration_cell(rows[0], ctx.now)
    ctx.calibration = {cell: {"cell": cell, "w": 0.4, "ci95": [0.2, 0.6], "verdict": "overconfident", "games": 80}}
    ctx.form_index = {dr.line_key(rows[6]): {"form5": {"games": 5, "hits": 3}, "form10": {"games": 10, "hits": 6}, "sheet": "s"}}
    recs = dr.build_records(rows, ctx)
    payload = {"records": [dr._compact(r) for r in recs],
               "context": {"calibration_cells": 1, "form_lines": 1, "paper_bankroll": 1000.0}}
    fed = drc.run(payload)
    assert fed["alarms"] == [], fed["alarms"]
    unfed = drc.run({**payload, "context": {"calibration_cells": 0, "form_lines": 1, "paper_bankroll": 1000.0}})
    assert "context.calibration_cells" in unfed["alarms"]
    field_names = {r["field"] for r in fed["fields"]}
    import dataclasses

    assert {f"ModelView.{f.name}" for f in dataclasses.fields(dr.ModelView)} <= field_names
