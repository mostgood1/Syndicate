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
