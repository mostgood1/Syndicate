"""The research harness scores totals/spreads as POINT FORECASTS against nulls
that are not a constant 0.50.

Until 2026-09-15 `point_forecast_side` existed but `main()` never called it, so
every totals/spreads run printed REFUSED. The reachability test comes first; the
null tests encode the two artifacts a 0.50 null let through (always-over, and a
scoreboard-follower).
"""
import importlib.util
import json
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "bucket_realised_performance.py"


@pytest.fixture(scope="module")
def brp():
    spec = importlib.util.spec_from_file_location("brp_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(pk, market, line, mean, *, score=(0, 0), mp=0.5, band_progress=0.1,
         stamp="2026-09-10T20:00:00Z", date="2026-09-10", segment="full"):
    col = "model_total_mean" if market.startswith("totals") else "model_margin_mean"
    return {"game_pk": pk, "market": market, "line": line, col: mean,
            "away_score": score[0], "home_score": score[1], "market_fair_prob": mp,
            "progress_fraction": band_progress, "recorded_at": stamp, "date": date,
            "segment": segment, "game_state": "live"}


def test_main_reaches_the_point_forecast_scorer(brp, tmp_path, monkeypatch, capsys):
    """off != on: totals must come out as a scored bucket, not REFUSED."""
    finals, rows = {}, []
    for i in range(40):
        pk = str(1000 + i)
        away, home = (5, 5) if i % 2 == 0 else (3, 3)      # totals 10 / 6
        finals[pk] = (away, home)
        # the line must VARY and track the total, or the line gate has no reading
        rows.append(_row(pk, "totals", 9.0 if i % 2 == 0 else 7.0, 9.5 if i % 2 == 0 else 6.5,
                         date=f"2026-09-{10 + i % 5:02d}",
                         mp=0.6 if i % 2 == 0 else 0.4))
    replay = tmp_path / "rows.jsonl"
    replay.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setattr(brp, "finals_for", lambda dates: finals)
    out = tmp_path / "out.json"

    assert brp.main(["--rows-jsonl", str(replay), "--json", str(out)]) == 0

    text = capsys.readouterr().out
    assert "USABLE (point forecast)" in text
    scored = json.loads(out.read_text(encoding="utf-8"))
    assert [r["market"] for r in scored] == ["totals"]
    assert scored[0]["scoring"] == "point_forecast"
    assert scored[0]["n_games"] == 40
    assert scored[0]["won_pct"] == 100.0       # a perfect forecaster on this fixture
    assert set(scored[0]["nulls"]) == {"coin_flip", "side_base_rate", "scoreboard", "market_price"}


def test_always_over_scores_zero_against_side_base_rate(brp):
    """The 09-15 totals artifact: backs over every game, overs land 62%."""
    vals = []
    for i in range(100):
        over_won = i < 62
        vals.append({"kind": "point", "won": over_won, "backs_first": True,
                     "first_won": over_won, "scoreboard": 0.5, "implied": 0.5})
    s = brp.score_bucket(vals)
    assert s["nulls"]["coin_flip"]["edge_pp"] == pytest.approx(12.0)
    assert s["nulls"]["side_base_rate"]["edge_pp"] == pytest.approx(0.0)
    assert s["edge_pp"] <= 0.0 + 1e-9
    assert s["binding_null"] in {"side_base_rate", "scoreboard", "market_price"}


def test_scoreboard_follower_is_not_an_edge(brp):
    """The 09-15 spreads q4_late artifact: the model backs the current cover, and
    the current cover wins more often than the model."""
    vals = []
    for i in range(54):
        rule_won = i < 39            # 72%
        model_won = i < 37           # 68.5%
        vals.append({"kind": "point", "won": model_won, "backs_first": i % 2 == 0,
                     "first_won": (i % 2 == 0) == model_won,
                     "scoreboard": 1.0 if rule_won else 0.0, "implied": 0.67})
    s = brp.score_bucket(vals)
    assert s["nulls"]["coin_flip"]["edge_pp"] > 15
    assert s["binding_null"] == "scoreboard"
    assert s["edge_pp"] < 0


def test_probability_buckets_keep_the_market_null_only(brp):
    vals = [{"kind": "probability", "won": i < 55, "implied": 0.5} for i in range(100)]
    s = brp.score_bucket(vals)
    assert set(s["nulls"]) == {"market_price"}
    assert s["edge_pp"] == pytest.approx(5.0)
    # binomial se, as before this change: sqrt(.55*.45/100)
    assert s["se"] == pytest.approx(4.975, abs=0.01)


def test_entry_resolves_from_point_forecast_side_not_the_price(brp):
    """A price that says the opposite must not change what a hit is."""
    rec = _row("g", "totals", 8.5, 10.0, score=(1, 2), mp=0.05)
    entry, reason = brp.point_forecast_entry(rec, (5, 5))
    assert reason is None
    assert entry["won"] is True and entry["backs_first"] is True
    assert entry["implied"] == pytest.approx(0.05)
    # current total 3 < 8.5 -> rule backs under, and the over landed
    assert entry["scoreboard"] == 0.0


def test_spreads_scoreboard_uses_the_current_margin(brp):
    rec = _row("g", "spreads", 1.5, 3.0, score=(1, 5), mp=0.8)   # home up 4
    entry, _ = brp.point_forecast_entry(rec, (2, 6))              # home won by 4
    assert entry["won"] is True and entry["scoreboard"] == 1.0


@pytest.mark.parametrize("change, reason", [
    ({"segment": "first5"}, "segment_not_full_game"),
    ({"model_total_mean": None}, "no_mean_or_push_or_no_lean"),
    ({"away_score": None}, "no_current_score"),
    ({"market_fair_prob": None}, "no_market_price"),
])
def test_missing_null_inputs_skip_by_name(brp, change, reason):
    rec = {**_row("g", "totals", 8.5, 10.0, score=(1, 2)), **change}
    entry, got = brp.point_forecast_entry(rec, (5, 5))
    assert entry is None and got == reason


def test_line_gate_refuses_a_flipped_frame(brp):
    finals, rows = {}, []
    for i in range(40):
        pk = str(i)
        margin = (i % 7) - 3
        finals[pk] = (5, 5 + margin)
        rows.append(_row(pk, "spreads", -margin + 0.5, 0.0))     # line anti-tracks
    corr, n = brp.line_convention_gate(rows, finals, "spreads", 30)
    assert n == 40 and corr < 0


def test_reversed_price_orientation_is_detected(brp):
    ents = [{"first_won": i < 50, "first_price": 0.3 if i < 50 else 0.7} for i in range(100)]
    assert brp.price_points_the_right_way(ents) is False
    ents = [{"first_won": i < 50, "first_price": 0.7 if i < 50 else 0.3} for i in range(100)]
    assert brp.price_points_the_right_way(ents) is True


def test_concentration_script_imports_still_resolve(brp):
    for name in ("band_for", "finals_for", "ledger_rows", "resolve", "secret", "point_forecast_side"):
        assert callable(getattr(brp, name))
