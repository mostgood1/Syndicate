"""`#617` — Kalshi's own prices reach `book_quotes`, so exchange PROP prices
become visible to anything that reads the quote log.

THE GAP THIS CLOSES, measured rather than assumed. `book_quotes` is fed from
OddsAPI, and OddsAPI carries GAME LINES ONLY for exchanges. On
`mlb_source/tracking/book_quotes/2026-08-31.jsonl` — 274,129 rows, 124.4 MB —
exchange quotes on game markets numbered **26,710** (kalshi 13,768, prophetx
5,605, novig 4,987, polymarket 2,350) and exchange quotes on prop markets
numbered **ZERO**. Kalshi filled 23 real MLB prop orders that same day, with
`KXMLBHR-` / `KXMLBHIT-` / `KXMLBTB-` / `KXMLBHA-` tickers.

WHAT THIS DOES NOT DO. It does not change what the board ranks or stakes. The
board reads `quote.book_prices`, which this does not touch. It makes the prop
side of the price-shopping question MEASURABLE — on game markets, where both
sources are present, adding exchanges improves the best available price on
52.5% of 13,093 paired snapshots by a mean of 1.57pp; whether props behave the
same way cannot be measured until the quotes exist.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.odds_book_quotes import quote_rows_from_kalshi_matches


def _match(**over):
    m = {
        "ticker": "KXMLBHR-26AUG311840SDCIN-SDTFRANCE4-1",
        "series": "KXMLBHR",
        "market": "batter_home_runs",
        "player_name": "Ty France",
        "line": 0.5,
        "board_side": "over",
        "kalshi_side": "yes",
        "kalshi_american": 567,
        "board_event_id": "evt-1",
    }
    m.update(over)
    return m


# ---------------------------------------------------------------------------
# The row builder
# ---------------------------------------------------------------------------


def test_a_prop_match_becomes_a_kalshi_quote_row():
    rows = quote_rows_from_kalshi_matches([_match()])
    assert len(rows) == 1
    row = rows[0]
    assert row["bookmaker"] == "kalshi"
    assert row["market"] == "batter_home_runs"
    assert row["price"] == 567
    assert row["line"] == 0.5
    assert row["selection"] == "over"
    assert row["player_name"] == "Ty France"
    assert row["kind"] == "prop"
    assert row["event_id"] == "evt-1"


def test_the_builder_emits_only_fields_NORMALIZE_will_keep():
    """A field this builder sets that `_normalize` does not know about is
    silently dropped, and a test asserting on the builder's OUTPUT cannot see
    that. This one asserted `venue_ticker` was present -- it passed for the
    whole first deploy, while the real run wrote 603 prop rows and 0 carried
    the field. Assert against `_normalize`'s key set, which is the boundary
    that decides what survives."""
    from syndicate.features.shared.odds_book_quotes import _normalize

    row = quote_rows_from_kalshi_matches([_match()])[0]
    kept = _normalize(row, sport="mlb", date_str="2026-08-31", captured_at="2026-08-31T00:00:00Z")
    dropped = set(row) - set(kept)
    assert dropped == set(), f"builder emits fields _normalize discards: {sorted(dropped)}"


def test_a_GAME_match_is_REFUSED_because_two_sources_would_share_a_dedup_key():
    """THE COLLISION THIS BOUND EXISTS TO PREVENT, and it shipped before it was
    caught. `_KEY_FIELDS` is (sport, kind, event_id, bookmaker, segment, market,
    selection, player_name, line) -- NO source field. So a directly-captured
    Kalshi game row and OddsAPI's copy of the same market share a key, and
    `append_book_quotes` appends whenever (line, price) differs from that key's
    last observation. They do not merge, they ALTERNATE, and every alternation
    reads as a Kalshi price change that never happened.

    Measured on the 2026-08-31 MLB shard: existing Kalshi rows are 13,768 GAME
    and 0 PROP. So props cannot collide and games always would."""
    assert quote_rows_from_kalshi_matches(
        [_match(player_name=None, market="totals", line=8.5)]
    ) == []


def test_a_prop_still_passes_so_the_bound_is_not_a_blanket_refusal():
    """Off is not on: a guard that refused everything would satisfy the test
    above while destroying the entire point of the capture."""
    assert len(quote_rows_from_kalshi_matches([_match()])) == 1


def test_a_match_with_no_price_is_SKIPPED_not_defaulted():
    """A quote with no price records nothing about the market, and a zero would
    be read as an even-money line."""
    assert quote_rows_from_kalshi_matches([_match(kalshi_american=None)]) == []


def test_a_match_with_no_market_is_skipped():
    assert quote_rows_from_kalshi_matches([_match(market="")]) == []


def test_the_BOARD_line_is_kept_not_kalshis_strike():
    """`_match_key`'s docstring: storing the strike instead of the board's
    signed line rebuilds the +X/-X collision. The builder must not re-derive.
    Uses a PROP with a signed line, since game rows are refused above."""
    rows = quote_rows_from_kalshi_matches(
        [_match(market="batter_total_bases", line=1.5, player_name="Nolan Arenado")]
    )
    assert rows[0]["line"] == 1.5


def test_non_mappings_and_empties_do_not_raise():
    assert quote_rows_from_kalshi_matches([]) == []
    assert quote_rows_from_kalshi_matches(None) == []
    assert quote_rows_from_kalshi_matches(["not a mapping", None]) == []


# ---------------------------------------------------------------------------
# The wiring — a builder nothing calls captures nothing
# ---------------------------------------------------------------------------


def _capture(monkeypatch, matches, board_rows, *, date="2026-08-31"):
    """Drive `_capture_kalshi_quotes` with the writer spied, so the assertion is
    on WHAT REACHED THE WRITER rather than on the call returning cleanly."""
    from pipeline import kalshi_odds_refresh as k
    import syndicate.features.shared.odds_book_quotes as obq

    seen: list[dict] = []

    def fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        seen.append({"sport": sport, "date_str": date_str, "rows": list(rows),
                     "captured_at": captured_at})
        return {"appended": len(list(rows))}

    monkeypatch.setattr(obq, "append_book_quotes", fake_append)
    k._capture_kalshi_quotes({"matches": matches}, board_rows, selected_date=date)
    return seen


def test_OFF_IS_NOT_ON_no_matches_writes_nothing(monkeypatch):
    """Reachability first. If this passed while the loaded case also wrote
    nothing, every other assertion here would be vacuous."""
    assert _capture(monkeypatch, [], [{"event_id": "evt-1", "sport": "mlb"}]) == []


def test_a_matched_prop_reaches_the_writer_under_its_sport(monkeypatch):
    seen = _capture(monkeypatch, [_match()], [{"event_id": "evt-1", "sport": "mlb"}])
    assert len(seen) == 1
    assert seen[0]["sport"] == "mlb"
    assert seen[0]["date_str"] == "2026-08-31"
    assert seen[0]["rows"][0]["bookmaker"] == "kalshi"
    assert seen[0]["rows"][0]["player_name"] == "Ty France"


def test_the_SPORT_comes_from_the_board_row_because_a_match_carries_none(monkeypatch):
    """Verified against the source: neither `matches.append` block in
    `kalshi_board_join` writes a `sport`. Looking it up from the row the match
    paired with keeps one derivation rather than inventing a second."""
    seen = _capture(monkeypatch, [_match(board_event_id="evt-9")],
                    [{"event_id": "evt-9", "sport": "wnba"}])
    assert seen[0]["sport"] == "wnba"


def test_a_match_whose_event_is_not_on_the_board_is_DROPPED_not_guessed(monkeypatch):
    """A quote in the wrong shard is worse than a missing one — it would later
    be read as another sport's price."""
    assert _capture(monkeypatch, [_match(board_event_id="evt-unknown")],
                    [{"event_id": "evt-1", "sport": "mlb"}]) == []


