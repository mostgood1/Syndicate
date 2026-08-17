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
        # A healthy slate under the peer rule: every card tied, deviation small.
        "identicalContentSpreadByState": {
            "Preview": {"spreadPx": 40, "atU": 45, "n": 15, "cardsTied": 15,
                        "worstGroupPx": 40, "tiedGroups": 1,
                        "medianH": 3800, "spreadPct": 1.1},
        },
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


class _ScriptedPage:
    """Replays one fingerprint per poll. `wait_for_timeout` advances the tape."""

    def __init__(self, fingerprints):
        self._tape = list(fingerprints)
        self._poll = 0

    def evaluate(self, _js):
        return self._tape[min(self._poll, len(self._tape) - 1)]

    def wait_for_timeout(self, _ms):
        self._poll += 1


def test_settle_does_not_call_a_plateau_finished():
    """The exact shape that shipped a bad row on 2026-08-16.

    mlb desktop sat still for two polls before enrichment started, and the old
    two-equal-polls rule returned `settled: true` at 800ms -- reporting 15 cards
    at a uniform 33 pairs when mobile read 33-49 on the same slate.
    """
    plateau_then_growth = [100, 100, 100, 200, 300, 400] + [400] * 10
    settle = probe._settle(_ScriptedPage(plateau_then_growth))
    assert settle["settled"] is True
    assert settle["sawChange"] is True
    # The old rule stopped at 800ms, inside the plateau, before any of the
    # growth existed. Anything that returns there is the bug.
    assert settle["settledMs"] > 800
    assert settle["finalFingerprint"] == 400


def test_a_still_dom_settles_but_says_the_verdict_rests_on_absence():
    """Seven of eight sports render server-side; a still DOM is their normal.

    So this must still settle -- but `sawChange` has to carry that the verdict
    is the absence of change, which "finished" and "never started" share.
    """
    settle = probe._settle(_ScriptedPage([700] * 20))
    assert settle["settled"] is True
    assert settle["sawChange"] is False
    assert settle["settledMs"] == probe.SETTLE_QUIET_MS


def test_a_dom_still_growing_at_the_deadline_is_a_timeout_not_a_settle():
    settle = probe._settle(_ScriptedPage(range(1, 200)))
    assert settle["settled"] is False
    assert settle["sawChange"] is True
    assert settle["settledMs"] == probe.SETTLE_MAX_MS


def test_the_quiet_window_outlasts_the_measured_growth_step():
    """The 2026-08-15 curve moved at every 400ms step through 3000ms, so no
    quiet window inside it can be mistaken for the end of the render."""
    assert probe.SETTLE_QUIET_MS >= 3 * probe.SETTLE_POLL_MS


def _widths(desktop, mobile, sport="mlb"):
    report = _report(sport=sport)
    report["sports"][sport]["desktop"].update(desktop)
    report["sports"][sport]["mobile"].update(mobile)
    return report


def test_content_contradicted_across_widths_fails_the_short_row():
    """`rerun_2026-08-16.json` mlb desktop, reproduced.

    No card renderer keys `.cards-data-pair` on viewport width, so a width
    reading LESS content while its own settle never saw the DOM change was
    measured before the slate finished arriving.
    """
    text, ok = _summarize(_widths(
        desktop={"contentUnits": {"min": 33, "max": 33, "spread": 0},
                 "renderSettled": True, "settleSawChange": False},
        mobile={"contentUnits": {"min": 33, "max": 49, "spread": 16},
                "renderSettled": True, "settleSawChange": True},
    ))
    assert not ok
    assert "CONTENT CONTRADICTED by mobile" in text
    assert "33-33 vs 33-49" in text
    assert "NOT a uniform slate" in text


def test_a_width_disagreement_alone_does_not_fail():
    """The widths are separate navigations, so the slate can genuinely grow
    between them. Disagreement is only damning against a settle with no
    affirmative evidence behind it."""
    text, ok = _summarize(_widths(
        desktop={"contentUnits": {"min": 33, "max": 40, "spread": 7},
                 "renderSettled": True, "settleSawChange": True},
        mobile={"contentUnits": {"min": 33, "max": 49, "spread": 16},
                "renderSettled": True, "settleSawChange": True},
    ))
    assert ok
    assert "CONTENT CONTRADICTED" not in text


def test_a_still_dom_is_footnoted_not_failed_when_the_widths_agree():
    units = {"min": 3, "max": 3, "spread": 0}
    text, ok = _summarize(_widths(
        desktop={"contentUnits": dict(units), "renderSettled": True, "settleSawChange": False},
        mobile={"contentUnits": dict(units), "renderSettled": True, "settleSawChange": False},
        sport="nfl",
    ))
    assert ok
    assert "CONTENT CONTRADICTED" not in text
    assert "settle rests on absence" in text
    assert "nfl desktop, nfl mobile" in text


