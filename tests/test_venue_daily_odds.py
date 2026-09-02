"""The capture-first daily odds layer.

The point of this module is that an unparsed market family becomes a COUNTED
ROW rather than a silence. These tests pin that, plus the properties inherited
from `kalshi_board.record_snapshot` that make the record usable for CLV.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import venue_daily_odds as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    yield


def _row(market_id="m1", yes=0.5, no=0.5, market="h2h", **kw):
    row = {"id": market_id, "yes": yes, "no": no, "market": market,
           "sport": "mlb", "game_date": "2026-08-25", "family": "KXTEST"}
    row.update(kw)
    return row


# --------------------------------------------------------------------------
# The inversion: what the join refuses, this keeps
# --------------------------------------------------------------------------


def test_an_unparsed_market_is_STORED_and_counted_by_family():
    """THE WHOLE POINT. Today an unparsed family is invisible -- not refused,
    not counted, not stored -- so the only way to find it is for a human to see
    it on the venue's website. That is the whack-a-mole mechanism."""
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [
        _row("m1", market=None, family="unreadable_title", raw_title="9th inning: Over 1.5 runs"),
    ])
    assert report["status"] == "ok"
    assert report["unparsed_by_family"] == {"unreadable_title": 1}
    assert report["markets"] == 1


def test_the_raw_title_survives_so_a_grammar_can_be_written_from_it():
    """Three grammars written from imagined strings matched none of production
    and left 302 markets unreadable. The stored string is what makes the next
    one writable from data."""
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [
        _row("m1", market=None, raw_title="Will Minnesota be the 2026 AL Central Division Winner"),
    ])
    from syndicate.features.shared.refresh_state_store import read_json_file

    state = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))
    assert state["markets"]["m1"]["raw_title"].startswith("Will Minnesota")


def test_a_grammar_landing_later_names_the_market_without_moving_the_opening():
    """A market first seen unparsed and later understood keeps its OPENING --
    which is the only price CLV can be measured against."""
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                          [_row("m1", yes=0.40, no=0.62, market=None)])
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                          [_row("m1", yes=0.55, no=0.47, market="totals")])

    from syndicate.features.shared.refresh_state_store import read_json_file

    entry = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))["markets"]["m1"]
    assert entry["market"] == "totals"
    assert entry["opening_yes"] == 0.40, "the opening moved when the grammar landed"


# --------------------------------------------------------------------------
# Inherited from record_snapshot, and load-bearing
# --------------------------------------------------------------------------


def test_a_point_is_appended_only_when_the_price_MOVED():
    """A point per fetch recording that nothing happened would push the real
    moves out of a bounded window."""
    first = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=0.5, no=0.5)])
    second = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=0.5, no=0.5)])
    third = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=0.6, no=0.4)])
    assert (first["appended"], first["opened"]) == (1, 1)
    assert (second["appended"], second["unchanged"]) == (0, 1)
    assert third["appended"] == 1


def test_the_opening_is_first_sight_not_the_first_board_build():
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=0.31, no=0.71)])
    for price in (0.44, 0.52, 0.61):
        mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=price, no=1 - price)])

    from syndicate.features.shared.refresh_state_store import read_json_file

    entry = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))["markets"]["m1"]
    assert entry["opening_yes"] == 0.31


def test_every_counter_is_returned_including_the_zeroes():
    """A counter that appears only when it fires cannot distinguish "ran and
    nothing changed" from "never ran"."""
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row()])
    for key in ("listed", "opened", "appended", "unchanged", "unpriced",
                "skipped_no_id", "parsed", "trimmed_points", "trimmed_markets"):
        assert key in report, key


def test_an_unpriced_market_is_counted_not_silently_dropped():
    """"They do not offer this" and "nobody is making a price right now" are
    different facts about coverage."""
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                                   [_row(yes=None, no=None)])
    assert report["unpriced"] == 1
    assert report["markets"] == 0


def test_points_are_trimmed_oldest_first_and_counted(monkeypatch):
    monkeypatch.setattr(mod, "MAX_POINTS_PER_MARKET", 3)
    for n in range(6):
        mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                              [_row(yes=0.1 * (n + 1), no=0.9)])

    from syndicate.features.shared.refresh_state_store import read_json_file

    entry = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))["markets"]["m1"]
    assert len(entry["points"]) == 3
    # Safe only because the opening lives in `opening_yes`, never in points[0].
    assert entry["opening_yes"] == pytest.approx(0.1)


