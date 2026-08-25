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
        "SYNDICATE_KALSHI_DORMANT_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    # NO REAL SLEEPING IN TESTS. The spacing is what makes a large per-tick cap
    # safe against the venue; it has its own tests below, and paying it in
    # every other test buys nothing but wall clock.
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "0")
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


def _stub(monkeypatch, calls, *, fails=(), empty=()):
    """`fails` is a venue that would not answer. `empty` is a venue that
    answered with an empty book -- an out-of-season series. The two must not
    behave alike, which is what the starvation test below pins."""
    def fake(series):
        calls.append(series)
        if series in fails:
            return {"markets": [], "strategy": "failed", "reason": "http_429"}
        if series in empty:
            return {"markets": [], "strategy": "series_filter"}
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


# --------------------------------------------------------------------------
# An out-of-season series must not monopolise the queue forever
# --------------------------------------------------------------------------


def test_an_empty_series_does_not_starve_every_other_series(monkeypatch):
    """THE WHACK-A-MOLE MECHANISM, and it is a starved queue rather than a
    missing grammar.

    `fetched_at` used to move only when markets came back. A series that
    genuinely has none -- NBA quarter lines in August, the All-Star game,
    parlays -- therefore never got stamped, `_due_series` saw `age=None` and
    sorted it at `inf` ahead of everything, and it returned to the front of the
    queue on every tick forever. With a per-tick cap of 12 and more than twelve
    such series, the entire budget went to markets that cannot exist this month.

    MEASURED 2026-08-25T16:41:09Z, twice, identical:

        TICK series_wanted=191 due=191 fetched=12 cap=12 markets=883
          this_tick={'KXATTENDMLB': (0,'series_filter'),
                     'KXMLBASGAME': (0,'series_filter'),
                     'KXMVENBASINGLEGAME': (0,'series_filter'), ...} ALL ZERO
          oldest_s=142655        <- 39.6 hours

    It also inverts auto-discovery: each newly registered out-of-season series
    joins the permanent front of the queue, so registering MORE series makes
    coverage WORSE.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "EMPTY1,EMPTY2,LIVE1,LIVE2")
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES_PER_TICK", "2")
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")
    calls = []
    _stub(monkeypatch, calls, empty=("EMPTY1", "EMPTY2"))

    mod.run_kalshi_odds_refresh()   # tick 1 -- the two empties sort first
    first = list(calls)
    calls.clear()
    mod.run_kalshi_odds_refresh()   # tick 2 -- must move on
    second = list(calls)

    assert set(first) == {"EMPTY1", "EMPTY2"}, first
    # THE ASSERTION THAT MATTERS: the live series get their turn.
    assert set(second) == {"LIVE1", "LIVE2"}, (
        f"empty series monopolised the queue: tick2 fetched {second}"
    )


def test_a_FAILED_series_still_backs_off_rather_than_being_stamped(monkeypatch):
    """The control. The stamp follows a successful READ, not a non-empty
    payload -- so a venue that would not answer must still look unfetched, or
    the backoff that stopped the 2026-08-23 http_429s is gone."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "BROKEN")
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")
    calls = []
    _stub(monkeypatch, calls, fails=("BROKEN",))

    mod.run_kalshi_odds_refresh()
    state = mod._load_state() if hasattr(mod, "_load_state") else None
    if state is not None:
        entry = (state.get("series") or {}).get("BROKEN") or {}
        assert entry.get("fetched_at") != entry.get("attempted_at")


def test_an_empty_read_keeps_the_last_known_markets(monkeypatch):
    """"Nothing open right now" is not "the previous prices were wrong".
    Blanking on an empty read would delete a live series' prices the moment its
    last market settled."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A")
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")
    calls = []
    _stub(monkeypatch, calls)
    first = mod.run_kalshi_odds_refresh()
    assert len(first["markets"]) == 1

    _stub(monkeypatch, calls, empty=("A",))
    second = mod.run_kalshi_odds_refresh()
    assert len(second["markets"]) == 1, "an empty read blanked the stored prices"


# --------------------------------------------------------------------------
# Cadence: the calls are FREE, so the limit is the venue's rate, not our budget
# --------------------------------------------------------------------------


def test_the_burst_is_bounded_by_TIME_not_only_by_the_cap(monkeypatch):
    """The 2026-08-23 http_429s came from RATE, not count.

    The per-tick cap was the only burst control, which is why it sat at 12 --
    raising it for freshness would have put the burst straight back. Spacing
    bounds requests per second, so the cap can be about coverage instead.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B,C")
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "40")
    calls: list[str] = []
    _stub(monkeypatch, calls)

    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))

    mod.run_kalshi_odds_refresh()
    assert sorted(calls) == ["A", "B", "C"]
    # Three calls, two gaps -- the first pays nothing, so a one-series tick is
    # not taxed for a burst it cannot create.
    assert slept == [0.04, 0.04]