def test_a_report_predating_the_field_is_not_failed_on_it():
    """Older JSONs carry no `settleSawChange`; absent must not read as False."""
    text, ok = _summarize(_widths(
        desktop={"contentUnits": {"min": 33, "max": 33, "spread": 0}, "renderSettled": True},
        mobile={"contentUnits": {"min": 33, "max": 49, "spread": 16}, "renderSettled": True},
    ))
    assert ok
    assert "CONTENT CONTRADICTED" not in text
    assert "settle rests on absence" not in text


# --- the desktop height model: unfittable, not mis-tuned -------------------
#
# Measured on production MLB, 2026-08-16, one slate, one instant, 15 Preview
# cards. Cards with IDENTICAL pair counts still differ in height because the
# summary grid is a wrapping flow (10 columns at 1440, 2 at 390) and text width
# decides where it wraps:
#
#     desktop u=45 (n=7) 1092..1208 = 116px      mobile u=45 (n=7) = 81px
#     desktop u=49 (n=5) 1106..1203 =  97px      mobile u=49 (n=5) = 40px
#
# Agreeing on visible pair count AND visible row count still leaves 74px on
# desktop, so this is not a missing variable either.


def _fit(pts):
    """Run the real `fitGroup` over points, via the JS the probe ships."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(
            "<div id='s'>"
            + "".join(
                f"<div class='cards-game-card' style='height:{h}px'>"
                f"<span class='cards-status-badge'>Preview</span>"
                + "<div class='cards-data-pair'>x</div>" * u
                + "</div>"
                for u, h in pts
            )
            + "</div>"
        )
        model = page.evaluate(
            probe.MEASURE_JS,
            {"typeClasses": probe.TYPE_CLASSES, "numericClasses": probe.NUMERIC_CLASSES},
        )
        browser.close()
    return (model.get("heightModelByState") or {}).get("Preview")


def _fit_tie(pts):
    """The `identicalContentSpread` block for one Preview group, via real JS."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content("".join(
            f"<div class='cards-game-card' style='height:{h}px'>"
            f"<span class='cards-status-badge'>Preview</span>"
            + "<div class='cards-data-pair'>x</div>" * u
            + "</div>"
            for u, h in pts))
        measured = page.evaluate(
            probe.MEASURE_JS,
            {"typeClasses": probe.TYPE_CLASSES, "numericClasses": probe.NUMERIC_CLASSES})
        browser.close()
    return measured["identicalContentSpread"]


DESKTOP_PTS = [(49, 1157), (49, 1197), (45, 1134), (49, 1120), (45, 1111),
               (53, 1129), (45, 1092), (49, 1106), (45, 1157), (45, 1208),
               (41, 914), (45, 1180), (45, 1180), (41, 914), (49, 1203)]
MOBILE_PTS = [(49, 4162), (49, 4174), (45, 3867), (49, 4145), (45, 3930),
              (53, 4358), (45, 3849), (49, 4134), (45, 3907), (45, 3907),
              (41, 3627), (45, 3907), (45, 3907), (41, 3657), (49, 4162)]


def test_the_desktop_slate_is_unfittable_not_merely_unreliable():
    m = _fit(DESKTOP_PTS)
    assert m["floorPx"] == 116, m
    assert m["unfittable"] is True
    # 116px of floor needs 464px of explained range to clear the 0.25 bar.
    # Desktop's content spans 197px, so no threshold rescues it.
    assert m["explainedPx"] < 4 * m["floorPx"]
    assert m["reliable"] is False


def test_the_mobile_fit_sits_exactly_on_its_own_noise_floor():
    """It passes -- but its residual IS the identical-content spread, so it is
    reporting text wrap rather than a layout deviation."""
    m = _fit(MOBILE_PTS)
    assert m["reliable"] is True
    assert m["floorPx"] == 81
    assert m["residualSpread"] == 81
    assert m["atNoiseFloor"] is True
    assert m["unfittable"] is False


def test_mobile_passes_only_because_its_slope_buys_range():
    """Same noise, four times the slope. That is the whole difference."""
    desktop, mobile = _fit(DESKTOP_PTS), _fit(MOBILE_PTS)
    assert desktop["floorPx"] >= mobile["floorPx"]
    assert mobile["explainedPx"] > 3 * desktop["explainedPx"]


def test_unfittable_is_reported_as_impossible_not_as_no_signal():
    text, ok = _summarize(_report(heightModel=_model(
        reliable=False, unfittable=True, floorPx=116, explainedPx=197, fitRatio=1.16)))
    assert ok, text
    assert "UNFITTABLE" in text
    assert "identical-content cards differ by 116px" in text
    assert "at ANY threshold" in text
    # The old wording invited a threshold tweak; it must not be what prints.
    assert "no layout signal here" not in text


def test_a_fit_on_its_noise_floor_says_so_rather_than_claiming_a_residual():
    text, ok = _summarize(_report(heightModel=_model(
        residualSpread=81, floorPx=81, atNoiseFloor=True)))
    assert ok, text
    assert "AT ITS NOISE FLOOR (81px between identical-content cards)" in text
    assert "text wrap, not layout deviation" in text


def test_a_fit_clear_of_its_floor_still_reads_as_a_real_residual():
    text, ok = _summarize(_report(heightModel=_model(
        residualSpread=54, floorPx=20, atNoiseFloor=False)))
    assert ok, text
    assert "layout residual 54px in Preview" in text
    assert "NOISE FLOOR" not in text


