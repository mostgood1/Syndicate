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


def test_card_wait_constant_is_generous_enough_for_a_js_render():
    """Guards the regression directly: MLB needed >600ms and got 400."""
    assert probe.CARD_WAIT_MS >= 10000
