"""Tests for the scorer-era split in `scripts/pool_live_gameline_trend.py`.

The load-bearing case is 2026-08-30 / 2026-08-31: rows with NO `scored_markets`
stamp that were nonetheless produced by the POST-fix scorer. Classifying them by
the stamp alone excluded them and halved the poolable sample, so the regression
these tests guard is a silent one -- the wrong answer is a smaller, plausible
number, not an error.
"""
import importlib.util
import json
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "pool_live_gameline_trend.py"
_spec = importlib.util.spec_from_file_location("pool_live_gameline_trend", _SRC)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def row(date, games, captured, *, stamped=False, model=0.2, market=0.25, n=100,
        market_n=None, cut="priceable_only"):
    payload = {
        "date": date,
        "games_with_outcome": games,
        "captured_at": captured,
        cut: {
            "model": {"brier": model, "n": n},
            "market": {"brier": market, "n": market_n if market_n is not None else n},
            "model_minus_market_brier": round(model - market, 5),
        },
    }
    if stamped:
        payload["scored_markets"] = ["h2h"]
    return payload


# --- era classification -----------------------------------------------------

def test_stamped_row_is_post_fix():
    assert mod.row_era(row("2026-09-02", 14, "2026-09-03T04:52:03", stamped=True)) == mod.POST


def test_unstamped_row_captured_AFTER_the_fix_is_post_fix():
    """The 08-30 / 08-31 case -- the whole point of this module.

    Both were captured after `75cf9aec` but before the snapshot script learned
    to stamp, so the stamp is absent and the scorer was still the fixed one.
    """
    assert mod.row_era(row("2026-08-30", 14, "2026-08-31T14:30:45")) == mod.POST
    assert mod.row_era(row("2026-08-31", 11, "2026-09-01T12:38:45")) == mod.POST


def test_unstamped_row_captured_BEFORE_the_fix_is_pre_fix():
    # 08-29's real capture, 22 minutes before the fix commit.
    assert mod.row_era(row("2026-08-29", 16, "2026-08-30T16:36:47")) == mod.PRE


def test_row_with_no_capture_time_defaults_to_pre_fix():
    """Unknown provenance must not default into the poolable era."""
    assert mod.row_era({"date": "2026-08-20", "games_with_outcome": 3}) == mod.PRE


# --- pooling ----------------------------------------------------------------

def test_pool_refuses_a_mixed_era_set():
    rows = [
        row("2026-08-29", 16, "2026-08-30T16:36:47"),
        row("2026-08-30", 14, "2026-08-31T14:30:45"),
    ]
    with pytest.raises(ValueError, match="scorer eras"):
        mod.pool(rows, "priceable_only")


def test_pool_is_game_weighted_not_record_weighted():
    """A 3-game day must not count the same as a 15-game day."""
    rows = [
        row("2026-09-01", 15, "2026-09-02T00:00:00", stamped=True, model=0.10, market=0.10, n=10),
        row("2026-09-02", 3, "2026-09-03T00:00:00", stamped=True, model=0.50, market=0.10, n=9000),
    ]
    res = mod.pool(rows, "priceable_only")
    assert res["games"] == 18
    # game-weighted: (0.10*15 + 0.50*3)/18 == 0.16667, NOT the record-weighted
    # value the huge n on the 3-game day would produce.
    assert res["model"] == pytest.approx((0.10 * 15 + 0.50 * 3) / 18)
    assert res["diff"] == pytest.approx((0.10 * 15 + 0.50 * 3) / 18 - 0.10)


def test_best_per_date_keeps_the_most_complete_capture():
    rows = [
        row("2026-09-01", 4, "2026-09-02T00:00:00", stamped=True, model=0.9),
        row("2026-09-01", 14, "2026-09-02T12:00:00", stamped=True, model=0.1),
    ]
    res = mod.pool(rows, "priceable_only")
    assert res["dates"] == 1
    assert res["games"] == 14
    assert res["model"] == pytest.approx(0.1)


def test_rows_without_outcomes_are_excluded():
    rows = [
        row("2026-09-01", 0, "2026-09-02T00:00:00", stamped=True),
        row("2026-09-02", 14, "2026-09-03T00:00:00", stamped=True, model=0.2, market=0.25),
    ]
    res = mod.pool(rows, "priceable_only")
    assert res["dates"] == 1 and res["games"] == 14