def test_a_slate_with_no_tied_cards_reports_no_floor_rather_than_zero():
    """No two cards share a pair count, so the floor is unmeasured -- and an
    unmeasured floor must not read as a floor of 0px (a perfect instrument)."""
    m = _fit([(41, 900), (45, 1000), (49, 1100), (53, 1200), (57, 1300)])
    assert m["floorPx"] is None
    assert m["unfittable"] is False
    assert m["atNoiseFloor"] is False


# --- the identical-content spread: collected, not judged -------------------


def test_the_floor_survives_a_slate_where_nothing_can_be_fitted():
    """The 2026-08-16 11:5x CDT slate: every card carried exactly 33 pairs, so
    there is ONE distinct `u` and no line exists -- which is precisely when 15
    mutually tied cards make this the only height signal on the page."""
    m = _fit([(33, 1100), (33, 1150), (33, 1180), (33, 1216), (33, 1120)])
    assert m is None, "a single distinct u must not produce a fit"


def test_the_floor_is_emitted_when_no_model_is():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    pts = [(33, 1100), (33, 1150), (33, 1180), (33, 1216), (33, 1120)]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(
            "".join(
                f"<div class='cards-game-card' style='height:{h}px'>"
                f"<span class='cards-status-badge'>Preview</span>"
                + "<div class='cards-data-pair'>x</div>" * u
                + "</div>"
                for u, h in pts
            )
        )
        measured = page.evaluate(
            probe.MEASURE_JS,
            {"typeClasses": probe.TYPE_CLASSES, "numericClasses": probe.NUMERIC_CLASSES},
        )
        browser.close()
    assert measured["heightModel"] is None
    assert measured["statesUnfitted"] == ["Preview"]
    tie = measured["identicalContentSpread"]
    assert tie["spreadPx"] == 116  # 1216 - 1100
    assert tie["worstGroupPx"] == 116  # one group, so both statistics agree
    assert tie["n"] == 5 and tie["atU"] == 33
    assert tie["state"] == "Preview"


def test_the_floor_is_printed_even_with_no_model():
    text, ok = _summarize(_report(
        heightModel=None,
        identicalContentSpread={"state": "Live", "spreadPx": 116, "atU": 33,
                                "n": 15, "worstGroupPx": 116, "largestGroupPx": 116,
                                "largestAtU": 33, "largestN": 15,
                                "tiedGroups": 1, "cardsTied": 15},
    ))
    assert ok, text
    assert "identical-content spread 116px in Live" in text
    assert "worst group: 15 cards at 33 pairs" in text
    # One group, so the two statistics agree and the second clause is noise.
    assert "largest group " not in text


def test_the_floor_never_fails_a_run_while_its_stability_is_unknown():
    """One reading per width is not a baseline. Promoting it to STABLE_METRICS
    on that basis is the mistake this harness keeps recording."""
    assert "identicalContentSpread" in probe.WATCH_METRICS
    assert "identicalContentSpread" not in probe.STABLE_METRICS
    text, ok = _summarize(_report(
        identicalContentSpread={"state": "Preview", "floorPx": 900, "atU": 33,
                                "n": 9, "tiedGroups": 1, "cardsTied": 9}))
    assert ok, "a watch metric must not fail a run, however large"


def test_a_watch_metric_is_printed_even_when_it_did_not_move():
    """A metric shown only when it moves can never be shown to be stable.

    On soccer, not the default mlb: mlb was baselined 2026-08-17 and now takes
    the judged branch, so a sport that has NOT earned a baseline is what holds
    this branch open."""
    tie = {"state": "Preview", "floorPx": 116, "atU": 33, "n": 5,
           "tiedGroups": 1, "cardsTied": 5}
    base = _report(sport="soccer", identicalContentSpread=dict(tie))
    cur = _report(sport="soccer", identicalContentSpread=dict(tie))
    text, ok = _compare(base, cur)
    assert ok
    assert "watch (stability unknown): identicalContentSpread unchanged" in text


def test_a_watch_metric_reports_movement_without_failing():
    base = _report(sport="soccer",
                   identicalContentSpread={"state": "Preview", "floorPx": 116,
                                           "atU": 33, "n": 5, "tiedGroups": 1, "cardsTied": 5})
    cur = _report(sport="soccer",
                  identicalContentSpread={"state": "Preview", "floorPx": 402,
                                          "atU": 33, "n": 5, "tiedGroups": 1, "cardsTied": 5})
    text, ok = _compare(base, cur)
    assert ok, "movement is the DATA this lane is collecting, not a failure"
    assert "identicalContentSpread 116 -> 402" in text
    assert "CODE-DRIVEN DRIFT" not in text


def test_the_comparator_can_read_the_floor_out_of_its_own_dict():
    """Without a `floorPx` branch `_cmp_value` returns None both sides, and the
    watch line reads 'unchanged' forever."""
    assert probe._cmp_value({"state": "Preview", "floorPx": 116, "n": 5}) == 116