# --------------------------------------------------------------------------
# The per-sport, per-date split
# --------------------------------------------------------------------------


def test_the_book_is_split_per_sport_and_date():
    """The keyvalue store refuses at 8MB and `layer2_shortlist` already holds
    5.0MB. A single whole-book document is a write that starts failing
    silently one sport from now."""
    report = mod.record_venue_book("kalshi", [
        _row("a", sport="mlb", game_date="2026-08-25"),
        _row("b", sport="wnba", game_date="2026-08-25"),
        _row("c", sport="mlb", game_date="2026-08-26"),
    ])
    assert report["files"] == 3
    assert mod.daily_odds_path("kalshi", "mlb", "2026-08-25").exists()
    assert mod.daily_odds_path("kalshi", "wnba", "2026-08-25").exists()


def test_an_undated_row_is_counted_never_filed_under_today():
    """Filing an undated market under the current date is how a stale market
    becomes tomorrow's opening line. Futures land here correctly -- a
    season-long market has no game day."""
    report = mod.record_venue_book("kalshi", [
        _row("future", game_date=None, market=None,
             raw_title="Will Minnesota be the 2026 AL Central Division Winner"),
        _row("game", game_date="2026-08-25"),
    ])
    assert report["undated"] == 1
    assert report["files"] == 1


def test_a_futures_ticker_has_no_game_date_so_it_does_not_reach_a_daily_file():
    """End to end through the real Kalshi adapter, on a real measured ticker
    pair: `KXMLBALCENT-26-MIN` carries no game date, `KXMLBKS-26AUG24...` does.
    That separation is what keeps futures out of the daily odds without any
    title parsing."""
    rows = mod.kalshi_daily_rows([
        {"ticker": "KXMLBALCENT-26-MIN", "series": "KXMLBALCENT",
         "title": "Will Minnesota be the 2026 AL Central Division Winner",
         "yes_ask_dollars": 0.2, "no_ask_dollars": 0.8},
        {"ticker": "KXMLBKS-26AUG242145CINSF-CINCBURNS26-7", "series": "KXMLBKS",
         "title": "Chase Burns: 7+ strikeouts?",
         "yes_ask_dollars": 0.48, "no_ask_dollars": 0.54},
    ])
    report = mod.record_venue_book("kalshi", rows)
    assert report["undated"] == 1
    assert report["listed"] == 1


def test_the_polymarket_adapter_keeps_what_the_join_refuses():
    """6,838 `market_type_not_a_game_line` are fetched and discarded every
    cycle. `SPORTS_MARKET_TYPE_PROP` is a MIXED bucket -- it holds League of
    Legends map winners -- so the family is the venue's own type and nothing is
    inferred from it here."""
    rows = mod.polymarket_daily_rows([{
        "slug": "astatc-lol-bam-gng-2026-08-20-game1",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "question": "Will Baam Esports win Game 1 vs GnG Amazigh?",
        "outcomePrices": '["0.01","0.99"]',
    }])
    assert len(rows) == 1
    assert rows[0]["market"] is None
    assert rows[0]["family"] == "SPORTS_MARKET_TYPE_PROP"
    assert rows[0]["raw_title"].startswith("Will Baam")
    assert rows[0]["sport"] == "lol"


def test_a_one_sided_polymarket_quote_is_recorded_not_discarded():
    """209 rows on 2026-08-25 had two outcomes and one price. Half a quote is
    still a price the venue showed."""
    rows = mod.polymarket_daily_rows([{
        "slug": "aec-mlb-tex-cws-2026-08-25",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
        "question": "Who wins?", "outcomePrices": '["0.495"]',
    }])
    assert rows[0]["yes"] == "0.495"
    assert rows[0]["no"] is None


# --------------------------------------------------------------------------
# Sports only, and only the ones Syndicate models
# --------------------------------------------------------------------------


