"""The Polymarket catalogue pull, and the properties that keep it honest.

This module's OUTPUT is its point: the sample lines are what a join will be
written from. Kalshi's join was guessed twice and wrong twice — "Will the X win
by over N runs?" against an actual "Texas wins by over 3.5 runs?", and
`close_time` against a game date encoded in the event ticker. So the tests here
are mostly about the log being trustworthy and the artifact never lying.
"""

from __future__ import annotations

import pytest

from pipeline import polymarket_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    for name in (
        "SYNDICATE_POLYMARKET_ODDS_ENABLED",
        "SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS",
        "SYNDICATE_POLYMARKET_SAMPLE_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _market(**kw):
    """A Gamma row as `normalize_market` leaves it — camelCase, verbatim."""
    row = {
        "id": "1", "question": "Yankees vs. Red Sox — will the Yankees win?",
        "outcomes": ["Yes", "No"], "outcomePrices": ["0.58", "0.42"],
        "clobTokenIds": ["111", "222"], "endDate": "2026-08-25T23:00:00Z",
        "enableOrderBook": True, "liquidity": "12000", "missing_fields": [],
    }
    row.update(kw)
    return row


def _fetch(markets, **extra):
    payload = {"markets": markets, "count": len(markets), "pages": 1,
               "truncated": False, "missing_fields": {}, "decode_errors": 0}
    payload.update(extra)
    return lambda **_kw: payload


# --------------------------------------------------------------------------
# Reachability: off must differ from on
# --------------------------------------------------------------------------


def test_it_is_on_by_default():
    """Read-only price data, no credential, nothing tradeable — the same
    reasoning `kalshi_odds_enabled` uses. There is nothing here to arm."""
    assert mod.polymarket_odds_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_it_can_be_turned_off_without_a_deploy(value, monkeypatch):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_ODDS_ENABLED", value)
    assert mod.polymarket_odds_enabled() is False
    assert mod.run_polymarket_odds_refresh()["reason"] == "disabled"


def test_disabled_writes_no_artifact(monkeypatch):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_ODDS_ENABLED", "off")
    mod.run_polymarket_odds_refresh()
    assert not mod.markets_artifact_path().exists()


# --------------------------------------------------------------------------
# A typo must not become an unpaced loop against an anonymous quota
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "   ", "nonsense", "-5", None])
def test_a_bad_interval_falls_back_rather_than_to_zero(value, monkeypatch):
    """`int("")` raising into a bare except returning 0 would turn a typo into
    an unpaced loop. Kalshi's refresh documents this gate; the trap is the
    same here and worse, because these reads are unauthenticated."""
    if value is None:
        monkeypatch.delenv("SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS", value)
    assert mod.refresh_interval_seconds() == mod.DEFAULT_REFRESH_INTERVAL_SECONDS


def test_a_sample_size_of_zero_is_a_typo_not_an_instruction(monkeypatch):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_SAMPLE_SIZE", "0")
    assert mod.sample_size() == mod.DEFAULT_SAMPLE_SIZE


# --------------------------------------------------------------------------
# The sample line is the deliverable, so it must not print None
# --------------------------------------------------------------------------


def test_the_sample_prints_the_fields_gamma_actually_returns(monkeypatch, capsys):
    """`normalize_market` keeps Gamma's camelCase verbatim — `outcomePrices`,
    `clobTokenIds`, `endDate`. This was first written against snake_case
    guesses, which would have printed `None` on every line of the one output
    this module exists to produce, while looking like it worked."""
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets",
        _fetch([_market()]),
    )
    mod.run_polymarket_odds_refresh()
    out = capsys.readouterr().out

    assert "QUESTION" in out
    assert "0.58" in out, "outcomePrices did not reach the log"
    assert "2026-08-25" in out, "endDate did not reach the log"
    assert "111" in out, "clobTokenIds did not reach the log"
    assert "None" not in out.split("QUESTION")[1].split("\n")[0]


def test_sporting_markets_are_preferred_in_the_sample(monkeypatch, capsys):
    """A sports board can only ever join to sporting questions. The classifier
    is crude on purpose and is NOT a filter — a market it misses is still
    fetched and persisted, it just does not crowd the sample."""
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets",
        _fetch([
            _market(id="p", question="Will the Fed cut rates in September?"),
            _market(id="s", question="Yankees vs. Red Sox — will the Yankees win?"),
        ]),
    )
    result = mod.run_polymarket_odds_refresh()
    out = capsys.readouterr().out

    assert result["count"] == 2, "both markets must be kept"
    assert result["sporting"] == 1
    assert "Yankees" in out
    assert "Fed cut rates" not in out


