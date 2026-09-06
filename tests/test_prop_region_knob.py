"""Prop-call regions are widenable PER SPORT, and the soccer fetcher reads it.

WHY THIS EXISTS. Measured on the served board 2026-09-06: soccer rows carried
12 books overall, but `oddsapi_props` rows were **164 of 174 SINGLE-BOOK**
(fanduel 135, betrivers 39). `us` is not thin in general -- it is thin for
player props. Widening it was impossible in isolation: `ODDS_API_REGION`
(singular) is read by SIX fetchers across four sports and unset in production,
so reaching `eu` for soccer would have widened NFL and NCAAF props too, at the
~1M/month per-event billing tier rather than the ~30K game-line tier.

THE REACHABILITY TEST IS THE POINT OF THE FILE. `odds_regions.py`'s own
docstring records that `ODDS_API_REGION` was **inert for NCAAF** -- present in
the environment, read by nothing, and nobody noticed until the sharps failed to
appear. A knob that is defined and unread looks identical to a knob that works
until you check the bill. So `test_the_soccer_fetcher_actually_READS_the_knob`
asserts the outbound REGION, not the presence of a symbol.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.odds_regions import (  # noqa: E402
    prop_regions,
    prop_regions_env,
)


def test_unset_is_todays_behaviour():
    """The property that makes this landable with no spend: absent changes
    nothing, so merely deploying it cannot cost a credit."""
    assert prop_regions("soccer", "us", env={}) == "us"


def test_set_widens_and_off_is_not_on():
    """off != on. A knob that returns the base in both states would pass every
    other test in this file."""
    off = prop_regions("soccer", "us", env={})
    on = prop_regions("soccer", "us", env={"SYNDICATE_SOCCER_PROP_REGIONS": "eu"})
    assert off == "us"
    assert on == "us,eu"
    assert off != on


def test_it_is_PER_SPORT_which_is_the_whole_reason_it_exists():
    """Setting soccer must not widen NFL. The single global `ODDS_API_REGION`
    could not express this, and props bill per EVENT, so the blast radius of
    getting it wrong is ~1M credits/month across three sports."""
    env = {"SYNDICATE_SOCCER_PROP_REGIONS": "eu"}
    assert prop_regions("soccer", "us", env=env) == "us,eu"
    assert prop_regions("nfl", "us", env=env) == "us"
    assert prop_regions("ncaaf", "us", env=env) == "us"


def test_it_never_NARROWS():
    """The base is always kept, so a misconfigured value can widen coverage but
    can never silently drop `us` -- the safety property the module states."""
    assert prop_regions("soccer", "us", env={"SYNDICATE_SOCCER_PROP_REGIONS": "eu"}).startswith("us")
    # a region named twice is not billed twice
    assert prop_regions("soccer", "us", env={"SYNDICATE_SOCCER_PROP_REGIONS": "us"}) == "us"
    assert prop_regions("soccer", "us", env={"SYNDICATE_SOCCER_PROP_REGIONS": "eu,us"}) == "us,eu"


def test_the_env_name_is_stable_and_sport_scoped():
    assert prop_regions_env("soccer") == "SYNDICATE_SOCCER_PROP_REGIONS"
    assert prop_regions_env("nfl") == "SYNDICATE_NFL_PROP_REGIONS"


def test_the_soccer_fetcher_actually_READS_the_knob(monkeypatch, tmp_path):
    """REACHABILITY, asserted on the OUTBOUND REGION rather than on a symbol.

    `odds_regions.py` records that `ODDS_API_REGION` was inert for NCAAF --
    set, read by nothing, and silent about it. This drives the fetcher's own
    `main()` with the network stubbed and captures what region it would have
    requested, so a future refactor that stops calling `prop_regions` fails here
    instead of on the invoice.
    """
    import scripts.fetch_soccer_oddsapi_props_local as fetcher

    seen: dict[str, object] = {}

    def fake_fetch_events(api_key, *, sport_key, region):
        seen["events_region"] = region
        return []

    monkeypatch.setattr(fetcher, "fetch_events", fake_fetch_events)
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("SYNDICATE_SOCCER_PROP_REGIONS", "eu")
    out = tmp_path / "props.json"
    monkeypatch.setattr(sys, "argv", ["fetch_soccer_oddsapi_props_local.py",
                                      "--league", "epl", "--out", str(out)])

    try:
        fetcher.main()
    except SystemExit:
        pass
    except Exception:
        # An empty event list can end the run in many ways; the assertion below
        # is about what was REQUESTED, which is already captured by then.
        pass

    assert seen.get("events_region") == "us,eu", (
        "the fetcher requested %r -- the per-sport prop knob is NOT reaching the "
        "outbound call, which is exactly how ODDS_API_REGION was inert for NCAAF"
        % seen.get("events_region"))


def test_the_per_event_odds_call_uses_the_SAME_region(monkeypatch):
    """Events and odds must come from one region set. If the slate is fetched
    widened and the odds are not, the extra books are paid for and discarded."""
    import inspect

    import scripts.fetch_soccer_oddsapi_props_local as fetcher

    src = inspect.getsource(fetcher.main)
    assert "region=args.region" not in src, (
        "the per-event odds call still passes the UNWIDENED args.region")
    assert "region = prop_regions(" in src