def test_a_sport_syndicate_does_not_model_gets_no_file():
    """MEASURED 2026-08-25T17:34:36Z, before this filter: files=211 --
    Argentine second division, tennis, table tennis, esports -- written to the
    keyvalue store every 180s for leagues no module models. Capture-first is
    not capture-everything: a market with no sim, no board and no grader
    cannot be priced, and storing it crowds out the sports that can."""
    report = mod.record_venue_book("polymarket", [
        _row("a", sport="mlb", game_date="2026-08-25"),
        _row("b", sport="atp", game_date="2026-08-25"),
        _row("c", sport="arg2", game_date="2026-08-25"),
        _row("d", sport="arg2", game_date="2026-08-25"),
    ])
    assert report["files"] == 1
    assert report["skipped_by_sport"] == {"arg2": 2, "atp": 1}
    assert report["skipped_total"] == 3


def test_an_out_of_scope_sport_is_COUNTED_never_silent():
    """This is where Polymarket's soccer league codes will surface. Syndicate
    models ten soccer leagues; Polymarket names leagues in its own vocabulary
    and the mapping has never been read. Counting makes those codes addable
    from data instead of guessed."""
    report = mod.record_venue_book("polymarket", [
        _row("a", sport="epl", game_date="2026-08-25"),
    ])
    assert report["files"] == 0
    assert report["skipped_by_sport"]["epl"] == 1


def test_the_scope_is_extendable_without_a_deploy(monkeypatch):
    """A soccer code goes in the minute it is identified."""
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_SPORTS", "mlb, arg2")
    assert mod.in_scope_sports() == frozenset({"mlb", "arg2"})
    report = mod.record_venue_book("polymarket", [
        _row("a", sport="arg2", game_date="2026-08-25"),
    ])
    assert report["files"] == 1


def test_the_default_scope_covers_the_sports_the_platform_models():
    scope = mod.in_scope_sports()
    for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"):
        assert sport in scope, sport


# --------------------------------------------------------------------------
# Zero is not a price -- it is an empty side of the book
# --------------------------------------------------------------------------


def test_a_zero_price_is_not_recorded_as_an_opening():
    """MEASURED 2026-08-25T17:43:05Z:

        MOVER KXMLBKS-26AUG251907KCTOR-TORMSCHERZER31-2
              open=0.0 now=0.93 move_pts=93.0 n=4

    `yes_ask_dollars = 0.0` means there is NO ASK. Recorded as an opening it
    manufactures a 93-point move that never happened -- and CLV is measured
    against the opening, so every bet on that market would score a beat it
    never got. A missing opening is a known unknown; a fabricated one is a
    wrong number that looks like a signal.
    """
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                                   [_row(yes=0.0, no=0.0)])
    assert report["unpriced"] == 1
    assert report["markets"] == 0


def test_a_one_price_is_also_refused():
    """1.0 is a settled market, or the empty side of the other leg."""
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                                   [_row(yes=1.0, no=1.0)])
    assert report["unpriced"] == 1


def test_one_live_side_is_still_recorded_when_the_other_is_empty():
    """A one-sided book is real. Half a quote is still a price the venue
    showed -- refusing the row entirely would discard a live market."""
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25",
                                   [_row(yes=0.93, no=0.0)])
    assert report["unpriced"] == 0
    assert report["opened"] == 1

    from syndicate.features.shared.refresh_state_store import read_json_file

    entry = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))["markets"]["m1"]
    assert entry["opening_yes"] == 0.93
    assert entry["opening_no"] is None


def test_the_opening_waits_for_a_real_price_rather_than_taking_zero():
    """The whole point: a market first seen unquoted must open at its first
    REAL price, not at the emptiness."""
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=0.0, no=0.0)])
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row(yes=0.93, no=0.08)])

    from syndicate.features.shared.refresh_state_store import read_json_file

    entry = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))["markets"]["m1"]
    assert entry["opening_yes"] == 0.93, "the empty book became the opening"


# --------------------------------------------------------------------------
# A frozen feed and a flat market must never share a number
# --------------------------------------------------------------------------


def _frozen_feed_row(**kw):
    row = {
        "id": "m1", "market": "totals", "line": 7.5, "side": None, "player": None,
        "family": "TOTAL", "event": "cin-sf", "raw_title": "x",
        "game_date": "2026-08-25", "sport": "mlb", "yes": "0.51", "no": "0.49",
    }
    row.update(kw)
    return row


