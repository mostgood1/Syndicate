"""Novig keeps its OWN clock -- hourly manifest checks, not Kalshi's
per-series continuous cadence, because Novig's public mirror publishes once
a day. See `pipeline/novig_odds_refresh.py`'s header for why this is
deliberately simpler than `kalshi_odds_refresh.py`.
"""

from __future__ import annotations

import pytest

from pipeline import novig_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    for name in ("SYNDICATE_NOVIG_ODDS_ENABLED", "SYNDICATE_NOVIG_ODDS_CHECK_INTERVAL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


def _snapshot(*, date="2026-08-23", count=2, is_stale_by_days=1):
    return {
        "status": "ok",
        "date": date,
        "is_stale_by_days": is_stale_by_days,
        "status_filter": ["active"],
        "count": count,
        "markets": [
            {"market_id": "m1", "report_ticker": "MLB-MONEY", "close_probability": 0.51},
            {"market_id": "m2", "report_ticker": "NBA-SPREAD", "close_probability": 0.48},
        ][:count],
        "available_market_dates": [date],
    }


def _stub(monkeypatch, result):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.fetch_latest_markets_snapshot", fake
    )
    return calls


# --- configuration -------------------------------------------------------


def test_the_default_interval_is_hourly_not_kalshis_two_minutes():
    """Novig publishes once a day; Kalshi's 120s cadence would just hammer a
    CDN manifest that changes once every ~24h the other way."""
    assert mod.check_interval_seconds() == 3600


