"""WNBA's OddsAPI regions knob: widens, never narrows, and is its OWN knob.

THE DEFECT, measured 2026-09-01 (lane `wnba-accuracy-assessment`): WNBA's served
book set was 11 books with ZERO exchanges -- 101,129 quote rows on 2026-08-30 and
not one novig, prophetx, betopenly, kalshi or polymarket. MLB's grid carried
novig 33 / prophetx 13 the same day, so it is not that exchanges skip WNBA. Those
books live in OddsAPI's `us_ex`, and the WNBA fetcher asked for `us` alone.

`SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS=eu,us_ex` was SET on both workers the
whole time with exactly two readers, neither of them WNBA -- the same inert
env-var failure `odds_regions.py` records for NCAAF, on a third sport.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import odds_regions


# --------------------------------------------------------------- reachability
def test_unset_is_exactly_todays_behaviour():
    """The pre-fix state. If this ever changes, the fix became a default."""
    assert odds_regions.wnba_regions("us", env={}) == "us"


def test_the_game_line_knob_alone_does_NOT_widen_wnba():
    """This is the whole bug: a var set in the environment, read by nobody.

    WNBA must not silently inherit the shared game-line knob -- its calls are
    per-EVENT, the expensive side of the billing split.
    """
    env = {odds_regions.GAME_LINE_REGIONS_ENV: "eu,us_ex"}
    assert odds_regions.wnba_regions("us", env=env) == "us"


# ------------------------------------------------------------------ behaviour
def test_wnba_knob_widens():
    env = {odds_regions.WNBA_REGIONS_ENV: "eu,us_ex"}
    assert odds_regions.wnba_regions("us", env=env) == "us,eu,us_ex"


def test_base_region_can_never_be_dropped():
    """A misconfigured value may widen coverage; it may never narrow it."""
    for extra in ("us_ex", "eu", "", "   ", "us"):
        out = odds_regions.wnba_regions("us", env={odds_regions.WNBA_REGIONS_ENV: extra})
        assert out.split(",")[0] == "us", extra


def test_a_region_named_twice_is_not_billed_twice():
    env = {odds_regions.WNBA_REGIONS_ENV: "us,us_ex,us_ex"}
    assert odds_regions.wnba_regions("us", env=env) == "us,us_ex"


def test_order_is_preserved_so_us_stays_first():
    env = {odds_regions.WNBA_REGIONS_ENV: "eu,us_ex"}
    assert odds_regions.wnba_regions("us", env=env).split(",") == ["us", "eu", "us_ex"]


def test_the_two_knobs_are_independent():
    """Each name carries its own billing contract; neither may leak to the other."""
    env = {odds_regions.WNBA_REGIONS_ENV: "us_ex",
           odds_regions.GAME_LINE_REGIONS_ENV: "eu"}
    assert odds_regions.wnba_regions("us", env=env) == "us,us_ex"
    assert odds_regions.game_line_regions("us", env=env) == "us,eu"


# -------------------------------------------------------------------- wiring
def test_the_fetcher_actually_applies_it(monkeypatch):
    """A correct knob nobody consults is inert -- which is the bug being fixed."""
    from scripts import refresh_wnba_oddsapi_props as refresher
    from pathlib import Path

    monkeypatch.setenv(odds_regions.WNBA_REGIONS_ENV, "us_ex")
    args = refresher._owned_snapshot_cli_args(
        date_str="2026-09-18", out_path=Path("/tmp/x.csv"),
        regions="us", bookmakers="", markets="",
    )
    assert "--regions" in args
    assert args[args.index("--regions") + 1] == "us,us_ex"


def test_the_fetcher_is_unchanged_when_unset(monkeypatch):
    from scripts import refresh_wnba_oddsapi_props as refresher
    from pathlib import Path

    monkeypatch.delenv(odds_regions.WNBA_REGIONS_ENV, raising=False)
    args = refresher._owned_snapshot_cli_args(
        date_str="2026-09-18", out_path=Path("/tmp/x.csv"),
        regions="us", bookmakers="", markets="",
    )
    assert args[args.index("--regions") + 1] == "us"
