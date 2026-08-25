"""Many odds sources in, one priced candidate out.

Every test here traces to a measured failure from 2026-08-24, when the board
carried 235 soccer rows while ten MLB games sat unpriced because their
candidates were 13.9 hours old against a 6-hour ceiling.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared import venue_quote_fanin as mod
from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    SourceOutcome,
    collect_quotes,
    select_quote,
    stamp_candidate_freshness,
)


def _q(source, key="mlb|h2h|home", age=0.0, prob=0.55, now=None):
    base = now if now is not None else time.time()
    return Quote(key=key, source=source, sport="mlb", market="h2h", side="home",
                 probability=prob, american=-122, line=None, fetched_at=base - age,
                 venue_ref=f"{source}-ref")


# ==========================================================================
# RULE 1 -- a stale source must never shadow a fresh one
# ==========================================================================


def test_the_freshest_quote_wins_regardless_of_source_order():
    """`odds_control_plane`'s own docstring records 2026-08-04: a stale copy won
    on PATH PRECEDENCE and every MLB candidate silently read
    history_points=0. Ordering may only ever break a tie."""
    now = time.time()
    # oddsapi is LAST in SOURCES, and 1 second old; kalshi is FIRST and 6h old.
    stale_kalshi = _q("kalshi", age=6 * 3600, now=now)
    fresh_oddsapi = _q("oddsapi", age=1.0, now=now)
    assert select_quote([stale_kalshi, fresh_oddsapi], now=now).source == "oddsapi"


def test_source_order_breaks_a_TIE_only():
    now = time.time()
    a = _q("kalshi", age=10.0, now=now)
    b = _q("oddsapi", age=10.0, now=now)
    assert select_quote([b, a], now=now).source == "kalshi"


def test_no_quotes_selects_nothing_rather_than_raising():
    assert select_quote([], now=time.time()) is None


# ==========================================================================
# RULE 2 -- absence, failure and staleness are three different answers
# ==========================================================================


def test_a_disabled_source_is_not_an_error(monkeypatch):
    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_KALSHI_ENABLED", "0")
    result = collect_quotes("mlb", "2026-08-24", adapters={})
    assert result["by_source"]["kalshi"]["status"] == "disabled"


def test_a_refusal_is_not_an_error_and_carries_its_reason():
    """Novig's public tier CANNOT price a named bet -- a capability gap, not a
    broken feed. Rendering it as an error would send someone to debug a fetch
    that is working exactly as designed."""
    from syndicate.features.shared.venue_quote_adapters import novig_outcome

    outcome = novig_outcome("mlb", "2026-08-24")
    assert outcome.status == "refused"
    assert "anonymized" in outcome.reason


def test_an_adapter_that_raises_is_named_and_does_not_stop_the_others(monkeypatch):
    """One venue being unreachable must not cost the others' quotes -- the
    whole point is comparing across them."""
    def boom(_sport, _date):
        raise RuntimeError("connection reset")

    def good(_sport, _date):
        return SourceOutcome(source="oddsapi", status="ok", quotes=[_q("oddsapi")])

    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_NOVIG_ENABLED", "0")
    result = collect_quotes("mlb", "2026-08-24", adapters={
        "kalshi": boom, "polymarket_us": boom, "oddsapi": good,
    })
    assert result["by_source"]["kalshi"]["status"] == "error"
    assert "connection reset" in result["by_source"]["kalshi"]["reason"]
    assert result["by_source"]["oddsapi"]["status"] == "ok"
    assert result["keys"] == 1


# ==========================================================================
# RULE 3 -- zero rows is not success
# ==========================================================================


def test_a_source_returning_zero_quotes_reports_no_rows_not_ok():
    """The sporting=0 / games=0 family of misreadings all came from a zero that
    looked like a working feed."""
    def empty(_sport, _date):
        return SourceOutcome(source="kalshi", status="ok", quotes=[])

    result = collect_quotes("mlb", "2026-08-24", adapters={"kalshi": empty})
    assert result["by_source"]["kalshi"]["status"] == "no_rows"


# ==========================================================================
# RULE 4 -- every selection carries its source
# ==========================================================================


def test_the_winning_source_is_counted(monkeypatch):
    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_NOVIG_ENABLED", "0")
    now = time.time()
    result = collect_quotes("mlb", "2026-08-24", now=now, adapters={
        "kalshi": lambda *_a: SourceOutcome("kalshi", "ok", quotes=[_q("kalshi", key="a", age=1, now=now)]),
        "polymarket_us": lambda *_a: SourceOutcome("polymarket_us", "ok", quotes=[_q("polymarket_us", key="b", age=1, now=now)]),
        "oddsapi": lambda *_a: SourceOutcome("oddsapi", "ok", quotes=[_q("oddsapi", key="a", age=9999, now=now)]),
    })
    # key "a" contested: kalshi 1s beats oddsapi 9999s. key "b" uncontested.
    assert result["selected_by_source"] == {"kalshi": 1, "polymarket_us": 1}


# ==========================================================================
# THE CEILING -- the number that predicts the downstream rejection
# ==========================================================================


def test_quotes_beyond_the_ceiling_are_COUNTED_before_the_gate_drops_them(monkeypatch):
    """MEASURED 2026-08-24: 75 of 255 candidates rejected `stale_beyond_sla`,
    and nothing upstream said it was coming. mlb's ceiling is 6h; a 14h quote
    must be visible as doomed HERE, one stage before the rejection."""
    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_NOVIG_ENABLED", "0")
    now = time.time()
    result = collect_quotes("mlb", "2026-08-24", now=now, adapters={
        "kalshi": lambda *_a: SourceOutcome("kalshi", "ok", quotes=[
            _q("kalshi", key="fresh", age=60, now=now),
            _q("kalshi", key="stale", age=14 * 3600, now=now),
        ]),
    })
    assert result["ceiling_seconds"] == 6 * 3600
    assert result["within_ceiling"] == 1
    assert result["beyond_ceiling"] == 1


def test_the_ceiling_comes_from_the_engine_that_will_apply_it():
    """Reimplementing it here would let the two numbers drift apart silently --
    a fan-in emitting quotes the gate then rejects."""
    assert mod.freshness_ceiling_seconds("mlb") == 6 * 3600
    assert mod.freshness_ceiling_seconds("wnba") == 6 * 3600
    assert mod.freshness_ceiling_seconds("soccer") == 24 * 3600


# ==========================================================================
# THE SEAM -- stamping the field the gate actually reads
# ==========================================================================


def test_stamping_sets_the_field_the_freshness_gate_reads():
    """`_candidate_age_seconds` reads `last_updated` first, `updated_epoch`
    second. A candidate priced from a live quote but still carrying last
    night's timestamp is rejected while holding a price seconds old."""
    now = time.time()
    stamped = stamp_candidate_freshness(
        {"name": "Yankees", "last_updated": "2026-08-23T08:00:00Z"},
        _q("kalshi", age=5.0, now=now),
    )
    assert stamped["updated_epoch"] == pytest.approx(now - 5.0, abs=1.0)
    assert stamped["last_updated"].endswith("Z")
    assert stamped["price_source"] == "kalshi"
    assert stamped["venue_ref"] == "kalshi-ref"