def test_a_bad_spacing_value_does_not_become_an_unpaced_loop(monkeypatch):
    """The failure this guard exists to prevent. A typo must fall back to the
    default, never to zero -- zero is precisely the unpaced loop that drew the
    429s."""
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "lots")
    assert mod.request_spacing_seconds() == mod.DEFAULT_REQUEST_SPACING_MS / 1000.0
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "-5")
    assert mod.request_spacing_seconds() == mod.DEFAULT_REQUEST_SPACING_MS / 1000.0


def test_a_dormant_series_waits_longer_than_a_live_one(monkeypatch):
    """Where the tick budget was going. An out-of-season series is worth
    checking hourly, not every two minutes -- and the budget it frees goes to
    series that actually have markets, which is what makes a high cadence
    affordable on a free API."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "LIVE,DORMANT")
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("SYNDICATE_KALSHI_DORMANT_INTERVAL_SECONDS", "3600")
    calls: list[str] = []
    _stub(monkeypatch, calls, empty=("DORMANT",))

    mod.run_kalshi_odds_refresh()      # both asked; DORMANT returns nothing
    assert sorted(calls) == ["DORMANT", "LIVE"]
    calls.clear()

    mod.run_kalshi_odds_refresh()      # DORMANT is now on the hourly clock
    assert calls == ["LIVE"], f"a dormant series kept consuming the budget: {calls}"


def test_a_series_never_fetched_is_NOT_treated_as_dormant(monkeypatch):
    """`count == 0` is a positive statement -- we asked, there was nothing.
    Absence of `count` is unknown, and unknown must be asked at the normal
    cadence or a newly registered series would wait an hour to be seen once."""
    assert mod._is_dormant({}) is False
    assert mod._is_dormant({"count": 0}) is True
    assert mod._is_dormant({"count": 7}) is False


# --------------------------------------------------------------------------
# The artifact has a hard 8MB ceiling, and it hit it
# --------------------------------------------------------------------------


def test_the_merged_list_is_not_persisted_twice(monkeypatch):
    """MEASURED 2026-08-25T17:53:48Z, the tick after the queue started rotating:

      KEYVALUE_WRITE_REJECTED size_bytes=13315551 max_bytes=8388608
      COMPOSITION series=7399941 markets=6682458

    The artifact stored every series' markets AND their concatenation. Same
    payload, twice, in a document with a hard 8MB ceiling -- so it stopped
    being written at all and the board fell back to the last good write.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "A,B")
    calls: list[str] = []
    _stub(monkeypatch, calls)
    mod.run_kalshi_odds_refresh()

    from syndicate.features.shared.refresh_state_store import read_json_file

    payload = read_json_file(mod.markets_artifact_path())
    assert "markets" not in payload, "the merged list is persisted twice again"
    # ...and it is still READABLE, merged back from the per-series entries.
    assert len(mod.markets_from_state(payload)) == 2


def test_a_legacy_payload_still_reads(monkeypatch):
    """A deploy must not empty the board. A payload written before the change
    has the top-level key and no per-series markets."""
    assert mod.markets_from_state({"markets": [{"ticker": "T1"}]})[0]["ticker"] == "T1"
    assert mod.markets_from_state(None) == []
    assert mod.markets_from_state({}) == []


def test_one_ladder_series_cannot_crowd_out_a_sport(monkeypatch):
    """`KXNCAAFSPREAD` was 2.3MB on its own -- a spread ladder with every rung
    of every game. Bounding per series is safe only because `venue_daily_odds`
    now records the complete book separately; this artifact is the JOIN's
    working set, and a working set may be bounded where a record may not."""
    monkeypatch.setattr(mod, "MAX_MARKETS_PER_SERIES", 3)
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "BIG")

    def fake(series):
        return {"markets": [_market(f"{series}-{n}", 0.4, series=series) for n in range(10)],
                "strategy": "series_filter"}

    monkeypatch.setattr(mod, "fetch_series_markets", fake)
    result = mod.run_kalshi_odds_refresh()
    assert len(result["markets"]) == 3


