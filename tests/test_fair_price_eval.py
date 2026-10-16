"""`scripts/fair_price_eval.py` -- grouping, shared-feed detection, the per-book fair it scores, and calibration.

The de-vig itself is production's (`opportunity_signals.devig`); its properties are tested in
`tests/test_fair_devig_shin.py`. Here: that the evaluator calls it the way the board does.
"""
from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path

from syndicate.features.shared.opportunity_signals import devig

_SPEC = importlib.util.spec_from_file_location(
    "fair_price_eval", Path(__file__).resolve().parents[1] / "scripts" / "fair_price_eval.py"
)
fpe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fpe)


def test_fair_is_productions_devig_per_book_then_the_median() -> None:
    per_book = {"a": {"home": -400, "away": 300}}
    for method, name in (("mult", "multiplicative"), ("power", "power"), ("shin", "shin")):
        fair, n = fpe.fair_for(per_book, "away", method)
        assert n == 1 and math.isclose(fair, devig([300, -400], method=name)[0])


def test_spread_sides_share_one_group_on_the_home_line() -> None:
    home = fpe.group_key("e1", "spreads", "full", None, "home", -3.5)
    away = fpe.group_key("e1", "spreads", "full", None, "away", 3.5)
    other = fpe.group_key("e1", "spreads", "full", None, "away", -3.5)
    assert home == away != other
    assert fpe.group_key("e1", "totals", "full", None, "over", 44.5) == fpe.group_key("e1", "totals", "full", None, "under", 44.5)


def test_shared_feed_books_are_detected_and_vote_once() -> None:
    last = {}
    for i in range(300):
        p = -110 - (i % 7)
        last[(("e", "m", "full", "", float(i)), "over")] = {"dk": p, "mgm": p, "fd": p + 5}
    clusters = fpe.feed_clusters(last, threshold=0.9)
    assert clusters["dk"] == clusters["mgm"] != clusters["fd"]
    per_book = {
        "dk": {"over": -150, "under": 125},
        "mgm": {"over": -150, "under": 125},
        "fd": {"over": -110, "under": -110},
    }
    plain, n_plain = fpe.fair_for(per_book, "over", "power")
    dedup, n_dedup = fpe.fair_for(per_book, "over", "power_dedup", clusters)
    assert n_plain == 3 and n_dedup == 2
    assert dedup < plain  # the duplicated -150 no longer wins the median by itself


def test_incomplete_or_impossible_books_are_refused() -> None:
    assert fpe.fair_for({"a": {"over": -110}}, "over", "mult") == (None, 0)
    assert fpe.fair_for({"a": {"over": 200, "under": 200}}, "over", "mult") == (None, 0)  # underround


def test_ev_at_is_productions_expected_value_as_a_fraction() -> None:
    assert math.isclose(fpe.ev_at(100, 0.55), 0.10, abs_tol=1e-9)
    assert fpe.ev_at(None, 0.5) is None


def test_calibration_recovers_a_known_slope() -> None:
    rng = random.Random(1)
    ps, ys = [], []
    for _ in range(6000):
        p = rng.uniform(0.05, 0.95)
        x = math.log(p / (1 - p))
        true = 1 / (1 + math.exp(-(0.0 + 0.7 * x)))  # an over-spread forecast: true slope 0.7
        ps.append(p)
        ys.append(1.0 if rng.random() < true else 0.0)
    a, b = fpe.calibration(ps, ys)
    assert abs(a) < 0.1 and 0.6 < b < 0.8


def test_h5_shin_fresh_drops_a_book_that_moved_off_the_line_and_keeps_the_rest() -> None:
    """The 10-15 Knicks total: books that re-posted at 226.5 still count at 225.5 in today's fair. `shin_fresh` drops them."""
    from datetime import datetime, timezone

    t0 = datetime(2026, 10, 15, 13, 17, tzinfo=timezone.utc)
    start = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    sight = datetime(2026, 10, 15, 23, 0, tzinfo=timezone.utc)
    g = fpe.group_key("ev1", "totals", "full", "", "under", 225.5)
    hist = {
        (g, "fanduel", "over"): [(t0, -110, start)], (g, "fanduel", "under"): [(t0, -110, start)],      # moved off later
        (g, "betrivers", "over"): [(t0, -130, start)], (g, "betrivers", "under"): [(t0, 107, start)],   # still here
    }
    later = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc)
    activity = {(g[:4], "fanduel"): [(t0, 225.5), (later, 226.5)], (g[:4], "betrivers"): [(t0, 225.5)]}
    row = {"gkey": g, "t": sight.isoformat(), "sd": "under", "sport": "nba", "game": "nba|ev1", "y": 1.0, "px": 107, "pnl": 1.07}
    fpe.evaluate([dict(row)], hist, max_age_h=24.0, max_stale_h=24.0, dup_threshold=0.9)          # no activity: shin == shin_fresh
    scored = [dict(row)]
    report = fpe.evaluate(scored, hist, max_age_h=24.0, max_stale_h=24.0, dup_threshold=0.9, activity=activity)
    r = scored[0]
    assert r["stale_books"] == 1
    assert r["sight_books_shin"] == 2 and r["sight_books_shin_fresh"] == 1
    assert math.isclose(r["sight_shin_fresh"], devig([-130, 107], method="shin")[1], rel_tol=1e-9)
    assert r["sight_shin_fresh"] < r["sight_shin"], "betrivers' own no-vig under is below the stale -110 median"
    assert report["h5_fresh_vs_shin"]["by_sport"]["nba"]["share_rows_with_a_stale_book"] == 1.0
    assert report["h5_fresh_vs_shin"]["pooled_ex_nba"] == {"n": 0}, "NBA (preseason) is never pooled"


def test_h5_a_move_after_the_sighting_does_not_count() -> None:
    from datetime import datetime, timezone

    g = fpe.group_key("ev1", "totals", "full", "", "over", 225.5)
    t0, t = datetime(2026, 10, 15, 13, tzinfo=timezone.utc), datetime(2026, 10, 15, 14, tzinfo=timezone.utc)
    later = datetime(2026, 10, 15, 15, tzinfo=timezone.utc)
    assert not fpe.moved_off({(g[:4], "fd"): [(later, 226.5)]}, g, "fd", t0, t)
    assert fpe.moved_off({(g[:4], "fd"): [(datetime(2026, 10, 15, 13, 30, tzinfo=timezone.utc), 226.5)]}, g, "fd", t0, t)
    assert not fpe.moved_off({(g[:4], "fd"): [(datetime(2026, 10, 15, 13, 30, tzinfo=timezone.utc), 225.5)]}, g, "fd", t0, t)