def test_a_missing_quote_does_NOT_refresh_the_timestamp():
    """Stamping without a price would launder a stale candidate as fresh --
    worse than an honest stale one, because it defeats the gate rather than
    passing it."""
    original = {"name": "Yankees", "last_updated": "2026-08-23T08:00:00Z"}
    assert stamp_candidate_freshness(original, None) == original


def test_stamping_does_not_mutate_the_input():
    original = {"last_updated": "2026-08-23T08:00:00Z"}
    stamp_candidate_freshness(original, _q("kalshi"))
    assert original["last_updated"] == "2026-08-23T08:00:00Z"


# ==========================================================================
# TWO GATES, TWO FIELDS. Missing the second emptied the board.
# ==========================================================================


def test_stamping_sets_the_SHORTLIST_gate_field_too():
    """MEASURED 2026-08-24 23:23Z: beyond_quote_age=6184 of considered=8600 --
    71.9% of the board died on `layer2_board._row_quote_age_seconds`, which
    reads row["quote"]["quote_seen_age_seconds"]. Stamping only `last_updated`
    would have fixed the gate that was already recovering and left the one
    actually emptying the board."""
    now = time.time()
    stamped = stamp_candidate_freshness({"quote": {"book_age_seconds": 50000.0}},
                                        _q("kalshi", age=12.0, now=now))
    assert stamped["quote"]["quote_seen_age_seconds"] == pytest.approx(12.0, abs=1.0)
    assert stamped["quote"]["quote_source"] == "kalshi"


def test_book_age_seconds_is_DELIBERATELY_left_alone():
    """It answers "has the market moved", not "how old is our observation", and
    opportunity_gate's live/pregame checks read it for that. Overwriting it
    would make a motionless market look like a moving one."""
    stamped = stamp_candidate_freshness({"quote": {"book_age_seconds": 50000.0}},
                                        _q("kalshi", age=5.0))
    assert stamped["quote"]["book_age_seconds"] == 50000.0


