"""`market_gone` rows leave the board; everything else stays.

A `market_gone` row advertises a price no book is offering. It is unbettable,
and before this it outranked rows you could actually bet.

THE TEST THAT MATTERS MOST IS THE ONE THAT PROTECTS SLOW SWEEPS, and it is first
below. The obvious version of this feature -- drop rows past some age -- deletes
most of the board. Measured on the 2026-08-30T13:56:30Z production board, 1,565
rows, classified against the live state files:

    soccer   stale= 289  sidecar=   9min   market_gone 288
    mlb      stale= 304  sidecar= 152min   as_fresh_as_sweep 304
    ncaaf    stale= 192  sidecar= 540min   as_fresh_as_sweep 192
    wnba     stale= 360  sidecar= 168min   as_fresh_as_sweep 359

**855 of 1,145 "stale" rows are AS FRESH AS THE SWEEP ITSELF.** NCAAF's sidecar
is nine HOURS old, so a nine-hour-old NCAAF row is the freshest price that
exists for it. An age rule deletes every NCAAF and WNBA row and calls it a
cleanup.

Verified against that same production payload before shipping:

    rows 1565 -> 1277   dropped 288
    mlb 400->400   ncaaf 365->365   wnba 400->400   soccer 400->112
    non-market_gone rows dropped: 0
"""
from __future__ import annotations

import pytest

import pipeline.layer2_shortlist as L
import syndicate.features.shared.odds_book_quotes as OBQ

NOW = "2026-08-30T14:00:00Z"
FRESH = "2026-08-30T13:59:00+00:00"     # seconds old
OLD = "2026-08-30T04:00:00+00:00"       # 10h old


def _row(sport="soccer", event="e1", market="totals", line="8.5", seen=7200.0):
    return {
        "sport": sport, "kind": "game", "event_id": event, "segment": "full",
        "market": market, "player_name": "", "line": line,
        "quote": {"quote_seen_age_seconds": seen},
    }


def _key(sport="soccer", event="e1", market="totals", line="8.5", book="fanduel"):
    parts = {
        "sport": sport, "kind": "game", "event_id": event, "bookmaker": book,
        "segment": "full", "market": market, "selection": "over",
        "player_name": "", "line": line,
    }
    return "|".join(parts[f] for f in L._QUOTE_KEY_ORDER)


@pytest.fixture
def state(monkeypatch):
    """Install a per-sport last_seen map the module will read."""
    store: dict[str, dict[str, str]] = {}
    monkeypatch.setattr(OBQ, "read_quote_last_seen", lambda sport, date: store.get(str(sport).lower(), {}))
    return store


# --------------------------------------------------------------------------
# THE PROTECTION. A slow sweep is not a dead market.
# --------------------------------------------------------------------------


def test_a_slow_sweep_sport_keeps_every_row(state):
    """NCAAF's sidecar was NINE HOURS old in production. Its rows are the
    freshest prices that exist and must all survive."""
    state["ncaaf"] = {_key("ncaaf", line="8.5"): OLD}      # sidecar itself is old
    rows = [_row("ncaaf", line="8.5", seen=32000.0) for _ in range(5)]
    kept = L._drop_market_gone_rows(list(rows), "2026-08-30", {})
    assert len(kept) == 5, "a slow-sweep sport lost rows -- this deletes whole boards"


def test_a_state_file_with_no_parseable_keys_drops_nothing(state, capsys):
    """A BROKEN state file is not a dead market -- and this one nearly was.

    Written expecting an `unknown_*` label. There is none: a state file whose
    keys do not parse yields an EMPTY group index, and "no sibling was seen" is
    precisely what `market_gone` means, so every row classified market_gone and
    the whole sport was dropped. The test failed, the CODE was fixed rather than
    the test, and this pins the guard: entries present but none parseable ->
    keep everything and report the reason.
    """
    state["soccer"] = {"malformed|key": FRESH, "also|bad": FRESH}
    rows = [_row(seen=9000.0) for _ in range(4)]
    kept = L._drop_market_gone_rows(list(rows), "2026-08-30", {})
    assert len(kept) == 4, "a corrupt state file emptied the board for that sport"
    assert "MARKET_GONE_DROP_SKIPPED" in capsys.readouterr().out