def test_the_trim_drops_the_STALEST_series_not_the_alphabetically_last(monkeypatch):
    """The docstring always said "trimmed OLDEST-SERIES-FIRST"; the code was
    `all_markets[:MAX_STORED_MARKETS]` -- the alphabetically FIRST N, because
    `sports_series()` returns sorted tickers. `KXWNBA*` sorts LAST, so the
    first thing a trim deleted was every WNBA market, silently, while the
    comment claimed otherwise.
    """
    monkeypatch.setattr(mod, "MAX_STORED_MARKETS", 2)
    monkeypatch.setattr(mod, "MAX_MARKETS_PER_SERIES", 10)
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "AAA,ZZZ")
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")

    calls: list[str] = []
    _stub(monkeypatch, calls)
    mod.run_kalshi_odds_refresh()

    # Make AAA stale and ZZZ fresh, then re-merge: the FRESH one must survive.
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    path = mod.markets_artifact_path()
    state = read_json_file(path)
    state["series"]["AAA"]["fetched_at"] = "2020-01-01T00:00:00Z"
    for n in range(3):
        state["series"]["ZZZ"]["markets"].append(_market(f"ZZZ-{n}", 0.4, series="ZZZ"))
    write_json_file(path, state)

    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "999999")
    result = mod.run_kalshi_odds_refresh()
    kept = {m["series"] for m in result["markets"]}
    assert kept == {"ZZZ"}, f"the stale series survived the trim: {kept}"


def test_the_daily_book_records_the_COMPLETE_set_not_the_working_set(monkeypatch):
    """The bound on the working set is justified by the record being complete.
    If the record inherits the bound, the justification is circular and the
    bound becomes real data loss.

    MEASURED 2026-08-25T18:33:55Z: `trimmed=2121` markets never reached the
    daily book, and `KXNCAAFSPREAD`'s ladder was truncated 1994 -> 400 in the
    one place whose purpose is keeping whole ladders.
    """
    monkeypatch.setattr(mod, "MAX_MARKETS_PER_SERIES", 2)
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "LADDER")

    def fake(series):
        return {"markets": [_market(f"{series}-{n}", 0.4, series=series) for n in range(9)],
                "strategy": "series_filter"}

    monkeypatch.setattr(mod, "fetch_series_markets", fake)

    recorded: list[list] = []
    monkeypatch.setattr(mod, "_record_daily_book", lambda markets: recorded.append(list(markets)))

    result = mod.run_kalshi_odds_refresh()

    # The WORKING SET is bounded -- that is what keeps the artifact writable.
    assert len(result["markets"]) == 2
    # The RECORD is not. Every rung of the ladder reaches it.
    assert len(recorded[0]) == 9


def test_the_PERSISTED_markets_are_bounded_too(monkeypatch):
    """The 400-per-series cap was applied only when BUILDING the working set;
    `per_series[<ticker>]["markets"]` still held every market, and that dict is
    what gets written.

    MEASURED 2026-08-25T18:53:11Z:

      KEYVALUE_WRITE_REJECTED size_bytes=8701075 max_bytes=8388608
      COMPOSITION series=9196911  KXNCAAFSPREAD=2306201 KXNFLSPREAD=903759 ...

    So the artifact could not be written, `fetched_at` never persisted, and the
    queue re-fetched the SAME 60 series every tick while `oldest_s` merely
    aged. A rotation that cannot record its own progress does not rotate.
    """
    monkeypatch.setattr(mod, "MAX_MARKETS_PER_SERIES", 3)
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "BIG")

    def fake(series):
        return {"markets": [
            {"ticker": f"BIG-26AUG24{n:04d}MINATH-X", "series": series,
             "title": f"Player P{n}: 7+ strikeouts?",
             "yes_ask_dollars": 0.4, "no_ask_dollars": 0.6,
             "close_time": "2026-08-24T23:10:00Z"}
            for n in range(9)
        ], "strategy": "series_filter"}

    monkeypatch.setattr(mod, "fetch_series_markets", fake)
    mod.run_kalshi_odds_refresh()

    from syndicate.features.shared.refresh_state_store import read_json_file

    stored = read_json_file(mod.markets_artifact_path())["series"]["BIG"]["markets"]
    assert len(stored) == 3, f"persisted {len(stored)} markets, unbounded"