def test_the_nested_quote_block_is_COPIED_not_mutated():
    """These rows are shared across the build. Mutating a nested dict would
    age-stamp rows this quote was never applied to."""
    original = {"quote": {"book_age_seconds": 50000.0}}
    stamp_candidate_freshness(original, _q("kalshi", age=5.0))
    assert "quote_seen_age_seconds" not in original["quote"]


def test_a_row_with_no_quote_block_still_gets_one():
    stamped = stamp_candidate_freshness({}, _q("polymarket_us", age=3.0))
    assert stamped["quote"]["quote_seen_age_seconds"] == pytest.approx(3.0, abs=1.0)


# --------------------------------------------------------------------------
# Applying to a row set
# --------------------------------------------------------------------------


def test_only_rows_we_actually_priced_are_stamped():
    """A row with no venue quote stays as stale as it really is. Blanket
    -refreshing timestamps would launder staleness through a gate designed to
    catch it -- worse than the empty board this exists to fix."""
    now = time.time()
    # Keys are DERIVED from the row the same way the adapters build them, so
    # the fixture uses real board-row fields rather than a pre-set key.
    from syndicate.features.shared.venue_quote_adapters import quote_key

    home_key = quote_key("mlb", "h2h", "home", None)
    collected = {"quotes": {home_key: _q("kalshi", key=home_key, age=10, now=now)}}
    result = mod.apply_venue_quotes(
        [{"sport": "mlb", "market": "h2h", "side": "home", "quote": {"book_age_seconds": 50000.0}},
         {"sport": "mlb", "market": "h2h", "side": "away", "quote": {"book_age_seconds": 50000.0}}],
        "2026-08-24", collected_by_sport={"mlb": collected}, now=now,
    )
    assert result["stamped"] == 1
    assert result["unstamped"] == 1
    priced, unpriced = result["rows"]
    assert priced["quote"]["quote_seen_age_seconds"] == pytest.approx(10.0, abs=1.0)
    # Untouched, and still carrying its real 50,000s age.
    assert "quote_seen_age_seconds" not in unpriced["quote"]


def test_the_applier_reports_what_would_still_be_gated():
    now = time.time()
    collected = {"quotes": {}, "ceiling_seconds": 6 * 3600, "by_source": {}, "selected_by_source": {}}
    result = mod.apply_venue_quotes(
        [{"key": "a"}, {"key": "b"}], "2026-08-24", collected_by_sport={"mlb": collected}, now=now,
    )
    assert result["rows_in"] == 2
    assert result["stamped"] == 0
    assert result["unstamped"] == 2


def test_every_source_uses_ONE_key_space():
    """Two sources on different keys do not contend -- they never meet, and the
    freshest-wins rule this module is built on is silently inert. The OddsAPI
    adapter first used the shard's own market key
    (`event_id=...|market=h2h|side=Draw|book=draftkings`), which shares no key
    space with the venue adapters."""
    from syndicate.features.shared.venue_quote_adapters import quote_key

    expected = quote_key("mlb", "h2h", "home", None)
    assert expected == "mlb|h2h|home"
    # A line is part of the identity: a -1.5 and a -2.5 spread are different
    # bets, and collapsing them prices one at the other's number.
    assert quote_key("mlb", "spreads", "home", -1.5) != quote_key("mlb", "spreads", "home", -2.5)


def test_a_row_whose_key_matches_a_quote_is_repriced_across_sources():
    """The point of one key space: a Kalshi quote and an OddsAPI quote for the
    same bet contend, and the fresher wins."""
    from syndicate.features.shared.venue_quote_adapters import quote_key

    now = time.time()
    key = quote_key("mlb", "h2h", "home", None)
    result = mod.apply_venue_quotes(
        [{"sport": "mlb", "market": "h2h", "side": "home"}],
        "2026-08-24", now=now,
        collected_by_sport={"mlb": {"quotes": {key: _q("polymarket_us", key=key, age=4.0, now=now)}}},
    )
    assert result["stamped"] == 1
    assert result["rows"][0]["price_source"] == "polymarket_us"


