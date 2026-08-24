"""Kalshi keeps its own clock, PER SERIES -- the thing that makes it economical.

A single whole-fetch clock means adding a sport costs a bigger burst on the same
schedule. A per-series clock means it costs exactly one more call per interval,
and the per-tick cap only decides how bursty that is.
"""

from __future__ import annotations

import pytest

from pipeline import kalshi_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    for name in (
        "SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS",
        "SYNDICATE_KALSHI_SERIES",
        "SYNDICATE_KALSHI_SERIES_PER_TICK",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


def _market(ticker, yes, series="KXMLBKS"):
    return {
        "ticker": ticker,
        "yes_ask_dollars": yes,
        "no_ask_dollars": round(1 - yes, 4),
        "series": series,
        "title": f"Player {ticker}: 7+ strikeouts?",
        "close_time": "2026-08-24T23:10:00Z",
    }


def _stub(monkeypatch, calls, *, fails=()):
    def fake(series):
        calls.append(series)
        if series in fails:
            return {"markets": [], "strategy": "failed", "reason": "http_429"}
        return {"markets": [_market(f"{series}-1", 0.4, series=series)], "strategy": "series_filter"}

    monkeypatch.setattr(mod, "fetch_series_markets", fake)


# --- configuration ---------------------------------------------------------


def test_the_series_list_comes_from_the_catalogue(monkeypatch):
    from syndicate.features.shared.kalshi_catalogue import SERIES_SPORT

    # One registry line adds a sport; a second list here would be a second place
    # to forget.
    assert set(mod.default_sports_series()) == set(SERIES_SPORT)


def test_the_interval_is_short_enough_to_act_on_a_live_game():
    """Hourly was written when the only consumer was a next-day opening line.

    A rebounds line moves every possession, so an hour-old price sent as a limit
    order is a memory. Affordable now because reads are SIGNED — the 429s that
    forced pacing were on the anonymous quota.
    """
    assert mod.refresh_interval_seconds() == 120


def test_a_bad_interval_falls_back_to_the_default_not_to_zero(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "not-a-number")
    # Falling back to 0 would turn a typo into an unpaced loop against a venue
    # that rate-limits us -- the exact failure the gate exists to prevent.
    assert mod.refresh_interval_seconds() == mod.DEFAULT_REFRESH_INTERVAL_SECONDS


def test_a_bad_per_tick_cap_falls_back_rather_than_to_zero(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "lots")
    assert mod.series_per_tick() == mod.DEFAULT_SERIES_PER_TICK
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "0")
    # Zero would silently stop the feed.
    assert mod.series_per_tick() == mod.DEFAULT_SERIES_PER_TICK


def test_the_series_list_is_overridable_without_a_deploy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "kxmlbks, KXNBAPTS ")
    assert mod.sports_series() == ("KXMLBKS", "KXNBAPTS")


def test_an_override_that_parses_to_nothing_keeps_the_catalogue(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", " , ,")
    assert mod.sports_series() == mod.default_sports_series()


# --- the per-series clock --------------------------------------------------


def test_a_second_tick_inside_the_interval_fetches_nothing(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    first = mod.run_kalshi_odds_refresh()
    assert first["status"] == "ok"
    assert sorted(calls) == ["A", "B"]

    second = mod.run_kalshi_odds_refresh()
    # CACHED, not skipped: the board still gets prices, it just does not get an
    # HTTP call.
    assert second["status"] == "cached"
    assert len(second["markets"]) == 2
    assert sorted(calls) == ["A", "B"], "the per-series clock did not hold"


def test_a_series_not_fetched_this_tick_keeps_its_prices(monkeypatch):
    """The merge. Without it a staggered fetch is unusable: three quarters of
    the board's Kalshi prices would vanish on every tick."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B,C")
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "1")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    seen = set()
    for _ in range(3):
        result = mod.run_kalshi_odds_refresh()
        seen |= {m["series"] for m in result["markets"]}

    assert calls == ["A", "B", "C"], "one series per tick, in order"
    # By the third tick all three are present even though only one was fetched.
    assert seen == {"A", "B", "C"}
    assert len(mod.run_kalshi_odds_refresh()["markets"]) == 3


def test_the_per_tick_cap_bounds_the_burst_not_the_coverage(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B,C,D,E")
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "2")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    mod.run_kalshi_odds_refresh()
    assert len(calls) == 2
    mod.run_kalshi_odds_refresh()
    assert len(calls) == 4
    mod.run_kalshi_odds_refresh()
    # All five covered in three ticks, which at a ~2min board build is minutes,
    # not hours.
    assert sorted(calls) == ["A", "B", "C", "D", "E"]


def test_a_waiting_series_is_not_starved_by_a_newly_added_one(monkeypatch):
    """Oldest first. With a cap and no ordering the alphabetically-first N would
    refresh forever and the rest never would."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B")
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "1")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    mod.run_kalshi_odds_refresh()
    assert calls == ["A"]
    mod.run_kalshi_odds_refresh()
    # B has never been fetched; A has. B sorts ahead.
    assert calls == ["A", "B"]


