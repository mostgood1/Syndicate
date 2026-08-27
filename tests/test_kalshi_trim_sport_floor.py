"""One sport must not be able to evict another out of the working set.

The trim is ordered freshest-series-first, which is the right ORDER and the
wrong BUDGET. MLB carries 14 registered series; on volume alone it can fill all
6,000 slots and every soccer market falls off -- not because it is stale, but
because it queued behind a bigger sport.

MEASURED 2026-08-27: kalshi served 173 soccer quotes at 15:0xZ
(`h2h_keyed_by_team:149`) and ZERO an hour later
(`no_kalshi_market_classified_to_this_sport`) while its MLB set was 2,189 keys,
and `selected_by_sport['soccer']` carried no kalshi entry at all.
"""

from __future__ import annotations

import pytest

from pipeline import kalshi_odds_refresh as mod


def _markets(series, n):
    return [{"ticker": f"{series}-{i}", "series": series} for i in range(n)]


@pytest.fixture(autouse=True)
def small_budget(monkeypatch):
    """1,000 slots with a 300 floor -- production's 6,000/300 ratio, small
    enough to reason about exactly."""
    monkeypatch.setattr(mod, "MAX_STORED_MARKETS", 1000)
    monkeypatch.setattr(mod, "PER_SPORT_FLOOR_MARKETS", 300)


@pytest.fixture(autouse=True)
def sport_map(monkeypatch):
    mapping = {"KXMLBGAME": "mlb", "KXMLBHR": "mlb", "KXSOCCER": "soccer", "KXWNBA": "wnba"}
    from syndicate.features.shared import kalshi_catalogue

    monkeypatch.setattr(kalshi_catalogue, "sport_for_series", lambda s: mapping.get(str(s)))


def _sports_of(markets):
    from collections import Counter
    return Counter(m["series"] for m in markets)


def test_a_high_volume_sport_cannot_evict_a_small_one():
    """THE DEFECT. MLB is fresher AND far larger; without a floor it takes all
    1,000 slots and soccer gets none."""
    kept, trimmed, by_sport = mod._trim_to_storage_bounds([
        (10.0, "KXMLBGAME", _markets("KXMLBGAME", 2000)),
        (20.0, "KXSOCCER", _markets("KXSOCCER", 200)),
    ])

    assert by_sport.get("soccer") == 200, by_sport
    assert _sports_of(kept)["KXSOCCER"] == 200
    assert len(kept) == 1000
    assert trimmed == 1200


def test_the_floor_is_a_guarantee_not_a_reservation():
    """A sport with fewer markets than the floor takes what it has, and the
    unused slots go to whoever else wants them rather than sitting empty."""
    kept, _trimmed, by_sport = mod._trim_to_storage_bounds([
        (10.0, "KXSOCCER", _markets("KXSOCCER", 50)),
        (20.0, "KXMLBGAME", _markets("KXMLBGAME", 5000)),
    ])

    assert by_sport["soccer"] == 50
    assert len(kept) == 1000, "unused floor slots were held empty instead of reused"


def test_freshest_first_still_decides_WITHIN_a_sport():
    """The floor changes the budget, not the order. Two MLB series competing for
    one sport's floor must be taken freshest-first."""
    kept, _t, _b = mod._trim_to_storage_bounds([
        (5.0, "KXMLBHR", _markets("KXMLBHR", 300)),
        (99.0, "KXMLBGAME", _markets("KXMLBGAME", 300)),
        (10.0, "KXSOCCER", _markets("KXSOCCER", 300)),
    ])
    counts = _sports_of(kept)

    assert counts["KXMLBHR"] == 300, "the fresher MLB series lost its floor share"
    assert counts["KXSOCCER"] == 300


