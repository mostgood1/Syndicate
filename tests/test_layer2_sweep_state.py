"""#296 -- a sport with no quotes must say WHY, not vanish.

The L2-A board is quote-driven. The board it replaces is card/schedule-driven,
so it can render a sport with 15 games and empty markets; L2-A renders nothing
at all, and "not swept yet" becomes indistinguishable from "broken".

Measured on production 2026-08-09 at 02:58Z: MLB had 15 scheduled games and no
quote log whatsoever (HTTP 404), because MLB capture for a date begins ~06:43Z
-- the first `captured_at` in the 08-08 log. So for roughly six hours a night
the biggest sport is absent from the board with no marker.

The schedule is known hours before the odds are, which is what makes the two
states separable: scheduled games > 0 with zero quotes is PENDING; zero of both
is NO_SLATE.
"""
from __future__ import annotations

import pytest

import pipeline.layer2_shortlist as shortlist


@pytest.fixture
def no_quotes(monkeypatch):
    """A sport whose sweep has not run: no quote rows at all.

    **PATCHES THE FUNCTION THE CODE ACTUALLY CALLS.** This patched
    `read_book_quotes` while `layer2_shortlist.py:100` calls
    `read_book_quotes_latest`, so `raising=False` swallowed the mismatch and the
    fixture was INERT -- the build read the real disk. These three tests
    therefore passed or failed on whether the machine happened to have local
    quote data, not on the code: measured 2026-08-16, a fresh checkout returns 0
    rows for 2026-08-09 and they pass, while this repo's working tree returns
    **36,424** and they fail. A green run was evidence about the checkout.

    `raising=False` is kept for the module-attribute form but the name is now
    correct, so a future rename fails loudly here instead of silently reverting
    the fixture to a no-op.
    """
    monkeypatch.setattr(
        "syndicate.features.shared.odds_book_quotes.read_book_quotes_latest",
        lambda sport, date_str: [],
        raising=False,
    )
    # The importing module binds the name locally (`from ... import
    # read_book_quotes_latest` inside the function body), so patch there too --
    # patching only the source module is the other half of the same trap.
    monkeypatch.setattr(
        "pipeline.layer2_shortlist.read_book_quotes_latest",
        lambda sport, date_str: [],
        raising=False,
    )


def _stats(out, sport="mlb"):
    return (out.get("per_sport_ingest") or {}).get(sport) or {}


def test_scheduled_games_with_no_quotes_reads_pending(monkeypatch, no_quotes):
    monkeypatch.setattr(
        "syndicate.features.shared.board_enrichment.attach_game_state",
        lambda grid, *, sport, selected_date: {"chips": 15, "rows_matched": 0},
        raising=False,
    )
    stats = _stats(shortlist.build_layer2_shortlist("2026-08-09", ["mlb"]))

    assert stats.get("sweep_state") == "pending", (
        "15 scheduled games and zero quotes is the pre-sweep window, not an "
        "empty slate -- the board must be able to say 'not swept yet'"
    )
    assert stats.get("scheduled_games") == 15
    assert stats.get("quote_rows") == 0


def test_no_games_and_no_quotes_reads_no_slate(monkeypatch, no_quotes):
    monkeypatch.setattr(
        "syndicate.features.shared.board_enrichment.attach_game_state",
        lambda grid, *, sport, selected_date: {"chips": 0, "rows_matched": 0},
        raising=False,
    )
    stats = _stats(shortlist.build_layer2_shortlist("2026-08-09", ["mlb"]))

    assert stats.get("sweep_state") == "no_slate", (
        "an out-of-season sport is legitimately empty and must NOT be reported "
        "as pending, or the marker cries wolf every night"
    )
    assert stats.get("scheduled_games") == 0


def test_chip_lookup_failure_does_not_break_the_build(monkeypatch, no_quotes):
    """The chip count is an instrument. An instrument that can take down the
    board is worse than no instrument -- the same rule applied to the
    seen-age counter."""
    def _boom(grid, *, sport, selected_date):
        raise RuntimeError("chips unavailable")

    monkeypatch.setattr(
        "syndicate.features.shared.board_enrichment.attach_game_state",
        _boom,
        raising=False,
    )
    out = shortlist.build_layer2_shortlist("2026-08-09", ["mlb"])

    assert isinstance(out.get("per_sport_ingest"), dict)
    stats = _stats(out)
    assert stats.get("quote_rows") == 0
    assert stats.get("sweep_state") == "no_slate", (
        "unknown scheduled-game count must degrade to the conservative answer "
        "rather than claiming a pending sweep it cannot evidence"
    )
