"""S6c — the venue liquidity fields Kalshi already returns stop being discarded.

THE DEFECT, as found 2026-09-09 by reading all three seams:

* FETCHED. `kalshi_client._MARKET_FIELDS` has pulled `yes_bid_dollars`,
  `no_bid_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp` and
  `liquidity_dollars` on every tick since 2026-08-23, and `normalize_market`
  carries all six.
* DROPPED at the lean artifact. `kalshi_odds_refresh._LEAN_MARKET_FIELDS` keeps
  asks only. That drop is CORRECT and stays — see the falsification test below.
* DROPPED at the daily book. `venue_daily_odds.kalshi_daily_rows` built a row
  whose only prices were `yes`/`no` = the two asks. That drop was NOT correct:
  the daily book runs on the full unshrunk market set and is the capture-first
  record, so it is exactly where history belongs.

CONSEQUENCE OF THE SECOND DROP: hold is measurable from an ask; whether an
order would have been FILLED at it is not measurable from stored data at all.

THIS PACKAGE CHANGES NO SERVED PRICE AND ADDS NO PRICING LOGIC. It stops a
discard. Nothing here computes a fill probability.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import venue_daily_odds as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    yield


# A dated, classifiable ticker so the row reaches storage rather than being
# counted `undated`.
_TICKER = "KXMLBKS-26AUG242145CINSF-CINCBURNS26-7"


def _market(**over):
    m = {
        "ticker": _TICKER,
        "series": "KXMLBKS",
        "event_ticker": "KXMLBKS-26AUG242145CINSF",
        "title": "Chase Burns: 7+ strikeouts?",
        "yes_ask_dollars": 0.48,
        "no_ask_dollars": 0.54,
        "yes_bid_dollars": 0.46,
        "no_bid_dollars": 0.52,
        "volume_fp": 12345,
        "volume_24h_fp": 678,
        "open_interest_fp": 910,
        "liquidity_dollars": 1234.56,
    }
    m.update(over)
    return m


# --------------------------------------------------------------------------
# 1. The six fields round-trip into the daily row
# --------------------------------------------------------------------------


def test_all_six_liquidity_fields_reach_the_daily_row():
    """The venue's own names on the left, the common `DEPTH_FIELDS` shape on
    the right. Before this package every one of these was fetched and thrown
    away at this exact function."""
    row = mod.kalshi_daily_rows([_market()])[0]
    assert row["yes_bid"] == 0.46
    assert row["no_bid"] == 0.52
    assert row["volume"] == 12345
    assert row["volume_24h"] == 678
    assert row["open_interest"] == 910
    assert row["liquidity"] == 1234.56
    # Every one of them, not a subset that happened to be easy.
    assert set(mod.DEPTH_FIELDS) <= set(row)


def test_the_rows_existing_fields_keep_their_names_and_their_values():
    """A capture change that renamed or moved an existing key would break every
    reader of the daily book silently. The asks in particular stay `yes`/`no`
    and stay the ASKS."""
    row = mod.kalshi_daily_rows([_market()])[0]
    assert row["id"] == _TICKER
    assert row["yes"] == 0.48
    assert row["no"] == 0.54
    assert row["family"] == "KXMLBKS"
    assert row["event"] == "KXMLBKS-26AUG242145CINSF"
    assert row["raw_title"] == "Chase Burns: 7+ strikeouts?"
    assert row["sport"] == "mlb"
    assert row["game_date"] == "2026-08-24"


# --------------------------------------------------------------------------
# 2. Missing must stay distinguishable from zero
# --------------------------------------------------------------------------


def test_a_market_without_the_fields_yields_None_not_zero_and_not_absent():
    """`open_interest` ABSENT and `open_interest == 0` are different facts --
    "the venue told us nothing" versus "a market nobody holds". A fill model
    that collapses them reads an untraded market as a fetch failure. The key is
    PRESENT so the absence is stated rather than inferred from a missing key."""
    bare = {k: v for k, v in _market().items()
            if k not in {"yes_bid_dollars", "no_bid_dollars", "volume_fp",
                         "volume_24h_fp", "open_interest_fp", "liquidity_dollars"}}
    row = mod.kalshi_daily_rows([bare])[0]
    for field in mod.DEPTH_FIELDS:
        assert field in row, f"{field} went absent instead of None"
        assert row[field] is None, f"{field} was defaulted to {row[field]!r}"
        assert row[field] != 0


def test_zero_open_interest_survives_as_zero():
    """The other half of the same distinction, and the reason `_as_depth`
    exists rather than reusing `_as_float` -- which maps 0.0 to None ON PURPOSE
    because zero is not a PRICE. Zero very much is a depth."""
    row = mod.kalshi_daily_rows([_market(open_interest_fp=0, volume_fp=0)])[0]
    assert row["open_interest"] == 0
    assert row["volume"] == 0
    assert mod._as_depth(0) == 0.0
    assert mod._as_depth(0) is not None
    # The contrast, pinned: the price coercion still refuses zero.
    assert mod._as_float(0) is None


# --------------------------------------------------------------------------
# 3. The row reaches STORAGE. `record_daily_odds` is an allowlist, so a field
#    on the row is not yet a field in the record.
# --------------------------------------------------------------------------


def _stored(venue="kalshi", sport="mlb", date="2026-08-24"):
    from syndicate.features.shared.refresh_state_store import read_json_file

    return read_json_file(mod.daily_odds_path(venue, sport, date)) or {}


def test_depth_is_persisted_on_the_point_that_observed_it():
    """A depth reading is only meaningful beside the price it stood next to, so
    it rides the timestamped point rather than the market entry."""
    report = mod.record_venue_book("kalshi", mod.kalshi_daily_rows([_market()]))
    assert report["status"] == "ok"
    point = _stored()["markets"][_TICKER]["points"][-1]
    assert point["yes"] == 0.48
    assert point["yes_bid"] == 0.46
    assert point["no_bid"] == 0.52
    assert point["volume"] == 12345
    assert point["volume_24h"] == 678
    assert point["open_interest"] == 910
    assert point["liquidity"] == 1234.56


def test_a_partially_reported_market_keeps_its_Nones_in_the_stored_point():
    """ALL SIX OR NONE. Once the venue has reported anything, a None inside the
    block means "this venue does not report this one" -- a different fact from
    the block being absent because the venue reports no depth at all."""
    mod.record_venue_book(
        "kalshi", mod.kalshi_daily_rows([_market(open_interest_fp=None)])
    )
    point = _stored()["markets"][_TICKER]["points"][-1]
    assert "open_interest" in point
    assert point["open_interest"] is None
    assert point["volume"] == 12345


def test_the_append_rule_is_unchanged_so_depth_does_not_multiply_points():
    """Volume is monotonic. Folding depth into the equality test would turn "a
    point per ask move" into "a point per fetch" -- precisely the growth
    `MAX_POINTS_PER_MARKET` and `_trim_to_budget` exist to stop. The stated
    consequence is that depth is sampled AT ASK-MOVE TIMES."""
    rows = mod.kalshi_daily_rows([_market()])
    mod.record_venue_book("kalshi", rows)
    # Same asks, moved volume and open interest.
    second = mod.record_venue_book(
        "kalshi",
        mod.kalshi_daily_rows([_market(volume_fp=99999, open_interest_fp=4242)]),
    )
    assert second["appended"] == 0
    assert second["unchanged"] == 1
    assert len(_stored()["markets"][_TICKER]["points"]) == 1


def test_polymarket_rows_pay_no_bytes_for_depth_they_do_not_have():
    """ASYMMETRIC AND HONEST. Nothing on Polymarket's daily-book path carries a
    bid, a volume, an open interest or a liquidity: these rows are read from
    `GAME_SLATE_ARTIFACT`, whose shape is `_SLATE_STORAGE_FIELDS`, and the
    `_KEEP` trim upstream drops the rest first. `polymarket_client` fetches
    volume/volume24hr/liquidity but does not feed this builder and has no
    bid/ask depth either. So no mapping is invented, and no empty depth block
    is written across ~12,000 markets."""
    rows = mod.polymarket_daily_rows([{
        "slug": "ml-mlb-cin-sf-2026-08-25",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
        "question": "Cincinnati vs San Francisco",
        "outcomePrices": '["0.48","0.52"]',
    }])
    assert rows and not (set(mod.DEPTH_FIELDS) & set(rows[0]))
    mod.record_venue_book("polymarket", rows)
    point = _stored("polymarket", date="2026-08-25")["markets"]["ml-mlb-cin-sf-2026-08-25"]["points"][-1]
    assert set(point) == {"ts", "yes", "no"}


# --------------------------------------------------------------------------
# 4. THE FALSIFICATION TEST. The size-constrained path must not move.
# --------------------------------------------------------------------------

# `_LEAN_MARKET_FIELDS` exactly as it stood before this package, transcribed
# rather than imported so the assertion is against a RECORD and not against
# whatever the module currently says.
_LEAN_FIELDS_BEFORE_S6C = (
    "ticker",
    "event_ticker",
    "series",
    "title",
    "yes_sub_title",
    "no_sub_title",
    "status",
    "yes_ask_dollars",
    "no_ask_dollars",
    "yes_american",
    "no_american",
    "yes_probability",
    "no_probability",
    "close_time",
)


def test_the_lean_artifact_is_byte_identical_after_this_change():
    """THE FALSIFICATION. `kalshi_markets.json` is size-constrained on purpose:
    production logged `KEYVALUE_WRITE_LARGE size_bytes=5314201
    warn_bytes=1048576`, and the refusal that created the lean row prescribed
    its own fix -- "Shrink the payload rather than raising the ceiling". Six
    extra fields across ~11,000 markets is exactly that growth. Depth went into
    the daily book instead; this asserts none of it leaked here.

    A market carrying every depth field must serialize to the same bytes as one
    carrying none, because the lean row must not see them either way.
    """
    from pipeline import kalshi_odds_refresh as kor

    assert kor._LEAN_MARKET_FIELDS == _LEAN_FIELDS_BEFORE_S6C

    from syndicate.features.shared.kalshi_client import normalize_market

    with_depth = normalize_market(_market())
    without = {k: v for k, v in with_depth.items()
               if k not in {"yes_bid_dollars", "no_bid_dollars", "volume_fp",
                            "volume_24h_fp", "open_interest_fp",
                            "liquidity_dollars"}}

    dumped_with = json.dumps(kor._lean_market(with_depth), separators=(",", ":"))
    dumped_without = json.dumps(kor._lean_market(without), separators=(",", ":"))
    assert dumped_with == dumped_without
    assert not (set(json.loads(dumped_with)) & set(mod.DEPTH_FIELDS))
    # And none of the venue-native names either.
    assert "yes_bid_dollars" not in dumped_with
    assert "open_interest_fp" not in dumped_with