def test_the_persisted_row_is_LEAN(monkeypatch):
    """"Shrink the payload rather than raising the ceiling" is what the store's
    own refusal says. `normalize_market` keeps ~29 fields for diagnosis --
    bids, volumes, open interest, liquidity, strike type -- and nothing
    downstream of the artifact reads them. The full row survives in the daily
    book, which is the record."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "LEAN")

    fat = {
        "ticker": "LEAN-26AUG242145CINSF-X", "series": "LEAN",
        "title": "Player A: 7+ strikeouts?", "close_time": "2026-08-24T23:10:00Z",
        "yes_ask_dollars": 0.4, "no_ask_dollars": 0.6,
        "yes_american": 150, "no_american": -150,
        # Diagnosis-only weight that must not persist.
        "volume_fp": 12345, "open_interest_fp": 999, "liquidity_dollars": 4242,
        "yes_bid_dollars": 0.39, "strike_type": "greater", "missing_fields": [],
    }
    monkeypatch.setattr(mod, "fetch_series_markets",
                        lambda series: {"markets": [dict(fat)], "strategy": "series_filter"})

    recorded: list[list] = []
    monkeypatch.setattr(mod, "_record_daily_book", lambda markets: recorded.append(list(markets)))
    mod.run_kalshi_odds_refresh()

    from syndicate.features.shared.refresh_state_store import read_json_file

    stored = read_json_file(mod.markets_artifact_path())["series"]["LEAN"]["markets"][0]
    for gone in ("volume_fp", "open_interest_fp", "liquidity_dollars",
                 "yes_bid_dollars", "strike_type", "missing_fields"):
        assert gone not in stored, gone
    # ...and everything the join, the price lookup and the snapshot read stays.
    for kept in ("ticker", "series", "title", "yes_ask_dollars", "no_ask_dollars",
                 "yes_american", "no_american", "close_time"):
        assert kept in stored, kept

    # THE RECORD IS UNTOUCHED -- it saw the full row.
    assert recorded[0][0]["volume_fp"] == 12345


def test_an_undated_market_is_still_persisted(monkeypatch):
    """A date filter on the working set was tried and REVERTED. Futures can
    never match a board row, so dropping them looked free -- but PLAYER PROPS
    SKIP THE JOIN'S DATE CHECK ENTIRELY (it lives inside the
    `needs_event_identity` branch), so a prop whose ticker shape does not parse
    would have been silently dropped from the venue we actually trade."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "UNDATED")
    monkeypatch.setattr(mod, "fetch_series_markets", lambda series: {
        "markets": [{"ticker": "UNDATED-1", "series": series,
                     "title": "Player A: 7+ strikeouts?",
                     "yes_ask_dollars": 0.4, "no_ask_dollars": 0.6}],
        "strategy": "series_filter"})
    result = mod.run_kalshi_odds_refresh()
    assert len(result["markets"]) == 1


def test_the_unregistered_sport_series_are_named(monkeypatch):
    """Registration is the FIRST gate, and a series that fails it is INVISIBLE:
    never fetched, so it cannot appear in `unreadable_title`, in BOARD_JOIN
    reasons, or in the daily book. The only symptom is a board row that never
    gets a price -- which reads as "Kalshi does not offer this".

    That is exactly how `KXMLBGAME` hid: title "Professional Baseball Game",
    no `game` entry in the vocabulary, and the moneyline was unreachable on
    every sport until a user found a live market on kalshi.com.
    """
    titles = {
        "KXMLBGAME": "Professional Baseball Game",       # registers
        "KXMLBTOTAL": "Professional Baseball Total Runs",  # does NOT
        "KXNPBTOTAL": "Japanese Baseball Total",          # out of scope
        "KXPOLITICS": "Some Election",                    # no sport token
    }
    props = {}
    games = {"KXMLBGAME": "mlb"}
    rows = mod._unregistered_sport_series(titles, props, games)
    series = [r["series"] for r in rows]

    assert series == ["KXMLBTOTAL"], rows
    assert rows[0]["title"] == "Professional Baseball Total Runs"
    assert rows[0]["sport"] == "mlb"


def test_an_already_registered_series_is_not_reported_as_a_gap():
    """A work list that fills with successes is noise."""
    rows = mod._unregistered_sport_series(
        {"KXMLBGAME": "Professional Baseball Game"}, {}, {"KXMLBGAME": "mlb"}
    )
    assert rows == []
