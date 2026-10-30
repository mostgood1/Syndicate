"""Forward Kalshi combo capture (lane `kalshi-combo-capture`, todo #742). Hermetic: no network."""
from __future__ import annotations

import ast
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "kalshi_combo_capture.py"


def _load():
    spec = importlib.util.spec_from_file_location("kalshi_combo_capture", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = _load()

T0 = 1_800_000_000  # an arbitrary epoch (2027-01-15T08:00:00Z)


def _iso(epoch: float) -> str:
    return cc.ms.iso(epoch)


def _leg(event: str, market: str | None = None, side: str = "yes") -> dict:
    return {"event_ticker": event, "market_ticker": market or f"{event}-X", "side": side}


def _combo(ticker: str, legs: list[dict], settled: float, *, volume: str = "0.00", result: str = "no",
           created: float | None = None) -> dict:
    return {
        "ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "status": "finalized", "result": result,
        "mve_collection_ticker": "KXMVECROSSCATEGORY-R", "mve_selected_legs": legs, "is_provisional": True,
        "created_time": _iso(created if created is not None else settled - 3600), "open_time": _iso(settled - 3600),
        "close_time": _iso(settled - 5), "expected_expiration_time": _iso(settled + 3600),
        "settlement_ts": _iso(settled) if settled is not None else None,
        "volume_fp": volume, "open_interest_fp": "0.00", "yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.0000",
        "no_bid_dollars": "0.0000", "no_ask_dollars": "0.0000", "last_price_dollars": "0.2630" if volume != "0.00" else "0.0000",
        "rules_secondary": "long text", "custom_strike": {"Associated Markets": "..."},
    }


# The 2026-10-27 probe's own example: SAS win + Wembanyama 30+ pts + Fox 4+ reb + Wembanyama 12+ reb in one game,
# plus a BKN/BOS winner and two NHL legs from different games.
NBA_SGP_LEGS = [
    _leg("KXNBAGAME-26OCT27BKNBOS", "KXNBAGAME-26OCT27BKNBOS-BOS"),
    _leg("KXNBAGAME-26OCT27SACSAS", "KXNBAGAME-26OCT27SACSAS-SAS"),
    _leg("KXNBAPTS-26OCT27SACSAS", "KXNBAPTS-26OCT27SACSAS-SASVWEMBANYAMA1-30"),
    _leg("KXNBAREB-26OCT27SACSAS", "KXNBAREB-26OCT27SACSAS-SASDFOX4-4"),
    _leg("KXNBAREB-26OCT27SACSAS", "KXNBAREB-26OCT27SACSAS-SASVWEMBANYAMA1-12"),
    _leg("KXNHLGAME-26OCT27BOSCAR", "KXNHLGAME-26OCT27BOSCAR-BOS"),
    _leg("KXNHLTOTAL-26OCT27NJDAL", "KXNHLTOTAL-26OCT27NJDAL-10", "no"),
]
CRYPTO_LEGS = [_leg("KXBTC15M-26OCT260800", "KXBTC15M-26OCT260800-00"),
               _leg("KXETH15M-26OCT260800", "KXETH15M-26OCT260800-00")]


# ------------------------------------------------------------------ same-game filter
@pytest.mark.parametrize("ticker, scope", [
    ("KXNBAREB-26OCT27SACSAS", ("nba", None)),
    ("KXWNBAPTS-26AUG01LVNY", ("wnba", None)),
    ("KXMLBHIT-26OCT24LADNYY", ("mlb", None)),
    ("KXNFLRECYDS-26OCT26DALPHI", ("nfl", None)),
    ("KXNHLTOTAL-26OCT27NJDAL", ("nhl", None)),
    ("KXNCAAFGAME-26OCT25OSUMICH", ("ncaaf", None)),
    ("KXEPLGAME-26OCT25ARSCRY", ("soccer", "epl")),
    ("KXSERIEABTTS-26OCT26INTMIL", ("soccer", "serie_a")),
    ("KXLALIGATOTAL-26OCT26RMABAR", ("soccer", "la_liga")),
    ("KXSERIEAWGAME-26OCT26INTMIL", None),   # Serie A Femminile: women's clubs share the men's codes
    ("KXLIGAMXGAME-26OCT26AMECRU", None),    # not a competition the platform models
    ("KXMLBBGAME-26OCT26ABCDEF", None),      # Mobile Legends, not MLB
    ("KXNCAABBGAME-26OCT26ABCDEF", None),    # college baseball, not NCAAB
    ("KXWTAMATCH-26OCT27RIEMAS", None),      # tennis is not modelled
    ("KXNBAWINS-26", None),                  # a future, out of scope
    ("KXNFLMENTION-26OCT26DALPHI", None),    # a broadcast mention is not a game outcome
    ("KXBTC15M-26OCT260800", None),
    ("KXMVECROSSCATEGORY-S2026ZZIUZE6KIGKSYPXY", None),
])
def test_leg_scope(ticker, scope):
    assert cc.leg_scope(ticker) == scope


def test_leg_game_needs_a_dated_game_segment():
    assert cc.leg_game("KXNBAREB-26OCT27SACSAS") == "26OCT27SACSAS"
    assert cc.leg_game("KXMLBHIT-26SEP091310MINDET-MINBBUXTON25-2") == "26SEP091310MINDET"
    assert cc.leg_game("KXNBAWINS-26-BOS") is None  # "26" is no game: two futures legs never pair
    assert cc.leg_game("KXNBAGAME") is None


def test_same_game_groups_finds_the_one_sgp_inside_a_cross_category_ticket():
    groups = cc.same_game_groups(NBA_SGP_LEGS)
    assert groups == [{"sport": "nba", "league": None, "game": "26OCT27SACSAS", "legs": [1, 2, 3, 4]}]


def test_same_game_is_scoped_by_sport_and_soccer_competition():
    # the same segment string in two scopes is two games
    assert cc.same_game_groups([_leg("KXNBAGAME-26OCT27LVNY"), _leg("KXWNBAGAME-26OCT27LVNY")]) == []
    assert cc.same_game_groups([_leg("KXEPLGAME-26OCT25ARSCRY"), _leg("KXSERIEAGAME-26OCT25ARSCRY")]) == []
    # a men's and a women's Serie A leg never pair, even on the same codes
    assert cc.same_game_groups([_leg("KXSERIEAGAME-26OCT26INTMIL"), _leg("KXSERIEAWGAME-26OCT26INTMIL")]) == []
    # MLB doubleheader games carry their start time, so game 1 and game 2 do not pair
    assert cc.same_game_groups([_leg("KXMLBGAME-26SEP091310MINDET"), _leg("KXMLBHIT-26SEP091910MINDET")]) == []
    soccer = cc.same_game_groups([_leg("KXEPLGAME-26OCT25ARSCRY"), _leg("KXEPLBTTS-26OCT25ARSCRY"),
                                  _leg("KXEPLTOTAL-26OCT25ARSCRY")])
    assert soccer == [{"sport": "soccer", "league": "epl", "game": "26OCT25ARSCRY", "legs": [0, 1, 2]}]


def test_unmodelled_or_cross_game_tickets_are_not_kept():
    assert cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-A", CRYPTO_LEGS, T0), "now") is None
    tennis = [_leg("KXWTAMATCH-26OCT27RIEMAS"), _leg("KXWTAGAMETOTAL-26OCT27RIEMAS")]
    assert cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-B", tennis, T0), "now") is None
    cross = [_leg("KXNBAGAME-26OCT27BKNBOS"), _leg("KXNBAGAME-26OCT27SACSAS")]
    assert cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-C", cross, T0), "now") is None
    assert cc.combo_row({"ticker": "X", "mve_selected_legs": [_leg("KXNBAGAME-26OCT27SACSAS")]}, "now") is None


# ------------------------------------------------------------------ parser
def test_combo_row_stores_legs_quote_volume_and_result():
    raw = _combo("KXMVECROSSCATEGORY-S2026D7LVWVY24GR2XRRR-ABC", NBA_SGP_LEGS, T0, volume="36.15", result="yes")
    row = cc.combo_row(raw, "2027-01-15T09:00:00Z")
    assert row["ticker"] == "KXMVECROSSCATEGORY-S2026D7LVWVY24GR2XRRR-ABC"
    assert row["series"] == "KXMVECROSSCATEGORY" and row["collection"] == "KXMVECROSSCATEGORY-R"
    assert row["result"] == "yes" and row["status"] == "finalized"
    assert row["settlement_ts"] == _iso(T0) and row["created_time"] == _iso(T0 - 3600)
    assert row["n_legs"] == 7 and [leg["market_ticker"] for leg in row["legs"]][2] == \
        "KXNBAPTS-26OCT27SACSAS-SASVWEMBANYAMA1-30"
    assert row["legs"][6] == {"event_ticker": "KXNHLTOTAL-26OCT27NJDAL", "market_ticker": "KXNHLTOTAL-26OCT27NJDAL-10",
                              "side": "no", "sport": "nhl", "league": None, "game": "26OCT27NJDAL"}
    assert row["sports"] == ["nba"]
    assert row["volume_fp"] == pytest.approx(36.15) and row["traded"] is True
    assert row["quote_at_capture"]["last_price"] == pytest.approx(0.263)
    assert row["quote_at_capture"]["yes_ask"] == 0.0
    assert row["trades_status"] == "pending" and row["trades"] is None
    # the bulky venue text is not copied
    assert "rules_secondary" not in row and "custom_strike" not in row


def test_an_untraded_combo_is_kept_without_trades():
    row = cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-D", NBA_SGP_LEGS, T0), "now")
    assert row["traded"] is False and row["trades_status"] == "not_traded"


# ------------------------------------------------------------------ fake public API
class FakeKalshi:
    """Serves `/markets` by settlement window with cursor paging, and `/markets/trades` per ticker."""

    def __init__(self, combos, *, page_size=2, fail_pages=(), trades=None, collections=None):
        self.combos = sorted(combos, key=lambda c: -cc.ms.ts(c.get("settlement_ts") or 0))  # newest first
        self.page_size = page_size
        self.fail_pages = set(fail_pages)
        self.trades = trades or {}
        self.collections = collections if collections is not None else [
            {"collection_ticker": "KXMVECROSSCATEGORY-R", "series_ticker": "KXMVECROSSCATEGORY"},
            {"collection_ticker": "KXMVEOSCARS-R", "series_ticker": "KXMVEOSCARS"},
        ]
        self.calls: list[tuple[str, dict]] = []
        self.market_pages = 0

    def __call__(self, path, params=None):
        params = dict(params or {})
        self.calls.append((path, params))
        if path == "/multivariate_event_collections":
            return {"multivariate_contracts": self.collections, "cursor": ""}
        if path == "/markets/trades":
            return {"trades": self.trades.get(params["ticker"], []), "cursor": ""}
        if path == "/markets":
            self.market_pages += 1
            if self.market_pages in self.fail_pages:
                return None
            lo, hi = params["min_settled_ts"], params["max_settled_ts"]
            rows = [c for c in self.combos
                    if c["ticker"].startswith(params["series_ticker"] + "-")
                    and (c.get("settlement_ts") is None or lo <= cc.ms.ts(c["settlement_ts"]) <= hi)]
            start = int(params.get("cursor") or 0)
            page = rows[start:start + self.page_size]
            nxt = start + self.page_size
            return {"markets": page, "cursor": str(nxt) if nxt < len(rows) else ""}
        raise AssertionError(path)


ONE_SERIES = {"KXMVECROSSCATEGORY": (900, 0)}


def _run(tmp_path, fake, now, **kw):
    kw.setdefault("series", ONE_SERIES)
    kw.setdefault("snapshot", False)
    kw.setdefault("store_untraded", True)  # the sweep tests read every kept row back; the default is pinned below
    return cc.run(tmp_path, get=fake, now=now, enabled=True, trade_pause=0, **kw)


def _stored(tmp_path):
    out = []
    for path in sorted(cc.store_dir(tmp_path).glob("combos_*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            out += [json.loads(line) for line in fh]
    return out


# ------------------------------------------------------------------ reachability: off != on
def test_off_by_default_makes_no_request_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(cc.ENV_FLAG, raising=False)
    fake = FakeKalshi([_combo("KXMVECROSSCATEGORY-S1-A", NBA_SGP_LEGS, T0 - 1000, volume="1.00")])
    assert cc.run(tmp_path, get=fake, now=T0)["status"] == "off"
    assert fake.calls == [] and not cc.store_dir(tmp_path).exists()

    monkeypatch.setenv(cc.ENV_FLAG, "on")
    summary = cc.run(tmp_path, get=fake, now=T0, series=ONE_SERIES, snapshot=False, trade_pause=0)
    assert summary["status"] == "ok" and fake.calls and summary["kept_by_sport"] == {"nba": 1}
    assert [r["ticker"] for r in _stored(tmp_path)] == ["KXMVECROSSCATEGORY-S1-A"]


@pytest.mark.parametrize("value, on", [("on", True), ("1", True), ("true", True), ("", False), ("off", False),
                                       ("0", False)])
def test_env_flag_values(value, on):
    assert cc.capture_enabled({cc.ENV_FLAG: value}) is on
    assert cc.capture_enabled({}) is False


# ------------------------------------------------------------------ sweep
def test_rows_are_owned_by_the_slice_that_holds_their_settlement_second(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    start = end - 3600
    boundary = start + 900  # first slice is [start+1, start+900]; a settlement at +0.4 s belongs to it
    combos = [
        _combo("KXMVECROSSCATEGORY-S1-A", NBA_SGP_LEGS, boundary + 0.4),
        _combo("KXMVECROSSCATEGORY-S1-B", NBA_SGP_LEGS, boundary + 1.2),
        _combo("KXMVECROSSCATEGORY-S1-C", NBA_SGP_LEGS, start + 5),
        _combo("KXMVECROSSCATEGORY-S1-Z", CRYPTO_LEGS, start + 6),
    ]
    summary = _run(tmp_path, FakeKalshi(combos), T0, lookback_s=3600)
    tickers = [r["ticker"] for r in _stored(tmp_path)]
    assert sorted(tickers) == ["KXMVECROSSCATEGORY-S1-A", "KXMVECROSSCATEGORY-S1-B", "KXMVECROSSCATEGORY-S1-C"]
    assert len(tickers) == 3  # nothing twice, nothing lost, at the boundary
    s = summary["series"]["KXMVECROSSCATEGORY"]
    assert s["slices"] == 4 and s["kept"] == 3 and s["outside_slice"] == 1 and s["seconds_covered"] == 3600
    state = json.loads((cc.store_dir(tmp_path) / "state.json").read_text())
    assert state["series"]["KXMVECROSSCATEGORY"]["swept_to"] == end


def test_queries_ask_for_one_second_past_the_slice(tmp_path):
    fake = FakeKalshi([])
    _run(tmp_path, fake, T0, lookback_s=900)
    (path, params), = [c for c in fake.calls if c[0] == "/markets"]
    assert params["max_settled_ts"] - params["min_settled_ts"] == 900  # [lo, hi] is 900 s; the query asks hi + 1
    assert params["series_ticker"] == "KXMVECROSSCATEGORY" and params["limit"] == cc.PAGE_LIMIT


def test_an_unreadable_page_writes_nothing_and_keeps_the_watermark(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-{i}", NBA_SGP_LEGS, end - 100 - i) for i in range(5)]
    fake = FakeKalshi(combos, page_size=2, fail_pages={2})
    summary = _run(tmp_path, fake, T0, lookback_s=900)
    assert summary["status"] == "errors" and "SliceUnreadable" in summary["errors"][0]
    assert _stored(tmp_path) == []  # page 1's two rows were NOT written: a slice is all or nothing
    state = json.loads((cc.store_dir(tmp_path) / "state.json").read_text())
    assert state["series"]["KXMVECROSSCATEGORY"].get("swept_to") is None
    # the next run resumes the same window and gets all five
    fake.fail_pages = set()
    summary = _run(tmp_path, fake, T0 + 60, lookback_s=900)
    assert summary["status"] == "ok" and len(_stored(tmp_path)) == 5


def test_a_slice_over_the_page_cap_is_split(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-{i}", NBA_SGP_LEGS, end - 10 * i) for i in range(1, 60)]
    summary = _run(tmp_path, FakeKalshi(combos, page_size=5), T0, lookback_s=900, page_cap=4)
    s = summary["series"]["KXMVECROSSCATEGORY"]
    assert s["splits"] >= 1 and s["kept"] == 59 and len(_stored(tmp_path)) == 59
    # a split re-reads both halves: the thrown-away pages are counted, and the budget paid for them
    assert s["discarded_pages"] == 4 * s["splits"] and summary["pages"] == s["pages"] + s["discarded_pages"]


def test_slices_are_sized_from_the_last_slices_page_density(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "TARGET_SLICE_PAGES", 2)
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-{i}", NBA_SGP_LEGS, end - 10 - i) for i in range(6)]
    fake = FakeKalshi(combos, page_size=1)
    _run(tmp_path, fake, T0, lookback_s=900)
    state = json.loads((cc.store_dir(tmp_path) / "state.json").read_text())["series"]["KXMVECROSSCATEGORY"]
    assert state["pages_per_s"] == pytest.approx(6 / 900)
    fake.calls.clear()
    _run(tmp_path, fake, T0 + 900)
    spans = [c[1]["max_settled_ts"] - c[1]["min_settled_ts"] for c in fake.calls if c[0] == "/markets"]
    assert spans[0] == 300 and sum(spans) == 900  # 2 pages / (6 pages / 900 s); then the empty slice widens it


def test_a_short_remainder_is_folded_into_the_last_slice_and_does_not_set_the_density(tmp_path):
    fake = FakeKalshi([])
    _run(tmp_path, fake, T0, lookback_s=1830)  # 2 x 900 s + 30 s: the 30 s are read with the second slice
    spans = [c[1]["max_settled_ts"] - c[1]["min_settled_ts"] for c in fake.calls if c[0] == "/markets"]
    assert spans == [900, 930]
    fake.calls.clear()
    _run(tmp_path, fake, T0 + 20)  # 20 s of new settlement time: one slice, too short to re-estimate density
    state = json.loads((cc.store_dir(tmp_path) / "state.json").read_text())["series"]["KXMVECROSSCATEGORY"]
    assert state["pages_per_s"] == pytest.approx(1 / 930) and state["swept_to"] == T0 + 20 - cc.SETTLE_LAG_S


def test_the_budget_stops_between_slices_and_the_next_run_resumes(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-{i}", NBA_SGP_LEGS, end - 300 * i - 1) for i in range(12)]
    summary = _run(tmp_path, FakeKalshi(combos, page_size=10), T0, lookback_s=3600, max_pages=2)
    assert summary["status"] == "budget_stopped" and summary["pages"] == 2
    swept = json.loads((cc.store_dir(tmp_path) / "state.json").read_text())["series"]["KXMVECROSSCATEGORY"]["swept_to"]
    assert swept == end - 3600 + 1800  # two whole 900 s slices, no partial one
    first = {r["ticker"] for r in _stored(tmp_path)}
    _run(tmp_path, FakeKalshi(combos, page_size=10), T0, lookback_s=3600)
    assert len({r["ticker"] for r in _stored(tmp_path)}) == 12 and first


def test_interval_series_are_read_at_most_every_interval(tmp_path):
    series = {"KXMVECROSSCATEGORY": (900, 0), "KXMVENBASINGLEGAME": (21600, 21600)}
    fake = FakeKalshi([])
    _run(tmp_path, fake, T0, series=series, lookback_s=900)
    _run(tmp_path, fake, T0 + 3600, series=series)
    nba = [c for c in fake.calls if c[0] == "/markets" and c[1]["series_ticker"] == "KXMVENBASINGLEGAME"]
    assert len(nba) == 1


# ------------------------------------------------------------------ trades
def test_trades_are_read_only_for_kept_traded_combos(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [
        _combo("KXMVECROSSCATEGORY-S1-T", NBA_SGP_LEGS, end - 50, volume="36.15", result="yes", created=end - 4000),
        _combo("KXMVECROSSCATEGORY-S1-U", NBA_SGP_LEGS, end - 60),
        _combo("KXMVECROSSCATEGORY-S1-Z", CRYPTO_LEGS, end - 70, volume="10.00"),
    ]
    trades = {"KXMVECROSSCATEGORY-S1-T": [
        {"created_time": _iso(end - 3000), "yes_price_dollars": "0.2630", "no_price_dollars": "0.7370",
         "count_fp": "36.15", "taker_side": "yes", "ticker": "KXMVECROSSCATEGORY-S1-T"}]}
    fake = FakeKalshi(combos, trades=trades, page_size=10)
    summary = _run(tmp_path, fake, T0, lookback_s=900, trades_max_legs=None)
    trade_calls = [c for c in fake.calls if c[0] == "/markets/trades"]
    assert [c[1]["ticker"] for c in trade_calls] == ["KXMVECROSSCATEGORY-S1-T"]
    assert trade_calls[0][1]["min_ts"] <= end - 4000 and trade_calls[0][1]["max_ts"] >= end - 50
    rows = {r["ticker"]: r for r in _stored(tmp_path)}
    assert rows["KXMVECROSSCATEGORY-S1-T"]["trades_status"] == "ok"
    assert rows["KXMVECROSSCATEGORY-S1-T"]["trades"] == [
        {"t": _iso(end - 3000), "yes": 0.263, "no": 0.737, "count": 36.15, "taker_side": "yes"}]
    assert rows["KXMVECROSSCATEGORY-S1-U"]["trades_status"] == "not_traded"
    assert summary["gets"] == {"markets": 1, "trades": 1} and summary["trades"]["prints"] == 1
    assert summary["kept_traded_by_sport"] == {"nba": 1}


def test_trades_max_legs_bounds_the_trade_reads(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    short = [_leg("KXEPLGAME-26OCT25ARSCRY"), _leg("KXEPLBTTS-26OCT25ARSCRY"), _leg("KXNBAGAME-26OCT27BKNBOS")]
    combos = [_combo("KXMVECROSSCATEGORY-S1-S", short, end - 50, volume="2.00"),
              _combo("KXMVECROSSCATEGORY-S1-L", NBA_SGP_LEGS, end - 60, volume="2.00")]
    trades = {t: [{"created_time": _iso(end - 3000), "yes_price_dollars": "0.30", "no_price_dollars": "0.70",
                   "count_fp": "2.00", "taker_side": "yes"}] for t in ("KXMVECROSSCATEGORY-S1-S", "KXMVECROSSCATEGORY-S1-L")}
    fake = FakeKalshi(combos, trades=trades, page_size=10)
    summary = _run(tmp_path, fake, T0, lookback_s=900, trades_max_legs=3)
    assert [c[1]["ticker"] for c in fake.calls if c[0] == "/markets/trades"] == ["KXMVECROSSCATEGORY-S1-S"]
    rows = {r["ticker"]: r for r in _stored(tmp_path)}
    assert rows["KXMVECROSSCATEGORY-S1-S"]["trades_status"] == "ok"
    assert rows["KXMVECROSSCATEGORY-S1-L"]["trades_status"] == "skipped" and rows["KXMVECROSSCATEGORY-S1-L"]["traded"]
    assert summary["trades_max_legs"] == 3 and summary["trades"]["trades_skipped"] == 1
    rep = cc.report(tmp_path, [cc.utc_date(end - 50)])["by_settlement_date"][cc.utc_date(end - 50)]
    assert rep["traded_total"] == 2 and rep["traded_at_most_legs"][3] == 1 and rep["traded_at_most_legs"][10] == 2
    assert rep["traded_every_leg_same_game"] == 0

    fake0 = FakeKalshi(combos, trades=trades, page_size=10)
    _run(tmp_path / "none", fake0, T0, lookback_s=900, trades_max_legs=0)
    assert not [c for c in fake0.calls if c[0] == "/markets/trades"]


def test_by_default_untraded_combos_are_counted_not_stored_and_no_trade_is_read(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    short = [_leg("KXEPLGAME-26OCT25ARSCRY"), _leg("KXEPLBTTS-26OCT25ARSCRY"), _leg("KXNBAGAME-26OCT27BKNBOS")]
    combos = [_combo("KXMVECROSSCATEGORY-S1-S", short, end - 50, volume="2.00"),
              _combo("KXMVECROSSCATEGORY-S1-L", NBA_SGP_LEGS, end - 60, volume="2.00"),
              _combo("KXMVECROSSCATEGORY-S1-U", NBA_SGP_LEGS, end - 70)]
    fake = FakeKalshi(combos, page_size=10)
    summary = cc.run(tmp_path, get=fake, now=T0, enabled=True, series=ONE_SERIES, snapshot=False, lookback_s=900,
                     trade_pause=0)
    assert cc.DEFAULT_TRADES_MAX_LEGS == 0 and summary["trades_max_legs"] == 0
    assert summary["store_untraded"] is False and summary["gets"] == {"markets": 1}
    stored = {r["ticker"]: r for r in _stored(tmp_path)}
    assert sorted(stored) == ["KXMVECROSSCATEGORY-S1-L", "KXMVECROSSCATEGORY-S1-S"]
    # the price survives without a trade read: last_price, volume and created_time are on the row
    assert stored["KXMVECROSSCATEGORY-S1-S"]["trades_status"] == "skipped"
    assert stored["KXMVECROSSCATEGORY-S1-S"]["quote_at_capture"]["last_price"] == 0.263
    assert stored["KXMVECROSSCATEGORY-S1-S"]["volume_fp"] == 2.0 and stored["KXMVECROSSCATEGORY-S1-S"]["created_time"]
    # the untraded one is still counted: the run row is the kept-per-day instrument
    assert summary["kept_by_sport"] == {"nba": 2, "soccer": 1} and summary["kept_traded_by_sport"] == {"nba": 1, "soccer": 1}
    assert summary["kept_traded_by_legs"] == {"03": 1, "07": 1} and sum(summary["written"].values()) == 2
    rep = cc.report(tmp_path, [cc.utc_date(end - 50)])
    assert rep["kept_by_sport_per_day"] == {"nba": round(2 * 96, 1), "soccer": round(96, 1)}  # 900 s covered
    assert rep["by_settlement_date"][cc.utc_date(end - 50)]["stored"] == 2
    # the sweep itself drops the untraded row after tallying it, so a peak slice never holds them
    rows, stats = cc.sweep_slice(FakeKalshi(combos, page_size=10), "KXMVECROSSCATEGORY", end - 899, end,
                                 budget=cc.RunBudget(10, 60), captured_at="t", keep_untraded=False)
    assert len(rows) == 2 and stats["kept"] == 3 and stats["kept_traded"] == 2 and stats["sport:nba"] == 2


def test_a_row_that_gets_no_trade_read_is_held_encoded_and_stored_byte_for_byte(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    short = [_leg("KXEPLGAME-26OCT25ARSCRY"), _leg("KXEPLBTTS-26OCT25ARSCRY"), _leg("KXNBAGAME-26OCT27BKNBOS")]
    long_raw = _combo("KXMVECROSSCATEGORY-S1-L", NBA_SGP_LEGS, end - 60, volume="2.00")
    combos = [_combo("KXMVECROSSCATEGORY-S1-S", short, end - 50, volume="2.00"), long_raw,
              _combo("KXMVECROSSCATEGORY-S1-U", NBA_SGP_LEGS, end - 70)]

    def sweep(max_legs):
        return cc.sweep_slice(FakeKalshi(combos, page_size=10), "KXMVECROSSCATEGORY", end - 899, end,
                              budget=cc.RunBudget(10, 60), captured_at="t", trades_max_legs=max_legs)

    rows, stats = sweep(3)
    by = {(r["ticker"] if isinstance(r, dict) else json.loads(r.line)["ticker"]): r for r in rows}
    assert isinstance(by["KXMVECROSSCATEGORY-S1-S"], dict)  # may get a trade read, so attach_trades needs the dict
    encoded = by["KXMVECROSSCATEGORY-S1-L"]
    assert isinstance(encoded, cc.EncodedRow) and encoded.date == cc.utc_date(end - 60)
    assert json.loads(by["KXMVECROSSCATEGORY-S1-U"].line)["trades_status"] == "not_traded"
    assert stats["trades:trades_skipped"] == 1
    direct = cc.combo_row(long_raw, "t")
    direct["trades_status"] = "skipped"
    assert encoded.line == cc.encode_row(direct)  # one serialiser: the stored text does not depend on the path

    rows0, stats0 = sweep(0)  # the default: no row is held as a dict
    assert all(isinstance(r, cc.EncodedRow) for r in rows0) and stats0["trades:trades_skipped"] == 2
    assert cc.append_rows(tmp_path, rows0) == {cc.utc_date(end - 50): 3}
    assert {r["ticker"]: r["trades_status"] for r in _stored(tmp_path)} == {
        "KXMVECROSSCATEGORY-S1-S": "skipped", "KXMVECROSSCATEGORY-S1-L": "skipped",
        "KXMVECROSSCATEGORY-S1-U": "not_traded"}


def test_trade_reads_are_charged_to_the_run_budget(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-{i}", NBA_SGP_LEGS, end - 50 - i, volume="1.00") for i in range(5)]
    fake = FakeKalshi(combos, page_size=10)
    summary = _run(tmp_path, fake, T0, lookback_s=900, trades_max_legs=None, max_pages=3)
    assert summary["status"] == "budget_stopped" and summary["pages"] == 3
    assert summary["gets"] == {"markets": 1, "trades": 2}
    assert summary["trades"]["trades_skipped_budget"] == 3
    rows = _stored(tmp_path)
    assert len(rows) == 5 and sum(r["trades_status"] == "skipped_budget" for r in rows) == 3
    # the slice's listing was complete, so its watermark advances; the rows keep last_price and volume
    assert json.loads((cc.store_dir(tmp_path) / "state.json").read_text())["series"]["KXMVECROSSCATEGORY"]["swept_to"] == end


def test_the_cli_maps_minus_one_to_every_trade_read(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cc, "_nice", lambda: None)
    monkeypatch.setattr(cc, "run", lambda root, **kw: seen.update(kw) or {"status": "ok"})
    assert cc.main(["run", "--data-root", str(tmp_path), "--trades-max-legs", "-1"]) == 0
    assert seen["trades_max_legs"] is None and seen["store_untraded"] is False
    cc.main(["run", "--data-root", str(tmp_path)])
    assert seen["trades_max_legs"] == cc.DEFAULT_TRADES_MAX_LEGS


def test_unreadable_trades_are_named_not_dropped(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo("KXMVECROSSCATEGORY-S1-T", NBA_SGP_LEGS, end - 50, volume="5.00")]
    fake = FakeKalshi(combos)
    real = fake.__call__
    fake_get = lambda path, params=None: None if path == "/markets/trades" else real(path, params)  # noqa: E731
    summary = cc.run(tmp_path, get=fake_get, now=T0, enabled=True, series=ONE_SERIES, snapshot=False,
                     lookback_s=900, trade_pause=0, trades_max_legs=None)
    (row,) = _stored(tmp_path)
    assert row["trades_status"] == "unreadable" and row["trades"] is None
    assert summary["trades"] == {"trades_unreadable": 1}


# ------------------------------------------------------------------ store, snapshot, report
def test_collections_are_snapshot_once_a_day_and_name_unswept_series(tmp_path):
    fake = FakeKalshi([])
    summary = cc.run(tmp_path, get=fake, now=T0, enabled=True, series=ONE_SERIES, lookback_s=900, trade_pause=0)
    assert summary["collections"]["unswept_series"] == ["KXMVEOSCARS"]
    snap = json.loads((cc.store_dir(tmp_path) / f"collections_{cc.utc_date(T0)}.json").read_text())
    assert snap["complete"] and snap["by_series"] == {"KXMVECROSSCATEGORY": 1, "KXMVEOSCARS": 1}
    cc.run(tmp_path, get=fake, now=T0 + 3600, enabled=True, series=ONE_SERIES, trade_pause=0)
    assert sum(1 for c in fake.calls if c[0] == "/multivariate_event_collections") == 1


def test_a_held_lock_refuses_a_second_run(tmp_path):
    store = cc.store_dir(tmp_path)
    store.mkdir(parents=True)
    (store / ".lock").write_text("{}")
    fake = FakeKalshi([])
    assert cc.run(tmp_path, get=fake, now=T0, enabled=True)["status"] == "locked" and fake.calls == []


def test_load_combos_dedups_a_repeated_slice_and_report_counts_per_sport(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    soccer = [_leg("KXEPLGAME-26OCT25ARSCRY"), _leg("KXEPLBTTS-26OCT25ARSCRY")]
    rows = [cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-A", NBA_SGP_LEGS, end - 50, volume="1.00"), "a"),
            cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-E", soccer, end - 60), "a")]
    cc.append_rows(tmp_path, rows)
    cc.append_rows(tmp_path, rows[:1])  # a crash between write and watermark repeats a slice
    date = cc.utc_date(end - 50)
    assert len(cc.load_combos(tmp_path, [date])) == 2
    rep = cc.report(tmp_path, [date])["by_settlement_date"][date]
    assert rep["stored"] == 2 and rep["by_sport"] == {"nba": 1, "soccer": 1}
    assert rep["traded_by_sport"] == {"nba": 1, "soccer": 0} and rep["two_leg_by_sport"] == {"nba": 0, "soccer": 1}
    assert rep["soccer_by_league"] == {"epl": 1}


def _run_row(at, lo, hi, *, status="ok", kept=0, traded=0, gets=0, sports=None):
    return {"run_at": _iso(at), "status": status, "invoker": "bridge", "gets_total": gets, "pages": gets,
            "kept_by_sport": sports or {}, "kept_traded_by_sport": sports or {},
            "series": {"KXMVECROSSCATEGORY": {"from": _iso(lo), "to": _iso(hi), "kept": kept, "kept_traded": traded}}}


def _status_store(tmp_path, rows):
    store = cc.store_dir(tmp_path)
    store.mkdir(parents=True, exist_ok=True)
    (store / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


D0 = T0 - T0 % cc.DAY  # midnight UTC of T0's date
BACKFILL = [
    _run_row(D0 + 3600, D0 - 20 * cc.DAY, D0 - 10 * cc.DAY, status="budget_stopped", kept=5000, traded=5000),  # purged
    _run_row(D0 + 3600, D0 - 10 * cc.DAY, D0 - cc.DAY, status="budget_stopped", kept=10, traded=10),  # too few kept
    _run_row(D0 + 7200, D0 - cc.DAY + 1, D0 - 2 * 3600, status="budget_stopped", kept=5000, traded=500),  # unpurged
    _run_row(D0 + 3 * 3600, D0 - 2 * 3600 + 1, D0 + 10500, kept=2000, traded=1400),  # first ok run: caught up
]


def test_status_brackets_the_purge_age_and_reads_the_first_full_forward_day(tmp_path):
    forward = [
        _run_row(D0 + cc.DAY, D0 + 10501, D0 + cc.DAY - 1, gets=7),
        _run_row(D0 + cc.DAY + 43500, D0 + cc.DAY, D0 + cc.DAY + 43199, gets=40, sports={"nfl": 100}),
        _run_row(D0 + 2 * cc.DAY + 3900, D0 + cc.DAY + 43200, D0 + 2 * cc.DAY + 3599, gets=13, sports={"nfl": 13}),
    ]
    _status_store(tmp_path, BACKFILL + forward)
    day = D0 + cc.DAY
    cc.append_rows(tmp_path, [
        cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-Y", NBA_SGP_LEGS, day + 100, volume="1.00", result="yes"), "t"),
        cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-N", NBA_SGP_LEGS, day + 200, volume="1.00", result="no"), "t")])
    st = cc.forward_status(tmp_path, now=D0 + 2 * cc.DAY + 4000)
    purge = st["purge"]
    # the youngest purged row was 10 days + 1 h old; the youngest still-listed untraded rows were 2 h + 2 h old
    assert purge["age_hours_at_most"] == 241.0 and purge["age_hours_above"] == 4.0
    assert purge["purged_runs"] == 1 and purge["unpurged_runs"] == 1 and len(purge["boundary_runs"]) == 1
    assert st["caught_up"]["swept_to"] == _iso(D0 + 10500)
    assert st["first_full_forward_day"] == cc.utc_date(day) and st["met"] is True
    d = st["day"]
    # the third run straddles midnight: 43,200 of its 46,800 settlement seconds are on the day, so 12 of its 13 GETs
    assert d["runs_overlapping"] == 2 and d["gets_prorated"] == 52 and d["kept_by_sport_prorated"] == {"nfl": 112}
    assert d["stored"] == 2 and d["results"] == {"yes": 1, "no": 1} and d["traded_total"] == 2
    assert st["last_run"]["swept_to"] == _iso(D0 + 2 * cc.DAY + 3599) and st["invokers"] == {"bridge": 7}


def test_status_is_not_met_until_a_whole_forward_day_is_swept(tmp_path):
    _status_store(tmp_path, BACKFILL + [_run_row(D0 + cc.DAY + 43500, D0 + 10501, D0 + cc.DAY + 43199)])
    st = cc.forward_status(tmp_path, now=D0 + cc.DAY + 43600)
    assert st["first_full_forward_day"] is None and "day" not in st and st["met"] is False
    assert st["caught_up"]["run_at"] == _iso(D0 + 3 * 3600)
    _status_store(tmp_path, BACKFILL[:1])  # still backfilling: no run has ended ok, nothing is unpurged yet
    st = cc.forward_status(tmp_path, now=D0 + 4000)
    assert "caught_up" not in st and st["purge"]["age_hours_above"] is None and st["met"] is False
    assert cc.forward_status(tmp_path / "empty", now=D0)["runs"] == 0


def test_report_normalises_gets_by_the_settlement_time_covered(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-{i}", NBA_SGP_LEGS, end - 100 * i - 1) for i in range(9)]
    _run(tmp_path, FakeKalshi(combos, page_size=3), T0, lookback_s=3600)
    rep = cc.report(tmp_path, [])
    assert rep["cross_category_days_covered"] == round(3600 / 86400, 3)
    assert rep["gets_per_day"] == pytest.approx(rep["gets_total"] * 24, rel=1e-3)


# ------------------------------------------------------------------ the job and its guard rails
def test_the_fleet_job_is_hourly_and_runs_the_capture():
    from scripts import local_production as lp

    job = {j.name: j for j in lp.SCHEDULED_JOBS}["kalshi-combo-capture"]
    assert job.every_minutes == 60
    assert job.argv[:2] == ("scripts/kalshi_combo_capture.py", "run") and "--enable" not in job.argv


def test_the_capture_sends_only_public_gets_through_the_shared_reader():
    text = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in ("POST", "PUT", "DELETE", "PATCH")
            assert "/portfolio" not in node.value
    assert not any("order" in name or "auth" in name or "execution" in name for name in imported), imported
    assert "urlopen(" not in text and "urllib" not in imported  # requests go through ms.public_get_json only
    assert cc.run.__kwdefaults__["get"] is cc.ms.public_get_json


# ------------------------------------------------------------------ E4 (e): the shaped trade read (lane e4-pregame-prints, A5)
GL_LEGS = [_leg("KXEPLGAME-26OCT31ARSCRY", "KXEPLGAME-26OCT31ARSCRY-ARS"),
           _leg("KXEPLTOTAL-26OCT31ARSCRY", "KXEPLTOTAL-26OCT31ARSCRY-3")]
RESULT_X_RESULT_LEGS = [_leg("KXEPLGAME-26OCT31ARSCRY", "KXEPLGAME-26OCT31ARSCRY-ARS"),
                        _leg("KXEPLGAME-26OCT31ARSCRY", "KXEPLGAME-26OCT31ARSCRY-TIE")]
NBA_NESTED_LEGS = [_leg("KXNBAPTS-26OCT31SACSAS", "KXNBAPTS-26OCT31SACSAS-SASVWEMBANYAMA1-30"),
                   _leg("KXNBAPRA-26OCT31SACSAS", "KXNBAPRA-26OCT31SACSAS-SASVWEMBANYAMA1-45")]
NBA_DISJOINT_LEGS = [_leg("KXNBAPTS-26OCT31SACSAS", "KXNBAPTS-26OCT31SACSAS-SASVWEMBANYAMA1-30"),
                     _leg("KXNBAREB-26OCT31SACSAS", "KXNBAREB-26OCT31SACSAS-SASVWEMBANYAMA1-12")]
MLB_OTHER_LEGS = [_leg("KXMLBHIT-26OCT31LADTOR", "KXMLBHIT-26OCT31LADTOR-LADSOHTANI17-1"),
                  _leg("KXMLBRBI-26OCT31LADTOR", "KXMLBRBI-26OCT31LADTOR-LADSOHTANI17-1")]
UCL_GL_LEGS = [_leg("KXUCLGAME-26NOV04ARSBAY", "KXUCLGAME-26NOV04ARSBAY-ARS"),
               _leg("KXUCLTOTAL-26NOV04ARSBAY", "KXUCLTOTAL-26NOV04ARSBAY-3")]


def _stage2():
    import sys

    for path in (str(REPO / "scripts"), str(REPO)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import e4_stage2_combo_prices as s2

    return s2


def test_the_shape_cell_equals_stage2s_registered_classifier_on_a_ticker_grid():
    s2 = _stage2()
    series = ["KXMLBHIT", "KXMLBTB", "KXMLBHR", "KXMLBRBI", "KXMLBHRR", "KXMLBKS", "KXNBAPTS", "KXNBAREB",
              "KXNBAAST", "KXNBAPRA", "KXNBA3PT", "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPL1HTOTAL",
              "KXEPLTEAMTOTAL", "KXEPLSPREAD", "KXMLSGAME", "KXMLSBTTS", "XEPLTOTAL"]
    tickers = []
    for s in series:
        tickers += [f"{s}-26OCT31ABCDEF", f"{s}-26OCT31ABCDEF-PLAYERA1-2", f"{s}-26OCT31ABCDEF-PLAYERB2-2",
                    f"{s.lower()}-26oct31abcdef-playera1-2"]
    leagues = sorted(s2.s1.SOCCER_LEAGUES) + ["ucl", None]
    checked = 0
    for sport in ("mlb", "nba", "soccer", "nhl", "nfl"):
        for league in (leagues if sport == "soccer" else [None, "epl"]):
            for a in tickers:
                for b in tickers:
                    assert cc.e4_shape_cell(sport, league, a, b) == s2.shape_cell(sport, league, a, b), (sport, league, a, b)
                    checked += 1
    assert checked > 50_000
    assert cc.E4_PASSING == frozenset(s2.PASSING)
    assert cc.E4_SOCCER_LEAGUES == frozenset(s2.s1.SOCCER_LEAGUES)


@pytest.mark.parametrize("legs, cell", [
    (GL_LEGS, "GL"), (NBA_NESTED_LEGS, "SP-nested"), (MLB_OTHER_LEGS, "SP-other"),
    (RESULT_X_RESULT_LEGS, None),   # result x result is never a cell
    (NBA_DISJOINT_LEGS, None),      # SP-disjoint is counted by Stage 2, never tested
    (UCL_GL_LEGS, None),            # no Stage 1 sim for the UCL
    (GL_LEGS + [_leg("KXNBAGAME-26OCT31BKNBOS")], None),  # a third leg: not a two-leg combo
    (NBA_SGP_LEGS, None),
])
def test_e4_trade_shape_names_only_the_passing_two_leg_cells(legs, cell):
    row = cc.combo_row(_combo("KXMVECROSSCATEGORY-S1-X", legs, T0, volume="2.00"), "t")
    assert cc.e4_trade_shape(row) == cell


def _shaped_world(end):
    combos = [
        _combo("KXMVECROSSCATEGORY-S1-GL", GL_LEGS, end - 50, volume="12.00", result="yes", created=end - 9000),
        _combo("KXMVECROSSCATEGORY-S1-NB", NBA_NESTED_LEGS, end - 51, volume="3.00"),
        _combo("KXMVECROSSCATEGORY-S1-MO", MLB_OTHER_LEGS, end - 52, volume="1.00"),
        _combo("KXMVECROSSCATEGORY-S1-RR", RESULT_X_RESULT_LEGS, end - 53, volume="5.00"),
        _combo("KXMVECROSSCATEGORY-S1-ND", NBA_DISJOINT_LEGS, end - 54, volume="5.00"),
        _combo("KXMVECROSSCATEGORY-S1-GU", GL_LEGS, end - 55),  # shaped, never traded
        _combo("KXMVECROSSCATEGORY-S1-L7", NBA_SGP_LEGS, end - 56, volume="9.00"),
    ]
    trades = {"KXMVECROSSCATEGORY-S1-GL": [
        {"created_time": _iso(end - 8000), "yes_price_dollars": "0.3100", "no_price_dollars": "0.6900",
         "count_fp": "10.00", "taker_side": "yes"},
        {"created_time": _iso(end - 2000), "yes_price_dollars": "0.9600", "no_price_dollars": "0.0400",
         "count_fp": "2.00", "taker_side": "no"}]}
    return combos, trades


def test_shapes_off_reads_no_trade_and_shapes_e4_reads_exactly_the_shaped_traded_combos(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos, trades = _shaped_world(end)
    off = FakeKalshi(combos, trades=trades, page_size=10)
    summary_off = _run(tmp_path / "off", off, T0, lookback_s=900, trades_shapes="none")
    assert not [c for c in off.calls if c[0] == "/markets/trades"]
    assert summary_off["trades_shapes"] == "none" and summary_off["shaped_reads"] == 0

    on = FakeKalshi(combos, trades=trades, page_size=10)
    summary = _run(tmp_path / "on", on, T0, lookback_s=900, trades_shapes="e4")
    read = sorted(c[1]["ticker"] for c in on.calls if c[0] == "/markets/trades")
    assert read == ["KXMVECROSSCATEGORY-S1-GL", "KXMVECROSSCATEGORY-S1-MO", "KXMVECROSSCATEGORY-S1-NB"]
    rows = {r["ticker"]: r for r in _stored(tmp_path / "on")}
    gl = rows["KXMVECROSSCATEGORY-S1-GL"]
    assert gl["trades_status"] == "ok" and [p["taker_side"] for p in gl["trades"]] == ["yes", "no"]
    assert gl["trades"][0] == {"t": _iso(end - 8000), "yes": 0.31, "no": 0.69, "count": 10.0, "taker_side": "yes"}
    assert rows["KXMVECROSSCATEGORY-S1-NB"]["trades_status"] == "empty"
    for unshaped in ("RR", "ND", "L7"):
        assert rows[f"KXMVECROSSCATEGORY-S1-{unshaped}"]["trades_status"] == "skipped"
    assert rows["KXMVECROSSCATEGORY-S1-GU"]["trades_status"] == "not_traded"
    assert summary["trades_shapes"] == "e4" and summary["shaped_reads"] == 3
    assert summary["trades"]["shaped"] == 3 and summary["trades"]["shaped_ok"] == 1
    assert summary["trades"]["shaped_empty"] == 2 and summary["trades"]["shaped_prints"] == 2
    # the listing's own budget is untouched by the shaped reads
    assert summary["pages"] == summary_off["pages"] == 1 and summary["status"] == "ok"


def test_shaped_reads_have_their_own_cap_and_a_row_past_it_says_skipped_budget(tmp_path):
    end = T0 - cc.SETTLE_LAG_S
    combos = [_combo(f"KXMVECROSSCATEGORY-S1-G{i}", GL_LEGS, end - 50 - i, volume="1.00") for i in range(4)]
    fake = FakeKalshi(combos, page_size=10)
    summary = _run(tmp_path, fake, T0, lookback_s=900, trades_shapes="e4", max_shaped_reads=1, max_pages=1)
    assert summary["gets"] == {"markets": 1, "trades": 1} and summary["pages"] == 1
    assert summary["shaped_reads"] == 1 and summary["shaped_budget_stopped"] is True
    assert summary["trades"]["shaped"] == 4 and summary["trades"]["shaped_skipped_budget"] == 3
    rows = _stored(tmp_path)
    assert sorted(r["trades_status"] for r in rows) == ["empty", "skipped_budget", "skipped_budget", "skipped_budget"]
    assert summary["status"] == "ok"  # the listing finished; the shaped cap is reported, not an error


def test_the_shaped_read_is_on_by_default_and_reaches_the_fleet_job(tmp_path, monkeypatch):
    from scripts import local_production as lp

    assert cc.DEFAULT_TRADES_SHAPES == "e4" and cc.run.__kwdefaults__["trades_shapes"] == "e4"
    with pytest.raises(ValueError):
        cc.run(tmp_path, get=FakeKalshi([]), now=T0, enabled=True, trades_shapes="all")
    job = {j.name: j for j in lp.SCHEDULED_JOBS}["kalshi-combo-capture"]
    assert "--trades-shapes" not in job.argv  # the job runs the default
    seen = {}
    monkeypatch.setattr(cc, "_nice", lambda: None)
    monkeypatch.setattr(cc, "run", lambda root, **kw: seen.update(kw) or {"status": "ok"})
    cc.main(["run", "--data-root", str(tmp_path)])
    assert seen["trades_shapes"] == "e4"
    cc.main(["run", "--data-root", str(tmp_path), "--trades-shapes", "none"])
    assert seen["trades_shapes"] == "none"


def test_the_capture_imports_no_research_module():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    assert not {"numpy", "e4_stage2_combo_prices", "e4_combo_correlation"} & imported, imported
