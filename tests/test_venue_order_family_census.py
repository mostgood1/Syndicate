"""The census that would have caught `#682`: a market family with positions and zero builds.

Polymarket player props were refused at build 100% of the time for as long as
the prop join produced matches, and the per-cycle `ORDER_PATH` line carried the
counts that said so the whole time. Nobody reads a per-cycle line for an
ABSENCE, so these tests are written against the REAL lines from 2026-09-22 --
before the fix (`strikeouts: {'market_unresolved': 1}`) and after it
(`strikeouts: {'would_build': 1}`).

The other half is that the check must never report health it cannot see: no
lines, or an unreadable `markets={...}`, is INCONCLUSIVE, never CLEAR.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from venue_order_family_census import (  # noqa: E402
    EXIT_ALERT,
    EXIT_CLEAR,
    EXIT_INCONCLUSIVE,
    census,
    exit_code,
    render,
)

# Verbatim from live-odds-worker, 2026-09-22 15:57:22Z -- the pass that exposed the defect.
BEFORE = (
    "2026-09-22T15:57:22.458959386Z",
    "[live_odds_worker] ORDER_PATH venue=polymarket status=ok positions=4 "
    "markets={'totals': {'would_build': 3}, 'strikeouts': {'market_unresolved': 1}} "
    "examples={'totals|would_build': 'tsc-cfb-unlv-akron-2026-09-26-total-51pt5 @ 0.5', "
    "'strikeouts|market_unresolved': 'astatc-mlb-az-col-2026-09-22-k-micsor-gte5'}",
)
# Verbatim from 16:35:04Z -- the first pass after `f15ffb80`, the same family building.
AFTER = (
    "2026-09-22T16:35:04.815423568Z",
    "[live_odds_worker] ORDER_PATH venue=polymarket status=ok positions=2 "
    "markets={'totals': {'would_build': 1}, 'strikeouts': {'would_build': 1}} "
    "examples={'totals|would_build': 'tsc-cfb-tcu-ucf-2026-09-26-total-49pt5 @ 0.49', "
    "'strikeouts|would_build': 'astatc-mlb-az-col-2026-09-22-k-micsor-gte5 @ 0.46'}",
)


def _rep(lines, **kw):
    return census(lines, **kw)


# ------------------------------------------------------- the case it was built for
def test_the_real_pre_fix_lines_ALERT_on_strikeouts():
    report = _rep([BEFORE] * 4)
    assert report["verdict"] == "ALERT", render(report)
    assert exit_code(report) == EXIT_ALERT
    alerts = {(a["venue"], a["family"]) for a in report["alerts"]}
    assert alerts == {("polymarket", "strikeouts")}, alerts
    row = report["alerts"][0]
    assert row["builds"] == 0 and row["occurrences"] == 4
    assert row["refusals"] == {"market_unresolved": 4}
    # totals built in the same passes and must NOT be flagged.
    assert report["venues"]["polymarket"]["families"]["totals"]["builds"] == 12


def test_the_real_post_fix_lines_are_CLEAR():
    report = _rep([AFTER] * 4)
    assert report["verdict"] == "CLEAR", render(report)
    assert exit_code(report) == EXIT_CLEAR
    assert report["alerts"] == []


def test_one_build_in_the_window_clears_a_family_that_otherwise_refuses():
    """The bound is ZERO builds, not 'mostly refuses'. A family that reaches the
    venue even once is not the silent-zero failure this exists for."""
    report = _rep([BEFORE] * 20 + [AFTER])
    assert report["verdict"] == "CLEAR", render(report)
    assert report["venues"]["polymarket"]["families"]["strikeouts"]["builds"] == 1


# ------------------------------------------------------------------ the bound
def test_a_single_refusal_is_watched_not_alerted():
    report = _rep([BEFORE])
    assert report["alerts"] == []
    assert [(w["venue"], w["family"]) for w in report["watch"]] == [("polymarket", "strikeouts")]
    assert report["verdict"] == "CLEAR"
    assert "reported, not alerted" in render(report)


def test_min_occurrences_is_tunable():
    report = _rep([BEFORE], min_occurrences=1)
    assert [(a["venue"], a["family"]) for a in report["alerts"]] == [("polymarket", "strikeouts")]


# --------------------------------------------- unknown must not read as healthy
def test_no_lines_is_INCONCLUSIVE_not_clear():
    report = _rep([])
    assert report["verdict"] == "INCONCLUSIVE"
    assert exit_code(report) == EXIT_INCONCLUSIVE
    assert "silent" in report["reason"]


def test_an_unreadable_markets_payload_is_INCONCLUSIVE():
    bad = ("2026-09-22T16:00:00Z",
           "[live_odds_worker] ORDER_PATH venue=kalshi status=ok positions=2 "
           "markets={'totals': {'would_build': truncated examples={}")
    report = _rep([AFTER, bad])
    assert report["verdict"] == "INCONCLUSIVE", render(report)
    assert exit_code(report) == EXIT_INCONCLUSIVE
    assert report["unreadable"], "the unreadable line must be named, not silently dropped"


def test_an_unreadable_line_never_counts_as_a_build():
    bad = ("2026-09-22T16:00:00Z",
           "[live_odds_worker] ORDER_PATH venue=polymarket status=ok positions=1 "
           "markets={'strikeouts': {'would_bui")
    report = _rep([bad] * 5)
    assert report["venues"]["polymarket"]["families"] == {}
    assert report["verdict"] == "INCONCLUSIVE"


def test_ORDER_PATH_FAILED_is_not_counted_as_unreadable():
    """The emitter's own failure line has no `markets=` and is not a census row;
    counting it as unreadable would make every such cycle INCONCLUSIVE forever."""
    failed = ("2026-09-22T16:00:00Z", "[live_odds_worker] ORDER_PATH_FAILED KeyError: 'plan'")
    report = _rep([AFTER, failed])
    assert report["verdict"] == "CLEAR", render(report)
    assert report["unreadable"] == []


# ------------------------------------------------------------------ shape
def test_a_venue_with_no_positions_reports_and_does_not_alert():
    idle = ("2026-09-22T16:00:00Z",
            "[live_odds_worker] ORDER_PATH venue=kalshi status=no_positions positions=0 markets={} examples={}")
    report = _rep([AFTER, idle])
    assert report["verdict"] == "CLEAR"
    kalshi = report["venues"]["kalshi"]
    assert kalshi["passes"] == 1 and kalshi["families"] == {}
    assert kalshi["statuses"] == {"no_positions": 1}
    assert "(no market families in any pass)" in render(report)


def test_both_venues_are_censused_independently():
    kalshi_bad = ("2026-09-22T16:10:00Z",
                  "[live_odds_worker] ORDER_PATH venue=kalshi status=ok positions=3 "
                  "markets={'batter_home_runs': {'no_venue_ticker': 3}} examples={}")
    report = _rep([AFTER] * 3 + [kalshi_bad] * 3)
    assert {(a["venue"], a["family"]) for a in report["alerts"]} == {("kalshi", "batter_home_runs")}
    assert set(report["venues"]) == {"kalshi", "polymarket"}


def test_the_census_prints_every_family_including_the_healthy_ones():
    """A line printed only on failure cannot tell a healthy day from a day the
    instrument stopped -- the same rule the emitter itself follows."""
    text = render(_rep([BEFORE] * 3 + [AFTER]))
    assert "totals" in text and "strikeouts" in text
    assert "passes=" in text and "builds=" in text


def test_positions_and_window_are_reported():
    report = _rep([BEFORE, AFTER])
    venue = report["venues"]["polymarket"]
    assert venue["passes"] == 2 and venue["positions_total"] == 6
    assert venue["first_seen"] == BEFORE[0] and venue["last_seen"] == AFTER[0]
