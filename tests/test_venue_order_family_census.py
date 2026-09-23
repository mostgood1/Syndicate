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

import pytest  # noqa: E402

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


# ===========================================================================
# THE PLACEMENT HALF -- `ORDER_PATH` says a position WOULD build; `EXECUTED`
# says whether anything reached the venue. Reading only the first called
# 2026-09-23 CLEAR for kalshi while all 11 positions died at
# `insufficient_venue_balance`. Lines below are verbatim from production.
# ===========================================================================

KALSHI_BROKE = (
    "2026-09-23T16:01:12.673223488Z",
    "[execute_portfolio] EXECUTED date=2026-09-23 mode=live venue=kalshi plan_source=live armed=True "
    "positions=7 placed=0 filled=0 failed=0 duplicates=0 retried=0 skipped=7 "
    "refused={'insufficient_venue_balance': 7} spent={'dollars': 0.0, 'orders': 0} summary={'selected_date': '2026-09-23'}",
)
POLY_BROKE = (
    "2026-09-23T16:01:24.552789787Z",
    "[execute_portfolio] EXECUTED date=2026-09-23 mode=live venue=polymarket plan_source=live armed=True "
    "positions=4 placed=0 filled=0 failed=0 duplicates=0 retried=0 skipped=4 "
    "refused={'insufficient_venue_balance': 4} spent={'dollars': 5.67, 'orders': 4} summary={'selected_date': '2026-09-23'}",
)
POLY_PLACING = (
    "2026-09-22T16:35:29.247140022Z",
    "[execute_portfolio] EXECUTED date=2026-09-22 mode=live venue=polymarket plan_source=live armed=True "
    "positions=2 placed=1 filled=0 failed=0 duplicates=1 retried=0 skipped=0 refused={} "
    "spent={'dollars': 3.31, 'orders': 3} summary={'selected_date': '2026-09-22'}",
)


def test_a_venue_that_builds_and_places_nothing_ALERTS():
    """The blind spot itself."""
    report = census([AFTER] * 3, exec_lines=[POLY_BROKE] * 3, placement_checked=True)
    assert report["verdict"] == "ALERT", render(report)
    assert exit_code(report) == EXIT_ALERT
    row = report["placement_alerts"][0]
    assert row["venue"] == "polymarket" and row["status"] == "never_places"
    assert row["placed"] == 0 and row["positions"] == 12
    assert row["refusals"] == {"insufficient_venue_balance": 12}
    assert "places nothing" in report["reason"]


def test_a_DECLARED_dormant_venue_is_reported_and_does_not_alert():
    """User decision 2026-09-23: kalshi is unfunded on purpose. Declaring it
    states the expectation; it must still be printed, never hidden."""
    report = census([AFTER] * 3, exec_lines=[KALSHI_BROKE, POLY_PLACING],
                    dormant_venues=["kalshi"], placement_checked=True)
    assert report["verdict"] == "CLEAR", render(report)
    assert report["placement"]["kalshi"]["status"] == "dormant_by_decision"
    assert report["placement"]["kalshi"]["declared_dormant"] is True
    text = render(report)
    assert "kalshi PLACEMENT: dormant_by_decision" in text and "declared dormant" in text


def test_a_dormant_venue_that_PLACES_alerts_because_the_declaration_is_stale():
    """Checked in BOTH directions: the day kalshi is funded, a stale
    --dormant-venue must not quietly suppress the venue."""
    funded = (POLY_PLACING[0], POLY_PLACING[1].replace("venue=polymarket", "venue=kalshi"))
    report = census([AFTER], exec_lines=[funded, POLY_PLACING], dormant_venues=["kalshi"], placement_checked=True)
    assert report["verdict"] == "ALERT"
    assert report["placement_alerts"][0]["status"] == "placing_while_declared_dormant"
    assert "declared dormant and PLACED" in report["reason"]


def test_a_placing_venue_is_clear():
    report = census([AFTER], exec_lines=[POLY_PLACING], placement_checked=True)
    assert report["verdict"] == "CLEAR", render(report)
    assert report["placement"]["polymarket"]["status"] == "placing"
    assert report["placement"]["polymarket"]["placed_total"] == 1


