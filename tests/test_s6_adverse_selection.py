"""Tests for scripts/s6_adverse_selection.py (study S6, lane s6-adverse-selection). Pure functions only."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import numpy as np

from scripts import s6_adverse_selection as s6


def _t(minute: int) -> datetime:
    return datetime(2026, 11, 10, 18, minute, tzinfo=timezone.utc)


ORDER = {"submitted_at": "2026-11-10T18:30:00Z", "market": "totals", "side": "over", "line": 220.5,
         "venue": "paper:kalshi:ladder", "sport": "nba"}


def test_quote_features_books_dispersion_and_venue_move_toward():
    series = [
        (_t(0), None, "draftkings", "over", 220.5, -110), (_t(0), None, "draftkings", "under", 220.5, -110),
        (_t(1), None, "pinnacle", "over", 220.5, -120), (_t(1), None, "pinnacle", "under", 220.5, +100),
        (_t(2), None, "kalshi", "over", 220.5, 0.50),       # venue at the reference fetch
        (_t(25), None, "kalshi", "over", 220.5, 0.53),      # venue moved up, toward Pinnacle's fair (~0.53)
        (_t(31), None, "fanduel", "over", 220.5, -150), (_t(31), None, "fanduel", "under", 220.5, +130),  # after submit
    ]
    out = s6.quote_features(ORDER, series, {"pin_age_s": 600.0, "cons_age_s": 300.0})
    assert out["n_books"] == 2                        # fanduel is after submit; the venue never counts
    assert out["disp_pp"] is not None and out["disp_pp"] > 0
    assert out["pin_fair"] is not None and 0.5 < out["pin_fair"] < 0.56
    assert out["vmove"] == 1 and out["vmove_ref"] == "pin"


def test_quote_features_away_flat_and_missing():
    base = [(_t(1), None, "pinnacle", "over", 220.5, -120), (_t(1), None, "pinnacle", "under", 220.5, +100)]
    away = base + [(_t(2), None, "kalshi", "over", 220.5, 0.50), (_t(25), None, "kalshi", "over", 220.5, 0.47)]
    flat = base + [(_t(2), None, "kalshi", "over", 220.5, 0.50)]
    assert s6.quote_features(ORDER, away, {"pin_age_s": 600.0})["vmove"] == -1
    assert s6.quote_features(ORDER, flat, {"pin_age_s": 600.0})["vmove"] == 0
    assert s6.quote_features(ORDER, base, {"pin_age_s": 600.0})["vmove"] is None      # no venue quote
    assert s6.quote_features(ORDER, flat, {})["vmove"] is None                         # no reference fetch
    assert s6.quote_features(ORDER, [], {"pin_age_s": 1.0})["n_books"] == 0


def test_quote_eligible_excludes_three_way_and_unflippable_sides():
    assert s6.quote_eligible({"side": "home", "market": "h2h", "sport": "nba"})
    assert not s6.quote_eligible({"side": "home", "market": "h2h", "sport": "soccer"})
    assert not s6.quote_eligible({"side": "yes", "market": "btts", "sport": "soccer"})


def test_fit_logistic_recovers_the_sign_with_an_offset():
    rng = random.Random(7)
    n = 4000
    x = np.array([rng.gauss(0, 1) for _ in range(n)])
    off = np.array([rng.uniform(-1, 1) for _ in range(n)])
    p = 1 / (1 + np.exp(-(off - 0.2 - 0.5 * x)))
    y = np.array([1.0 if rng.random() < pi else 0.0 for pi in p])
    X = np.column_stack([np.ones(n), x])
    th = s6.fit_logistic(X, y, off, lam=1.0)
    assert -0.4 < th[0] < 0.0 and -0.7 < th[1] < -0.3
    heavy = s6.fit_logistic(X, y, off, lam=1e7)
    assert abs(heavy[1]) < 0.01                        # the penalty shrinks the slope, not the intercept


def test_quantile_cut_keeps_the_top_share():
    vals = list(range(100))
    cut = s6.quantile_cut(vals, 0.7)
    assert sum(v >= cut for v in vals) == 70


def test_time_folds_are_contiguous_event_blocks():
    rows = [{"game": f"g{i}", "submitted": f"2026-11-0{1 + i // 4}T00:00:0{i % 4}Z"} for i in range(20)]
    folds = s6.time_folds(rows, k=5)
    assert folds == sorted(folds) and set(folds) == {0, 1, 2, 3, 4}
    rows.append({"game": "g0", "submitted": "2026-11-09T00:00:00Z"})     # a later order on the first event
    assert s6.time_folds(rows, k=5)[-1] == 0


def test_window_boundaries():
    first = "2026-10-25T18:36:27+00:00"
    assert s6.window_of({"submitted": "2026-10-25T18:00:00Z"}, first) == "pre_heartbeat"
    assert s6.window_of({"submitted": "2026-11-07T23:59:59Z"}, first) == "FIT"
    assert s6.window_of({"submitted": "2026-11-08T00:00:00Z"}, first) == "TEST"
    assert s6.window_of({"submitted": "2026-11-18T23:59:59Z"}, first) == "TEST"
    assert s6.window_of({"submitted": "2026-11-19T12:00:00Z"}, first) == "gap"
    assert s6.window_of({"submitted": "2026-11-20T00:00:00Z"}, first) == "FORWARD"


def test_verdict_rules():
    assert s6.verdict({"keep": None}, None).startswith("NO CHALLENGER")
    assert s6.verdict({"keep": 0.8}, {"diff": {"hi": -0.1}}).startswith("KILL")
    assert s6.verdict({"keep": 0.8}, {"diff": {"hi": 0.1}}).startswith("FORWARD TEST")


def test_load_model_from_findings_block(tmp_path):
    p = tmp_path / "findings.md"
    p.write_text("text\n### S6_MODEL_JSON (frozen)\n\n```json\n{\"cut\": -0.05, \"theta\": [0.1]}\n```\n",
                 encoding="utf-8")
    assert s6.load_model_from(str(p)) == {"cut": -0.05, "theta": [0.1]}