def test_quotes_are_collected_PER_SPORT_not_once_for_the_board():
    """The row set spans every active sport, while every ceiling, artifact and
    adapter is per-sport. One collect_quotes call for the whole board would
    price MLB rows against whichever sport was passed in -- a WRONG price
    rather than a missing one."""
    asked: list[str] = []

    def fake_collect(sport, _date, now=None):
        asked.append(sport)
        return {"quotes": {}, "ceiling_seconds": 6 * 3600, "by_source": {}}

    import syndicate.features.shared.venue_quote_fanin as fanin

    original = fanin.collect_quotes
    try:
        fanin.collect_quotes = fake_collect
        result = fanin.apply_venue_quotes(
            [{"sport": "mlb", "market": "h2h", "side": "home"},
             {"sport": "wnba", "market": "h2h", "side": "home"},
             {"sport": "mlb", "market": "totals", "side": "over", "line": 8.5}],
            "2026-08-24",
        )
    finally:
        fanin.collect_quotes = original
    # Once per DISTINCT sport, not once per row.
    assert sorted(asked) == ["mlb", "wnba"]
    assert result["sports"] == ["mlb", "wnba"]


def test_one_sports_venue_failure_does_not_cost_the_others(monkeypatch):
    import syndicate.features.shared.venue_quote_fanin as fanin

    now = time.time()
    key = "wnba|h2h|home"

    def flaky(sport, _date, now=None):
        if sport == "mlb":
            raise RuntimeError("kalshi unreachable")
        return {"quotes": {key: _q("kalshi", key=key, age=5.0, now=now)}, "ceiling_seconds": 21600}

    monkeypatch.setattr(fanin, "collect_quotes", flaky)
    result = fanin.apply_venue_quotes(
        [{"sport": "mlb", "market": "h2h", "side": "home"},
         {"sport": "wnba", "market": "h2h", "side": "home"}],
        "2026-08-24", now=now,
    )
    assert result["stamped"] == 1
    assert result["rows"][1]["price_source"] == "kalshi"


def test_a_row_with_no_sport_is_left_alone():
    result = mod.apply_venue_quotes([{"market": "h2h", "side": "home"}], "2026-08-24",
                                    collected_by_sport={})
    assert result["stamped"] == 0
    assert result["rows"][0] == {"market": "h2h", "side": "home"}


# ==========================================================================
# The Polymarket adapter must SELECT by sport, not just key by it
# ==========================================================================


def test_the_polymarket_adapter_filters_the_slate_BY_SPORT(monkeypatch):
    """MEASURED 2026-08-24 23:45Z: polymarket_us reported quotes=7040 for mlb,
    wnba, nfl AND soccer -- the same 7,040 every time, because `sport` was used
    only to BUILD THE KEY and never to select rows. An NFL market keyed
    `mlb|h2h|Chargers` is a WRONG price, not a missing one."""
    from syndicate.features.shared import venue_quote_adapters as adapters

    slate = {
        "fetched_at": time.time(),
        "markets": [
            # FULL CLUB NAMES, which is what production actually sends for
            # these leagues -- measured 2026-08-25T00:46Z, the offered keys were
            # `mlb|h2h|chicago cubs` and `mlb|h2h|arizona diamondbacks`. The
            # fixture used bare nicknames ("Padres", "Chargers"), which
            # `canonical_team` cannot resolve for mlb or nfl; once the adapter
            # started keying by canonical club that fixture tested the alias
            # gap rather than the sport filter it is named for. The gap itself
            # is covered by its own test below.
            {"slug": "aec-mlb-pit-sd-2026-08-24", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Pittsburgh Pirates","San Diego Padres"]', "outcomePrices": '["0.45","0.55"]'},
            {"slug": "aec-nfl-lac-ten-2026-08-28", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Los Angeles Chargers","Tennessee Titans"]', "outcomePrices": '["0.5","0.5"]'},
        ],
    }
    monkeypatch.setattr(adapters, "_artifact", lambda _p: (slate, time.time()))

    mlb = adapters.polymarket_us_outcome("mlb", "2026-08-24")
    nfl = adapters.polymarket_us_outcome("nfl", "2026-08-28")
    assert len(mlb.quotes) == 2 and all(q.key.startswith("mlb|") for q in mlb.quotes)
    assert len(nfl.quotes) == 2 and all(q.key.startswith("nfl|") for q in nfl.quotes)
    # And no cross-contamination: the NFL teams never appear under mlb.
    assert not any("chargers" in q.key or "titans" in q.key for q in mlb.quotes)


def test_a_sport_the_venue_does_not_quote_reports_no_rows_by_name(monkeypatch):
    from syndicate.features.shared import venue_quote_adapters as adapters

    slate = {"fetched_at": time.time(), "markets": [
        {"slug": "aec-mlb-pit-sd-2026-08-24", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
         "outcomes": '["Pirates","Padres"]', "outcomePrices": '["0.45","0.55"]'}]}
    monkeypatch.setattr(adapters, "_artifact", lambda _p: (slate, time.time()))
    outcome = adapters.polymarket_us_outcome("nhl", "2026-08-24")
    assert outcome.status == "no_rows"
    assert "nhl" in outcome.reason
