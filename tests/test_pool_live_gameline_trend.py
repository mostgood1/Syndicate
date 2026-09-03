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