def test_matches_are_split_across_sports(monkeypatch):
    seen = _capture(
        monkeypatch,
        [_match(board_event_id="evt-1"), _match(board_event_id="evt-2")],
        [{"event_id": "evt-1", "sport": "mlb"}, {"event_id": "evt-2", "sport": "wnba"}],
    )
    assert sorted(s["sport"] for s in seen) == ["mlb", "wnba"]


def test_a_writer_failure_never_breaks_the_join(monkeypatch):
    """The quote log is instrumentation; the join is the product. Same contract
    `append_book_quotes` itself keeps."""
    from pipeline import kalshi_odds_refresh as k
    import syndicate.features.shared.odds_book_quotes as obq

    def boom(**kw):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(obq, "append_book_quotes", boom)
    k._capture_kalshi_quotes({"matches": [_match()]},
                             [{"event_id": "evt-1", "sport": "mlb"}],
                             selected_date="2026-08-31")


def test_a_report_with_no_matches_key_is_harmless(monkeypatch):
    from pipeline import kalshi_odds_refresh as k

    k._capture_kalshi_quotes({}, [{"event_id": "evt-1", "sport": "mlb"}], selected_date="2026-08-31")


# ---------------------------------------------------------------------------
# 2026-09-10 -- the shard's vocabulary, the game's identity, the kickoff shard
# ---------------------------------------------------------------------------
#
# User-reported on the NFL Layer 2 board: a game card titled "Matchup" holding
# 65 opportunities from eight games, every row NO SIM VIEW at -0.9% EV with a
# "fair" two points off its own price, and raw `player_pass_tds` labels.
# Measured on web's NFL `book_quotes/2026-09-10.jsonl`: 261 Kalshi prop rows,
# all under the canonical key, none with a `commence_time`, 150 of them for
# games on other days. See `book_quote_prop_market` and `_capture_kalshi_quotes`.

