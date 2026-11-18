"""scripts/s1_freshness_study.py -- population, reference ages via Test B's reader, the N fit, the TEST verdict."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from scripts import s1_freshness_study as s1

T0 = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)


def _order(**kw):
    base = {"venue": "paper:kalshi:ladder", "sport": "ncaaf", "status": "filled", "outcome": "won", "event_id": "e1",
            "side": "home", "market": "spreads", "line": -3.5, "segment": "full", "fill_stake_dollars": 2.0,
            "fill_price": 0.5, "fees_dollars": 0.02, "pnl_dollars": 1.98, "position_key": "p1", "ev_pct": 3.0,
            "submitted_at": (T0 + timedelta(minutes=10)).isoformat(), "commence_time": (T0 + timedelta(hours=2)).isoformat()}
    base.update(kw)
    return base


def _beat(minutes, events=(), pin=(), books=("draftkings",)):
    return {"captured_at": (T0 + timedelta(minutes=minutes)).isoformat(), "events": list(events),
            "pinnacle_events": list(pin), "books": list(books)}


def _row(game, ret, age, day="2026-11-10", book="ladder", venue="kalshi"):
    return {"game": game, "ret": ret, "pin_age_s": age, "cons_age_s": age, "stake": 1.0, "pnl": ret,
            "submitted": f"{day}T12:00:00+00:00", "day": day, "book": book, "venue": venue, "ev_pct": 2.0,
            "sport": "ncaaf", "move": None}


def test_population_is_pregame_settled_venue_orders_with_paper_deduplicated():
    orders = [_order(), _order(submitted_at=(T0 + timedelta(minutes=20)).isoformat()),           # paper duplicate
              _order(venue="kalshi", position_key="p1"), _order(venue="kalshi", position_key="p1"),  # live never deduped
              _order(position_key="p2", submitted_at=(T0 + timedelta(hours=3)).isoformat()),       # in game
              _order(position_key="p3", outcome=None), _order(position_key="p4", venue="paper:novig"),
              _order(position_key="p5", venue="kalshi", ev_pct=None)]                               # live in-game path
    kept, drops = s1.population(orders)
    assert len(kept) == 3
    assert drops == {"ladder:duplicate_position": 1, "ladder:in_game": 1, "ladder:unsettled": 1, "live:in_game": 1}
    assert [o["venue"] for o in kept].count("kalshi") == 2                  # both live fills kept


def test_reference_ages_reuse_capture_age_and_ignore_venue_only_fetches_for_the_consensus():
    beats = {("ncaaf", "2026-11-10"): [_beat(0, events=["e1"], pin=["e1"]),
                                        _beat(6, events=["e1"], pin=[]),                       # sportsbook, no Pinnacle
                                        _beat(9, events=["e1"], books=("kalshi",)),            # venue-only capture
                                        _beat(30, events=["e1"], pin=["e1"])]}                 # after submit
    ages = s1.reference_ages(_order(), s1.index_beats(beats))
    assert ages["pin_age_s"] == 600.0          # the 18:00 fetch that saw Pinnacle, 10 min before submit
    assert ages["cons_age_s"] == 240.0         # 18:06 sportsbook fetch; the 18:09 kalshi-only capture does not count


def test_reference_age_is_unknown_without_a_heartbeat_never_fresh():
    ages = s1.reference_ages(_order(event_id="other"), s1.index_beats({("ncaaf", "2026-11-10"): [_beat(0, ["e1"], ["e1"])]}))
    assert ages == {"pin_age_s": None, "cons_age_s": None}


def test_flat_roi_and_clustered_se_match_the_hand_computation():
    rows = [_row("g1", 1.0, 30), _row("g1", -1.0, 30), _row("g2", 0.5, 30)]
    s = s1.flat(rows)
    mean = 0.5 / 3
    se = math.sqrt(((1 - mean) + (-1 - mean)) ** 2 + (0.5 - mean) ** 2) / 3
    assert abs(s["roi"] - 100 * mean) < 1e-9 and abs(s["se"] - 100 * se) < 1e-9 and s["events"] == 2


def test_clustered_diff_of_nested_sets_has_zero_variance_when_the_subset_is_everything():
    rows = [_row("g1", 1.0, 30), _row("g2", -1.0, 30), _row("g3", 0.2, 30)]
    d = s1.clustered_diff(rows, rows)
    assert abs(d["d"]) < 1e-12 and abs(d["se"]) < 1e-12


def test_fit_picks_the_n_with_the_largest_fresh_minus_stale_among_qualifying_sizes(monkeypatch):
    monkeypatch.setattr(s1, "MIN_SIDE_ORDERS", 2)
    monkeypatch.setattr(s1, "MIN_SIDE_EVENTS", 2)
    rows = [_row("a", 1.0, 30), _row("b", 1.0, 50), _row("c", 0.5, 200), _row("d", 0.4, 250),
            _row("e", -1.0, 700), _row("f", -1.0, 800), _row("g", -1.0, 2000), _row("h", -1.0, 3000)]
    fit = s1.fit_n(rows, "pin_age_s")
    by_n = {t["n_min"]: t for t in fit["table"]}
    assert by_n[1]["fresh"]["n"] == 2 and by_n[5]["fresh"]["n"] == 4
    assert fit["chosen_n_min"] == 5            # fresh {1, 1, .5, .4} vs stale {-1 x4}: the largest gap
    assert by_n[15]["qualifies"] is True


def test_fit_refuses_an_n_that_leaves_a_side_too_small():
    rows = [_row(f"g{i}", 0.1, 30) for i in range(5)]
    assert s1.fit_n(rows, "pin_age_s")["chosen_n_min"] is None
    assert s1.test_n(rows, "pin_age_s", None)["verdict"].startswith("NOT TESTABLE")


def test_test_verdict_survives_only_when_the_interval_excludes_zero():
    good = [_row(f"f{i}", 0.5, 30) for i in range(40)] + [_row(f"s{i}", -0.5 + 0.01 * (i % 3), 900) for i in range(40)]
    t = s1.test_n(good, "pin_age_s", 2)
    assert t["verdict"] == "SURVIVES" and t["diff"]["lo"] > 0
    assert abs(t["diff"]["d"] - (t["fresh"]["roi"] - t["all"]["roi"])) < 1e-9
    flat_rows = [_row(f"f{i}", (-1) ** i, 30 if i % 2 else 900) for i in range(40)]
    assert s1.test_n(flat_rows, "pin_age_s", 2)["verdict"] == "FALSIFIED"


def test_unknown_age_rows_are_outside_the_tested_all():
    rows = [_row("a", 0.5, 30), _row("b", -0.5, 900), _row("c", -1.0, None)]
    t = s1.test_n(rows, "pin_age_s", 2)
    assert t["all"]["n"] == 2 and t["fresh"]["n"] == 1


def test_gradient_buckets_the_registered_edges():
    assert [s1.bucket_of(a) for a in (60, 61, 120, 300, 900, 3600, 3601, None)] == \
        ["0-1m", "1-2m", "1-2m", "2-5m", "5-15m", "15-60m", ">60m", "unknown"]


def test_windows_split_fit_and_test_at_the_registered_instants():
    first = "2026-10-25T18:36:00+00:00"
    assert s1.window_of({"submitted": "2026-10-25T10:00:00+00:00"}, first) == "pre_heartbeat"
    assert s1.window_of({"submitted": "2026-11-07T23:59:59+00:00"}, first) == "FIT"
    assert s1.window_of({"submitted": "2026-11-08T00:00:00+00:00"}, first) == "TEST"
    assert s1.window_of({"submitted": "2026-11-17T23:59:59+00:00"}, first) == "TEST"
    assert s1.window_of({"submitted": "2026-11-18T00:00:00+00:00"}, first) == "after_TEST"


def test_venue_move_reads_toward_or_away_from_the_reference_fair():
    ref_at, sub = T0, T0 + timedelta(minutes=10)
    series = [(T0 - timedelta(minutes=5), None, "kalshi", "home", -3.5, 0.48),
              (T0 + timedelta(minutes=5), None, "kalshi", "home", -3.5, 0.50),
              (T0 + timedelta(minutes=6), None, "draftkings", "home", -3.5, -120)]
    order = _order(venue="kalshi", submitted_at=sub.isoformat())
    assert s1.venue_move(order, series, ref_at, 0.55)["move"] == "toward"   # 0.48 -> 0.50, fair 0.55
    assert s1.venue_move(order, series, ref_at, 0.45)["move"] == "away"
    assert s1.venue_move(order, series[:1], ref_at, 0.55)["move"] == "flat"
    assert s1.venue_move(order, [], ref_at, 0.55)["move"] == "no_venue_quote"
    assert s1.venue_move(order, series, None, 0.55)["move"] == "no_reference"


def test_report_renders_counts_and_percentages_only():
    rows = [_row(f"f{i}", 0.3, 30, day="2026-11-01") for i in range(120)] + \
           [_row(f"s{i}", -0.3, 900, day="2026-11-01") for i in range(120)] + \
           [_row(f"t{i}", 0.2, 30, day="2026-11-10") for i in range(50)] + \
           [_row(f"u{i}", -0.2, 900, day="2026-11-10") for i in range(50)]
    meta = {"first_heartbeat_at": "2026-10-25T18:36:00+00:00", "heartbeat_days": {"ncaaf": ["2026-11-01", "2026-11-10"]},
            "shard_days": {}, "drops": {}}
    rep = s1.report(rows, meta)
    assert rep["primary"]["fit"]["chosen_n_min"] == 1
    assert rep["primary"]["test"]["verdict"] == "SURVIVES"
    md = s1.render_coverage(s1.coverage(rows, meta)) + s1.render_report(rep)
    assert "$" not in md and "staked" not in md.lower()