def test_population_mismatch_is_reported_not_silently_averaged():
    """A cut whose model and market briers span different row sets is not a
    comparison. It must be flagged rather than quietly pooled."""
    rows = [row("2026-09-02", 14, "2026-09-03T00:00:00", stamped=True, n=293, market_n=263)]
    res = mod.pool(rows, "priceable_only")
    assert res["population_mismatch"] == [("2026-09-02", 293, 263)]


# --- end to end against the real history ------------------------------------

def test_real_history_post_fix_pool_matches_the_committed_finding(tmp_path):
    """Guards the number recorded in `d9fb0b43`: 4 dates / 53 games / -0.00218.

    Skips rather than fails when the history is absent or has moved on, so this
    does not become a test that breaks every time the scheduled task appends.
    """
    hist = pathlib.Path(mod.DEFAULT_HISTORY)
    if not hist.exists():
        pytest.skip("history.jsonl not present")
    rows = [r for r in mod.load(str(hist)) if mod.row_era(r) == mod.POST]
    dates = {r["date"] for r in rows}
    if not {"2026-08-30", "2026-08-31"} <= dates:
        pytest.skip("history no longer covers the boundary dates")
    res = mod.pool(rows, "priceable_only")
    assert {"2026-08-30", "2026-08-31"} <= set(res["per_date"])
    assert res["per_date"]["2026-08-30"]["games"] == 14
    assert res["per_date"]["2026-08-31"]["games"] == 11
    # the finding itself
    assert res["dates"] >= 4 and res["games"] >= 53


def test_the_tool_never_writes_to_the_history(tmp_path):
    """`history.jsonl` is append-only and concurrently written."""
    hist = tmp_path / "history.jsonl"
    payload = [
        row("2026-09-01", 14, "2026-09-02T00:00:00", stamped=True),
        row("2026-08-29", 16, "2026-08-30T16:36:47"),
    ]
    hist.write_text("\n".join(json.dumps(p) for p in payload) + "\n", encoding="utf-8")
    before = hist.read_bytes()
    assert mod.main(["--history", str(hist), "--era", "each"]) == 0
    assert hist.read_bytes() == before


# --- coverage gap: a cut that stops being populated ------------------------
#
# The regression these guard is SILENT in the worst way. `best_per_date` skips
# a date whose cut has no brier, so a cut going permanently empty does not
# shrink the pool -- it freezes it, and the tool keeps printing the same total
# while new dates disappear. Measured 2026-09-12: MLB `priceable_only` hit
# model.n == 0 on 2026-09-11 (edge publishing switched off for the sport) and
# the pool still read "12 dates, 146 games", unchanged and unmarked.

def bare_row(date, games, captured, stamped=True):
    """A row with outcomes and NO cut block at all."""
    payload = {"date": date, "games_with_outcome": games, "captured_at": captured}
    if stamped:
        payload["scored_markets"] = ["h2h"]
    return payload


def test_coverage_gap_names_a_date_with_outcomes_but_no_brier():
    rows = [
        row("2026-09-10", 14, "2026-09-11T04:00:00", stamped=True),
        bare_row("2026-09-11", 13, "2026-09-12T04:00:00"),
    ]
    assert mod.coverage_gap(rows, "priceable_only") == [("2026-09-11", 13)]


def test_a_zero_model_n_counts_as_UNCOVERED():
    """n == 0 with a null brier is exactly how the real collapse presented."""
    r = row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True, n=0)
    r["priceable_only"]["model"]["brier"] = None
    r["priceable_only"]["market"]["brier"] = None
    assert mod.coverage_gap([r], "priceable_only") == [("2026-09-11", 13)]


def test_a_date_is_covered_if_ANY_capture_of_it_carries_the_cut():
    """A thin early snapshot must not mask a date a fuller capture measured."""
    rows = [
        bare_row("2026-09-11", 2, "2026-09-11T20:00:00"),
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True),
    ]
    assert mod.coverage_gap(rows, "priceable_only") == []


def test_dates_without_outcomes_are_not_a_gap():
    """A zero-outcome row is the post-roll artifact, not a missing measurement."""
    assert mod.coverage_gap(
        [bare_row("2026-09-12", 0, "2026-09-12T05:00:00")], "priceable_only") == []


def test_latest_dated_ignores_zero_outcome_rows():
    rows = [
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True),
        bare_row("2026-09-12", 0, "2026-09-12T05:00:00"),
    ]
    assert mod.latest_dated(rows) == "2026-09-11"


# --- the exit code ---------------------------------------------------------