def test_an_errored_row_is_not_reported_as_code_driven_drift():
    """Seen live 2026-08-16: soccer mobile hit a 30s `page.goto` timeout, and
    the comparison announced `CODE-DRIVEN DRIFT: overflowPx 0 -> None` on four
    metrics -- a failed measurement dressed as a measured change."""
    base = _report()
    cur = _report()
    cur["sports"]["mlb"]["mobile"] = {"error": "TimeoutError: Page.goto: Timeout 30000ms exceeded."}
    text, ok = _compare(base, cur)
    assert not ok, "an errored row still fails the run -- it is just not DRIFT"
    assert "SKIPPED -- the current row ERRORED" in text
    assert "CODE-DRIVEN DRIFT" not in text
    assert "overflowPx 0 -> None" not in text


def test_an_errored_baseline_row_is_named_as_the_errored_side():
    base = _report()
    base["sports"]["mlb"]["desktop"] = {"error": "TimeoutError: boom"}
    text, ok = _compare(base, _report())
    assert not ok
    assert "SKIPPED -- the baseline row ERRORED" in text


# --- largest tie group as the tracked statistic (user decision 2026-08-16) ---
#
# Chosen AFTER seeing that the max-across-groups statistic read 109/109/53 on
# mlb mobile. Recorded here because a statistic picked to look stable must not
# later be cited as having been predicted to be stable.


def test_the_tracked_statistic_is_the_worst_group():
    """Reverted 2026-08-16 after the largest-group variant measured WORSE on
    both mlb rows (2.45x vs 1.66x). The tracked number and the fit floor are
    one quantity again, so a row cannot print one and diff the other."""
    pts = [(41, 1000), (41, 1400)]                      # n=2, spread 400
    pts += [(45, 1100), (45, 1130), (45, 1120), (45, 1150)]  # n=4, spread 50
    m = _fit_tie(pts)
    assert m["spreadPx"] == 400 and m["atU"] == 41 and m["n"] == 2
    assert m["worstGroupPx"] == 400
    assert m["largestGroupPx"] == 50 and m["largestAtU"] == 45 and m["largestN"] == 4


def test_the_worst_group_still_drives_fit_impossibility():
    """A fit has to beat EVERY tie group, so the impossibility floor keeps
    using the max. Tracking the largest group must not make something read as
    fittable when it is not."""
    pts = [(41, 1000), (41, 1400)]
    pts += [(45, 1100), (45, 1130), (45, 1120), (45, 1150)]
    pts += [(49, 1200), (49, 1210), (49, 1205)]
    model = _fit(pts)
    assert model is not None
    assert model["floorPx"] == 400, "floorPx must be the worst tie, not the largest"


def test_equal_sized_groups_break_toward_the_larger_spread():
    """The tie-break can never be the thing that hides a difference."""
    pts = [(41, 1000), (41, 1040), (41, 1010)]   # n=3, spread 40
    pts += [(45, 1100), (45, 1220), (45, 1150)]  # n=3, spread 120
    m = _fit_tie(pts)
    assert m["n"] == 3
    assert m["spreadPx"] == 120 and m["atU"] == 45


def test_both_statistics_are_printed_when_they_disagree():
    """Them disagreeing is itself informative -- it says a small group is
    straddling the extremes."""
    text, ok = _summarize(_report(identicalContentSpread={
        "state": "Preview", "spreadPx": 400, "atU": 41, "n": 2,
        "worstGroupPx": 400, "largestGroupPx": 50, "largestAtU": 45,
        "largestN": 4, "tiedGroups": 2, "cardsTied": 6}))
    assert ok, text
    assert "identical-content spread 400px in Preview" in text
    assert "worst group: 2 cards at 41 pairs" in text
    assert "largest group 50px at 45 pairs, n=4" in text


def test_the_comparison_diffs_the_worst_group():
    base = _report(identicalContentSpread={
        "state": "Preview", "spreadPx": 400, "worstGroupPx": 400,
        "largestGroupPx": 50, "atU": 41, "n": 2})
    cur = _report(identicalContentSpread={
        "state": "Preview", "spreadPx": 400, "worstGroupPx": 400,
        "largestGroupPx": 900, "atU": 41, "n": 2})
    text, ok = _compare(base, cur)
    # mlb is baselined, so `ok` is load-bearing here: were `_cmp_value` to read
    # `largestGroupPx`, this would not merely misprint, it would FAIL the run.
    assert ok
    assert "identicalContentSpread 400px unchanged (baselined)" in text


def test_a_report_from_the_largest_group_window_compares_on_the_same_quantity():
    """Reports written 2026-08-16 between the switch and the revert carry
    `spreadPx` meaning the LARGEST group. Diffing that against a current report
    would compare two different quantities and call the difference movement --
    `worstGroupPx` is present in both eras and means one thing in both."""
    old_era = {"state": "Preview", "spreadPx": 67, "worstGroupPx": 99}
    new_era = {"state": "Preview", "spreadPx": 99, "worstGroupPx": 99,
               "largestGroupPx": 67}
    assert probe._cmp_value(old_era) == probe._cmp_value(new_era) == 99
    text, ok = _compare(_report(identicalContentSpread=old_era),
                        _report(identicalContentSpread=new_era))
    assert ok
    assert "identicalContentSpread 99px unchanged (baselined)" in text