def test_a_catalogue_with_no_sporting_markets_still_samples(monkeypatch, capsys):
    """Falling through to the unfiltered list matters: if the classifier is
    wrong about this venue, an empty sample would look like an empty
    catalogue, and the one output that could correct the classifier would be
    the thing it suppressed."""
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets",
        _fetch([_market(question="Will the Fed cut rates in September?")]),
    )
    mod.run_polymarket_odds_refresh()
    assert "Fed cut rates" in capsys.readouterr().out


def test_truncation_is_reported_loudly(monkeypatch, capsys):
    """`fetch_markets` stops at `max_pages`. A truncated catalogue read as the
    whole one is how a market we could have traded becomes invisible."""
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets",
        _fetch([_market()], truncated=True, pages=20),
    )
    result = mod.run_polymarket_odds_refresh()
    assert result["truncated"] is True
    assert "truncated=True" in capsys.readouterr().out


def test_an_empty_catalogue_says_so(monkeypatch, capsys):
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets", _fetch([])
    )
    mod.run_polymarket_odds_refresh()
    assert "EMPTY" in capsys.readouterr().out


# --------------------------------------------------------------------------
# A failed fetch must never look like an empty venue
# --------------------------------------------------------------------------


def test_a_failed_fetch_keeps_the_previous_catalogue(monkeypatch, capsys):
    """Clearing the artifact on a failure turns "we could not reach
    Polymarket" into "Polymarket lists nothing" — the absence/failure
    confusion this whole layer exists to keep apart."""
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets",
        _fetch([_market(), _market(id="2")]),
    )
    assert mod.run_polymarket_odds_refresh()["count"] == 2

    def boom(**_kw):
        from syndicate.features.shared.polymarket_client import PolymarketError

        raise PolymarketError("connect_rejected: 403")

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets", boom
    )
    monkeypatch.setenv("SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS", "0")
    result = mod.run_polymarket_odds_refresh()

    assert result["status"] == "error"
    assert result["kept"] == 2, "the previous catalogue must survive"
    assert "FETCH_FAILED" in capsys.readouterr().out

    from syndicate.features.shared.refresh_state_store import read_json_file

    assert len(read_json_file(mod.markets_artifact_path())["markets"]) == 2


def test_an_unexpected_exception_is_named_not_raised(monkeypatch):
    """This runs inside the refresh loop. A venue being unreachable must not
    take the loop down with it."""
    def boom(**_kw):
        raise RuntimeError("something else entirely")

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets", boom
    )
    result = mod.run_polymarket_odds_refresh()
    assert result["status"] == "error"
    assert "RuntimeError" in result["reason"]


# --------------------------------------------------------------------------
# Cadence
# --------------------------------------------------------------------------


def test_a_fresh_catalogue_is_not_refetched(monkeypatch):
    calls = []

    def counting(**_kw):
        calls.append(1)
        return {"markets": [_market()], "count": 1, "pages": 1,
                "truncated": False, "missing_fields": {}, "decode_errors": 0}

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets", counting
    )
    assert mod.run_polymarket_odds_refresh()["status"] == "ok"
    assert mod.run_polymarket_odds_refresh()["status"] == "cached"
    assert len(calls) == 1


def test_force_overrides_the_interval(monkeypatch):
    calls = []

    def counting(**_kw):
        calls.append(1)
        return {"markets": [_market()], "count": 1, "pages": 1,
                "truncated": False, "missing_fields": {}, "decode_errors": 0}

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_client.fetch_markets", counting
    )
    mod.run_polymarket_odds_refresh()
    assert mod.run_polymarket_odds_refresh(force=True)["status"] == "ok"
    assert len(calls) == 2


def test_the_artifact_path_carries_no_date_token():
    """A date-tokened path takes the keyvalue store's 10-day TTL. The
    catalogue must survive a quiet week rather than expire into an empty read
    that looks like "no markets" — the same choice `kalshi_markets.json` makes."""
    assert mod.markets_artifact_path().name == "polymarket_markets.json"
