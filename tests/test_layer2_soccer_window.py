"""`#379` -- Layer 2 asked soccer for a date soccer does not store by.

MEASURED LIVE 2026-08-12, two current readings that contradicted each other:

    Layer 2   soccer  quote_rows: 0, grid_rows: 0, opportunities: 0
    Layer 1   soccer  3,298 rows, 60-minute seen-age, 58 games

Soccer shards by KICKOFF date, not capture date. Today's captures land in
`2026-08-15.jsonl` (3.4 MB) and `2026-08-16.jsonl` (4.2 MB), while
`2026-08-12.jsonl` does not exist at all -- almost nothing kicks off today. So
`read_book_quotes("soccer", selected_date)` returned nothing, and would return
nothing on ANY day, not merely quiet ones. Soccer could never reach Layer 2.

Layer 1 has scoped by `resolve_window_dates` since `#329`. Layer 2 never did.
Reusing that resolver rather than writing a second one is deliberate: two
independent notions of "which dates is this sport's board" would drift, and the
drift would show up as a sport silently missing from one surface.

MEMORY, measured before shipping because this turns one read into seven and the
module's own docstring warns a shard costs ~6.3x file size resident:

    soccer, whole 7-day window   8.8 MB  (~56 MB resident)
    mlb,    single shard        16.0 MB  (~101 MB resident)

The widened soccer read is CHEAPER than the single MLB read that already runs
beside it. `#241` is the standing reason to check rather than assume.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.layer1_board import resolve_window_dates


# `#435` RENAMED THE FUNCTION THESE TESTS PATCH, AND THEY WENT ON PASSING.
#
# Production reads quotes through `read_book_quotes_latest`
# (`pipeline/layer2_shortlist.py:176`) and has since `#435`. These tests patched
# `read_book_quotes` -- which still exists, so nothing errored; the patch simply
# bound to a function nobody calls. `asked` stayed empty and the two tests that
# assert on it failed, while `test_a_zero_records_which_dates_were_asked` kept
# PASSING VACUOUSLY: it asserts `quote_rows == 0`, which is trivially true when
# the read is never intercepted at all.
#
# `raising=False` is what made it silent. It was there so the patch would tolerate
# the attribute being absent -- but "tolerate absent" and "silently bind to
# nothing after a rename" are the same behaviour, and the second is exactly the
# failure this file exists to catch. These now patch with `raising=True` (the
# default): if the production name moves again, the patch RAISES here instead of
# quietly measuring nothing.
#
# The import in `layer2_shortlist` is inside the function body, so setting the
# attribute on the module is what production actually resolves at call time.
_QUOTE_READER = "read_book_quotes_latest"


def test_the_patched_name_is_the_one_production_calls():
    """The guard that would have caught `#435` the day it landed.

    Asserting the two names agree is cheap and is the only thing standing between
    a rename and three tests that measure nothing. Reads the source rather than
    the attribute because the import is function-local.
    """
    import inspect

    import pipeline.layer2_shortlist as mod
    import syndicate.features.shared.odds_book_quotes as quotes

    assert hasattr(quotes, _QUOTE_READER), f"{_QUOTE_READER} no longer exists on odds_book_quotes"
    source = inspect.getsource(mod.build_layer2_shortlist)
    assert f"{_QUOTE_READER}(" in source, (
        f"layer2_shortlist no longer calls {_QUOTE_READER} -- the monkeypatches in "
        "this file are now measuring a function production does not use. Update "
        "_QUOTE_READER to whatever it calls now."
    )


def test_soccer_resolves_a_multi_day_window():
    dates = resolve_window_dates("soccer", "2026-08-12", window="slate")
    assert len(dates) == 7, dates
    assert dates[0] == "2026-08-12"
    # The dates that actually held the live shards on the day this was fixed.
    assert "2026-08-15" in dates and "2026-08-16" in dates


def test_single_date_sports_are_unaffected():
    # The change must be a no-op for sports that already worked -- a widened
    # read for MLB would be pure cost against the largest shard in the system.
    for sport in ("mlb", "nba", "wnba", "nhl", "ncaab"):
        dates = resolve_window_dates(sport, "2026-08-12", window="slate")
        assert dates == ["2026-08-12"], f"{sport} widened unexpectedly: {dates}"


def test_multi_day_sports_match_their_layer1_windows():
    # NFL and NCAAF fixtures also span days; they get the same treatment for the
    # same reason, and their windows must not diverge from Layer 1's.
    #
    # NFL is SEVEN since 2026-08-16 (was five). This is the THIRD file asserting
    # that width -- the others are `test_layer1_board` and
    # `test_layer2_sport_horizon` -- and all three read it from the same
    # `slate_window_days` table, which is the thing that keeps the two boards
    # from diverging. Three literal 5s were the cost of that guarantee.
    assert len(resolve_window_dates("nfl", "2026-08-12", window="slate")) == 7
    assert len(resolve_window_dates("ncaaf", "2026-08-12", window="slate")) == 3


def test_the_shortlist_reads_every_window_date(monkeypatch):
    """The behaviour: one read per window date, all rows concatenated."""
    import pipeline.layer2_shortlist as mod
    import syndicate.features.shared.odds_book_quotes as quotes

    asked: list[str] = []

    def _fake_read(sport, date_str):
        asked.append(str(date_str))
        # Only the kickoff-dated shards hold anything, exactly as measured.
        if str(date_str) in {"2026-08-15", "2026-08-16"}:
            return [{"sport": sport, "date": date_str}]
        return []

    monkeypatch.setattr(quotes, _QUOTE_READER, _fake_read)
    monkeypatch.setattr(quotes, "read_quote_last_seen", lambda *a, **k: {})

    # Never raises by contract, so a failure downstream cannot mask the read.
    result = mod.build_layer2_shortlist("2026-08-12", ["soccer"])
    assert asked == [
        "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15",
        "2026-08-16", "2026-08-17", "2026-08-18",
    ], asked
    stats = (result.get("per_sport_ingest") or {}).get("soccer") or {}
    assert stats.get("window_dates"), "the window must be recorded, so a zero is attributable"


def test_a_zero_records_which_dates_were_asked(monkeypatch):
    # "Zero against one date" and "zero against seven" are different facts, and
    # the old payload could not tell them apart.
    import pipeline.layer2_shortlist as mod
    import syndicate.features.shared.odds_book_quotes as quotes

    monkeypatch.setattr(quotes, _QUOTE_READER, lambda *a, **k: [])
    monkeypatch.setattr(quotes, "read_quote_last_seen", lambda *a, **k: {})
    result = mod.build_layer2_shortlist("2026-08-12", ["soccer"])
    stats = (result.get("per_sport_ingest") or {}).get("soccer") or {}
    assert stats.get("quote_rows") == 0
    assert len(stats.get("window_dates") or []) == 7


def test_one_unreadable_date_does_not_lose_the_others(monkeypatch):
    # A missing shard mid-window is normal (08-12/08-13/08-18 were absent on the
    # measured day). It must skip, never abort the sport.
    import pipeline.layer2_shortlist as mod
    import syndicate.features.shared.odds_book_quotes as quotes

    def _flaky(sport, date_str):
        if str(date_str) == "2026-08-14":
            raise OSError("shard vanished mid-read")
        return [{"sport": sport, "date": date_str}] if str(date_str) == "2026-08-15" else []

    monkeypatch.setattr(quotes, _QUOTE_READER, _flaky)
    monkeypatch.setattr(quotes, "read_quote_last_seen", lambda *a, **k: {})
    result = mod.build_layer2_shortlist("2026-08-12", ["soccer"])
    stats = (result.get("per_sport_ingest") or {}).get("soccer") or {}
    assert stats.get("quote_rows", 0) > 0, "a mid-window read error swallowed the whole sport"