def _hist(tmp_path, payload):
    h = tmp_path / "history.jsonl"
    h.write_text("\n".join(json.dumps(p) for p in payload) + "\n", encoding="utf-8")
    return str(h)


def test_a_stale_headline_cut_exits_NONZERO(tmp_path, capsys):
    """The frozen-pool case: newest date carries nothing for the cut."""
    path = _hist(tmp_path, [
        row("2026-09-10", 14, "2026-09-11T04:00:00", stamped=True),
        bare_row("2026-09-11", 13, "2026-09-12T04:00:00"),
    ])
    assert mod.main(["--history", path, "--era", "post-fix"]) == 3
    out = capsys.readouterr().out
    assert "HEADLINE CUT IS STALE" in out
    assert "2026-09-11" in out


def test_allow_stale_cut_accepts_the_frozen_pool(tmp_path):
    path = _hist(tmp_path, [
        row("2026-09-10", 14, "2026-09-11T04:00:00", stamped=True),
        bare_row("2026-09-11", 13, "2026-09-12T04:00:00"),
    ])
    assert mod.main(
        ["--history", path, "--era", "post-fix", "--allow-stale-cut"]) == 0


def test_a_populated_cut_exits_zero(tmp_path):
    path = _hist(tmp_path, [
        row("2026-09-10", 14, "2026-09-11T04:00:00", stamped=True),
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True),
    ])
    assert mod.main(["--history", path, "--era", "post-fix"]) == 0


def test_a_cut_populated_on_the_newest_date_is_not_stale_despite_older_gaps(tmp_path, capsys):
    """An old uncovered date is reported, but does not fail the run."""
    path = _hist(tmp_path, [
        bare_row("2026-09-09", 11, "2026-09-10T04:00:00"),
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True),
    ])
    assert mod.main(["--history", path, "--era", "post-fix"]) == 0
    out = capsys.readouterr().out
    assert "COVERAGE GAP" in out and "2026-09-09" in out
    assert "HEADLINE CUT IS STALE" not in out


def test_the_gap_is_scoped_to_the_eras_being_reported(tmp_path, capsys):
    """A post-fix query must not list pre-fix dates that predate the cut.

    Ten such dates once buried the single date that mattered; a block the
    reader learns to skip is the same as no block.
    """
    path = _hist(tmp_path, [
        bare_row("2026-08-25", 15, "2026-08-26T04:00:00", stamped=False),
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True),
    ])
    assert mod.main(["--history", path, "--era", "post-fix"]) == 0
    out = capsys.readouterr().out
    assert "2026-08-25" not in out


def test_an_era_with_no_dates_for_the_cut_does_not_crash(tmp_path, capsys):
    """Pre-fix rows predate `fresh_quotes_only` entirely.

    `pool()` omits the pooled keys when nothing carries the cut, and `main`
    used to print them regardless -- a KeyError on the EXACT command the
    scheduled task prescribes (`--era each --cut fresh_quotes_only`).
    """
    path = _hist(tmp_path, [
        row("2026-08-25", 15, "2026-08-26T04:00:00", cut="priceable_only"),
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True,
            cut="fresh_quotes_only"),
    ])
    assert mod.main(
        ["--history", path, "--era", "each", "--cut", "fresh_quotes_only"]) == 0
    out = capsys.readouterr().out
    assert "No date in this era carries cut=fresh_quotes_only" in out
    assert "134" not in out


def test_an_era_that_carries_the_cut_on_no_date_is_not_enumerated(tmp_path, capsys):
    """Structural absence is not a gap.

    `--era each --cut fresh_quotes_only` is the command the scheduled task
    runs, and pre-fix rows never carry that cut. Listing all ten pre-fix dates
    buries the one or two real gaps -- the same failure era-scoping fixed.
    """
    path = _hist(tmp_path, [
        row("2026-08-24", 10, "2026-08-25T04:00:00", cut="priceable_only"),
        row("2026-08-25", 15, "2026-08-26T04:00:00", cut="priceable_only"),
        bare_row("2026-08-30", 14, "2026-08-31T04:00:00"),
        row("2026-09-11", 13, "2026-09-12T04:00:00", stamped=True,
            cut="fresh_quotes_only"),
    ])
    assert mod.main(
        ["--history", path, "--era", "each", "--cut", "fresh_quotes_only"]) == 0
    out = capsys.readouterr().out
    # the post-fix date that genuinely lacks the cut IS named
    assert "2026-08-30" in out
    # the pre-fix era, which carries the cut on no date at all, is not
    assert "2026-08-24" not in out
    assert "2026-08-25" not in out
    assert "Nothing to pool" in out