def test_no_state_file_keeps_everything(state):
    """Absence of a state file is not evidence a market is gone."""
    rows = [_row(seen=9000.0) for _ in range(3)]
    assert len(L._drop_market_gone_rows(list(rows), "2026-08-30", {})) == 3


def test_fresh_rows_are_never_examined(state):
    """Below the 900s threshold nothing is dropped regardless of state."""
    state["soccer"] = {_key(line="9.5"): FRESH}
    rows = [_row(line="8.5", seen=10.0)]
    assert len(L._drop_market_gone_rows(list(rows), "2026-08-30", {})) == 1


# --------------------------------------------------------------------------
# THEN the drop itself.
# --------------------------------------------------------------------------


def test_market_gone_rows_are_dropped(state):
    """Sidecar FRESH, but this row's group has not been seen -- a dead market."""
    state["soccer"] = {_key(event="other", line="1.5"): FRESH}
    rows = [_row(event="e1", line="8.5", seen=9000.0)]
    shortlist: dict = {}
    kept = L._drop_market_gone_rows(list(rows), "2026-08-30", shortlist)
    assert kept == []
    assert shortlist["rows_market_gone_dropped"] == 1
    assert shortlist["rows_market_gone_dropped_by_sport"] == {"soccer": 1}


def test_an_orphaned_line_is_kept_not_dropped(state):
    """The market is LIVE and this row's line was superseded. That is a
    different defect with a different fix, and dropping it here would hide it."""
    state["soccer"] = {_key(line="9.5"): FRESH}     # sibling line seen just now
    rows = [_row(line="8.5", seen=9000.0)]
    assert len(L._drop_market_gone_rows(list(rows), "2026-08-30", {})) == 1


def test_one_sports_dead_market_does_not_touch_another(state):
    state["soccer"] = {_key("soccer", event="other", line="1.5"): FRESH}
    state["mlb"] = {_key("mlb", line="8.5"): OLD}
    rows = [_row("soccer", seen=9000.0), _row("mlb", seen=9000.0)]
    kept = L._drop_market_gone_rows(list(rows), "2026-08-30", {})
    assert [r["sport"] for r in kept] == ["mlb"]


# --------------------------------------------------------------------------
# Operability.
# --------------------------------------------------------------------------


def test_the_drop_is_reversible_without_a_deploy(state, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DROP_MARKET_GONE_ROWS", "0")
    state["soccer"] = {_key(event="other", line="1.5"): FRESH}
    rows = [_row(seen=9000.0)]
    assert len(L._drop_market_gone_rows(list(rows), "2026-08-30", {})) == 1


def test_a_zero_is_reported_not_silent(state, capsys):
    """"ran and found none" must not look like "never ran"."""
    state["soccer"] = {_key(line="9.5"): FRESH}
    L._drop_market_gone_rows([_row(line="8.5", seen=9000.0)], "2026-08-30", {})
    assert "MARKET_GONE_DROPPED none" in capsys.readouterr().out


def test_a_failure_returns_the_rows_untouched(state, monkeypatch, capsys):
    """Serving a stale row is a smaller harm than serving an empty board."""
    def boom(*_a, **_k):
        raise RuntimeError("state store down")

    monkeypatch.setattr(L, "_index_last_seen", boom)
    state["soccer"] = {_key(event="other", line="1.5"): FRESH}
    rows = [_row(seen=9000.0)]
    assert len(L._drop_market_gone_rows(list(rows), "2026-08-30", {})) == 1
    assert "MARKET_GONE_DROP_FAILED" in capsys.readouterr().out
