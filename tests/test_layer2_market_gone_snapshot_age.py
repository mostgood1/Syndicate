"""`market_gone` judges a row's age from the SAME state-file read as the reference. `#801`.

Lane `board-market-gone-snapshot-age`, 2026-11-14. The shortlist computes a row's `quote_seen_age_seconds` when it
builds that sport's grid, early in the board build; `_drop_market_gone_rows` reads the reference from the state file at
the drop step, minutes later. An NFL pull captured 12:38:02Z landed in between: the drop step saw a reference 17 s old,
every single-line prop group still carried its ~1,500 s pre-pull grid age, and `MARKET_GONE_DROPPED nfl=454` took the
NFL board from 1,216 to 883 rows. The next build read the same pull and kept them.

The first test FAILS on the pre-change code (the re-looked rows are dropped). The rest pass on both and are the guards
that the drop still removes a market nobody re-looked at. Ages, not dates: the function reads the wall clock (see
`test_market_gone_drop.py`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import pipeline.layer2_shortlist as L
import syndicate.features.shared.odds_book_quotes as OBQ

PULL_AGE = 17.0  # the 11-14 12:38:20Z drop step's reference
GRID_AGE = 1500.0  # one NFL pregame cadence, the age the grid read gave every row


def _ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _key(event, player, line, book, selection="over", market="player_rush_yds"):
    parts = {
        "sport": "nfl", "kind": "player_prop", "event_id": event, "bookmaker": book,
        "segment": "full", "market": market, "selection": selection,
        "player_name": player, "line": line,
    }
    return "|".join(parts[f] for f in L._QUOTE_KEY_ORDER)


def _row(event, player, line, book, today, seen=GRID_AGE, market="player_rush_yds"):
    return {
        "sport": "nfl", "kind": "player_prop", "event_id": event, "segment": "full",
        "market": market, "player_name": player, "line": line, "commence_time": today,
        "quote": {"quote_seen_age_seconds": float(seen), "bookmaker": book},
    }


def _pull(events, players, age, books=("draftkings", "fanduel")):
    """One pull: every (event, player) single-line prop, both sides, at each book."""
    return {
        _key(e, p, "54.5", b, side): _ago(age)
        for e in events for p in players for b in books for side in ("over", "under")
    }


@pytest.fixture
def files(monkeypatch):
    store: dict[tuple[str, str], dict[str, str]] = {}
    monkeypatch.setattr(OBQ, "read_quote_last_seen", lambda sport, date: store.get((str(sport).lower(), str(date)), {}))
    return store


@pytest.fixture
def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


EVENTS = [f"g{i}" for i in range(12)]
PLAYERS = [f"Player {i}" for i in range(6)]


def test_a_pull_landing_mid_build_does_not_drop_the_rows_it_re_looked_at(files, today):
    """The 11-14 12:38Z shape: the pull re-stamped every row's own key 17 s ago; the grid still says 1,500 s."""
    files[("nfl", today)] = _pull(EVENTS, PLAYERS, PULL_AGE)
    rows = [_row(e, p, "54.5", "draftkings", today) for e in EVENTS for p in PLAYERS]
    shortlist: dict = {}
    kept = L._drop_market_gone_rows(list(rows), today, shortlist)
    assert len(kept) == len(rows), (
        f"{len(rows) - len(kept)} of {len(rows)} rows the judging file had just re-looked at were dropped as market_gone"
    )
    assert shortlist["rows_market_gone_dropped"] == 0
    # The branch ran, and it is the branch that kept them: every row would have been dropped on its grid age.
    assert shortlist["rows_market_gone_relooked_kept_by_sport"] == {"nfl": len(rows)}


def test_a_row_the_pull_did_not_re_look_at_is_still_dropped(files, today):
    """The drop still works: a market absent from a pull that demonstrably covered the slate."""
    state = _pull(EVENTS, PLAYERS, PULL_AGE)
    state.update(_pull(["dead"], ["Gone Player"], GRID_AGE))
    files[("nfl", today)] = state
    rows = [_row("dead", "Gone Player", "54.5", "draftkings", today)]
    shortlist: dict = {}
    assert L._drop_market_gone_rows(list(rows), today, shortlist) == []
    assert shortlist["rows_market_gone_relooked_kept_by_sport"] == {}