_SF_AT_LAR = {
    "event_id": "evt-sflar",
    "sport": "nfl",
    "home_team": "Los Angeles Rams",
    "away_team": "San Francisco 49ers",
    "commence_time": "2026-09-11T00:35:00Z",  # 7:35 PM CT on the 10th
}


def _nfl_match(**over):
    fields = {
        "ticker": "KXNFLREC-26SEP10SFLAR-LARTHIGBEE88-2",
        "series": "KXNFLREC",
        "market": "player_receptions",
        "player_name": "Tyler Higbee",
        "line": 1.5,
        "board_event_id": "evt-sflar",
    }
    fields.update(over)
    return _match(**fields)


def test_an_NFL_prop_is_filed_under_the_shards_display_label():
    rows = quote_rows_from_kalshi_matches(
        [_nfl_match(), _nfl_match(market="player_pass_tds", player_name="Brock Purdy")],
        sport="nfl",
    )
    assert [r["market"] for r in rows] == ["Receptions", "Passing TDs"]


def test_OFF_IS_NOT_ON_other_sports_and_no_sport_keep_the_canonical_key():
    """The relabel is scoped to the shards that speak display labels. MLB's
    shard IS canonical, so relabelling it would split the merge it has today."""
    assert quote_rows_from_kalshi_matches([_match()], sport="mlb")[0]["market"] == "batter_home_runs"
    assert quote_rows_from_kalshi_matches([_nfl_match()])[0]["market"] == "player_receptions"


@pytest.mark.parametrize(
    "sport,module",
    [("nfl", "scripts.fetch_nfl_oddsapi_props_local"), ("ncaaf", "scripts.fetch_ncaaf_oddsapi_props_local")],
)
def test_the_label_is_the_one_the_OddsAPI_fetcher_writes(sport, module):
    """Three copies of one vocabulary: the fetchers' `MARKET_STD_MAP`, the NFL
    join's `_NFL_PROP_MARKET_TO_STAT`, and `market_keys`. This reads the
    fetcher's map at test time, so a label renamed in one place fails here
    instead of re-splitting the grid in production."""
    import importlib

    from syndicate.features.shared.odds_book_quotes import book_quote_prop_market

    std = importlib.import_module(module).MARKET_STD_MAP
    relabelled = {key: book_quote_prop_market(sport, key) for key in std}
    wrong = {key: got for key, got in relabelled.items() if got not in (std[key], key)}
    assert wrong == {}
    # Reachability, not just consistency: the two markets Kalshi actually
    # quotes for NFL must BOTH relabel, or the map is consistent and useless.
    assert relabelled["player_receptions"] == "Receptions"
    assert relabelled["player_pass_tds"] == "Passing TDs"


def test_the_games_identity_rides_on_the_row_and_survives_normalize():
    from syndicate.features.shared.odds_book_quotes import _normalize

    identity = {k: _SF_AT_LAR[k] for k in ("home_team", "away_team", "commence_time")}
    row = quote_rows_from_kalshi_matches([_nfl_match(**identity)], sport="nfl")[0]
    kept = _normalize(row, sport="nfl", date_str="2026-09-10", captured_at="2026-09-10T22:00:00Z")
    assert (kept["home_team"], kept["away_team"], kept["commence_time"]) == (
        "Los Angeles Rams", "San Francisco 49ers", "2026-09-11T00:35:00Z")


def test_capture_stamps_the_games_identity_from_the_board_rows(monkeypatch):
    seen = _capture(monkeypatch, [_nfl_match()], [dict(_SF_AT_LAR)], date="2026-09-10")
    row = seen[0]["rows"][0]
    assert row["market"] == "Receptions"
    assert row["home_team"] == "Los Angeles Rams"
    assert row["commence_time"] == "2026-09-11T00:35:00Z"


def test_identity_comes_from_ANY_row_of_the_event_not_only_the_first(monkeypatch):
    """The board index holds Kalshi-derived rows too, and those carry blank
    teams -- a first-row-wins lookup would stamp nothing."""
    blank = {"event_id": "evt-sflar", "sport": "nfl", "home_team": "", "away_team": "", "commence_time": None}
    seen = _capture(monkeypatch, [_nfl_match()], [blank, dict(_SF_AT_LAR)], date="2026-09-10")
    assert seen[0]["rows"][0]["away_team"] == "San Francisco 49ers"