def test_an_older_report_using_floorPx_still_compares():
    """Reports written before the statistic changed carry `floorPx` only."""
    assert probe._cmp_value({"state": "Preview", "floorPx": 116}) == 116
    assert probe._cmp_value({"state": "Preview", "spreadPx": 50, "floorPx": 400}) == 50









# --- nfl/ncaaf/mlb baselined; soccer still only watched ---------------------


def _tie(px, state="Week 1"):
    return {"state": state, "spreadPx": px, "worstGroupPx": px, "atU": 3, "n": 16}


def _pair(sport, base_tie, cur_tie):
    return (_report(sport=sport, identicalContentSpread=base_tie),
            _report(sport=sport, identicalContentSpread=cur_tie))


def test_only_the_settled_slates_are_baselined():
    """A sport is opted in BY NAME after several bit-identical runs, never in a
    blanket promotion. nfl/ncaaf earned it on 7+ runs 2026-08-16; mlb earned it
    2026-08-17 on a pre-game slate (below). soccer has not, and must stay out."""
    assert probe.TIE_SPREAD_BASELINED == frozenset({"nfl", "ncaaf", "mlb"})
    assert "soccer" not in probe.TIE_SPREAD_BASELINED


def test_mlb_is_baselined_on_the_pregame_evidence():
    """Refused 2026-08-16 (81/109/123/164/193px in one day), armed 2026-08-17.

    Re-measured on an all-`Preview` slate -- 11 cards, one state, no game
    started -- three consecutive production runs against
    https://syndicate-an21.onrender.com were BIT-IDENTICAL on both widths, every
    per-group figure included:

        desktop  worstGroupPx 86, spreadPct 7.1   (3 cards at 49 pairs)
        mobile   worstGroupPx 43, spreadPct 1.1   (3 cards at 45 pairs)

    So the earlier instability was the SLATE, not the metric. The corollary is
    that mlb is only baselineable PRE-GAME; a live slate will move this number,
    and the per-state guard (see the state-change test below) is what keeps that
    from reading as a layout regression.
    """
    assert "mlb" in probe.TIE_SPREAD_BASELINED
    text, ok = _compare(*_pair("mlb", _tie(86, "Preview"), _tie(86, "Preview")))
    assert ok, text
    assert "identicalContentSpread 86px unchanged (baselined)" in text


def test_a_baselined_sport_fails_on_drift():
    text, ok = _compare(*_pair("nfl", _tie(14), _tie(38)))
    assert not ok
    assert "identicalContentSpread DRIFT 14px -> 38px" in text
    assert "cards with the SAME data changed height" in text
    # Whoever reads this must check the slate before calling it a regression.
    assert "Check whether the slate went live" in text


def test_a_baselined_sport_passes_when_unchanged():
    text, ok = _compare(*_pair("ncaaf", _tie(45), _tie(45)))
    assert ok, text
    assert "identicalContentSpread 45px unchanged (baselined)" in text


def test_mlb_drift_within_pregame_now_fails():
    """The movement that used to be tolerated on mlb is now the finding: two
    Preview readings that disagree mean cards with identical data changed
    height, because the pre-game slate was measured as bit-identical."""
    text, ok = _compare(*_pair("mlb", _tie(86, "Preview"), _tie(164, "Preview")))
    assert not ok
    assert "identicalContentSpread DRIFT 86px -> 164px" in text
    assert "Check whether the slate went live" in text


def test_mlb_first_pitch_is_not_comparable_rather_than_drift():
    """The limit mlb's baseline carries, and the reason arming it is safe: mlb is
    only stable PRE-GAME, so first pitch MUST NOT read as a layout regression."""
    text, ok = _compare(*_pair("mlb", _tie(86, "Preview"), _tie(193, "Live")))
    assert ok, text
    assert "NOT COMPARABLE -- state moved 'Preview' -> 'Live'" in text
    assert "DRIFT" not in text


def test_a_state_change_is_not_comparable_rather_than_drift():
    """The tie spread is per-state, so two states are two quantities. This is
    what stops kickoff from being reported as a layout regression."""
    text, ok = _compare(*_pair("nfl", _tie(14, "Week 1"), _tie(220, "Live")))
    assert ok, text
    assert "NOT COMPARABLE -- state moved 'Week 1' -> 'Live'" in text
    assert "DRIFT" not in text


def test_a_baseline_predating_the_metric_does_not_fail():
    base = _report(sport="nfl")           # no identicalContentSpread at all
    cur = _report(sport="nfl", identicalContentSpread=_tie(14))
    text, ok = _compare(base, cur)
    assert ok, text
    assert "NOT COMPARED" in text
    assert "re-baseline to arm it" in text