def test_another_book_still_quoting_the_line_does_not_rescue_the_row(files, today):
    """Keyed by the row's OWN book: fanduel re-looked, the row's draftkings price was not."""
    state = _pull(EVENTS, PLAYERS, PULL_AGE)
    state.update(_pull(["g0"], ["Stale Book"], PULL_AGE, books=("fanduel",)))
    state.update(_pull(["g0"], ["Stale Book"], GRID_AGE, books=("draftkings",)))
    files[("nfl", today)] = state
    rows = [_row("g0", "Stale Book", "54.5", "draftkings", today)]
    assert L._drop_market_gone_rows(list(rows), today, {}) == []


def test_a_row_with_no_book_keeps_the_old_rule(files, today):
    """No `quote.bookmaker` means no own key to look up: judged on the grid age exactly as before."""
    files[("nfl", today)] = _pull(EVENTS, PLAYERS, PULL_AGE)
    row = _row("g0", "Player 0", "54.5", "draftkings", today)
    row["quote"].pop("bookmaker")
    assert L._drop_market_gone_rows([row], today, {}) == []


def test_an_old_re_look_is_judged_on_its_own_age(files, today):
    """Re-looked 1,000 s ago against a pull 17 s ago: still older than the sweep by far, so still gone."""
    state = _pull(EVENTS, PLAYERS, PULL_AGE)
    state.update(_pull(["g0"], ["Old Look"], 1000.0))
    files[("nfl", today)] = state
    rows = [_row("g0", "Old Look", "54.5", "draftkings", today, seen=1400.0)]
    assert L._drop_market_gone_rows(list(rows), today, {}) == []


def test_a_night_game_is_judged_by_the_central_date_file_its_quotes_are_filed_in(files):
    """SNF commences 01:20Z on the 16th -- 7:20 PM CST on the 15th, the file the writer files it in. The UTC-date file
    (16th) exists and does not hold the group; it used to be the only kickoff file asked."""
    snf = {**_row("snf", "Mike Gesicki", "2.5", "pinnacle", ""), "commence_time": "2026-11-16T01:20:00Z"}
    snf["market"] = "Receptions"
    files[("nfl", "2026-11-15")] = {
        **_pull(EVENTS, PLAYERS, PULL_AGE),
        **{_key("snf", "Mike Gesicki", "2.5", "pinnacle", side, market="Receptions"): _ago(PULL_AGE) for side in ("over", "under")},
    }
    files[("nfl", "2026-11-16")] = _pull(["mnf"], PLAYERS, PULL_AGE)
    files[("nfl", "2026-11-14")] = _pull(["sat"], PLAYERS, PULL_AGE)
    assert L._row_kickoff_shard_date(snf) == "2026-11-15"
    assert len(L._drop_market_gone_rows([snf], "2026-11-14", {})) == 1, (
        "a night game's re-looked prop was judged by the UTC-date file, which never held it"
    )


def test_the_instrument_line_is_printed_and_is_not_the_dropped_line(files, today, capsys):
    files[("nfl", today)] = _pull(EVENTS, PLAYERS, PULL_AGE)
    rows = [_row(e, p, "54.5", "draftkings", today) for e in EVENTS for p in PLAYERS]
    L._drop_market_gone_rows(list(rows), today, {})
    out = capsys.readouterr().out
    assert f"MARKET_GONE_RELOOKED_KEPT nfl={len(rows)} total={len(rows)} of {len(rows)}" in out
    assert f"MARKET_GONE_DROPPED none of {len(rows)}" in out


def test_the_stale_row_diagnostic_agrees_with_the_drop(files, today, capsys):
    """`STALE_ROW_CAUSE` must not call a row the drop kept on the same read `market_gone`."""
    files[("nfl", today)] = _pull(EVENTS, PLAYERS, PULL_AGE)
    rows = [_row(e, p, "54.5", "draftkings", today) for e in EVENTS for p in PLAYERS]
    L._report_stale_row_causes(rows, today)
    line = [ln for ln in capsys.readouterr().out.splitlines() if "STALE_ROW_CAUSE" in ln][0]
    assert "market_gone" not in line, line
    assert f"as_fresh_as_sweep={len(rows)}" in line, line