def test_force_bypasses_the_clock_and_the_cap(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B,C")
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "1")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    mod.run_kalshi_odds_refresh(force=True)
    assert sorted(calls) == ["A", "B", "C"]


# --- failures --------------------------------------------------------------


def test_a_failed_series_neither_blanks_its_prices_nor_starts_its_clock(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    calls: list[str] = []
    _stub(monkeypatch, calls)
    mod.run_kalshi_odds_refresh()

    _stub(monkeypatch, calls, fails={"A"})
    result = mod.run_kalshi_odds_refresh(force=True)
    # Stamping `fetched_at` on a failure would blank the series AND make the
    # artifact look fresh for an hour.
    assert [m["series"] for m in result["markets"]] == ["A"]


def test_a_failing_series_backs_off_instead_of_retrying_every_board_build(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    calls: list[str] = []
    _stub(monkeypatch, calls, fails={"A"})

    mod.run_kalshi_odds_refresh()
    assert calls == ["A"]
    mod.run_kalshi_odds_refresh()
    # Retrying a 403ing or rate-limited venue every ~2 minutes is how the
    # 2026-08-23 429s happened.
    assert calls == ["A"], "the failure backoff did not hold"


def test_one_series_failing_does_not_cost_the_others_their_refresh(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B")
    calls: list[str] = []
    _stub(monkeypatch, calls, fails={"A"})

    result = mod.run_kalshi_odds_refresh()
    assert sorted(calls) == ["A", "B"]
    assert [m["series"] for m in result["markets"]] == ["B"]


def test_a_success_clears_an_earlier_failures_backoff(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    calls: list[str] = []
    _stub(monkeypatch, calls, fails={"A"})
    mod.run_kalshi_odds_refresh()

    _stub(monkeypatch, calls)
    mod.run_kalshi_odds_refresh(force=True)
    # A stale failure stamp must not outlive the failure.
    assert mod.run_kalshi_odds_refresh()["status"] == "cached"


# --- history and bounds ----------------------------------------------------


def test_the_fetch_records_price_history(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    calls: list[str] = []
    _stub(monkeypatch, calls)
    mod.run_kalshi_odds_refresh()

    from syndicate.features.shared.kalshi_board import opening_line

    assert opening_line("A-1")["opening_yes"] == 0.4


def test_a_cached_tick_does_not_re_record_history(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    calls: list[str] = []
    _stub(monkeypatch, calls)
    mod.run_kalshi_odds_refresh()

    recorded: list[int] = []
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_board.record_snapshot",
        lambda markets, **kw: recorded.append(len(markets)) or {"status": "ok"},
    )
    mod.run_kalshi_odds_refresh()
    # Appending the same merged snapshot ~30 times an hour would leave the
    # `unchanged` counter meaning nothing.
    assert recorded == []


def test_a_history_failure_does_not_cost_the_board_its_prices(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    def boom(*_a, **_k):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr("syndicate.features.shared.kalshi_board.record_snapshot", boom)
    result = mod.run_kalshi_odds_refresh()
    assert result["status"] == "ok"
    assert len(result["markets"]) == 1


def test_the_merged_artifact_reports_how_stale_its_oldest_price_is(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    result = mod.run_kalshi_odds_refresh()
    # A merged artifact hides staleness by construction unless it is stated.
    assert set(result["staleness_seconds"]) == {"A", "B"}


# --------------------------------------------------------------------------
# Discovery must run in the process that PRICES, not in one worker's boot
# --------------------------------------------------------------------------


def test_discovery_runs_in_the_refresh_not_a_workers_boot(monkeypatch):
    """MEASURED 2026-08-24T01:35:57Z, with real money armed and the game-line
    flag ON:

        BOARD_JOIN kalshi_markets=203 board_rows=513 matched=0
          reasons={'market_is_for_another_date': 67, 'no_matching_board_row': 136}

    203 markets from SEVEN hand-registered series, and no `game_lines_disabled`
    in the refusals at all -- meaning not one game line even reached the
    resolver. Discovery had found football, NBA and the game-line series... in
    live-odds-worker, which does not do the join. `register_discovered` writes
    a module-level dict, so it does not cross the process boundary, and the
    join runs on refresh-worker where that dict was empty.
    """
    import pipeline.kalshi_odds_refresh as mod

    monkeypatch.setattr(mod, "_DISCOVERY_DONE", False)
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover_series",
        lambda: {
            "status": "ok",
            "count": 2,
            "titles": {
                "KXNFLPASSYDS": "Pro Football Player Passing Yards",
                "KXWNBA1QTOTAL": "Women's Pro Basketball 1st Quarter Total",
            },
        },
    )
    result = mod.ensure_series_discovered(force=True)
    assert result["status"] == "ok"
    # BOTH kinds, from one call: a prop series and a game-line series.
    assert result["prop_series"] == 1
    assert result["game_series"] == 1

    from syndicate.features.shared.kalshi_catalogue import all_series

    registered = all_series()
    assert registered.get("KXNFLPASSYDS") == "nfl"
    assert registered.get("KXWNBA1QTOTAL") == "wnba"


def test_a_failed_catalogue_is_retried_rather_than_latched(monkeypatch):
    """Not marked done on failure. One 429 at startup would otherwise leave the
    process pricing seven hand-registered series for its entire life -- the
    same silent-degradation shape as the auth probe that never ran."""
    import pipeline.kalshi_odds_refresh as mod

    monkeypatch.setattr(mod, "_DISCOVERY_DONE", False)
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover_series",
        lambda: {"status": "error", "errors": "429"},
    )
    assert mod.ensure_series_discovered(force=True)["status"] == "error"
    assert mod._DISCOVERY_DONE is False


def test_discovery_failure_never_takes_down_the_refresh(monkeypatch):
    """The hand-registered series must still price when the catalogue is
    unreachable. A discovery error is a smaller board, not an outage."""
    import pipeline.kalshi_odds_refresh as mod

    monkeypatch.setattr(mod, "_DISCOVERY_DONE", False)

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover_series", boom
    )
    result = mod.ensure_series_discovered(force=True)
    assert result["status"] == "error"
    assert "network down" in result["reason"]


# --------------------------------------------------------------------------
# Hot series: the markets we have money in must not wait behind 150 we don't
# --------------------------------------------------------------------------


def test_a_series_with_an_open_order_is_hot(monkeypatch):
    """MEASURED 2026-08-24: 155 series against a cap of 12 a tick is ~13 ticks
    to sweep, so any quote can be ~26 minutes old. Harmless for a series nobody
    trades; unacceptable for one with a resting order against it — and the old
    queue ordered by AGE alone, so it could not tell them apart.

    Derived from the LEDGER so it follows the money: no list to maintain, and a
    series stops being hot when its order stops being open.
    """
    import pipeline.kalshi_odds_refresh as mod
    import syndicate.features.shared.execution_ledger as ledger

    monkeypatch.delenv("SYNDICATE_KALSHI_HOT_SERIES", raising=False)
    monkeypatch.setattr(
        ledger, "_load",
        lambda: {"orders": [
            {"status": "submitted", "venue_ticker": "KXMLBKS-26AUG242140MINATH-X"},
        ]},
    )
    assert "KXMLBKS" in mod.hot_series()


def test_a_settled_or_dead_order_is_not_hot(monkeypatch):
    """A rejected order is not money at risk, and a graded one no longer cares
    what the price is. Neither should hold a refresh slot."""
    import pipeline.kalshi_odds_refresh as mod
    import syndicate.features.shared.execution_ledger as ledger

    monkeypatch.delenv("SYNDICATE_KALSHI_HOT_SERIES", raising=False)
    monkeypatch.setattr(
        ledger, "_load",
        lambda: {"orders": [
            {"status": "rejected", "venue_ticker": "KXMLBHR-26AUG242140MINATH-X"},
            {"status": "failed", "venue_ticker": "KXMLBOUTS-26AUG242140MINATH-X"},
            {"status": "filled", "outcome": "won",
             "venue_ticker": "KXWNBAPTS-26AUG23LVTOR-X"},
        ]},
    )
    assert mod.hot_series() == set()


def test_an_unreadable_ledger_degrades_to_the_ordinary_schedule(monkeypatch):
    """A hot list we cannot compute must not stop the refresh — the cold
    schedule is a worse outcome than no refresh at all is."""
    import pipeline.kalshi_odds_refresh as mod
    import syndicate.features.shared.execution_ledger as ledger

    monkeypatch.delenv("SYNDICATE_KALSHI_HOT_SERIES", raising=False)

    def boom():
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(ledger, "_load", boom)
    assert mod.hot_series() == set()


def test_a_series_can_be_marked_hot_before_we_trade_it(monkeypatch):
    """For a market we want watched closely before there is an order on it."""
    import pipeline.kalshi_odds_refresh as mod
    import syndicate.features.shared.execution_ledger as ledger

    monkeypatch.setattr(ledger, "_load", lambda: {"orders": []})
    monkeypatch.setenv("SYNDICATE_KALSHI_HOT_SERIES", "kxwnbapts, KXMLBKS")
    assert mod.hot_series() == {"KXWNBAPTS", "KXMLBKS"}


def test_the_hot_clock_is_shorter_than_the_cold_one(monkeypatch):
    """The whole point: a series carrying money is not the same kind of thing
    as one of the 142 game-line series we have never priced."""
    import pipeline.kalshi_odds_refresh as mod

    monkeypatch.delenv("SYNDICATE_KALSHI_HOT_REFRESH_SECONDS", raising=False)
    assert mod.hot_refresh_interval_seconds() < mod.refresh_interval_seconds()


def test_a_bad_hot_interval_falls_back_rather_than_disabling(monkeypatch):
    """Zero would mean 'never', which is the opposite of what someone typing it
    intends — the same trap `_int_env` has for the order caps."""
    import pipeline.kalshi_odds_refresh as mod

    for bad in ("0", "-5", "soon", ""):
        monkeypatch.setenv("SYNDICATE_KALSHI_HOT_REFRESH_SECONDS", bad)
        assert mod.hot_refresh_interval_seconds() == 30