def test_a_vanished_measurement_fails_even_though_it_is_an_absence():
    """Absence on the CURRENT side is not the same as absence on the baseline:
    the check stopped running, and absence is never a pass."""
    base = _report(sport="nfl", identicalContentSpread=_tie(14))
    cur = _report(sport="nfl")            # no tied cards this run
    text, ok = _compare(base, cur)
    assert not ok
    assert "identicalContentSpread VANISHED (baseline 14px, now unmeasured)" in text
    assert "the check did NOT run" in text


# --- the one height failure rule: deviation from same-content PEERS ---------
#
# Replaces residual-from-the-line and raw-group-spread, which each produced a
# false alarm on a healthy board on 2026-08-16. See the block comment in
# `summarize`.


def _ties(median_h=3800, **states):
    """Budget is a SHARE of card height, so a tie block needs a height."""
    return {s: dict(spreadPx=px, atU=45, n=4, cardsTied=15, worstGroupPx=px,
                    tiedGroups=1, medianH=median_h,
                    spreadPct=round(px / median_h * 1000) / 10)
            for s, px in states.items()}


def test_a_card_that_differs_from_its_peers_fails():
    """The falsification test for this rule: a real defect must still be caught
    when the card HAS peers -- e.g. one card grew an extra block."""
    text, ok = _summarize(_report(
        identicalContentSpreadByState=_ties(median_h=2000, Preview=420)))
    assert not ok
    assert "PEER DEVIATION OVER BUDGET in Preview (21.0% > 15.0% of card height)" in text
    assert "differ by 420px on a 2000px card" in text
    assert "same data, different height" in text


def test_every_state_is_judged_not_just_the_worst():
    text, ok = _summarize(_report(
        identicalContentSpreadByState=_ties(median_h=2000, Preview=40, Live=400)))
    assert not ok
    assert "PEER DEVIATION OVER BUDGET in Live" in text
    assert "PEER DEVIATION OVER BUDGET in Preview" not in text


def test_a_curved_fit_no_longer_fails_on_its_residual():
    """mlb mobile Live, 2026-08-16: residual 151px on a CURVED fit that passed
    as `reliable` at ratio 0.2, while every card agreed with its own peers to
    40px. The residual is reported; it no longer judges."""
    text, ok = _summarize(_report(
        heightModel=_model(state="Live", residualSpread=151, maxAbsResidual=79,
                           fitRatio=0.2, explainedPx=771, floorPx=40,
                           atNoiseFloor=False,
                           worstCard={"u": 45, "h": 3989, "residual": 79}),
        identicalContentSpreadByState=_ties(Live=40)))
    assert ok, text
    assert "layout residual 151px in Live" in text          # context
    assert "OVER BUDGET" not in text                         # but not a verdict


def test_a_large_raw_spread_no_longer_fails_on_its_own():
    """mlb desktop, 2026-08-16: raw spread 313px, peers differed by 70px."""
    text, ok = _summarize(_report(
        heightModel=_model(contentIndependent=True, reliable=False,
                           groupHeightSpread=313, explainedPx=24, pxPerUnit=1.5),
        identicalContentSpreadByState=_ties(Preview=70)))
    assert ok, text
    assert "layout spread 313px in Preview" in text
    assert "the peer check below is what judges" in text
    assert "OVER BUDGET" not in text


def test_the_coverage_gap_is_printed_rather_than_implied():
    """A card with no same-`u` peer cannot be judged. That blind spot has to be
    visible on the row, not inferred from a clean line."""
    ties = _ties(Preview=40)
    ties["Preview"]["cardsTied"] = 9
    text, ok = _summarize(_report(cards=15, identicalContentSpreadByState=ties))
    assert ok, text
    assert "peer check covered 9/15 cards" in text
    assert "cannot be judged" in text


def test_full_coverage_prints_no_gap_note():
    text, ok = _summarize(_report(cards=15, identicalContentSpreadByState=_ties(Preview=40)))
    assert ok, text
    assert "peer check covered" not in text


def test_no_ties_at_all_is_a_stated_gap_not_a_pass_and_not_a_failure():
    text, ok = _summarize(_report(cards=15, identicalContentSpreadByState={}))
    assert ok, text
    assert "PEER CHECK DID NOT RUN -- no two of 15 cards share a pair count" in text


def test_the_peer_rule_runs_where_no_model_exists_at_all():
    """The uniform-33 slate: nothing fits, and the peer rule is all there is."""
    text, ok = _summarize(_report(
        heightModel=None, statesUnfitted=["Live", "Preview"],
        identicalContentSpreadByState=_ties(median_h=2000, Preview=400)))
    assert not ok
    assert "PEER DEVIATION OVER BUDGET in Preview" in text


# --- curvature: fitRatio must stop certifying a fit of the wrong shape ------
#
# Both series below are the real 2026-08-16 mlb mobile measurements. Live is
# convex (41.3 -> 61.8 -> 76.6 px/pair) and scored fitRatio 0.20 / reliable
# under the old rule. Preview is straight (65.6, 65.1) and must NOT be caught --
# that is this detector's falsification test.

LIVE_PTS = [(45, 3989), (49, 4168), (49, 4160), (49, 4128),
            (53, 4386), (53, 4352), (57, 4757)]
