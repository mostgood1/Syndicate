"""The Polymarket slate writer must tick, and a stale slate must not buy.

MEASURED 2026-08-25 on live-odds-worker:

  POLYMARKET_US_SLATE_WRITE  22:33:57Z  instance c2727
  POLYMARKET_US_SLATE_WRITE  00:13:15Z  instance fjc9x   <- 99 minutes later
  POLYMARKET_US_SLATE_WRITE  00:21:05Z  instance j6p7s

99 minutes on a 900s cadence should be about six writes. It was one, and every
write in the record came from a DIFFERENT instance -- i.e. every write was a
fresh-boot write, because `_POLYMARKET_SLATE_LAST_RUN` is per-process and
resets to 0.0 on restart.

`_polymarket_us_slate_refresh_tick()` was called once at boot, BEFORE the
`while` loop. The interval gate inside it was never wrong; it simply never got
a second chance, so the artifact aged with the worker's uptime. It survived
review because writes DO appear in the log with plausible-looking gaps -- it
reads as a cadence.

This matters because it is a MONEY PATH: `_polymarket_resolve_market` prices
real orders off that artifact and, by its own docstring, logged staleness
rather than bounding it. Kalshi is unaffected on both counts -- its writer is
called from the board build inside a loop, and `_kalshi_price_for` reads the
venue's live ask at submit time rather than the artifact.
"""

from __future__ import annotations

import time

import pytest

from pipeline import execute_portfolio


# ---------------------------------------------------------------------------
# The writer is in the loop, not only at boot.
# ---------------------------------------------------------------------------


def test_the_slate_writer_is_called_INSIDE_the_loop_not_only_at_boot():
    """A boot-only writer lets the artifact age with the worker's uptime.

    Read from the source rather than by running the loop: the loop is a
    long-lived process with network calls in it, and the fact under test is
    purely WHERE the call sits.
    """
    import inspect

    import scripts.run_live_odds_refresh_worker as worker

    source = inspect.getsource(worker.main)
    before_loop, _, inside_loop = source.partition("while not _LIVE_REFRESH_LOOP_STOP.is_set():")

    assert inside_loop, "could not locate the worker's main loop in main()"
    assert "_polymarket_us_slate_refresh_tick()" in inside_loop, (
        "the slate writer is not called inside the loop, so the artifact only "
        "refreshes when the worker restarts -- the 99-minute gap measured "
        "2026-08-25"
    )


def test_the_slate_writer_runs_BEFORE_the_execution_tick():
    """An order placed on a pass should use the freshest slate that pass can get."""
    import inspect

    import scripts.run_live_odds_refresh_worker as worker

    source = inspect.getsource(worker.main)
    _, _, inside_loop = source.partition("while not _LIVE_REFRESH_LOOP_STOP.is_set():")

    slate_at = inside_loop.find("_polymarket_us_slate_refresh_tick()")
    execution_at = inside_loop.find("_run_execution_tick()")

    assert slate_at != -1 and execution_at != -1
    assert slate_at < execution_at, (
        "the execution tick runs before the slate refresh, so an order is "
        "priced from the PREVIOUS pass's slate"
    )


# ---------------------------------------------------------------------------
# A stale slate refuses rather than pricing an order.
# ---------------------------------------------------------------------------


class _Request:
    venue_ticker = "aec-mlb-pit-sd-2026-08-24"
    home_team = "San Diego Padres"
    away_team = "Pittsburgh Pirates"
    sport = "mlb"
    side = "home"


def _payload(fetched_at):
    return {
        "fetched_at": fetched_at,
        "markets": [
            {
                "slug": _Request.venue_ticker,
                "orderable": True,
                "outcomes": '["San Diego Padres","Pittsburgh Pirates"]',
                "outcomePrices": '["0.55","0.45"]',
                "orderPriceMinTickSize": 0.01,
                "minimumTradeQty": 1,
            }
        ],
    }


@pytest.fixture
def _artifact(monkeypatch):
    holder = {}

    def read_json_file(_path):
        return holder.get("payload")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", read_json_file
    )
    return holder


def test_a_slate_older_than_the_ceiling_REFUSES(_artifact, monkeypatch):
    monkeypatch.delenv("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS", raising=False)
    _artifact["payload"] = _payload(time.time() - 5311.0)  # the measured age

    assert execute_portfolio._polymarket_resolve_market(_Request()) is None


def test_a_slate_with_NO_fetched_at_refuses_too(_artifact, monkeypatch):
    """"We cannot tell how old this is" must not share an outcome with "fresh"."""
    monkeypatch.delenv("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS", raising=False)
    _artifact["payload"] = _payload(None)

    assert execute_portfolio._polymarket_resolve_market(_Request()) is None


def test_a_fresh_slate_still_RESOLVES(_artifact, monkeypatch):
    """The guard must not refuse a healthy slate -- otherwise it is a kill switch."""
    monkeypatch.delenv("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS", raising=False)
    _artifact["payload"] = _payload(time.time() - 60.0)

    resolved = execute_portfolio._polymarket_resolve_market(_Request())

    assert resolved is not None, "a 60s-old slate was refused"
    slug, price, tick, min_qty, outcome_index = resolved
    assert slug == _Request.venue_ticker
    assert price == pytest.approx(0.55)
    # Tick size and minimum quantity come FROM THE MARKET, never inferred.
    assert tick == 0.01
    assert min_qty == 1
    # The index that names WHICH outcome the price belongs to, carried through
    # to `order_body` so the side cannot contradict it.
    assert outcome_index == 0


# ---------------------------------------------------------------------------
# The ceiling itself.
# ---------------------------------------------------------------------------


def test_the_default_ceiling_is_TWICE_the_writer_cadence(monkeypatch):
    """Tolerates one missed write; does not tolerate a stopped writer."""
    monkeypatch.delenv("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS", raising=False)
    assert execute_portfolio._polymarket_max_price_age_seconds() == 1800.0


@pytest.mark.parametrize("raw", ["0", "-1", "", "not-a-number"])
def test_a_nonsense_ceiling_falls_back_rather_than_refusing_forever(monkeypatch, raw):
    """A non-positive cap is a typo, not an instruction to trade nothing."""
    monkeypatch.setenv("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS", raw)
    assert execute_portfolio._polymarket_max_price_age_seconds() == 1800.0


def test_the_ceiling_is_configurable(monkeypatch):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS", "600")
    assert execute_portfolio._polymarket_max_price_age_seconds() == 600.0


# ---------------------------------------------------------------------------
# Kalshi, which the user asked about, is affected by neither.
# ---------------------------------------------------------------------------


def test_kalshi_prices_an_order_from_a_LIVE_read_not_the_artifact():
    """Why the staleness guard is a Polymarket-only need.

    `_kalshi_price_for` reads the venue's current ask at submit time and falls
    back to the artifact only when that read fails. Polymarket deliberately
    reads the artifact instead -- a second independent venue caller is a
    documented incident class here -- which is why only it needed bounding.
    """
    import inspect

    source = inspect.getsource(execute_portfolio._kalshi_price_for)

    assert "fetch_market" in source, (
        "Kalshi no longer reads a live price at submit time; if that is "
        "deliberate it now needs the same staleness ceiling Polymarket has"
    )