def test_a_frozen_source_is_NAMED_not_read_as_a_flat_market(tmp_path, monkeypatch):
    """THE DAY THE DAILY BOOK RECORDED NOTHING.

    Measured 2026-08-25: six consecutive `POLYMARKET_DAILY_BOOK` lines were
    BYTE-IDENTICAL (`listed=5688 parsed=2664 opened=0 appended=0`) while
    `persist_game_slate` was erroring on every cycle
    (`POLYMARKET_US_SLATE_WRITE status=error reason=no_game_offset: ok`). The
    book read as an hour of flat prices; the truth was that nothing had been
    fetched.

    "Prices did not change" and "we are looking at the same photograph again"
    produce the same `unchanged` count, and only one of them is a fact about
    the market. The SOURCE's own stamp is what tells them apart.
    """
    from syndicate.features.shared import refresh_state_store
    from syndicate.features.shared import venue_daily_odds as mod

    monkeypatch.setattr(refresh_state_store, "reports_root", lambda: tmp_path)

    first = mod.record_venue_book("polymarket", [_frozen_feed_row()], source_fetched_at=1000.0)
    assert (first["opened"], first["appended"], first["stale_source_files"]) == (1, 1, 0)

    # SAME source stamp: the feed did not advance.
    frozen = mod.record_venue_book("polymarket", [_frozen_feed_row()], source_fetched_at=1000.0)
    assert frozen["appended"] == 0
    assert frozen["unchanged"] == 1
    assert frozen["stale_source_files"] == 1, "a frozen feed must be named"

    # Fresh stamp AND a moved price: a real point.
    moved = mod.record_venue_book(
        "polymarket", [_frozen_feed_row(yes="0.55")], source_fetched_at=2000.0
    )
    assert moved["appended"] == 1
    assert moved["stale_source_files"] == 0


def test_a_genuinely_flat_market_on_a_FRESH_feed_is_not_flagged(tmp_path, monkeypatch):
    """The other direction, which is what makes the flag mean anything. A feed
    that advanced while the price held is a real observation, and it must not
    be reported as staleness or the counter becomes noise."""
    from syndicate.features.shared import refresh_state_store
    from syndicate.features.shared import venue_daily_odds as mod

    monkeypatch.setattr(refresh_state_store, "reports_root", lambda: tmp_path)

    mod.record_venue_book("polymarket", [_frozen_feed_row()], source_fetched_at=1000.0)
    flat = mod.record_venue_book("polymarket", [_frozen_feed_row()], source_fetched_at=2000.0)

    assert flat["appended"] == 0, "an unmoved price still appends no point"
    assert flat["unchanged"] == 1
    assert flat["stale_source_files"] == 0, "the FEED advanced -- that is not staleness"


def test_appended_zero_is_always_attributable(tmp_path, monkeypatch):
    """Three different problems with three different fixes, and the caller
    printed none of them. `appended=0` must always be explainable from the
    counters on the same line."""
    from syndicate.features.shared import refresh_state_store
    from syndicate.features.shared import venue_daily_odds as mod

    monkeypatch.setattr(refresh_state_store, "reports_root", lambda: tmp_path)

    report = mod.record_venue_book(
        "polymarket",
        [
            _frozen_feed_row(id="", market="totals"),                 # no id
            _frozen_feed_row(id="m2", yes=None, no=None),             # listed, not quoted
            _frozen_feed_row(id="m3"),                                # a real point
        ],
        source_fetched_at=1000.0,
    )
    assert report["skipped_no_id"] == 1
    assert report["unpriced"] == 1
    assert report["appended"] == 1
    # Every row is accounted for by a named counter.
    assert report["skipped_no_id"] + report["unpriced"] + report["appended"] == 3


# --------------------------------------------------------------------------
# The scope check was comparing two vocabularies
# --------------------------------------------------------------------------


