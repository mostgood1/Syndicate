"""`market_gone` is judged against the last LARGE pass, not the newest stamp.

Lane `soccer-board-tomorrow-shortlist-collapse`, 2026-09-16. Captures are partial:
soccer is swept per league on different cadences, MLB runs small prop passes
between full ones. Against the file's single newest stamp, every row outside the
most recent partial pass read as older than "the sweep" and was dropped as
`market_gone` -- served soccer 1,089 -> 186, flapping build to build, and MLB
(1,098 / 5) the same way.

The first three tests FAIL on the pre-change code (the rows are dropped); the
last three pass on both, and they are the guards that the drop still works.
Ages, not dates: the function reads the wall clock (see `test_market_gone_drop.py`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import pipeline.layer2_shortlist as L
import syndicate.features.shared.odds_book_quotes as OBQ


def _ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _key(sport, event, market, line, book="fanduel", kind="game", player=""):
    parts = {
        "sport": sport, "kind": kind, "event_id": event, "bookmaker": book,
        "segment": "full", "market": market, "selection": "over",
        "player_name": player, "line": line,
    }
    return "|".join(parts[f] for f in L._QUOTE_KEY_ORDER)


def _row(sport, event, market, line, seen, commence="", kind="game", player=""):
    return {
        "sport": sport, "kind": kind, "event_id": event, "segment": "full",
        "market": market, "player_name": player, "line": line,
        "commence_time": commence,
        "quote": {"quote_seen_age_seconds": float(seen)},
    }


@pytest.fixture
def files(monkeypatch):
    """`{(sport, date): {key: stamp}}`, read by date the way production reads it."""
    store: dict[tuple[str, str], dict[str, str]] = {}
    monkeypatch.setattr(OBQ, "read_quote_last_seen", lambda sport, date: store.get((str(sport).lower(), str(date)), {}))
    return store


def _full_pass(sport, events, market, age, lines=("8.5", "9.5", "10.5"), books=("fanduel", "draftkings")):
    return {_key(sport, e, market, ln, b): _ago(age) for e in events for ln in lines for b in books}


def test_a_partial_league_pass_does_not_delete_the_other_leagues(files):
    """The soccer shape: 30 fixtures swept an hour ago, 2 La Liga fixtures just now."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _full_pass("soccer", [f"epl{i}" for i in range(30)], "totals", 3600)
    state.update(_full_pass("soccer", ["laliga1", "laliga2"], "totals", 60))
    files[("soccer", today)] = state
    rows = [_row("soccer", f"epl{i}", "totals", "9.5", 3600, commence=today) for i in range(30)]
    kept = L._drop_market_gone_rows(list(rows), today, {})
    assert len(kept) == 30, "a La Liga-only pass made every other league's live market read as gone"


def test_a_partial_prop_pass_does_not_delete_the_full_pass(files):
    """The MLB shape: a full pass 40 min ago, a small prop pass 5 min ago."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    events = [f"g{i}" for i in range(15)]
    state = {}
    for market in ("batter_total_bases", "batter_hits", "batter_rbis"):
        for e in events:
            for player in ("a", "b", "c"):
                for ln in ("0.5", "1.5"):
                    state[_key("mlb", e, market, ln, kind="prop", player=player)] = _ago(2400)
    for e in events[:3]:  # the partial pass: one market, three games
        state[_key("mlb", e, "strikeouts", "5.5", kind="prop", player="p")] = _ago(300)
    files[("mlb", today)] = state
    rows = [_row("mlb", e, "batter_total_bases", "1.5", 2400, commence=today, kind="prop", player="a") for e in events]
    kept = L._drop_market_gone_rows(list(rows), today, {})
    assert len(kept) == 15, "a partial prop pass made the full pass's live props read as gone"


def test_a_later_fixture_is_judged_in_its_own_commence_date_file(files):
    """Game markets are FILED BY COMMENCE DATE. The shortlist date's file holds a
    fresh large pass for today's games and no key for the weekend fixture."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    weekend = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    files[("soccer", today)] = _full_pass("soccer", [f"t{i}" for i in range(20)], "h2h", 120, lines=("",))
    files[("soccer", weekend)] = _full_pass("soccer", [f"w{i}" for i in range(20)], "h2h", 3000, lines=("",))
    rows = [_row("soccer", "w3", "h2h", "", 3000, commence=f"{weekend}T15:00:00Z")]
    kept = L._drop_market_gone_rows(list(rows), today, {})
    assert len(kept) == 1, "a weekend row was judged against today's file, where its group does not exist"


def test_a_market_missing_from_the_large_pass_is_still_dropped(files):
    """The drop must keep working: the large pass ran 10 min ago and this group
    was last seen three hours ago."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _full_pass("soccer", [f"e{i}" for i in range(30)], "totals", 600)
    state[_key("soccer", "dead", "totals", "9.5")] = _ago(3 * 3600)
    files[("soccer", today)] = state
    shortlist: dict = {}
    kept = L._drop_market_gone_rows([_row("soccer", "dead", "totals", "9.5", 3 * 3600, commence=today)], today, shortlist)
    assert kept == []
    assert shortlist["rows_market_gone_dropped_by_sport"] == {"soccer": 1}


def test_a_sidecar_with_nothing_recent_still_protects_its_rows(files):
    """Nothing inside the 14 h ceiling: the reference falls back to the newest
    stamp, which is the old slow-sweep protection."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    files[("ncaaf", today)] = _full_pass("ncaaf", ["n1", "n2"], "totals", 20 * 3600)
    rows = [_row("ncaaf", "n1", "totals", "9.5", 20 * 3600, commence=today)]
    assert len(L._drop_market_gone_rows(list(rows), today, {})) == 1


def test_the_reference_line_shows_the_branch_ran(files, capsys):
    """Production proof that the new reference is in use, not just deployed:
    `reference_age_s` above `newest_age_s` when a partial pass is newest."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _full_pass("soccer", [f"epl{i}" for i in range(30)], "totals", 3600)
    state.update(_full_pass("soccer", ["laliga1"], "totals", 60))
    files[("soccer", today)] = state
    L._drop_market_gone_rows([_row("soccer", "epl1", "totals", "9.5", 3600, commence=today)], today, {})
    line = next(l for l in capsys.readouterr().out.splitlines() if "MARKET_GONE_REFERENCE" in l)
    fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
    assert fields["sport"] == "soccer" and fields["date"] == today
    assert int(fields["newest_age_s"]) < 120 <= 3000 < int(fields["reference_age_s"])
