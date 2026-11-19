"""The suggested-set grader: which row it grades, the numbers it reports, its windows, phases and state."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    source = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_test_{name}", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


G = _load("grade_suggested_set")
NOW = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)
KEY_A = "evtA|player_points|jane doe|full|over|19.5"
KEY_B = "evtB|totals||full|under|221.5"


def _central_date(ct):
    return str(ct)[:10] if ct else None


def _record(k, t, *, sport="nba", ct="2026-11-10T00:30:00Z", gs="pregame", sg=True, **extra):
    base = {"k": k, "t": t, "sport": sport, "ct": ct, "gs": gs, "sg": sg, "px": -110, "fp": 0.5,
            "ht": "Home", "at": "Away", "ln": "opportunity", "eb": "market_fair"}
    base.update(extra)
    return base


def _row(day, *, sport="nba", game="g1", pnl=1.0, y=1.0, price=100.0, p_market=0.5, p_model=None, eb="market_fair",
         market="player_points", phase="pregame"):
    return {"date": day, "sport": sport, "game": f"{sport}|{game}", "pnl": pnl, "y": y, "price": price,
            "p_market": p_market, "p_model": p_model, "eb": eb, "market": market, "phase": phase}


# --------------------------------------------------------------------------- the source


def _write_part(root: Path, name: str, records):
    folder = root / "reports" / "intelligence" / "opportunity_population"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("".join(
        (r if isinstance(r, str) else json.dumps(r, separators=(",", ":"))) + "\n" for r in records), encoding="utf-8")


def test_scan_keeps_only_suggested_records_and_counts_what_it_read(tmp_path):
    _write_part(tmp_path, "2026-11-10__nba__part000.jsonl", [
        _record(KEY_A, "2026-11-09T12:00:00Z", sg=True),
        _record(KEY_B, "2026-11-09T12:00:00Z", sg=False),
        _record(KEY_B, "2026-11-09T12:05:00Z", sg=None),
        '{"k": "torn',
    ])
    _write_part(tmp_path, "2026-11-11__nhl__part000.jsonl", [_record(KEY_B, "2026-11-10T12:00:00Z", sport="nhl")])
    _write_part(tmp_path, "2026-11-12__nhl__part000.jsonl", [_record(KEY_B, "2026-11-11T12:00:00Z", sport="nhl")])
    (tmp_path / "reports/intelligence/opportunity_population/2026-11-10__nba.keys").write_text("x\n")

    files = G.recorder_files(tmp_path, first="2026-11-10", last="2026-11-11")
    assert [(d, s) for d, s, _ in files] == [("2026-11-10", "nba"), ("2026-11-11", "nhl")]
    records, summary = G.scan_suggested(files)
    assert [(r["k"], r["sport"]) for r in records] == [(KEY_A, "nba"), (KEY_B, "nhl")]
    assert summary["records_scanned"] == 5
    assert summary["sg_records"] == 2
    assert summary["by_file_date"]["2026-11-10"] == {"records": 4, "sg_true": 1}
    assert summary["first_file_date"] == "2026-11-10" and summary["last_file_date"] == "2026-11-11"


def test_names_are_lent_across_sightings_of_one_event():
    named = _record(KEY_A, "2026-11-09T13:00:00Z")
    bare = _record("evtA|player_rebounds|jane doe|full|over|7.5", "2026-11-09T12:00:00Z", ht=None, at=None)
    assert G.lend_names([named, bare]) == 1
    assert (bare["ht"], bare["at"]) == ("Home", "Away")


# --------------------------------------------------------------------------- the row graded


def _grade_all(chosen, state=None, *, today="2026-11-18", results=None):
    state = state if state is not None else G.empty_state("sig", {"nba": "espn/1"})
    calls = []

    def grade_record(record):
        calls.append(record)
        outcome = (results or {}).get(record["k"], "win")
        if outcome in ("win", "loss"):
            return {"date": _central_date(record["ct"]), "sport": record["sport"], "game": "nba|g", "t": record["t"],
                    "k": record["k"], "y": 1.0 if outcome == "win" else 0.0, "pnl": 1.0 if outcome == "win" else -1.0,
                    "price": 100.0, "p_market": 0.5, "p_model": None, "bp": {"a": 1}}, None
        return None, outcome

    counts = G.grade_suggested(chosen, state, today=today, grade_record=grade_record, central_date=_central_date)
    return state, counts, calls


def test_the_earliest_suggested_sighting_is_graded_per_identity_and_phase():
    records = [
        _record(KEY_A, "2026-11-09T15:00:00Z"),
        _record(KEY_A, "2026-11-09T12:00:00Z"),
        _record(KEY_A, "2026-11-10T00:45:00Z", gs="live"),
    ]
    chosen = G.srb.earliest_per_phase(records)
    state, counts, calls = _grade_all(chosen)
    assert sorted(r["t"] for r in calls) == ["2026-11-09T12:00:00Z", "2026-11-10T00:45:00Z"]
    assert counts["counts"]["graded_now"] == 2
    entry = state["graded"][f"nba|{KEY_A}|pregame"]
    assert entry["t"] == "2026-11-09T12:00:00Z"
    assert "bp" not in entry["row"] and entry["row"]["p_market"] == 0.5


def test_a_rerun_reuses_graded_rows_and_grades_only_what_is_new():
    first = [_record(KEY_A, "2026-11-09T12:00:00Z")]
    state, _, _ = _grade_all(first)
    second = first + [_record(KEY_B, "2026-11-09T12:00:00Z")]
    state, counts, calls = _grade_all(second, state)
    assert [r["k"] for r in calls] == [KEY_B]
    assert counts["counts"]["reused"] == 1 and counts["counts"]["graded_now"] == 1
    # An earlier suggested sighting found later replaces the graded one: it is graded again.
    earlier = [_record(KEY_A, "2026-11-09T09:00:00Z"), _record(KEY_B, "2026-11-09T12:00:00Z")]
    state, counts, calls = _grade_all(earlier, state)
    assert [r["t"] for r in calls] == ["2026-11-09T09:00:00Z"]


def test_recent_ungraded_lines_are_retried_and_old_ones_are_settled_as_ungradable():
    recent = _record(KEY_A, "2026-11-16T12:00:00Z", ct="2026-11-16T23:00:00Z")
    old = _record(KEY_B, "2026-11-01T12:00:00Z", ct="2026-11-01T23:00:00Z")
    results = {KEY_A: "extra_box_score_unavailable", KEY_B: "extra_player_not_found"}
    state, counts, _ = _grade_all([recent, old], results=results)
    assert counts["counts"] == {"pending": 1, "ungradable_now": 1, "graded_total": 0}
    assert list(state["ungradable"]) == [f"nba|{KEY_B}|pregame"]
    state, counts, calls = _grade_all([recent, old], state, results=results)
    assert [r["k"] for r in calls] == [KEY_A]
    assert counts["ungraded_reasons"] == {"extra_box_score_unavailable": 1, "extra_player_not_found": 1}


def test_not_yet_is_always_pending():
    future = _record(KEY_A, "2026-11-18T12:00:00Z", ct="2026-11-19T00:00:00Z")
    state, counts, _ = _grade_all([future], results={KEY_A: "not_yet"})
    assert counts["counts"]["pending"] == 1 and not state["ungradable"]


def test_state_resets_on_the_scorecards_grader_signature_and_per_sport_version():
    saved = G.empty_state("sig", {"nba": "espn/1", "nhl": "nhl/1"})
    saved["graded"] = {f"nba|{KEY_A}|pregame": {"t": "x", "row": {}}, f"nhl|{KEY_B}|pregame": {"t": "y", "row": {}}}
    same, status = G.load_state(json.loads(json.dumps(saved)), "sig", {"nba": "espn/1", "nhl": "nhl/1"}, now=NOW)
    assert status == "loaded" and len(same["graded"]) == 2
    one, status = G.load_state(json.loads(json.dumps(saved)), "sig", {"nba": "espn/1", "nhl": "nhl/2"}, now=NOW)
    assert status == "reset:nhl" and list(one["graded"]) == [f"nba|{KEY_A}|pregame"]
    none, status = G.load_state(json.loads(json.dumps(saved)), "sig2", {"nba": "espn/1", "nhl": "nhl/1"}, now=NOW)
    assert status == "reset_all" and not none["graded"] and none["resets"][-1]["scope"] == "all"
    assert G.load_state(None, "sig", {}, now=NOW)[1] == "fresh"


# --------------------------------------------------------------------------- the numbers


def test_summarise_uses_the_optimizers_definitions():
    rows = [
        _row("2026-11-10", game="g1", pnl=1.0, y=1.0, price=100.0, p_market=0.52, p_model=0.56, eb="model_edge"),
        _row("2026-11-10", game="g1", pnl=-1.0, y=0.0, price=-110.0, p_market=0.5, p_model=0.6, eb="market_fair"),
        _row("2026-11-10", game="g2", pnl=-1.0, y=0.0, price=-110.0, p_market=0.5),
        _row("2026-11-10", game="g3", pnl=None, y=1.0, price=None),
    ]
    out = G.summarise(rows, row_id="x", resamples=200)
    assert out["bets"] == 3 and out["games"] == 2 and out["wins"] == 1
    assert out["hit_pct"] == pytest.approx(33.3)
    assert out["units"] == -1.0
    assert out["roi_pct"] == pytest.approx(-33.33, abs=0.01)
    dec = 1 + 100 / 110
    assert out["market_ev_pct"] == pytest.approx(100 * ((0.52 * 2 - 1) + 2 * (0.5 * dec - 1)) / 3, abs=0.01)
    # The model's EV only where the board ranked on the model (eb in MODEL_EV_BASES).
    assert out["model_bets"] == 1
    assert out["predicted_ev_pct"] == pytest.approx(100 * (0.56 * 2 - 1), abs=0.01)
    assert out["model_roi_pct"] == 100.0
    # The sim's EV wherever it priced the line, whatever the board ranked on -- a separate column.
    assert out["sim_bets"] == 2
    assert out["sim_ev_pct"] == pytest.approx(100 * ((0.56 * 2 - 1) + (0.6 * dec - 1)) / 2, abs=0.01)
    assert out["sim_roi_pct"] == 0.0
    assert out["roi_ci95_lo_pct"] <= out["roi_pct"] <= out["roi_ci95_hi_pct"]


def test_ladders_once_counts_each_alt_ladder_at_its_rungs_mean():
    def rung(market, line, pnl, player="jane doe"):
        return dict(_row("2026-11-10", pnl=pnl, y=1.0 if pnl > 0 else 0.0, market=market),
                    segment="full", player=player, side="over", line=line)

    rows = [rung("player_points", 19.5, 1.0), rung("player_points_alternate", 24.5, -1.0),
            rung("player_points_alternate", 29.5, -1.0), rung("player_points", 19.5, -1.0, player="john roe")]
    out = G.summarise(rows, row_id="x", resamples=50)
    assert out["bets"] == 4 and out["roi_pct"] == -50.0
    # jane doe's three rungs are one ladder at mean -1/3; john roe's one rung is another at -1.
    assert out["ladders"] == 2
    assert out["ladder_roi_pct"] == pytest.approx(100 * (-1 / 3 - 1) / 2, abs=0.01)


def test_a_market_ranked_set_has_no_predicted_ev_but_keeps_the_sims():
    rows = [_row("2026-11-10", p_model=0.55, eb="market_fair"), _row("2026-11-10", game="g2", pnl=-1.0, y=0.0)]
    out = G.summarise(rows, row_id="x", resamples=50)
    assert out["predicted_ev_pct"] is None and out["model_bets"] == 0
    assert out["sim_bets"] == 1 and out["sim_ev_pct"] == pytest.approx(10.0)
    assert G.summarise([_row("2026-11-10", pnl=None)], row_id="x", resamples=10) is None


def test_the_interval_does_not_depend_on_row_order():
    rows = [_row("2026-11-10", game=f"g{i}", pnl=(1.0 if i % 3 else -1.0), y=(1.0 if i % 3 else 0.0)) for i in range(30)]
    forward = G.summarise(rows, row_id="x", resamples=300)
    backward = G.summarise(list(reversed(rows)), row_id="x", resamples=300)
    assert (forward["roi_ci95_lo_pct"], forward["roi_ci95_hi_pct"]) == (backward["roi_ci95_lo_pct"],
                                                                         backward["roi_ci95_hi_pct"])


def test_the_interval_resamples_games_and_is_seeded():
    per_game = [(3.0, 4), (-2.0, 2), (-1.0, 1), (0.5, 3)]
    a = G.roi_interval(per_game, resamples=500, seed=7)
    assert a == G.roi_interval(per_game, resamples=500, seed=7)
    assert a[0] < 0.5 / 10 < a[1]
    assert G.roi_interval([(1.0, 1)], resamples=500, seed=7) is None


def test_the_rolling_window_is_the_scorecards_and_a_regular_sport_row_has_the_monitors_id():
    graded = [_row("2026-10-21", game="old"), _row("2026-10-22", game="first"),
              _row("2026-11-18", game="yesterday"), _row("2026-11-19", game="future")]
    rows = G.build_rows(graded, today="2026-11-19", resamples=50)
    rolling = {r["id"]: r for r in rows if r["window"] == "28d" and r["scope"] == "sport"}
    latest = rolling["2026-11-19|nba|Suggested by the board"]
    # Day D covers kickoffs [D-28, D-1]: 10-22..11-18. 10-21 is out; 11-19 (today) is never graded.
    assert (latest["window_first"], latest["window_last"]) == ("2026-10-22", "2026-11-18")
    assert latest["games"] == 2 and latest["sport"] == "NBA" and latest["set"] == "Suggested by the board"
    daily = [r for r in rows if r["window"] == "1d" and r["scope"] == "sport"]
    assert [r["id"] for r in daily] == ["2026-10-21|nba|Suggested by the board|1d",
                                        "2026-10-22|nba|Suggested by the board|1d",
                                        "2026-11-18|nba|Suggested by the board|1d"]
    assert {"id", "day", "sport", "set", "bets", "games", "roi_pct", "predicted_ev_pct",
            "market_ev_pct"} <= set(latest)


def test_season_phases_are_never_pooled_and_all_sports_is_regular_season_only():
    graded = [_row("2026-10-15", game="pre"),  # NBA preseason
              _row("2026-10-25", game="reg"),  # NBA regular season
              _row("2026-10-25", sport="mlb", game="ws")]  # MLB postseason
    rows = G.build_rows(graded, today="2026-10-26", resamples=50)
    latest = {r["id"]: r for r in rows if r["day"] == "2026-10-26" and r["window"] == "28d"}
    assert latest["2026-10-26|nba|Suggested by the board"]["bets"] == 1
    assert latest["2026-10-26|nba|Suggested by the board|preseason"]["bets"] == 1
    assert latest["2026-10-26|mlb|Suggested by the board|postseason"]["bets"] == 1
    everything = latest["2026-10-26|all|Suggested by the board"]
    assert everything["bets"] == 1 and everything["season_phase"] == "regular" and everything["sport"] == "All sports"


def test_market_and_pregame_live_cuts_are_their_own_rows():
    graded = [_row("2026-11-10", market="player_points"), _row("2026-11-10", market="totals", game="g2", phase="live")]
    rows = G.build_rows(graded, today="2026-11-11", resamples=50)
    ids = {r["id"] for r in rows if r["day"] == "2026-11-11"}
    assert "2026-11-11|nba|Suggested by the board|market:totals" in ids
    assert "2026-11-11|nba|Suggested by the board|state:live" in ids
    market_row = next(r for r in rows if r["id"] == "2026-11-11|nba|Suggested by the board|market:totals")
    assert market_row["market"] == "totals" and market_row["scope"] == "market" and market_row["bets"] == 1


# --------------------------------------------------------------------------- the grader is the scorecard's


def test_graded_row_carries_the_graders_probabilities_and_key():
    record = _record(KEY_B, "2026-11-09T12:00:00Z")
    graded = {"date": "2026-11-09", "sport": "nba", "game": "nba|evtB", "y": 1.0, "pnl": 0.91,
              "p_market": 0.48, "p_model": 0.51, "price": -110.0}
    row = G.srb.graded_row(record, graded)
    assert (row["k"], row["p_market"], row["p_model"], row["price"]) == (KEY_B, 0.48, 0.51, -110.0)


def test_make_grade_record_runs_the_record_through_grade_rows():
    seen = []

    def fake_population_grade(records, chips_by_date, named, *, today):
        seen.append((list(records), dict(chips_by_date), today))
        record = records[0]
        if record["k"] == KEY_B:
            return [], {"extra_player_not_found": 1}
        return [{"date": "2026-11-10", "sport": "nba", "game": "nba|evtA", "y": 1.0, "pnl": 1.0,
                 "p_market": 0.5, "p_model": None, "price": 100.0}], {}

    bs = SimpleNamespace(SCORECARD=SimpleNamespace(central_date=_central_date))
    grade_record = G.make_grade_record(bs, grade=fake_population_grade, chips_for=lambda day: [{"chip": day}],
                                       today="2026-11-18")
    row, reason = grade_record(_record(KEY_A, "2026-11-09T12:00:00Z"))
    assert reason is None and row["k"] == KEY_A and row["price"] == 100.0
    assert seen[0][1] == {"2026-11-10": [{"chip": "2026-11-10"}]} and seen[0][2] == "2026-11-18"
    row, reason = grade_record(_record(KEY_B, "2026-11-09T12:00:00Z"))
    assert row is None and reason == "extra_player_not_found"
    row, reason = grade_record(_record(KEY_A, "2026-11-18T12:00:00Z", ct="2026-11-19T00:00:00Z"))
    assert row is None and reason == "not_yet"


def test_prune_deletes_only_its_own_old_dated_copies(tmp_path):
    for name in ("suggested_set_20261101.json", "suggested_set_20261104.json", "suggested_set_20261118.json",
                 "suggested_set_latest.json", "suggested_set_state.json", "other_20261101.json"):
        (tmp_path / name).write_text("{}")
    assert G.prune_dated(tmp_path, "2026-11-18") == ["suggested_set_20261101.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "other_20261101.json", "suggested_set_20261104.json", "suggested_set_20261118.json",
        "suggested_set_latest.json", "suggested_set_state.json"]


# --------------------------------------------------------------------------- refusals


def test_main_refuses_without_a_data_root(monkeypatch):
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
    assert G.main([]) == 2


def test_main_refuses_when_no_recorder_file_is_read(tmp_path):
    assert G.main(["--data-root", str(tmp_path)]) == 3