def test_polymarkets_league_token_maps_to_the_sport_syndicate_models():
    """FIVE TOKENS COLLIDE BY COINCIDENCE AND THAT HID THE BUG.

    `in_scope_sports()` returns Syndicate's names (`mlb`, `nfl`, `wnba`, `nba`,
    `nhl`, `ncaaf`, `ncaab`, `soccer`); the row carries POLYMARKET's league
    token. The first five match by luck. `cfb` never matches `ncaaf`, and no
    soccer competition token has ever matched `soccer` -- so those markets were
    filed under "a sport Syndicate does not model", in sports we model
    completely.

    Measured 2026-08-25 5:48 PM Central, one cycle:

        'cfb': 555   'lal': 351   'lg1': 216   'epl': 80   'eflch': 36

    Every mapping is confirmed against a REAL GAME, never against the token
    resembling a league name: `cfb-ncar-tcu-2026-08-29` (North Carolina at
    TCU) and `epl-cry-mnc-2026-08-28` (Crystal Palace v Man City) are
    user-confirmed URLs; the other soccer codes are confirmed by the CLUBS in
    verbatim slugs in the coverage audit's §6.
    """
    from syndicate.features.shared.venue_daily_odds import (
        in_scope_sports,
        sport_for_polymarket_league,
    )

    wanted = in_scope_sports()
    assert sport_for_polymarket_league("cfb") == "ncaaf"
    assert sport_for_polymarket_league("cfb") in wanted, "555 markets/cycle"
    for token in ("epl", "lal", "lg1", "sea", "bun", "eflc", "eflch"):
        assert sport_for_polymarket_league(token) == "soccer", token
        assert sport_for_polymarket_league(token) in wanted, token

    # The five that already worked must keep working.
    for token in ("mlb", "nfl", "wnba", "nba", "nhl"):
        assert sport_for_polymarket_league(token) == token


def test_an_unmapped_competition_keeps_its_own_name_and_stays_counted():
    """THE TOKENS DRIFT, so the map is a floor and not a closed list: `eflc` in
    the audit's own reading became `eflch` hours later, and `lig2`, `csl`,
    `tdp` and `fibawcq` appeared in between.

    An unmapped token must pass through UNCHANGED rather than fall to a
    default. It then fails the scope check and lands in `skipped_by_sport` by
    its own name -- which is the surface the next mapping gets read from. A
    default would erase exactly that.
    """
    from syndicate.features.shared.venue_daily_odds import (
        in_scope_sports,
        sport_for_polymarket_league,
    )

    for token in ("lig2", "csl", "tdp", "fibawcq", "atp", "cs2"):
        assert sport_for_polymarket_league(token) == token, token
        assert sport_for_polymarket_league(token) not in in_scope_sports(), token


def test_the_row_keeps_the_venues_league_beside_the_mapped_sport():
    """Mapping six competitions onto one sport is right for the file split and
    wrong to do destructively. Which competition a market belongs to is the
    thing the next mapping -- and any per-league analysis -- is read from."""
    from syndicate.features.shared.venue_daily_odds import polymarket_daily_rows

    rows = polymarket_daily_rows([{
        "slug": "astatc-lal-ala-vil-2026-08-28-btts",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "outcomePrices": '["0.6","0.4"]',
    }])
    assert rows[0]["sport"] == "soccer"
    assert rows[0]["league"] == "lal"


# --------------------------------------------------------------------------
# `#638` -- the bound that actually fires is BYTES
#
# 2,203 `KEYVALUE_WRITE_REJECTED` on live-odds-worker in 40 hours, 1,652 of
# them one NCAAF date, each discarding that tick's prices while the file sat
# frozen at its last good write. The count caps could never have prevented it:
# they bound markets and points, the guard bounds bytes.
# --------------------------------------------------------------------------


def _big_state(markets=200, points=48):
    """A document whose SERIALIZED size is the thing under test."""
    state = {"venue": "kalshi", "sport": "ncaaf", "game_date": "2026-09-05",
             "updated_at": "2026-09-02T00:00:00Z", "markets": {}}
    for i in range(markets):
        state["markets"][f"m{i:05d}"] = {
            "market": None,
            "family": "unreadable_title",
            # The real payload's bulk: an unparsed market carries its title so
            # a grammar can be written from it later.
            "raw_title": f"Some quite long unreadable market title number {i} " * 6,
            "opened_at": "2026-08-20T00:00:00Z",
            "opening_yes": 0.11,
            "opening_no": 0.89,
            # STRICTLY ascending with i. An earlier draft used `i % 60`, which
            # wraps -- markets 60+ got the EARLIEST stamps and the recency test
            # failed against correct code. The fixture has to make the ordering
            # it asserts on unambiguous.
            "last_seen": f"2026-09-02T{i // 60:02d}:{i % 60:02d}:00Z",
            "points": [{"ts": f"2026-09-0{1 + (p % 2)}T00:{p % 60:02d}:00Z",
                        "yes": 0.5, "no": 0.5} for p in range(points)],
        }
    return state


