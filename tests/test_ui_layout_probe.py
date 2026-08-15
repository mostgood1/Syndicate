"""`summarize()` must never let an unfinished measurement read as a clean one.

Every case here is a real failure this harness produced against production
before it was fixed, not a hypothetical:

  * a 502 printed a full table and exit 0, because Render's error page has no
    cards and does not overflow;
  * MLB reported `0 cards` on a slate of 15, because the probe waited on a
    fixed 400ms timer and MLB renders through `cards_source.js` after `load`;
  * a numeric class matching zero elements was dropped from the report
    entirely, so NCAAF passed a tabular-figures check it had never run.

The shape they share is the thing under test: a value meaning *"this was not
measured"* must not travel the same path as a value meaning *"this is fine"*.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_probe():
    """Import the script by path -- `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "ui_layout_probe", REPO_ROOT / "scripts" / "ui_layout_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


def _report(sport="mlb", **measured):
    base = {
        "httpStatus": 200,
        "cards": 15,
        "overflowPx": 0,
        "cardHeightSpread": 40,
        "cardWaitTimedOut": False,
        "tabsWithoutPanel": [],
        "panelsWithoutTab": [],
        "tabularFigures": {".cards-data-pair strong": {"count": 9, "values": {"tabular-nums": 9}}},
        "numericSweep": [],
        "repeatedCopy": [],
        "emptyRegions": [],
        "typeScale": {},
        "unstyledLinks": [],
        "touchTargetFailures": [],
    }
    base.update(measured)
    return {
        "baseUrl": "http://x",
        # The out-of-season set travels ON the report, not as a module
        # constant, so `--expect-cards` can override it per run.
        "outOfSeason": sorted(probe.OUT_OF_SEASON),
        "sports": {sport: {"route": "/x", "desktop": base, "mobile": dict(base)}},
    }


def _summarize(report):
    lines, ok = probe.summarize(report)
    return "\n".join(lines), ok


def test_clean_run_passes():
    text, ok = _summarize(_report())
    assert ok, text
    assert "ok" in text


def test_card_wait_timeout_fails_and_is_not_called_an_empty_slate():
    """The MLB flake. 0 cards from an unfinished render is its own state."""
    text, ok = _summarize(_report(cards=0, cardWaitTimedOut=True))
    assert not ok
    assert "NO CARD ATTACHED" in text
    assert "render did not finish" in text
    # It must NOT be reported as a legitimately empty slate.
    assert "0 cards served" not in text


def test_card_wait_timeout_fails_even_for_an_out_of_season_sport():
    """`nothing to show` resolves fast; a 20s timeout is an anomaly regardless."""
    sport = sorted(probe.OUT_OF_SEASON)[0]
    text, ok = _summarize(_report(sport=sport, cards=0, cardWaitTimedOut=True))
    assert not ok, f"{sport} timeout must fail even though it is out of season:\n{text}"
    assert "NO CARD ATTACHED" in text


def test_zero_cards_without_a_timeout_is_tolerated_only_out_of_season():
    sport = sorted(probe.OUT_OF_SEASON)[0]
    _, ok_out = _summarize(_report(sport=sport, cards=0))
    assert ok_out, "an out-of-season sport serving 0 cards is a legitimate 0"

    _, ok_in = _summarize(_report(sport="mlb", cards=0))
    assert not ok_in, "0 cards on an in-season sport must fail"


def test_http_error_fails_and_disclaims_everything_below_it():
    text, ok = _summarize(_report(httpStatus=502, cards=0))
    assert not ok
    assert "HTTP 502" in text
    assert "NOTHING BELOW IS A MEASUREMENT" in text


def test_numeric_class_matching_nothing_fails_rather_than_vanishing():
    """NCAAF served 16 cards and matched zero `.cards-market-main`."""
    text, ok = _summarize(
        _report(tabularFigures={".cards-market-main": {"count": 0, "values": {}}})
    )
    assert not ok
    assert "measurement did NOT run" in text


def test_declared_exemption_passes_when_the_class_is_absent():
    """NCAAF has no market tile row; asserting one is asserting a design it lacks.

    This is opt-out BY NAME with a reason, the same shape as OUT_OF_SEASON --
    silent absence stays a failure, declared absence does not.
    """
    text, ok = _summarize(
        _report(sport="ncaaf", tabularFigures={".cards-market-main": {"count": 0, "values": {}}})
    )
    assert ok, text
    assert "measurement did NOT run" not in text


def test_declared_exemption_is_checked_in_the_other_direction_too():
    """An exemption is a claim that can rot. If the class appears, say so."""
    text, ok = _summarize(
        _report(
            sport="ncaaf",
            tabularFigures={".cards-market-main": {"count": 4, "values": {"tabular-nums": 4}}},
        )
    )
    assert not ok
    assert "STALE EXEMPTION" in text


def test_exemption_is_scoped_to_its_sport():
    """The same absent class on a sport that DOES have the row still fails."""
    text, ok = _summarize(
        _report(sport="nfl", tabularFigures={".cards-market-main": {"count": 0, "values": {}}})
    )
    assert not ok
    assert "measurement did NOT run" in text


def test_proportional_digits_fail():
    text, ok = _summarize(
        _report(tabularFigures={".cards-market-main": {"count": 4, "values": {"normal": 4}}})
    )
    assert not ok
    assert "proportional digits" in text


def test_missing_out_of_season_key_fails_closed():
    """A report with no `outOfSeason` must treat every 0 as suspect.

    Found by this suite: the set is data on the report, so a caller that omits
    it gets the STRICT reading rather than a permissive one. That is the
    correct direction and is worth pinning -- the opposite default would let a
    real outage pass on any sport.
    """
    report = _report(sport="nba", cards=0)
    report.pop("outOfSeason")
    _, ok = _summarize(report)
    assert not ok


def test_printed_spread_is_the_within_state_figure_not_the_slate_wide_one():
    """MLB's across-slate spread swung 796 -> 1716px with no code change.

    Measured on production 2026-08-15, 15 cards at 390px: Preview n=10 spread
    80px, Final n=2 spread 82px, Live n=3 spread 1393px. The layout is tight
    inside a state; the overall number reports how many games are live, so it
    cannot catch a layout regression.
    """
    text, _ = _summarize(
        _report(cardHeightSpread=1716, cardHeightSpreadWithinState=82)
    )
    assert "82px" in text
    assert "1716px" not in text


def test_printed_spread_falls_back_when_no_state_breakdown_exists():
    report = _report(cardHeightSpread=40)
    for label in ("desktop", "mobile"):
        report["sports"]["mlb"][label].pop("cardHeightSpreadWithinState", None)
    text, _ = _summarize(report)
    assert "40px" in text


def _model(**over):
    base = {"state": "Preview", "n": 10, "pxPerUnit": 62.5, "chromePx": 1029,
            "residualSpread": 54, "maxAbsResidual": 28, "fitRatio": 0.05,
            "explainedPx": 745, "groupHeightSpread": 797,
            "contentIndependent": False, "reliable": True,
            "worstCard": {"u": 45, "h": 3846, "residual": 28}}
    base.update(over)
    return base


def test_a_healthy_slate_passes_the_layout_model():
    """Production baseline 2026-08-15: mlb mobile Preview residual 54px."""
    text, ok = _summarize(_report(heightModel=_model()))
    assert ok, text
    assert "layout residual 54px in Preview" in text


def test_a_card_off_the_height_model_fails():
    """The falsification case: tall at constant content is a layout defect."""
    text, ok = _summarize(_report(heightModel=_model(
        residualSpread=420, maxAbsResidual=390,
        worstCard={"u": 45, "h": 4266, "residual": 390})))
    assert not ok
    assert "LAYOUT RESIDUAL OVER BUDGET" in text
    assert "+390px at 45 pairs" in text


def test_content_independent_reports_the_raw_spread_as_the_signal():
    """At 1440 the summary grid wraps, so a pair adds width not height.

    Measured: slope 0.4-5.5px/pair on desktop against 62px/pair on mobile, same
    cards same instant. Where content does not drive height the raw spread IS
    the layout signal -- calling that "no signal" was this metric's own bug.
    """
    text, ok = _summarize(_report(heightModel=_model(
        state="Final", pxPerUnit=0.4, explainedPx=10, groupHeightSpread=95,
        residualSpread=11, fitRatio=2.0, reliable=False, contentIndependent=True)))
    assert ok, text
    assert "layout spread 95px in Final" in text
    assert "content-independent" in text
    assert "UNRELIABLE" not in text


def test_content_independent_over_budget_fails():
    text, ok = _summarize(_report(heightModel=_model(
        state="Final", pxPerUnit=0.4, explainedPx=10, groupHeightSpread=420,
        residualSpread=11, fitRatio=2.0, reliable=False, contentIndependent=True)))
    assert not ok
    assert "LAYOUT SPREAD OVER BUDGET" in text
    assert "content not driving height" in text


def test_an_unreliable_fit_is_neither_an_alarm_nor_a_pass():
    """Desktop's grid is not linear in pairs: 201px residual over 261px range.

    Failing on that would make the run permanently red on a healthy board,
    which is how a guard gets ignored. It reports having no signal instead.
    """
    text, ok = _summarize(_report(heightModel=_model(
        state="Preview", residualSpread=201, fitRatio=0.77, reliable=False)))
    assert ok, text
    assert "UNRELIABLE" in text
    assert "no layout signal here" in text
    assert "OVER BUDGET" not in text


def test_a_render_that_never_settles_fails():
    """MLB was measured at 74% of its content under the old fixed settle."""
    text, ok = _summarize(_report(renderSettled=False))
    assert not ok
    assert "RENDER NEVER SETTLED" in text
    assert "mid-render" in text


def test_states_that_could_not_be_fitted_are_named_not_silent():
    text, _ = _summarize(_report(heightModel=_model(), statesUnfitted=["Final"]))
    assert "no layout fit for: Final" in text


def test_the_residual_budget_is_not_wide_enough_to_hide_an_extra_block():
    """~62px per pair on mobile; every real panel is larger than that."""
    assert probe.LAYOUT_RESIDUAL_BUDGET_PX < 300


def _compare(base, cur):
    lines, ok = probe.compare(base, cur)
    return "\n".join(lines), ok


def test_slate_movement_alone_does_not_fail_a_comparison():
    """Card-height spread read 796/1716/1583/1125px in one evening, no deploy."""
    base = _report(cardHeightSpread=796, cards=15)
    cur = _report(cardHeightSpread=1716, cards=12)
    text, ok = _compare(base, cur)
    assert ok, text
    assert "slate moved" in text
    assert "cardHeightSpread 796 -> 1716" in text
    assert "stable metrics unchanged" in text


def test_code_driven_drift_fails_the_comparison():
    """Overflow is a property of the CSS. An evening of games cannot move it."""
    base = _report(overflowPx=0)
    cur = _report(overflowPx=28)
    text, ok = _compare(base, cur)
    assert not ok
    assert "CODE-DRIVEN DRIFT" in text
    assert "overflowPx 0 -> 28" in text


def test_tab_wiring_drift_is_code_driven_too():
    base = _report(panelsWithoutTab=[])
    cur = _report(panelsWithoutTab=["coverage", "identity"])
    text, ok = _compare(base, cur)
    assert not ok
    assert "panelsWithoutTab 0 -> 2" in text


def test_an_http_error_on_either_side_is_not_a_comparison():
    base = _report()
    cur = _report(httpStatus=502, cards=0)
    text, ok = _compare(base, cur)
    assert not ok
    assert "SKIPPED" in text


def test_a_sport_absent_from_the_baseline_is_named_not_silently_passed():
    base = _report(sport="mlb")
    cur = _report(sport="nfl")
    text, _ = _compare(base, cur)
    assert "NEW -- not in baseline" in text


def test_card_wait_constant_is_generous_enough_for_a_js_render():
    """Guards the regression directly: MLB needed >600ms and got 400."""
    assert probe.CARD_WAIT_MS >= 10000
