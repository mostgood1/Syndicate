"""Kalshi keeps its own clock, and a failed fetch must not start it."""

from __future__ import annotations

import pytest

from pipeline import kalshi_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.delenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", raising=False)
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


def _stub_fetch(monkeypatch, markets, calls):
    def fake(series):
        calls.append(series)
        return {"markets": [m for m in markets if m.get("series") == series], "strategy": "series_filter"}

    monkeypatch.setattr(mod, "fetch_series_markets", fake)


def _market(ticker, yes, series="KXMLBKS"):
    return {
        "ticker": ticker,
        "yes_ask_dollars": yes,
        "no_ask_dollars": round(1 - yes, 4),
        "series": series,
        "title": ticker,
        "close_time": "2026-08-24T23:10:00Z",
    }


def test_the_interval_defaults_to_hourly():
    assert mod.refresh_interval_seconds() == 3600


def test_a_bad_interval_falls_back_to_the_default_not_to_zero(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "not-a-number")
    # Falling back to 0 would turn a typo into an unpaced loop against a venue
    # that rate-limits us -- the exact failure the gate exists to prevent.
    assert mod.refresh_interval_seconds() == 3600
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "-5")
    assert mod.refresh_interval_seconds() == 3600


def test_a_second_call_inside_the_interval_serves_cache_without_fetching(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)

    first = mod.run_kalshi_odds_refresh()
    assert first["status"] == "ok"
    assert len(calls) == len(mod.SPORTS_SERIES)

    second = mod.run_kalshi_odds_refresh()
    # CACHED, not skipped: the board still gets prices, it just does not get a
    # fresh HTTP call.
    assert second["status"] == "cached"
    assert [m["ticker"] for m in second["markets"]] == ["A"]
    assert len(calls) == len(mod.SPORTS_SERIES), "the interval gate did not hold"


def test_force_bypasses_the_interval(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)

    mod.run_kalshi_odds_refresh()
    mod.run_kalshi_odds_refresh(force=True)
    assert len(calls) == 2 * len(mod.SPORTS_SERIES)


def test_a_zero_interval_disables_the_gate(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")
    calls: list[str] = []
    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)

    mod.run_kalshi_odds_refresh()
    mod.run_kalshi_odds_refresh()
    assert len(calls) == 2 * len(mod.SPORTS_SERIES)


def test_an_empty_fetch_neither_blanks_the_board_nor_starts_the_clock(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)
    mod.run_kalshi_odds_refresh()

    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "0")
    _stub_fetch(monkeypatch, [], calls)
    result = mod.run_kalshi_odds_refresh()

    # Stamping `fetched_at` on a failed call would blank the board AND start the
    # clock, so the next hour would serve zero markets from a "fresh" artifact.
    assert result["status"] == "empty"
    assert [m["ticker"] for m in result["markets"]] == ["A"]

    from syndicate.features.shared.refresh_state_store import read_json_file

    stored = read_json_file(mod.markets_artifact_path()) or {}
    assert [m["ticker"] for m in stored.get("markets") or []] == ["A"]


def test_the_fetch_records_price_history(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)
    mod.run_kalshi_odds_refresh()

    from syndicate.features.shared.kalshi_board import opening_line

    assert opening_line("A")["opening_yes"] == 0.4


def test_a_history_failure_does_not_cost_the_board_its_prices(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)

    def boom(*_a, **_k):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_board.record_snapshot", boom
    )
    result = mod.run_kalshi_odds_refresh()
    assert result["status"] == "ok"
    assert [m["ticker"] for m in result["markets"]] == ["A"]


def test_a_failing_venue_is_backed_off_not_retried_every_board_build(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [], calls)

    first = mod.run_kalshi_odds_refresh()
    assert first["status"] == "empty"
    assert len(calls) == len(mod.SPORTS_SERIES)

    second = mod.run_kalshi_odds_refresh()
    # Retrying a 403ing or rate-limited venue every ~3 minutes is how the
    # 2026-08-23 429s happened. The failure has its own, shorter clock.
    assert second["status"] == "backoff"
    assert len(calls) == len(mod.SPORTS_SERIES)


def test_a_success_clears_an_earlier_failures_backoff(monkeypatch):
    calls: list[str] = []
    _stub_fetch(monkeypatch, [], calls)
    mod.run_kalshi_odds_refresh()

    _stub_fetch(monkeypatch, [_market("A", 0.4)], calls)
    recovered = mod.run_kalshi_odds_refresh(force=True)
    assert recovered["status"] == "ok"

    # The next call must be `cached` (the success clock), not `backoff` -- a
    # stale failure stamp must not outlive the failure.
    assert mod.run_kalshi_odds_refresh()["status"] == "cached"


def test_the_series_list_is_overridable_without_a_deploy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", "kxmlbks, KXNBAPTS ")
    assert mod.sports_series() == ("KXMLBKS", "KXNBAPTS")


def test_an_override_that_parses_to_nothing_keeps_the_defaults(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_SERIES", " , ,")
    # A typo must not silently stop the feed.
    assert mod.sports_series() == mod.DEFAULT_SPORTS_SERIES