def test_a_document_that_already_fits_is_returned_UNTOUCHED():
    """The trim must be inert on the happy path. A trim that always fires would
    silently shorten every history in the system."""
    state = _big_state(markets=3, points=4)
    before = mod._serialized_bytes(state)
    out, points_dropped, markets_dropped = mod._trim_to_budget(state, before + 1)
    assert (points_dropped, markets_dropped) == (0, 0)
    assert len(out["markets"]) == 3
    assert len(out["markets"]["m00000"]["points"]) == 4


def test_the_trim_is_measured_in_BYTES_not_counts_and_the_result_actually_fits():
    """ASSERTS THE SERIALIZED SIZE, not that a counter moved. A counter can
    move while the payload is still over the ceiling -- which is exactly the
    failure this replaces."""
    state = _big_state()
    budget = mod._serialized_bytes(state) // 4
    out, points_dropped, _ = mod._trim_to_budget(state, budget)
    assert mod._serialized_bytes(out) <= budget
    assert points_dropped > 0


def test_points_are_shed_BEFORE_markets_because_coverage_is_the_point():
    """An unparsed family is only discoverable because its `raw_title` is
    stored, so market coverage outranks price history."""
    state = _big_state(markets=60, points=48)
    # Loose enough that dropping points alone gets under it.
    budget = mod._serialized_bytes(state) // 2
    out, points_dropped, markets_dropped = mod._trim_to_budget(state, budget)
    assert markets_dropped == 0, "markets were dropped while points remained to shed"
    assert points_dropped > 0
    assert len(out["markets"]) == 60


def test_the_opening_SURVIVES_every_level_of_trimming():
    """CLV is measured against the opening, and it is never in `points[0]`.
    Trimmed to almost nothing, the opening must still be there."""
    state = _big_state()
    out, _, _ = mod._trim_to_budget(state, 4096)
    assert out["markets"], "trimmed to zero markets before reaching the budget"
    for entry in out["markets"].values():
        assert entry["opening_yes"] == 0.11
        assert entry["opening_no"] == 0.89
        assert entry["opened_at"] == "2026-08-20T00:00:00Z"


def test_when_markets_must_go_the_LEAST_RECENTLY_SEEN_go_first():
    """Same key the count-based trim already uses, so crossing the byte bound
    does not prune by a different rule than crossing the count bound."""
    state = _big_state(markets=64, points=1)
    out, _, markets_dropped = mod._trim_to_budget(state, 3000)
    assert markets_dropped > 0
    survivors = sorted(out["markets"])
    # last_seen ascends with the index, so the highest indices are newest.
    assert survivors[-1] == f"m{63:05d}"
    assert "m00000" not in out["markets"]


def test_an_oversized_write_is_RETRIED_and_the_report_says_so(monkeypatch):
    """End to end through `record_daily_odds`: the store refuses once, the
    document is trimmed, the retry lands, and `trimmed_to_fit` is reported."""
    from syndicate.features.shared.refresh_state_store import KeyValuePayloadTooLarge

    seen: list[int] = []
    real_budget = 20000

    def _fake_write(path, payload):
        size = mod._serialized_bytes(payload)
        seen.append(size)
        if size > real_budget:
            raise KeyValuePayloadTooLarge(f"{size} bytes")

    monkeypatch.setattr(mod, "MAX_POINTS_PER_MARKET", 48)
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.write_json_file", _fake_write
    )
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store._keyvalue_max_bytes",
        lambda: int(real_budget / 0.90),
    )

    rows = [
        {"id": f"m{i:04d}", "yes": 0.5, "no": 0.5, "market": None,
         "sport": "ncaaf", "game_date": "2026-09-05", "family": "unreadable_title",
         "raw_title": f"A long unreadable market title number {i} " * 8}
        for i in range(120)
    ]
    report = mod.record_daily_odds("kalshi", "ncaaf", "2026-09-05", rows)

    assert report["status"] == "ok"
    assert report["trimmed_to_fit"] is True
    assert len(seen) == 2, "expected exactly one refusal and one retry"
    assert seen[0] > real_budget
    assert seen[1] <= real_budget, "the retry was still over the ceiling"