PREVIEW_PTS = [(41, 3561), (41, 3596), (45, 3872), (45, 3842),
               (45, 3803), (45, 3846), (49, 4101)]


def test_the_curved_live_fit_is_no_longer_reliable():
    m = _fit(LIVE_PTS)
    assert m["curved"] is True
    assert m["reliable"] is False
    # The ratio still looks fine -- that is the whole point.
    assert m["fitRatio"] <= 0.25
    assert m["slopePerStep"] == [40.8, 54.2, 96.5] or m["slopePerStep"][0] < m["slopePerStep"][-1]
    assert m["slopeDrift"] > 0.5


def test_the_straight_preview_fit_is_not_flagged():
    """Falsification test: a known-linear series must survive the detector."""
    m = _fit(PREVIEW_PTS)
    assert m["curved"] is False
    assert m["reliable"] is True


def test_two_steps_are_never_enough_to_call_a_drift():
    """Two steps can only say 'one went up', which is noise, not drift."""
    m = _fit([(41, 1000), (41, 1010), (45, 1200), (45, 1210), (49, 1600), (49, 1610)])
    assert len(m["slopePerStep"]) == 2
    assert m["curved"] is False
    assert m["slopeDrift"] is None


def test_non_monotone_slope_wobble_is_noise_not_curvature():
    """Slopes that go up then down are a noisy line, not a bend."""
    m = _fit([(41, 1000), (45, 1300), (49, 1450), (53, 1780), (57, 1930)])
    assert m["curved"] is False


def test_a_curved_fit_is_reported_as_misspecified_not_as_no_signal():
    text, ok = _summarize(_report(heightModel=_model(
        state="Live", curved=True, reliable=False, fitRatio=0.2,
        slopePerStep=[40.8, 54.2, 96.5], slopeDrift=0.88)))
    assert ok, text
    assert "layout model MISSPECIFIED in Live" in text
    assert "40.8/54.2/96.5 px/pair" in text
    assert "the fit is CURVED" in text
    assert "certifies nothing" in text
    # It must NOT be described as an absence of signal.
    assert "no layout signal here" not in text


def test_curvature_does_not_fail_the_run():
    """The peer rule judges; this is a label on the fit, which is context."""
    text, ok = _summarize(_report(heightModel=_model(
        state="Live", curved=True, reliable=False, fitRatio=0.2,
        slopePerStep=[40.8, 54.2, 96.5], slopeDrift=0.88)))
    assert ok, text


def test_the_same_px_is_judged_differently_on_a_tall_and_a_short_card():
    """The width bias this change exists to fix. 150px is 2.8% of an mlb mobile
    card and 27% of an ncaaf desktop one -- a fixed px budget is strict on tall
    cards and loose on short ones."""
    tall, ok_tall = _summarize(_report(
        identicalContentSpreadByState=_ties(median_h=4800, Preview=400)))
    assert ok_tall, tall                      # 8.3% -- ordinary wrap on a tall card
    short, ok_short = _summarize(_report(
        identicalContentSpreadByState=_ties(median_h=541, Preview=400)))
    assert not ok_short                        # 73.9% -- a third of a short card
    assert "PEER DEVIATION OVER BUDGET" in short


def test_the_budget_is_calibrated_above_every_healthy_reading():
    """16 healthy production readings on 2026-08-16 topped out at 9.9%."""
    assert probe.PEER_DEVIATION_BUDGET_PCT > 9.9
    # ...but not so wide it stops catching anything: 3x the worst healthy
    # reading would be 30%, i.e. 1440px on a 4800px card.
    assert probe.PEER_DEVIATION_BUDGET_PCT < 30


def test_a_tie_group_with_no_measurable_height_is_named_not_skipped():
    """Absence must not land on the permissive branch."""
    ties = {"Preview": {"spreadPx": 400, "atU": 45, "n": 4, "cardsTied": 15,
                        "worstGroupPx": 400, "tiedGroups": 1,
                        "medianH": None, "spreadPct": None}}
    text, ok = _summarize(_report(identicalContentSpreadByState=ties))
    assert ok, text
    assert "peer deviation in Preview NOT JUDGED" in text
    assert "no measurable card height" in text


# --- tab click-through: the board rewrites itself underneath this check -----
#
# `game_board.js` polls every 30s and does `cardsGrid.innerHTML = fresh.innerHTML`,
# detaching every node the check holds. On 2026-08-16 `ncaaf desktop` reported
# `tab click identity` once and was clean on re-run and on 10 scripted repeats.
# The cause of that single instance is UNPROVEN -- the row printed only the tab
# name and the artifact was overwritten. These tests pin the two things that
# were actually wrong: the check sampled once with no defence against the swap,
# and the failure carried no reason.


def test_a_failed_tab_click_reports_WHY_not_just_which_tab():
    text, ok = _summarize(_report(tabClickThrough=[
        {"tab": "identity", "error": "TimeoutError: element is not attached", "ok": False}]))
    assert not ok
    assert "tab click identity [TimeoutError: element is not attached]" in text