def test_nothing_is_trimmed_when_everything_fits():
    kept, trimmed, _b = mod._trim_to_storage_bounds([
        (10.0, "KXSOCCER", _markets("KXSOCCER", 100)),
        (20.0, "KXWNBA", _markets("KXWNBA", 100)),
    ])

    assert trimmed == 0
    assert len(kept) == 200


def test_every_sport_present_survives_a_heavily_oversubscribed_budget():
    """Four sports, each wanting the whole budget. Each must come away with its
    floor and none may be starved."""
    kept, trimmed, by_sport = mod._trim_to_storage_bounds([
        (1.0, "KXMLBGAME", _markets("KXMLBGAME", 4000)),
        (2.0, "KXWNBA", _markets("KXWNBA", 4000)),
        (3.0, "KXSOCCER", _markets("KXSOCCER", 4000)),
    ])

    for sport in ("mlb", "wnba", "soccer"):
        assert by_sport.get(sport, 0) >= 300, (sport, by_sport)
    assert len(kept) == 1000
    assert trimmed == 11000


def test_an_unmapped_series_is_bucketed_not_dropped():
    """A series we cannot name a sport for still competes -- silently dropping
    it would be an eviction nobody could see."""
    kept, _t, by_sport = mod._trim_to_storage_bounds([
        (10.0, "KXMYSTERY", _markets("KXMYSTERY", 100)),
    ])

    assert by_sport == {"unmapped": 100}
    assert len(kept) == 100


def test_the_floor_constant_cannot_oversubscribe_the_budget(monkeypatch):
    """Guard on the real constants, not the test's. 6,000/300 supports 20 sports
    against the eight this platform carries; if either moves, this notices."""
    import importlib
    real = importlib.reload(mod)
    assert real.MAX_STORED_MARKETS // real.PER_SPORT_FLOOR_MARKETS >= 10


def test_the_breakdown_RECONCILES_with_its_own_total():
    """A tally that does not add up to the number beside it is worse than no
    tally: production printed `kept=6000 ... kept_by_sport={...}` summing to
    1,506, because the count was updated in the FLOOR pass and not the
    remainder pass. A reader had every reason to think 4,494 markets vanished.

    This is the guard for the line written to PROVE the floor worked.
    """
    kept, trimmed, by_sport = mod._trim_to_storage_bounds([
        (1.0, "KXMLBGAME", _markets("KXMLBGAME", 4000)),
        (2.0, "KXSOCCER", _markets("KXSOCCER", 400)),
        (3.0, "KXWNBA", _markets("KXWNBA", 50)),
    ])

    assert sum(by_sport.values()) == len(kept), (by_sport, len(kept))
    assert len(kept) + trimmed == 4450, "markets were neither kept nor counted as trimmed"


def test_the_remainder_pass_is_attributed_to_the_right_sport():
    """Not just reconciling -- reconciling CORRECTLY. The overflow beyond a
    sport's floor must be credited to that sport, not to whoever came first."""
    kept, _trimmed, by_sport = mod._trim_to_storage_bounds([
        (1.0, "KXSOCCER", _markets("KXSOCCER", 900)),
        (2.0, "KXWNBA", _markets("KXWNBA", 50)),
    ])

    # soccer: 300 by floor + 600 in the remainder = 900. wnba: 50.
    assert by_sport == {"soccer": 900, "wnba": 50}, by_sport
    assert sum(by_sport.values()) == len(kept) == 950


# ---------------------------------------------------------------------------
# demand-weighted allocation -- the failure a FLAT floor cannot see
# ---------------------------------------------------------------------------