def test_trimmed_to_fit_is_reported_even_when_FALSE(monkeypatch):
    """A flag that appears only when it fires cannot distinguish 'the document
    fits' from 'this build does not have the trim'."""
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row("m1")])
    assert report["trimmed_to_fit"] is False


# --------------------------------------------------------------------------
# `#637` -- venue_odds lives on DISK, not in the shared keyvalue store
# --------------------------------------------------------------------------


def test_a_venue_odds_path_is_NOT_keyvalue_backed_even_on_the_keyvalue_backend(monkeypatch):
    """The whole point of #637: 41 of these keys held 114.9MB of a 224.3MB
    store, on a 256MB plan at 93%, and nothing reads them."""
    from syndicate.features.shared import refresh_state_store as store

    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    assert store._keyvalue_backed(mod.daily_odds_path("kalshi", "ncaaf", "2026-09-05")) is False


def test_a_SIBLING_intelligence_path_is_still_keyvalue_backed(monkeypatch):
    """SCOPED. The exclusion must take `venue_odds` out and leave the rest of
    `reports/intelligence` -- which IS read cross-service -- where it was."""
    from syndicate.features.shared import refresh_state_store as store

    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    sibling = store.reports_root() / "intelligence" / "kalshi_markets.json"
    assert store._keyvalue_backed(sibling) is True


def test_read_and_write_AGREE_after_the_exclusion(monkeypatch):
    """`_keyvalue_backed` is documented as the one predicate both sides use so
    they cannot disagree -- a split sends writes to disk and reads to Redis and
    reads as 'the artifact vanished'. Pin that they still agree."""
    from syndicate.features.shared import refresh_state_store as store

    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    path = mod.daily_odds_path("kalshi", "ncaaf", "2026-09-05")
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_json_file(path, {"markets": {"m1": {"opening_yes": 0.4}}})
    assert path.is_file(), "write did not land on disk"
    assert store.read_json_file(path) == {"markets": {"m1": {"opening_yes": 0.4}}}


def test_the_old_keyvalue_copy_is_CARRIED_OVER_so_openings_are_not_reinvented(monkeypatch):
    """An accumulator that captures the opening on FIRST SIGHT does not fail
    quietly when it starts empty -- it rewrites every `opened_at` to the
    migration moment. Wrong data, not absent data."""
    carried = {
        "markets": {
            "m1": {"market": "h2h", "family": "KXTEST", "opened_at": "2026-08-20T00:00:00Z",
                   "opening_yes": 0.11, "opening_no": 0.89, "points": []},
        }
    }
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_keyvalue_copy",
        lambda path: carried,
    )
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row("m1", yes=0.6, no=0.4)])
    assert report["status"] == "ok"
    # NOT re-opened: the market was already known, so this is an append.
    assert report["opened"] == 0
    assert report["appended"] == 1
    from syndicate.features.shared.refresh_state_store import read_json_file
    state = read_json_file(mod.daily_odds_path("kalshi", "mlb", "2026-08-25"))
    assert state["markets"]["m1"]["opened_at"] == "2026-08-20T00:00:00Z"
    assert state["markets"]["m1"]["opening_yes"] == 0.11


def test_hydration_runs_ONCE_and_not_on_every_tick(monkeypatch):
    """Self-limiting by design: once the disk file exists the old copy must
    never be consulted again, or a stale Redis copy would keep resurrecting."""
    calls = {"n": 0}

    def _copy(path):
        calls["n"] += 1
        return {"markets": {"m1": {"opened_at": "2026-08-20T00:00:00Z",
                                   "opening_yes": 0.11, "points": []}}}

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_keyvalue_copy", _copy
    )
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row("m1", yes=0.6, no=0.4)])
    assert calls["n"] == 1
    mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row("m1", yes=0.7, no=0.3)])
    assert calls["n"] == 1, "the old keyvalue copy was consulted again after the disk file existed"


def test_a_brand_new_file_with_no_old_copy_is_unaffected(monkeypatch):
    """No old key: hydration is a no-op and the opening is recorded now, which
    for a genuinely new market is CORRECT."""
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_keyvalue_copy",
        lambda path: None,
    )
    report = mod.record_daily_odds("kalshi", "mlb", "2026-08-25", [_row("m9")])
    assert report["status"] == "ok"
    assert report["opened"] == 1