def test_a_bad_interval_falls_back_to_the_default_not_to_zero(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NOVIG_ODDS_CHECK_INTERVAL_SECONDS", "not-a-number")
    assert mod.check_interval_seconds() == mod.DEFAULT_CHECK_INTERVAL_SECONDS


def test_disabled_by_the_env_flag_skips_without_calling_the_client(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NOVIG_ODDS_ENABLED", "0")
    calls = _stub(monkeypatch, _snapshot())
    result = mod.run_novig_odds_refresh()
    assert result == {"status": "skipped", "reason": "disabled"}
    assert calls == []


# --- first run / refresh --------------------------------------------------


def test_first_run_fetches_and_stores_the_snapshot(monkeypatch):
    _stub(monkeypatch, _snapshot(date="2026-08-23"))
    result = mod.run_novig_odds_refresh()
    assert result["status"] == "ok"
    assert result["snapshot"]["date"] == "2026-08-23"

    # Persisted -- a second call within the interval must not re-fetch.
    path = mod.markets_artifact_path()
    from syndicate.features.shared.refresh_state_store import read_json_file

    state = read_json_file(path)
    assert state["snapshot"]["date"] == "2026-08-23"
    assert state["checked_at"]


def test_a_real_markets_row_carries_decimal_fields_and_the_write_still_lands(monkeypatch):
    """Measured 2026-08-24, first production cycle: `normalize_market_row`
    (see `novig_client.py`) deliberately returns `Decimal` for
    `open_interest`/`daily_volume`, and that rode unconverted into
    `write_json_file`'s plain `json.dumps`, which raised `Object of type
    Decimal is not JSON serializable` on every single write -- the fetch
    itself succeeded (REFRESHED, count=29469) but nothing was ever
    persisted. `test_first_run_fetches_and_stores_the_snapshot` above did
    not catch it because its stubbed snapshot never contains a Decimal --
    this one does, matching what `normalize_market_row` actually returns.
    """
    from decimal import Decimal

    snapshot = _snapshot(date="2026-08-24")
    snapshot["markets"] = [
        {
            "market_id": "m1",
            "report_ticker": "MLB-MONEY",
            "open_interest": Decimal("9.25"),
            "daily_volume": Decimal("420.73"),
            "close_probability": 0.51,
        }
    ]
    _stub(monkeypatch, snapshot)

    result = mod.run_novig_odds_refresh()
    assert result["status"] == "ok"

    path = mod.markets_artifact_path()
    from syndicate.features.shared.refresh_state_store import read_json_file

    state = read_json_file(path)
    # Persisted at all -- the bug this guards against silently dropped the
    # write while still reporting a WRITE_FAILED-only symptom, not a raise.
    assert state is not None
    stored_market = state["snapshot"]["markets"][0]
    # Round-trips through str, not float -- the whole reason `_decimal_or_none`
    # parses via `Decimal(str(...))` rather than `float()` in the first place.
    assert stored_market["open_interest"] == "9.25"
    assert stored_market["daily_volume"] == "420.73"
    # The OHLC intraday fields and the per-row `date` (redundant with the
    # snapshot's own top-level `date`) are NOT persisted -- see
    # `_trimmed_for_storage`'s docstring-comment for why.
    assert "open_probability" not in stored_market
    assert "high_probability" not in stored_market
    assert "low_probability" not in stored_market
    assert "date" not in stored_market


def test_a_full_catalogue_fits_under_the_keyvalue_store_size_ceiling(monkeypatch):
    """Measured 2026-08-24, the very next production cycle after the Decimal
    fix above: a real full day's catalogue (29,469 rows, un-trimmed) came in
    at 9,128,668 bytes -- over `refresh_state_store`'s ~8MB ceiling (#60 in
    docs/ai_context/todo.md), so the fix above just traded one WRITE_FAILED
    for another. This proves the trim actually buys enough headroom: a
    synthetic catalogue built at the SAME row count and field richness as the
    real one that failed must serialize under the ceiling after the fix.
    """
    import json

    row_template = {
        "market_id": "019fddfe-aaaa-bbbb-cccc-0123456789ab",
        "report_ticker": "NCAAF-SPREAD",
        "open_interest": "12.50",
        "daily_volume": "420.73",
        "open_probability": 0.505,
        "high_probability": 0.55,
        "low_probability": 0.49,
        "close_probability": 0.512,
        "close_american": -108,
        "status": "active",
        "traded_today": True,
        "date": "2026-08-23",
    }
    snapshot = _snapshot(date="2026-08-23", count=1)
    snapshot["markets"] = [dict(row_template) for _ in range(29469)]
    snapshot["count"] = len(snapshot["markets"])
    _stub(monkeypatch, snapshot)

    result = mod.run_novig_odds_refresh()
    assert result["status"] == "ok"

    path = mod.markets_artifact_path()
    from syndicate.features.shared.refresh_state_store import read_json_file

    state = read_json_file(path)
    # Persisted at all -- the size-ceiling failure, like the Decimal one
    # above, presented as a silent drop (WRITE_FAILED logged, no raise).
    assert state is not None
    assert len(state["snapshot"]["markets"]) == 29469

    serialized = json.dumps(mod._json_safe(state), separators=(",", ":"))
    assert len(serialized.encode("utf-8")) < 8 * 1024 * 1024


def test_a_second_call_within_the_interval_is_cached_and_does_not_call_the_client(monkeypatch):
    calls = _stub(monkeypatch, _snapshot(date="2026-08-23"))
    mod.run_novig_odds_refresh()
    assert len(calls) == 1

    result = mod.run_novig_odds_refresh()
    assert result["status"] == "cached"
    assert result["snapshot"]["date"] == "2026-08-23"
    # THE WHOLE ECONOMY OF THIS MODULE: no second network call within the hour.
    assert len(calls) == 1


def test_force_bypasses_both_the_enable_flag_and_the_clock(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NOVIG_ODDS_ENABLED", "0")
    calls = _stub(monkeypatch, _snapshot(date="2026-08-23"))
    result = mod.run_novig_odds_refresh(force=True)
    assert result["status"] == "ok"
    assert len(calls) == 1


def test_when_the_manifest_check_runs_but_no_new_date_has_published_the_csv_is_not_refetched(monkeypatch):
    """The manifest is checked on the hourly clock; the CSV itself is only
    refetched when the manifest actually names a NEW date -- most hourly
    checks land on the same published day."""
    calls = _stub(monkeypatch, _snapshot(date="2026-08-23"))
    mod.run_novig_odds_refresh()

    # Simulate the hourly clock elapsing by clearing the persisted checked_at
    # far enough in the past that _due_to_check fires again.
    path = mod.markets_artifact_path()
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    state = read_json_file(path)
    state["checked_at"] = "2020-01-01T00:00:00Z"
    write_json_file(path, state)

    result = mod.run_novig_odds_refresh()
    # The client WAS called (manifest check), but the date is unchanged, so
    # this reports cached rather than ok.
    assert len(calls) == 2
    assert result["status"] == "cached"
    assert result["snapshot"]["date"] == "2026-08-23"


def test_a_new_published_date_triggers_a_real_refresh(monkeypatch):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _snapshot(date="2026-08-23" if len(calls) == 1 else "2026-08-24")

    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.fetch_latest_markets_snapshot", fake
    )
    mod.run_novig_odds_refresh()

    path = mod.markets_artifact_path()
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    state = read_json_file(path)
    state["checked_at"] = "2020-01-01T00:00:00Z"
    write_json_file(path, state)

    result = mod.run_novig_odds_refresh()
    assert result["status"] == "ok"
    assert result["snapshot"]["date"] == "2026-08-24"


# --- failure handling ------------------------------------------------------


def test_a_failed_check_keeps_the_last_good_snapshot(monkeypatch):
    _stub(monkeypatch, _snapshot(date="2026-08-23"))
    mod.run_novig_odds_refresh()

    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.fetch_latest_markets_snapshot",
        lambda **kw: {"status": "error", "reason": "http_403"},
    )
    result = mod.run_novig_odds_refresh(force=True)
    assert result["status"] == "error"
    # Yesterday's good close is NOT wiped out by one bad manifest read.
    assert result["snapshot"]["date"] == "2026-08-23"


def test_a_failed_check_backs_off_on_its_own_shorter_clock(monkeypatch):
    calls = []

    def fake(**kw):
        calls.append(kw)
        return {"status": "error", "reason": "http_403"}

    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.fetch_latest_markets_snapshot", fake
    )
    mod.run_novig_odds_refresh(force=True)
    assert len(calls) == 1

    # A non-forced call immediately after a failure must not hammer again --
    # same "failed retries sooner, but not immediately" discipline
    # kalshi_odds_refresh's FAILED_RETRY_SECONDS uses.
    result = mod.run_novig_odds_refresh()
    assert result["status"] == "cached"
    assert len(calls) == 1