def test_the_flat_floor_cannot_see_a_42_row_sport_hoarding_slots(monkeypatch):
    """THE MEASURED FAILURE, 2026-08-27 NCAAF opening week, floor already live:

        kept_by_sport={mlb: 648, nba: 6, ncaaf: 1896, nfl: 2083, soccer: 1067, wnba: 300}
        board demand  ={mlb: 400, soccer: 400, wnba: 400, nfl: 88, ncaaf: 42}

    ~4,000 of 6,000 slots held markets for 130 rows while 1,200 rows shared the
    rest. Kalshi's far-dated football catalogue is FRESH, and staleness ordering
    rewards that -- but freshness is not relevance: a market for a game three
    weeks out cannot be joined to today's board. `BOARD_JOIN matched` fell
    210 -> 5, and the flat floor recovered it only to 13-24.
    """
    # PRODUCTION constants deliberately, not the small-budget fixture: this
    # test is about a failure measured at 6,000/300, and at 1,000/300 five
    # floors already exceed the whole budget so there is nothing left to
    # weight. A fixture that cannot reproduce the condition cannot test it.
    monkeypatch.setattr(mod, "MAX_STORED_MARKETS", 6000)
    monkeypatch.setattr(mod, "PER_SPORT_FLOOR_MARKETS", 300)

    caps = mod._sport_slot_caps(
        ["mlb", "soccer", "wnba", "nfl", "ncaaf"],
        {"mlb": 400, "soccer": 400, "wnba": 400, "nfl": 88, "ncaaf": 42},
    )

    # The sports actually playing outrank the ones merely listed.
    assert caps["mlb"] > caps["nfl"] * 2
    assert caps["soccer"] > caps["ncaaf"] * 2
    # And football is not starved either -- it keeps well above the floor.
    assert caps["ncaaf"] > mod.PER_SPORT_FLOOR_MARKETS
    assert sum(caps.values()) <= mod.MAX_STORED_MARKETS


def test_a_sport_with_no_demand_still_gets_the_floor(monkeypatch):
    """Demand is measured from the LAST join, so a sport whose slate opens
    between cycles has demand 0. Without the floor underneath, it would be
    locked out of the working set that would let it be joined at all -- a
    self-fulfilling zero."""
    monkeypatch.setattr(mod, "MAX_STORED_MARKETS", 6000)
    monkeypatch.setattr(mod, "PER_SPORT_FLOOR_MARKETS", 300)

    caps = mod._sport_slot_caps(["mlb", "soccer"], {"mlb": 400})

    assert caps["soccer"] >= mod.PER_SPORT_FLOOR_MARKETS


def test_no_demand_signal_keeps_the_flat_floor_path():
    """Returns None rather than inventing a distribution from nothing."""
    assert mod._sport_slot_caps(["mlb"], None) is None
    assert mod._sport_slot_caps(["mlb"], {}) is None
    assert mod._sport_slot_caps([], {"mlb": 400}) is None
    assert mod._sport_slot_caps(["mlb"], {"mlb": 0}) is None


def test_demand_actually_changes_what_is_kept(small_budget, sport_map):
    """End to end through the trim: same input, demand flips who wins."""
    series = [
        (1.0, "KXNCAAF", _markets("KXNCAAF", 900)),   # fresher, far-dated
        (9.0, "KXSOCCER", _markets("KXSOCCER", 900)),  # staler, playing today
    ]
    from syndicate.features.shared import kalshi_catalogue
    import pytest as _p
    mapping = {"KXNCAAF": "ncaaf", "KXSOCCER": "soccer"}
    orig = kalshi_catalogue.sport_for_series
    kalshi_catalogue.sport_for_series = lambda s: mapping.get(str(s))
    try:
        flat, _t1, by_flat = mod._trim_to_storage_bounds(series)
        weighted, _t2, by_weighted = mod._trim_to_storage_bounds(
            series, demand={"soccer": 400, "ncaaf": 20})
    finally:
        kalshi_catalogue.sport_for_series = orig

    # Flat: the FRESHER far-dated sport takes the surplus.
    assert by_flat["ncaaf"] > by_flat["soccer"], by_flat
    # Weighted: the sport the board actually asks for does.
    assert by_weighted["soccer"] > by_weighted["ncaaf"], by_weighted
    assert len(flat) == len(weighted) == 1000, "budget was not filled either way"
