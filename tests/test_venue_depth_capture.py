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

SECOND PASS, 2026-09-09 -- SIZE AT TOUCH. `yes_bid_size_fp`/`yes_ask_size_fp`
arrive on 12,000 of 12,000 open markets and were being dropped one seam
earlier, by `kalshi_client._MARKET_FIELDS` itself. They are captured here as
`bid_size`/`ask_size`. The same measurement found `liquidity_dollars` to be a
DEAD PLACEHOLDER -- the literal "0.0000" on all 12,000, including a market with
volume 343,240 and a 3-level book -- so it is deliberately NOT remapped onto
anything: its zero is a true fact about the venue.

STILL CAPTURE ONLY. Storing size at touch does not measure fill; it makes fill
measurable, which is a different sentence.
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
        # SIZE AT TOUCH -- added to `_MARKET_FIELDS` 2026-09-09. Present on
        # every market Kalshi lists and dropped by the allowlist until then.
        "yes_bid_size_fp": 2241.0,
        "yes_ask_size_fp": 1180.0,
    }
    m.update(over)
    return m


# The venue-native names for everything `DEPTH_FIELDS` maps, in one place so a
# "strip the depth" fixture cannot go stale when the list grows.
_VENUE_DEPTH_KEYS = {
    "yes_bid_dollars", "no_bid_dollars", "yes_bid_size_fp", "yes_ask_size_fp",
    "volume_fp", "volume_24h_fp", "open_interest_fp", "liquidity_dollars",
}


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


def test_size_at_touch_round_trips_from_the_venues_own_field_names():
    """THE TWO FIELDS THAT CARRY FILL SIGNAL, and the reason this second pass
    exists. `yes_bid_size_fp`/`yes_ask_size_fp` arrive on every market Kalshi
    lists and were dropped by `kalshi_client._MARKET_FIELDS` -- they sat in
    `probe()`'s `present_but_unexpected` the whole time, the same failure mode
    that cost a two-day diagnosis over `exchange_index`."""
    from syndicate.features.shared.kalshi_client import _MARKET_FIELDS, normalize_market

    assert "yes_bid_size_fp" in _MARKET_FIELDS
    assert "yes_ask_size_fp" in _MARKET_FIELDS
    normalized = normalize_market(_market())
    assert normalized["yes_bid_size_fp"] == 2241.0
    assert normalized["yes_ask_size_fp"] == 1180.0
    # Carried, not counted as a schema gap.
    assert "yes_bid_size_fp" not in normalized["missing_fields"]
    assert "yes_ask_size_fp" not in normalized["missing_fields"]
    # And a payload that stops carrying them says so by NAME rather than
    # defaulting to zero -- the whole reason the allowlist is an allowlist.
    silent = normalize_market({k: v for k, v in _market().items()
                               if not k.endswith("_size_fp")})
    assert silent["yes_bid_size_fp"] is None
    assert "yes_bid_size_fp" in silent["missing_fields"]
    assert "yes_ask_size_fp" in silent["missing_fields"]

    row = mod.kalshi_daily_rows([normalized])[0]
    assert row["bid_size"] == 2241.0
    assert row["ask_size"] == 1180.0


def test_the_sizes_are_named_for_what_they_are_and_liquidity_is_not_remapped():
    """NAMING IS THE POINT. `liquidity_dollars` is a DEAD PLACEHOLDER --
    measured 2026-09-09 as the literal "0.0000" on 12,000 of 12,000 open
    markets, one of them carrying volume 343,240, a 1-cent spread and a
    3-level book. Remapping it onto size at touch would fabricate a signal, so
    it stays captured and useless, and the real fields are called
    `bid_size`/`ask_size` rather than borrowing a poisoned word."""
    row = mod.kalshi_daily_rows([_market(liquidity_dollars="0.0000")])[0]
    assert row["liquidity"] == "0.0000"
    assert row["bid_size"] == 2241.0
    assert mod._as_depth(row["liquidity"]) == 0.0
    # No field in the row is named after liquidity except the placeholder.
    assert [f for f in mod.DEPTH_FIELDS if "liquid" in f] == ["liquidity"]
    # And volume/open interest are not standing in for depth either.
    assert row["volume"] != row["bid_size"]
    assert row["open_interest"] != row["ask_size"]


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
    bare = {k: v for k, v in _market().items() if k not in _VENUE_DEPTH_KEYS}
    row = mod.kalshi_daily_rows([bare])[0]
    for field in mod.DEPTH_FIELDS:
        assert field in row, f"{field} went absent instead of None"
        assert row[field] is None, f"{field} was defaulted to {row[field]!r}"
        assert row[field] != 0


def test_zero_open_interest_survives_as_zero():
    """The other half of the same distinction, and the reason `_as_depth`
    exists rather than reusing `_as_float` -- which maps 0.0 to None ON PURPOSE
    because zero is not a PRICE. Zero very much is a depth."""
    row = mod.kalshi_daily_rows([
        _market(open_interest_fp=0, volume_fp=0, yes_bid_size_fp=0, yes_ask_size_fp=0.0)
    ])[0]
    assert row["open_interest"] == 0
    assert row["volume"] == 0
    # A zero SIZE AT TOUCH is the sharpest case of the same rule: nothing is
    # resting there, which is a fill fact and not a missing reading.
    assert row["bid_size"] == 0
    assert row["bid_size"] is not None
    assert row["ask_size"] == 0.0
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
    assert point["bid_size"] == 2241.0
    assert point["ask_size"] == 1180.0


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
    without = {k: v for k, v in with_depth.items() if k not in _VENUE_DEPTH_KEYS}

    dumped_with = json.dumps(kor._lean_market(with_depth), separators=(",", ":"))
    dumped_without = json.dumps(kor._lean_market(without), separators=(",", ":"))
    assert dumped_with == dumped_without
    assert not (set(json.loads(dumped_with)) & set(mod.DEPTH_FIELDS))
    # And none of the venue-native names either -- including the two sizes
    # added 2026-09-09, which must not leak into the size-constrained row.
    assert "yes_bid_dollars" not in dumped_with
    assert "open_interest_fp" not in dumped_with
    assert "yes_bid_size_fp" not in dumped_with
    assert "yes_ask_size_fp" not in dumped_with
