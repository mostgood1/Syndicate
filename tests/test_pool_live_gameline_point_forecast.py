"""The totals/spreads (point-forecast) and first5 sections of the trend tools.

WHY THIS FILE EXISTS. The scorer has scored totals and spreads on every board
build since 2026-09-08 and the history has retained it since 2026-09-24, yet
`pool_live_gameline_trend.py` pooled only the h2h Brier and the nightly
snapshot labelled every non-h2h market `(refused)`. On 2026-09-28 a session
read that label and told the user totals and spreads were not scored. These
tests hold the parts that make the new section honest: games are the unit, the
board capture beats a re-score on a tie, a date with outcomes and no data is
NAMED, and an empty off-day board is not reported as a disabled scorer.
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pool = _load("pool_live_gameline_trend_pf", "scripts/pool_live_gameline_trend.py")


def _pf(games, n, model_mae, line_mae, hit=0.6, se=12.0):
    return {"games": games, "n": n, "model_mae": model_mae, "line_mae": line_mae,
            "model_minus_line_mae": model_mae - line_mae, "hit_rate": hit,
            "se_pp_on_games": se}


def _row(date, games, *, totals=None, spreads=None, rescored=False, first5=None,
         cut="fresh_quotes_only", captured="2026-09-20T04:00:00"):
    row = {"date": date, "games_with_outcome": games, "captured_at": captured,
           "scored_markets": ["h2h"], "scorer_contract": 3, "point_forecast": {}}
    if totals is not None:
        row["point_forecast"]["totals"] = {cut: totals}
    if spreads is not None:
        row["point_forecast"]["spreads"] = {cut: spreads}
    if rescored:
        row["rescored_from_ledger"] = True
    if first5 is not None:
        g, model, market, n = first5
        row["segments"] = {"by_segment": {"first5": {
            "games_with_outcome": g,
            "all_records": {"model_paired": {"brier": model, "n": n},
                            "market": {"brier": market, "n": n}}}}}
    return row


def test_the_point_forecast_pool_is_GAME_weighted_not_row_weighted():
    """A 2-game date with 1,000 rows must not outweigh a 10-game date with 50."""
    rows = [_row("2026-09-10", 2, totals=_pf(2, 1000, 3.0, 2.0)),
            _row("2026-09-11", 10, totals=_pf(10, 50, 2.0, 2.5))]
    res = pool.pool_point_forecast(rows, "totals", "fresh_quotes_only")
    assert res["games"] == 12 and res["dates"] == 2
    assert res["model_mae"] == pytest.approx((3.0 * 2 + 2.0 * 10) / 12)
    assert res["line_mae"] == pytest.approx((2.0 * 2 + 2.5 * 10) / 12)
    assert res["model_minus_line_mae"] == pytest.approx(res["model_mae"] - res["line_mae"])


def test_per_date_the_fullest_capture_wins_and_a_BOARD_capture_wins_a_tie():
    board = _row("2026-09-10", 10, totals=_pf(10, 300, 2.0, 2.2))
    rescore_same = _row("2026-09-10", 10, totals=_pf(10, 300, 9.0, 9.0), rescored=True)
    rescore_fuller = _row("2026-09-11", 11, totals=_pf(11, 300, 2.5, 2.1), rescored=True)
    board_thinner = _row("2026-09-11", 9, totals=_pf(9, 300, 1.0, 1.0))
    best = pool.best_pf_per_date([rescore_same, board, board_thinner, rescore_fuller],
                                 "totals", "fresh_quotes_only")
    assert best["2026-09-10"] is board
    assert best["2026-09-11"] is rescore_fuller


def test_a_date_with_outcomes_and_no_point_forecast_is_NAMED():
    """09-09's full-game totals/spreads rows never reached the ledger (126 h2h
    rows, 0 totals/spreads). It must print as a gap, never vanish."""
    rows = [_row("2026-09-08", 14, totals=_pf(14, 393, 2.6, 2.2)),
            _row("2026-09-09", 15),
            _row("2026-09-10", 4, totals=_pf(4, 127, 2.3, 2.7))]
    assert pool.pf_coverage_gap(rows, "totals", "fresh_quotes_only") == [("2026-09-09", 15)]


def test_dates_before_the_family_existed_are_not_a_gap():
    """Ledger v5 (the model means) shipped 2026-09-06 late; earlier dates are
    structurally without the family, which is not a coverage gap."""
    rows = [_row("2026-09-01", 14), _row("2026-09-07", 11, totals=_pf(11, 365, 2.2, 2.1))]
    assert pool.pf_coverage_gap(rows, "totals", "fresh_quotes_only") == []


def test_first5_h2h_pools_the_PAIRED_brier_by_games():
    rows = [_row("2026-09-08", 12, first5=(12, 0.14, 0.13, 238), rescored=True),
            _row("2026-09-09", 14, first5=(14, 0.17, 0.19, 300), rescored=True)]
    res = pool.pool_segment_h2h(rows, "first5")
    assert res["games"] == 26
    assert res["model"] == pytest.approx((0.14 * 12 + 0.17 * 14) / 26)
    assert res["diff"] == pytest.approx(res["model"] - res["market"])


def test_the_main_report_prints_the_new_sections_and_a_stale_family_fails(tmp_path, capsys):
    hist = tmp_path / "history.jsonl"
    rows = [_row("2026-09-10", 4, totals=_pf(4, 127, 2.3, 2.7), spreads=_pf(4, 135, 2.4, 2.7)),
            _row("2026-09-11", 15)]            # newest date with outcomes, no families
    for r in rows:
        r["fresh_quotes_only"] = {"model": {"brier": 0.2, "n": 5}, "market": {"brier": 0.2, "n": 5},
                                  "model_paired": {"brier": 0.2, "n": 5},
                                  "model_minus_market_brier": 0.0}
    hist.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    rc = pool.main(["--history", str(hist), "--cut", "fresh_quotes_only", "--era", "post-fix"])
    out = capsys.readouterr().out
    assert "=== point-forecast | totals" in out and "=== point-forecast | spreads" in out
    assert "STALE" in out
    assert rc == 3


def test_the_real_history_carries_the_backfill_when_present():
    """Guards the 2026-09-28 backfill: 09-07..09-27 point-forecast dates and
    the first5 re-scores. Skips when the history is absent (worktrees)."""
    hist = _ROOT / pool.DEFAULT_HISTORY
    if not hist.exists():
        pytest.skip("history.jsonl not present")
    rows = [r for r in pool.load(str(hist)) if pool.row_era(r) == pool.POST]
    res = pool.pool_point_forecast(rows, "spreads", "fresh_quotes_only")
    if res["dates"] < 20:
        pytest.skip("history predates the 2026-09-28 backfill")
    assert res["games"] >= 240
    assert "2026-09-09" in {d for d, _ in pool.pf_coverage_gap(rows, "spreads", "fresh_quotes_only")}


# --- the nightly snapshot ---------------------------------------------------

snap = _load("snapshot_lgs_pf", "scripts/snapshot_live_gameline_score.py")


def _run(served, tmp_path, argv_extra=()):
    out = tmp_path / "history.jsonl"
    snap.fetch = lambda *a, **k: served  # noqa: ARG005
    argv = sys.argv
    sys.argv = ["snapshot", "--sport", "mlb", "--out", str(out), *argv_extra]
    try:
        rc = snap.main()
    finally:
        sys.argv = argv
    rows = [json.loads(x) for x in io.open(out, encoding="utf-8")] if out.exists() else []
    return rc, rows


def test_an_empty_off_day_board_is_NO_SLATE_not_a_disabled_scorer(tmp_path, capsys):
    """2026-09-28, between the regular season and the Wild Card round: zero
    rows and no score block. It exited 3 ("a REAL FINDING") before this."""
    served = {"date": "2026-09-28", "ok": True, "rows": [], "total_rows": 0, "markets": []}
    rc, rows = _run(served, tmp_path)
    assert rc == 7 and rows == []
    assert "NO_SLATE" in capsys.readouterr().out


def test_a_board_WITH_rows_and_no_score_block_is_still_exit_3(tmp_path, capsys):
    served = {"date": "2026-09-29", "ok": True, "rows": [{"event_id": "e"}], "total_rows": 1}
    rc, rows = _run(served, tmp_path)
    assert rc == 3 and rows == []
    assert "SCORER_DISABLED" in capsys.readouterr().out


def test_the_market_mix_labels_how_each_market_was_scored(tmp_path, capsys):
    served = {"date": "2026-09-27", "generated_at": "2026-09-27T23:00:00+00:00",
              "live_gameline_score": {
                  "enabled": True, "games_with_outcome": 14, "records_considered": 10,
                  "scored_markets": ["h2h"], "point_forecast_markets": ["spreads", "totals"],
                  "records_by_market": {"h2h": 184, "spreads": 399, "totals_alt": 3, "weird": 1},
                  "point_forecast": {"totals": {"fresh_quotes_only": _pf(14, 363, 2.25, 2.09)}},
                  "segments": {"by_segment": {"first5": {
                      "games_with_outcome": 12,
                      "all_records": {"model_paired": {"brier": 0.11, "n": 176},
                                      "market": {"brier": 0.10, "n": 176},
                                      "model_minus_market_brier": 0.01}}}},
              }}
    rc, rows = _run(served, tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "(refused)" not in out
    assert "h2h=184(brier)" in out and "spreads=399(point-forecast)" in out
    assert "totals_alt=3(point-forecast)" in out and "weird=1(unscored)" in out
    assert "totals   point-forecast (fresh) games=14" in out
    assert "spreads  point-forecast (fresh) NO DATA" in out
    assert "segment first5 h2h" in out
    # RETAINED, not just printed: the shared allowlist carries `segments`.
    assert rows[-1]["segments"]["by_segment"]["first5"]["games_with_outcome"] == 12


def test_the_pool_is_ONE_sport_and_absent_sport_reads_as_mlb(tmp_path, capsys):
    """history.jsonl holds several sports (soccer/wnba since 2026-08-29, ncaaf
    from 2026-09-28) and every pool is per DATE, so a bigger soccer capture
    could otherwise stand in for an MLB date."""
    def with_cut(r, model):
        r["fresh_quotes_only"] = {"model": {"brier": model, "n": 5}, "market": {"brier": 0.2, "n": 5},
                                  "model_paired": {"brier": model, "n": 5},
                                  "model_minus_market_brier": model - 0.2}
        return r
    mlb_legacy = with_cut(_row("2026-09-10", 10), 0.10)                 # no `sport` key
    soccer = with_cut(dict(_row("2026-09-10", 40), sport="soccer"), 0.90)
    hist = tmp_path / "history.jsonl"
    hist.write_text("".join(json.dumps(r) + "\n" for r in (mlb_legacy, soccer)), encoding="utf-8")
    pool.main(["--history", str(hist), "--cut", "fresh_quotes_only", "--era", "post-fix",
               "--allow-stale-cut", "--json-out", str(tmp_path / "mlb.json")])
    mlb = json.loads((tmp_path / "mlb.json").read_text(encoding="utf-8"))
    assert mlb["post-fix"]["games"] == 10 and mlb["post-fix"]["model"] == pytest.approx(0.10)
    pool.main(["--history", str(hist), "--sport", "soccer", "--cut", "fresh_quotes_only",
               "--era", "post-fix", "--allow-stale-cut", "--json-out", str(tmp_path / "s.json")])
    soc = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert soc["post-fix"]["games"] == 40
    assert "segments" not in soc["point_forecast"]        # innings segments are MLB-only
    capsys.readouterr()


@pytest.mark.parametrize("sport, unit", [("mlb", "in runs;"), ("ncaaf", "in points;"),
                                         ("soccer", "in goals;"),
                                         ("cricket", "in the sport's scoring units;")])
def test_the_model_line_label_names_the_SPORTS_unit_not_always_runs(sport, unit, capsys):
    rows = [_row("2026-09-10", 4, totals=_pf(4, 127, 2.3, 2.7), spreads=_pf(4, 135, 2.4, 2.7))]
    pool.print_point_forecast(rows, "fresh_quotes_only", sport)
    out = capsys.readouterr().out
    assert out.count("model mean's error MINUS the line's, %s" % unit) == 2
    if sport != "mlb":
        assert "in runs" not in out