# --- the pooled difference is PAIRED -----------------------------------------
#
# `live_gameline_score._paired`: a record carries a model probability whenever
# it is scored, but `market_fair_prob` can be absent, so `model` spans MORE rows
# than `market`. Only `model_paired` may be subtracted. `cut_values` ignored it,
# and on the real history the post-fix fresh cut pooled to +0.00571 unpaired
# against +0.00460 paired, while the per-date `diff` column above it was
# already paired -- the table and its own POOLED line disagreed.

def paired_row(date, games, *, model, model_n, paired, paired_n, market, market_n,
               cut="fresh_quotes_only", captured="2026-09-12T04:00:00"):
    return {
        "date": date,
        "games_with_outcome": games,
        "captured_at": captured,
        "scored_markets": ["h2h"],
        cut: {
            "model": {"brier": model, "n": model_n},
            "model_paired": {"brier": paired, "n": paired_n},
            "market": {"brier": market, "n": market_n},
            "model_minus_market_brier": round(paired - market, 5),
        },
    }


def test_the_pool_uses_the_PAIRED_model_brier_when_the_row_carries_one():
    """The unpaired and paired differences here have OPPOSITE signs on purpose."""
    r = paired_row("2026-09-01", 10, model=0.30, model_n=100,
                   paired=0.20, paired_n=90, market=0.25, market_n=90)
    res = mod.pool([r], "fresh_quotes_only")
    assert res["diff"] == pytest.approx(-0.05)       # paired: model AHEAD
    assert res["model"] == pytest.approx(0.20)
    assert res["per_date"]["2026-09-01"]["paired"] is True


def test_a_paired_row_is_like_for_like_and_its_exclusion_is_COUNTED(tmp_path, capsys):
    r = paired_row("2026-09-01", 10, model=0.30, model_n=100,
                   paired=0.20, paired_n=90, market=0.25, market_n=90)
    res = mod.pool([r], "fresh_quotes_only")
    assert res["population_mismatch"] == []
    assert res["paired_exclusions"] == [("2026-09-01", 10)]
    path = _hist(tmp_path, [r])
    assert mod.main(["--history", path, "--era", "post-fix",
                     "--cut", "fresh_quotes_only"]) == 0
    out = capsys.readouterr().out
    assert "NOT LIKE-FOR-LIKE" not in out
    assert "The model column is PAIRED" in out


def test_a_row_without_model_paired_falls_back_and_is_still_flagged():
    """Pre-contract-2 rows carry no paired block. Nothing to pair on, so say so."""
    r = row("2026-08-29", 16, "2026-08-30T16:36:47", model=0.3, market=0.25,
            n=100, market_n=90)
    res = mod.pool([r], "priceable_only")
    assert res["per_date"]["2026-08-29"]["paired"] is False
    assert res["population_mismatch"] == [("2026-08-29", 100, 90)]
    assert res["paired_exclusions"] == []


def test_a_matched_row_pools_identically_paired_or_not():
    same = paired_row("2026-09-05", 14, model=0.18428, model_n=116,
                      paired=0.18428, paired_n=116, market=0.17587, market_n=116)
    res = mod.pool([same], "fresh_quotes_only")
    assert res["diff"] == pytest.approx(0.18428 - 0.17587)
    assert res["paired_exclusions"] == []


def test_real_history_pooled_diff_equals_the_rows_own_paired_diff():
    """The fix must reproduce the SCORER's arithmetic, not invent its own.

    Skips when the history is absent or no longer spans an unpaired date, so it
    does not break every time the scheduled task appends.
    """
    hist = pathlib.Path(mod.DEFAULT_HISTORY)
    if not hist.exists():
        pytest.skip("history.jsonl not present")
    rows = [r for r in mod.load(str(hist)) if mod.row_era(r) == mod.POST]
    cut = "fresh_quotes_only"
    best = mod.best_per_date(rows, cut)
    if not any((b[cut].get("model") or {}).get("n") != (b[cut].get("market") or {}).get("n")
               for b in best.values()):
        pytest.skip("history no longer holds a date with unpaired populations")
    res = mod.pool(rows, cut)
    games = sum(r["games_with_outcome"] for r in best.values())
    weighted = sum(r[cut]["model_minus_market_brier"] * r["games_with_outcome"]
                   for r in best.values()) / games
    assert res["diff"] == pytest.approx(weighted, abs=5e-5)
