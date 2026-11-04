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


# ----------------------------------------------------------------------------- shin_live (lane soccer-corners-fair-inflation)
#
# The tape is a CHANGE log: a corners ladder that sits still for a day writes one row. The age windows (12 h at
# sighting, 6 h at the close) read that as a dead book; `shin_live` asks the state file when the key was last LOOKED at.

def _corners_case():
    from datetime import datetime, timezone

    def at(day, hour, minute=0):
        return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)
    ct, sight = at(28, 20), at(28, 8)
    g = fpe.group_key("ev1", "alternate_totals_corners", "full", "", "over", 9.5)
    hist = {
        # still quoted at kickoff, price unmoved since the day before: 20 h old at sighting, 32 h at the close
        (g, "bet365", "over"): [(at(27, 12), 100, ct)], (g, "bet365", "under"): [(at(27, 12), -125, ct)],
        # moves often
        (g, "fanduel", "over"): [(at(28, 7), 120, ct), (at(28, 19), 115, ct)],
        (g, "fanduel", "under"): [(at(28, 7), -150, ct), (at(28, 19), -145, ct)],
        # moved 2 h before the sighting, then stopped being quoted at 06:30
        (g, "draftkings", "over"): [(at(28, 6), 140, ct)], (g, "draftkings", "under"): [(at(28, 6), -175, ct)],
    }
    seen = {(g, "bet365", s): at(28, 19, 58) for s in ("over", "under")}
    seen |= {(g, "fanduel", s): at(28, 19, 58) for s in ("over", "under")}
    seen |= {(g, "draftkings", s): at(28, 6, 30) for s in ("over", "under")}
    row = {"gkey": g, "t": sight.isoformat(), "sd": "over", "sport": "soccer", "game": "soccer|ev1",
           "y": 1.0, "px": 120, "pnl": 1.2}
    return hist, seen, row


def test_shin_live_counts_the_motionless_book_and_drops_the_one_no_longer_quoted() -> None:
    hist, seen, row = _corners_case()
    scored = [dict(row)]
    report = fpe.evaluate(scored, hist, max_age_h=12.0, max_stale_h=6.0, dup_threshold=0.9,
                          last_seen=seen, live_tol_min=60.0)
    r = scored[0]
    # the age windows: fanduel + draftkings at sighting (bet365 20 h old), fanduel alone at the close (bet365 32 h)
    assert r["sight_books_shin"] == 2 and r["close_books_shin"] == 1
    # observed: bet365 + fanduel at both moments; draftkings was last seen 90 min before the sighting
    assert r["sight_books_shin_live"] == 2 and r["close_books_shin_live"] == 2
    want_sight = (devig([100, -125], method="shin")[0] + devig([120, -150], method="shin")[0]) / 2
    want_close = (devig([100, -125], method="shin")[0] + devig([115, -145], method="shin")[0]) / 2
    assert math.isclose(r["sight_shin_live"], want_sight, rel_tol=1e-9)
    assert math.isclose(r["close_shin_live"], want_close, rel_tol=1e-9)
    assert r["sight_shin_live"] != r["sight_shin"] and r["close_shin_live"] != r["close_shin"]  # off != on
    block = report["live_vs_shin"]["by_sport"]["soccer"]
    assert block["n"] == 1 and block["rows_close_live"] == 1 and block["keys_last_seen_unknown"] == 0


def test_shin_live_with_no_last_seen_is_shin_and_off_by_default() -> None:
    """Control: a key with no last-seen is unknown, never stale -- the age windows decide, so shin_live == shin.
    Without --live-tol-min nothing new is computed or reported."""
    hist, _, row = _corners_case()
    scored = [dict(row)]
    report = fpe.evaluate(scored, hist, max_age_h=12.0, max_stale_h=6.0, dup_threshold=0.9,
                          last_seen=None, live_tol_min=60.0)
    r = scored[0]
    assert r["sight_shin_live"] == r["sight_shin"] and r["close_shin_live"] == r["close_shin"]
    assert r["live_unknown_keys"] == 6 and report["live_vs_shin"]["by_sport"]["soccer"]["keys_last_seen_unknown"] == 6

    off = [dict(row)]
    report = fpe.evaluate(off, hist, max_age_h=12.0, max_stale_h=6.0, dup_threshold=0.9)
    assert "live_vs_shin" not in report and "sight_shin_live" not in off[0]
    assert off[0]["sight_shin"] == r["sight_shin"] and off[0]["close_shin"] == r["close_shin"]


def test_read_quotes_fills_last_seen_from_the_state_file_beside_a_gz_shard(tmp_path) -> None:
    import gzip
    import json

    directory = tmp_path / "soccer_source" / "tracking" / "book_quotes"
    directory.mkdir(parents=True)
    base = {"sport": "soccer", "kind": "game", "event_id": "ev1", "bookmaker": "bet365", "segment": "full",
            "market": "alternate_totals_corners", "player_name": None, "line": 9.5,
            "captured_at": "2026-10-27T12:00:00+00:00", "commence_time": "2026-10-28T20:00:00Z"}
    with gzip.open(directory / "2026-10-28.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(base | {"selection": "Over", "price": 100}) + "\n")
        fh.write(json.dumps(base | {"selection": "Under", "price": -125}) + "\n")
    state = {
        "soccer|game|ev1|bet365|full|alternate_totals_corners|Over||9.5": [9.5, 100, "2026-10-28T19:58:00+00:00"],
        "soccer|game|ev1|bet365|full|alternate_totals_corners|Under||9.5": [9.5, -125, "2026-10-28T19:58:00+00:00"],
        "soccer|game|ev1|fanduel|full|alternate_totals_corners|Over||9.5": [9.5, 120],  # predates last-seen
        "soccer|game|ev2|bet365|full|alternate_totals_corners|Over||9.5": [9.5, 100, "2026-10-28T19:58:00+00:00"],
    }
    (directory / "2026-10-28.state.json").write_text(json.dumps(state), encoding="utf-8")
    g = fpe.group_key("ev1", "alternate_totals_corners", "full", "", "over", 9.5)
    seen: dict = {}
    hist = fpe.read_quotes(tmp_path, "soccer", {"ev1"}, {g}, None, seen)
    assert set(hist) == {(g, "bet365", "over"), (g, "bet365", "under")}
    assert set(seen) == {(g, "bet365", "over"), (g, "bet365", "under")}
    assert seen[(g, "bet365", "over")] == fpe.ts("2026-10-28T19:58:00Z")
    assert fpe.read_quotes(tmp_path, "soccer", {"ev1"}, {g}) == hist  # without last_seen: no state read, same quotes