def test_a_thursday_night_game_stays_on_its_CENTRAL_date(monkeypatch):
    """00:35Z on the 11th is 7:35 PM CT on the 10th -- the shard OddsAPI filed
    this game's sportsbook rows under. A UTC key would split them again."""
    seen = _capture(monkeypatch, [_nfl_match()], [dict(_SF_AT_LAR)], date="2026-09-10")
    assert [s["date_str"] for s in seen] == ["2026-09-10"]


def test_a_sunday_game_is_filed_under_its_kickoff_date_not_the_board_date(monkeypatch):
    sunday = dict(_SF_AT_LAR, event_id="evt-clejax", home_team="Jacksonville Jaguars",
                  away_team="Cleveland Browns", commence_time="2026-09-13T17:00:00Z")
    seen = _capture(
        monkeypatch,
        [_nfl_match(), _nfl_match(board_event_id="evt-clejax", player_name="Brenton Strange")],
        [dict(_SF_AT_LAR), sunday],
        date="2026-09-10",
    )
    by_date = {s["date_str"]: [r["player_name"] for r in s["rows"]] for s in seen}
    assert by_date == {"2026-09-10": ["Tyler Higbee"], "2026-09-13": ["Brenton Strange"]}


def test_a_match_with_no_known_kickoff_keeps_the_board_date(monkeypatch):
    seen = _capture(monkeypatch, [_nfl_match()], [{"event_id": "evt-sflar", "sport": "nfl"}],
                    date="2026-09-10")
    assert [s["date_str"] for s in seen] == ["2026-09-10"]


def test_OFF_IS_NOT_ON_mlb_stays_on_the_board_date_even_with_a_kickoff(monkeypatch):
    """Only the football shards are keyed by kickoff. The kickoff here is on
    another CENTRAL day (7:10 PM CT on 09-01), so bucketing it would move it."""
    seen = _capture(
        monkeypatch,
        [_match()],
        [{"event_id": "evt-1", "sport": "mlb", "commence_time": "2026-09-02T00:10:00Z",
          "home_team": "Cincinnati Reds", "away_team": "San Diego Padres"}],
        date="2026-08-31",
    )
    assert [s["date_str"] for s in seen] == ["2026-08-31"]
    assert seen[0]["rows"][0]["market"] == "batter_home_runs"


def test_on_the_GRID_the_relabelled_quote_is_a_cell_in_the_sportsbook_row():
    """What the relabel is FOR, asserted on `build_book_grid`'s output rather
    than on the row builder's -- `test_the_builder_emits_only_fields_NORMALIZE_will_keep`
    records why a builder-output assertion is not enough. The unrelabelled
    control reproduces the production defect: two grid rows for one bet."""
    from datetime import datetime, timezone

    from syndicate.features.shared.book_grid import build_book_grid
    from syndicate.features.shared.book_shortlist import (
        QUOTE_SOURCE_FIELD,
        QUOTE_SOURCE_VENUE_DIRECT,
    )
    from syndicate.features.shared.odds_book_quotes import _normalize

    identity = {k: _SF_AT_LAR[k] for k in ("home_team", "away_team", "commence_time")}
    stamp = "2026-09-10T22:00:00Z"
    book = [
        _normalize(
            {"bookmaker": "draftkings", "market": "Receptions", "selection": side,
             "player_name": "Tyler Higbee", "line": 1.5, "price": price,
             "event_id": "evt-sflar", "kind": "prop", **identity},
            sport="nfl", date_str="2026-09-10", captured_at=stamp,
        )
        for side, price in (("over", -120), ("under", -105))
    ]

    def kalshi(sport):
        matches = [_nfl_match(board_side=side, kalshi_american=price, **identity)
                   for side, price in (("over", -117), ("under", 113))]
        out = []
        for row in quote_rows_from_kalshi_matches(matches, sport=sport):
            normalized = _normalize(row, sport="nfl", date_str="2026-09-10", captured_at=stamp)
            normalized[QUOTE_SOURCE_FIELD] = QUOTE_SOURCE_VENUE_DIRECT
            out.append(normalized)
        return out

    now = datetime(2026, 9, 10, 22, 5, tzinfo=timezone.utc)
    merged = [g for g in build_book_grid(book + kalshi("nfl"), now=now) if g["kind"] == "prop"]
    split = [g for g in build_book_grid(book + kalshi(None), now=now) if g["kind"] == "prop"]
    assert len(split) == 2, "the control must reproduce the defect or this test proves nothing"
    assert len(merged) == 1
    assert sorted(merged[0]["books"]) == ["draftkings", "kalshi"]
    assert merged[0]["home_team"] == "Los Angeles Rams"