def test_a_pass_with_no_positions_is_not_a_placement_failure():
    idle = (POLY_BROKE[0], POLY_BROKE[1].replace("positions=4", "positions=0").replace(
        "refused={'insufficient_venue_balance': 4}", "refused={}"))
    report = census([AFTER], exec_lines=[idle], placement_checked=True)
    assert report["placement"]["polymarket"]["status"] == "no_positions"
    assert report["verdict"] == "CLEAR"


def test_a_PAPER_pass_is_ignored():
    """Paper places nothing by definition; counting it would make every venue
    look dead."""
    paper = (POLY_BROKE[0], POLY_BROKE[1].replace("mode=live", "mode=paper"))
    report = census([AFTER], exec_lines=[paper], placement_checked=True)
    assert report["placement"] == {}
    assert report["verdict"] == "INCONCLUSIVE"
    assert "no live EXECUTED line" in report["reason"]


def test_building_with_NO_live_execution_line_is_INCONCLUSIVE_not_clear():
    report = census([AFTER], exec_lines=[], placement_checked=True)
    assert report["verdict"] == "INCONCLUSIVE"
    assert exit_code(report) == EXIT_INCONCLUSIVE
    assert report["placement_unknown"] == ["polymarket"]
    assert "polymarket PLACEMENT: UNKNOWN" in render(report)


def test_not_asking_about_placement_is_not_the_same_as_asking_and_finding_none():
    """An empty `exec_lines` cannot tell those apart, so the caller says which.
    The family-half-only call keeps the old verdict AND says what it did not check."""
    report = census([AFTER])
    assert report["verdict"] == "CLEAR"
    assert report["placement_checked"] is False and report["placement_unknown"] == []
    assert "placement: NOT CHECKED" in render(report)


def test_an_unreadable_refused_payload_is_INCONCLUSIVE():
    bad = (POLY_BROKE[0], POLY_BROKE[1].replace("refused={'insufficient_venue_balance': 4}",
                                                "refused={'insufficient_venue_ba"))
    report = census([AFTER], exec_lines=[bad], placement_checked=True)
    assert report["verdict"] == "INCONCLUSIVE", render(report)
    assert any("refused_unreadable" in u for u in report["unreadable"])


def test_both_halves_failing_are_both_named_in_the_reason():
    report = census([BEFORE] * 4, exec_lines=[POLY_BROKE] * 2, placement_checked=True)
    assert report["verdict"] == "ALERT"
    assert "zero builds" in report["reason"] and "places nothing" in report["reason"]


@pytest.mark.parametrize("venue_arg", ["kalshi", "KALSHI", " Kalshi "])
def test_the_dormant_declaration_is_case_and_space_insensitive(venue_arg):
    report = census([AFTER], exec_lines=[KALSHI_BROKE, POLY_PLACING],
                    dormant_venues=[venue_arg], placement_checked=True)
    assert report["placement"]["kalshi"]["status"] == "dormant_by_decision"


def test_a_measured_failure_outranks_an_unknown_and_the_unknown_is_still_named():
    """One venue missing its EXECUTED line must not bury another venue's
    measured failure -- both exits are non-zero, so ALERT first loses nothing."""
    kalshi_path = (AFTER[0], AFTER[1].replace("venue=polymarket", "venue=kalshi"))
    report = census([AFTER, kalshi_path], exec_lines=[POLY_BROKE], placement_checked=True)
    assert report["verdict"] == "ALERT", render(report)
    assert "polymarket builds and places nothing" in report["reason"]
    assert "placement UNKNOWN for kalshi" in report["reason"]


def test_the_placement_row_says_WHEN_it_last_placed():
    """`placing` over a window is true and not the whole answer: a venue can
    place early and refuse for hours after. Measured 2026-09-23: polymarket
    placed 12 and then refused 406 straight."""
    report = census([AFTER], exec_lines=[POLY_PLACING, POLY_BROKE], placement_checked=True)
    row = report["placement"]["polymarket"]
    assert row["status"] == "placing" and row["last_placed"] == POLY_PLACING[0]
    assert row["last_seen"] == POLY_BROKE[0], "the window still ends at the latest pass"
    assert "last_placed=2026-09-22T16:35:29" in render(report)


def test_a_venue_that_never_placed_says_so_rather_than_printing_nothing():
    report = census([AFTER], exec_lines=[POLY_BROKE], placement_checked=True)
    assert report["placement"]["polymarket"]["last_placed"] is None
    assert "last_placed=never in this window" in render(report)