def test_a_wrong_panel_failure_reports_the_state_it_saw():
    text, ok = _summarize(_report(tabClickThrough=[
        {"tab": "identity", "activePanels": [], "cardHeight": 187, "ok": False}]))
    assert not ok
    assert "tab click identity [active=[] h=187px]" in text


def test_a_passing_tab_click_says_nothing():
    text, ok = _summarize(_report(tabClickThrough=[
        {"tab": "identity", "activePanels": ["identity"], "cardHeight": 900, "ok": True}]))
    assert ok, text
    assert "tab click" not in text


def test_a_result_with_no_measurement_carries_ok_false_explicitly():
    """It must not depend on a MISSING key reading as failure downstream --
    that is the same absent-vs-false conflation this harness keeps hitting."""
    text, ok = _summarize(_report(tabClickThrough=[
        {"tab": "identity", "error": "TimeoutError: boom", "attempts": 2, "ok": False}]))
    assert not ok
    assert "TimeoutError" in text


def test_the_activation_wait_is_bounded_and_short():
    """`activateTab` is a synchronous classList swap, so this window is for the
    innerHTML swap, not for a slow handler. It must not become a sleep."""
    assert probe.TAB_ACTIVATE_WAIT_MS <= 3000
    assert probe.TAB_POLL_MS <= 250


# --- a verdict needs n>=3 cards ---------------------------------------------
#
# 2026-08-16: one run failed at 30.9% on an n=2 Live group (2 cards at 41 pairs,
# 312px apart) while the n=6 group on the same board sat at 82px. Minutes later
# only ONE card remained at 41 pairs -- the pairing was transient, produced by
# MLB live enrichment giving a card a passing pair count that coincided with an
# unrelated card's.


def _grouped(state="Live", **kw):
    """A tie blob carrying the full per-group list."""
    groups = kw.pop("groups")
    return {state: {"state": state, "spreadPx": groups[0]["spread"],
                    "atU": groups[0]["u"], "n": groups[0]["n"],
                    "worstGroupPx": groups[0]["spread"], "cardsTied": sum(g["n"] for g in groups),
                    "tiedGroups": len(groups), "medianH": groups[0]["medianH"],
                    "spreadPct": groups[0]["pct"], "groups": groups}}


def test_a_two_card_group_over_budget_is_reported_but_does_not_fail():
    ties = _grouped(groups=[{"u": 41, "n": 2, "spread": 312, "medianH": 1009, "pct": 30.9}])
    text, ok = _summarize(_report(identicalContentSpreadByState=ties))
    assert ok, text
    assert "peer deviation in Live NOT JUDGED -- 30.9% over 2 card(s) at 41 pairs" in text
    assert "below the n>=3 a verdict needs" in text
    assert "PEER DEVIATION OVER BUDGET" not in text


def test_three_cards_is_enough_to_fail():
    ties = _grouped(groups=[{"u": 41, "n": 3, "spread": 312, "medianH": 1009, "pct": 30.9}])
    text, ok = _summarize(_report(identicalContentSpreadByState=ties))
    assert not ok
    assert "PEER DEVIATION OVER BUDGET in Live (30.9%" in text
    assert "3 cards carry 41 pairs each" in text


def test_a_thin_group_must_not_mask_a_fat_one():
    """The reason the per-group list exists. If the gate only saw the WORST
    group it would skip the n=6 one behind the n=2 one and pass."""
    ties = _grouped(groups=[
        {"u": 41, "n": 2, "spread": 312, "medianH": 1009, "pct": 30.9},   # thin, worst
        {"u": 45, "n": 6, "spread": 220, "medianH": 1009, "pct": 21.8},   # judged
    ])
    text, ok = _summarize(_report(identicalContentSpreadByState=ties))
    assert not ok, "the n=6 group is over budget and must still fail"
    assert "PEER DEVIATION OVER BUDGET in Live (21.8%" in text
    assert "6 cards carry 45 pairs each" in text
    assert "NOT JUDGED -- 30.9% over 2 card(s)" in text


def test_a_healthy_board_with_a_thin_group_stays_green():
    """The 2026-08-16 board after the churn passed: n=6 at 82px, n=2 at 51px."""
    ties = _grouped(groups=[
        {"u": 45, "n": 6, "spread": 82, "medianH": 1100, "pct": 7.5},
        {"u": 57, "n": 2, "spread": 51, "medianH": 1250, "pct": 4.1},
    ])
    text, ok = _summarize(_report(identicalContentSpreadByState=ties))
    assert ok, text
    assert "NOT JUDGED" not in text


def test_the_minimum_is_the_smallest_n_where_one_card_is_not_the_spread():
    assert probe.PEER_MIN_GROUP_N == 3


def test_a_report_predating_the_group_list_is_still_judged():
    """Older artifacts carry only the summary entry. They must not silently
    stop being checked -- absence of the list is not absence of a problem."""
    ties = {"Live": {"state": "Live", "spreadPx": 312, "atU": 41, "n": 4,
                     "medianH": 1009, "spreadPct": 30.9, "worstGroupPx": 312}}
    text, ok = _summarize(_report(identicalContentSpreadByState=ties))
    assert not ok
    assert "PEER DEVIATION OVER BUDGET in Live" in text
