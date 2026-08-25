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
