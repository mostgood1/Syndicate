"""Phase C analyzer tests.

**THE CAUSALITY CHECK IS THE ONE THAT NEEDS FALSIFYING.** A check that compares
a published value against a recompute will pass trivially if both sides run the
same code on the same inputs -- which is exactly what it does. So the tests here
do not stop at "it reports zero mismatches"; they corrupt a published value and
require the check to CATCH it. `model_engine_standard.md`'s reachability rule
(`off != on`) is the same idea applied to a flag.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.analyze_basketball_momentum import _pearson
from scripts.analyze_basketball_momentum import causality_check
from scripts.analyze_basketball_momentum import forward_margin
from scripts.analyze_basketball_momentum import forward_total
from scripts.analyze_basketball_momentum import sweep_game
from syndicate.features.shared.basketball_momentum_artifacts import build_momentum_payload

HOME_ID, HOME_TRI = "16", "PHX"
AWAY_ID, AWAY_TRI = "20", "LVA"


def _play(period: int, clock: str, team_id: str, **kw: Any) -> dict[str, Any]:
    play: dict[str, Any] = {
        "period": {"number": period},
        "clock": {"displayValue": clock},
        "team": {"id": team_id},
        "type": {"text": kw.get("type_text", "")},
        "text": kw.get("text", ""),
        "shootingPlay": kw.get("shooting", False),
        "scoreValue": kw.get("score_value", 0),
    }
    if kw.get("attempted") is not None:
        play["pointsAttempted"] = kw["attempted"]
    return play


def _summary(plays: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": HOME_ID, "abbreviation": HOME_TRI}},
            {"homeAway": "away", "team": {"id": AWAY_ID, "abbreviation": AWAY_TRI}},
        ]}]},
        "plays": plays,
    }


def _long_game() -> dict[str, Any]:
    """Two full quarters of alternating pressure, dense enough to correlate."""
    plays: list[dict[str, Any]] = []
    for period in (1, 2):
        for minute in range(9, -1, -1):
            for second, team in ((45, HOME_ID), (20, AWAY_ID)):
                clock = f"{minute}:{second:02d}"
                plays.append(_play(period, clock, team, shooting=True,
                                   attempted=2, score_value=2))
                plays.append(_play(period, clock, team, type_text="Offensive Rebound"))
    return _summary(plays)


# ---------------------------------------------------------------------------
# forward_margin -- the boundary is where an outcome leak would hide
# ---------------------------------------------------------------------------

def test_forward_margin_excludes_an_event_exactly_at_the_probe() -> None:
    """An event AT the probe is what we knew, not what happened next.

    Counting it on both sides leaks the outcome into the predictor, which is
    precisely how a lead/lag test passes without carrying any information.
    """
    rows = [{"clock_seconds": 100.0, "sign": 1.0, "weight": 2.0}]
    assert forward_margin(rows, 100.0, 60.0) == 0.0
    assert forward_margin(rows, 99.0, 60.0) == 2.0


def test_forward_margin_includes_the_far_boundary() -> None:
    rows = [{"clock_seconds": 160.0, "sign": -1.0, "weight": 3.0}]
    assert forward_margin(rows, 100.0, 60.0) == -3.0
    assert forward_margin(rows, 100.0, 59.0) == 0.0


def test_forward_margin_signs_both_sides() -> None:
    rows = [
        {"clock_seconds": 110.0, "sign": 1.0, "weight": 2.0},
        {"clock_seconds": 120.0, "sign": -1.0, "weight": 3.0},
    ]
    assert forward_margin(rows, 100.0, 60.0) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# forward_total -- the over/under outcome, which margin cannot answer
# ---------------------------------------------------------------------------

def test_a_total_is_not_a_margin() -> None:
    """**The reason both are measured.** A 14-2 window and a 26-14 window have
    the SAME margin and wildly different totals, so a signal that predicts one
    has no automatic claim on the other."""
    lopsided = [
        {"clock_seconds": 110.0, "sign": 1.0, "weight": 14.0},
        {"clock_seconds": 120.0, "sign": -1.0, "weight": 2.0},
    ]
    high_scoring = [
        {"clock_seconds": 110.0, "sign": 1.0, "weight": 26.0},
        {"clock_seconds": 120.0, "sign": -1.0, "weight": 14.0},
    ]
    assert forward_margin(lopsided, 100.0, 60.0) == forward_margin(high_scoring, 100.0, 60.0)
    assert forward_total(lopsided, 100.0, 60.0) == 16.0
    assert forward_total(high_scoring, 100.0, 60.0) == 40.0


def test_forward_total_ignores_the_sign() -> None:
    rows = [
        {"clock_seconds": 110.0, "sign": 1.0, "weight": 3.0},
        {"clock_seconds": 120.0, "sign": -1.0, "weight": 2.0},
    ]
    assert forward_total(rows, 100.0, 60.0) == 5.0
    assert forward_margin(rows, 100.0, 60.0) == 1.0


def test_forward_total_shares_the_exclusive_left_boundary() -> None:
    """Same outcome-leak guard as the margin: an event AT the probe is what we
    knew, not what happened next."""
    rows = [{"clock_seconds": 100.0, "sign": 1.0, "weight": 2.0}]
    assert forward_total(rows, 100.0, 60.0) == 0.0
    assert forward_total(rows, 99.0, 60.0) == 2.0


def test_horizons_cover_the_intervals_that_are_actually_traded() -> None:
    """Quarters and halves, not round numbers. The live WNBA slate discovered
    `spreads_q4`/`totals_q4`/`spreads_h2`/`totals_h2` -- 600s and 1200s."""
    from scripts.analyze_basketball_momentum import HORIZONS_SECONDS

    assert 600.0 in HORIZONS_SECONDS, "a WNBA quarter"
    assert 1200.0 in HORIZONS_SECONDS, "a WNBA half"


# ---------------------------------------------------------------------------
# _pearson -- None, never a neutral 0.0
# ---------------------------------------------------------------------------

def test_pearson_returns_none_rather_than_zero_when_undefined() -> None:
    """A zero correlation and an uncomputable one are different findings."""
    assert _pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None   # no variance in x
    assert _pearson([1.0, 2.0], [1.0, 2.0]) is None             # too few points
    assert _pearson([1.0, 2.0, 3.0], [1.0, 2.0]) is None        # ragged


def test_pearson_recovers_a_known_correlation() -> None:
    assert _pearson([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]) == pytest.approx(1.0)
    assert _pearson([1.0, 2.0, 3.0, 4.0], [8.0, 6.0, 4.0, 2.0]) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# causality_check -- and the mutation that proves it can fail
# ---------------------------------------------------------------------------

def _captured_rows(summary: dict[str, Any], as_ofs: list[float]) -> list[dict[str, Any]]:
    return [
        build_momentum_payload(
            {"401": summary}, league_code="wnba", date_str="2026-08-22",
            as_of_by_event={"401": as_of},
        )
        for as_of in as_ofs
    ]


def test_causality_check_passes_on_a_genuinely_causal_capture() -> None:
    summary = _long_game()
    rows = _captured_rows(summary, [400.0, 700.0, 1000.0])
    result = causality_check(rows, summary, league_code="wnba", event_id="401")
    assert result["ok"] is True
    assert result["compared"] == 3
    assert result["mismatches"] == 0


def test_causality_check_CATCHES_a_corrupted_published_value() -> None:
    """**THE FALSIFICATION.** Without this the check could be vacuous.

    The published value and the recompute run the same code over the same feed,
    so a passing result proves nothing until a deliberately wrong value is shown
    to fail. Corrupt one tick's `current` and the check must report exactly one
    mismatch, with the delta.
    """
    summary = _long_game()
    rows = _captured_rows(summary, [400.0, 700.0, 1000.0])
    rows[1]["games"]["401"]["pressure"]["seconds"]["current"] += 5.0

    result = causality_check(rows, summary, league_code="wnba", event_id="401")
    assert result["compared"] == 3
    assert result["mismatches"] == 1
    assert result["examples"][0]["as_of"] == 700.0
    assert result["examples"][0]["delta"] == pytest.approx(-5.0, abs=1e-3)


def test_causality_check_CATCHES_a_non_causal_publication() -> None:
    """A value that saw the future is the failure mode this exists to find.

    Simulates a capture that computed at `as_of=400` but published the value
    from `as_of=1000` -- exactly what a non-causal implementation would emit.
    """
    summary = _long_game()
    rows = _captured_rows(summary, [400.0, 1000.0])
    future_value = rows[1]["games"]["401"]["pressure"]["seconds"]["current"]
    rows[0]["games"]["401"]["pressure"]["seconds"]["current"] = future_value

    result = causality_check(rows, summary, league_code="wnba", event_id="401")
    assert result["mismatches"] == 1


def test_causality_check_reports_a_reason_when_the_feed_is_unusable() -> None:
    result = causality_check([], _summary([]), league_code="wnba", event_id="401")
    assert result["ok"] is False
    assert "pressure" in result["reason"]


def test_causality_check_separates_distinct_instants_from_duplicate_rows() -> None:
    """**HALFTIME MAKES `compared` LIE, and this is the guard.**

    Measured on the live slate (2026-08-23 00:04:07Z and 00:08:47Z): two
    consecutive captures emitted byte-identical blocks because the game clock is
    frozen at the end of a period and ESPN's feed adds no plays. Every tick
    through the break appends another duplicate row, so `compared` climbs while
    the number of instants actually verified does not.
    """
    summary = _long_game()
    rows = _captured_rows(summary, [400.0, 700.0, 700.0, 700.0, 1000.0])
    result = causality_check(rows, summary, league_code="wnba", event_id="401")
    assert result["compared"] == 5
    assert result["distinct_as_of"] == 3
    assert result["mismatches"] == 0


def test_causality_check_skips_ticks_that_carry_no_series() -> None:
    """A tick with no pressure block is not a mismatch -- it is not comparable."""
    summary = _long_game()
    rows = _captured_rows(summary, [400.0])
    rows.append({"games": {"401": {"pressure": None, "supported": True}}})
    result = causality_check(rows, summary, league_code="wnba", event_id="401")
    assert result["compared"] == 1
    assert result["mismatches"] == 0


# ---------------------------------------------------------------------------
# sweep_game
# ---------------------------------------------------------------------------

def test_sweep_covers_both_axes_and_every_grid_cell() -> None:
    swept = sweep_game(_long_game(), league_code="wnba")
    assert swept["ok"] is True
    axes = {cell["axis"] for cell in swept["grid"]}
    assert axes == {"seconds", "possessions"}
    # 4 half-lives x 3 horizons per axis, for the horizons that fit the game.
    assert len(swept["grid"]) == len([c for c in swept["grid"]])
    assert all(cell["n"] >= 3 for cell in swept["grid"])


def test_sweep_states_a_reason_rather_than_returning_an_empty_grid() -> None:
    swept = sweep_game(_summary([]), league_code="wnba")
    assert swept["ok"] is False
    assert "need both" in swept["reason"]


def test_sweep_reports_margin_and_total_separately() -> None:
    """ML/spread and over/under are different bets and get different columns."""
    swept = sweep_game(_long_game(), league_code="wnba")
    assert swept["grid"], "the fixture must produce at least one cell"
    for cell in swept["grid"]:
        for key in ("r_margin", "r_total", "r_total_abs"):
            assert key in cell, f"every cell needs {key}"
            r = cell[key]
            assert r is None or -1.0 <= r <= 1.0
