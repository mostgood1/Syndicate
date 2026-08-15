"""A close stamped after first pitch is an in-play price, not a close.

`close_age_seconds` is `(commence - stamp)`, so a NEGATIVE value means the
observation came AFTER the game started. Differencing an in-play moneyline
against an opening is not CLV -- the price is repricing on the game state.

Measured on mlb 2026-08-15: 37 of 172 same-book rows were post-commence and
carried 60% of the total loss. The worst four were one event, opened `-186` and
"closed" `+168` stamped 86 minutes into the game. Excluding them moved the
headline from -0.672 to -0.346 and reversed the book attribution. These tests
pin that exclusion so the headline cannot silently re-acquire live prices.
"""
from __future__ import annotations

from syndicate.features.shared.clv_join import compute_clv_for_date


def _opening(key, price, *, book="fanduel", event="evt1", market="h2h", side="away",
             commence="2026-08-15T19:08:00Z"):
    # `commence_time` is read off the OPENING, not the history market
    # (`clv_join.py:197`). Getting that wrong makes every row read as
    # `unknown` timing, which is how the first draft of this file failed.
    opening = {
        "key": key, "sport": "mlb", "market": market, "side": side, "line": None,
        "player_name": None, "bookmaker": book, "price": price, "event_id": event,
        "captured_at": "2026-08-15T05:07:53Z",
        "book_prices": {book: price},
    }
    if commence is not None:
        opening["commence_time"] = commence
    return opening


def _history(close_price, *, book="fanduel", event="evt1", market="h2h",
             stamp="2026-08-15T17:00:00Z"):
    """An `observed_transition` close -- the path that actually leaks in-play prices.

    Measured on mlb 2026-08-15: all 37 contaminated rows carried
    `close_source=observed_transition`, and all 135 clean ones carried
    `last_pregame_quote`. The pregame->live transition is DETECTED by a sweep
    that runs after first pitch, so `closing_captured_at` is the detection time
    and the price sampled with it is already in-play. The `last_pregame_quote`
    path cannot do this -- it skips any point at or after commence
    (`clv_join.py:232`).
    """
    return {
        "markets": {
            f"event_id={event}|home_team=H|away_team=A|market={market}|bookmaker={book}": {
                "closing_price": close_price,
                "closing_captured_at": stamp,
            }
        }
    }


def _run(openings, history, monkeypatch):
    import syndicate.features.shared.clv_opening_ledger as ledger
    monkeypatch.setattr(ledger, "load_openings", lambda _d, root=None: openings, raising=False)
    return compute_clv_for_date("2026-08-15", "mlb", history_payload=history)


# --- the headline must not contain in-play prices ---------------------------

def test_a_close_stamped_after_first_pitch_is_excluded_from_the_headline(monkeypatch):
    """The production case: stamped 86 minutes into the game."""
    report = _run(
        [_opening("k1", -186)],
        _history(168, stamp="2026-08-15T20:34:26Z"),
        monkeypatch,
    )
    assert report["in_play_excluded_n"] == 1
    assert report["same_book_n"] == 0, "an in-play price must not count as a close"
    assert report["avg_clv_pct"] is None


def test_a_pregame_close_still_counts(monkeypatch):
    report = _run(
        [_opening("k1", -186)],
        _history(-200, stamp="2026-08-15T18:00:00Z"),
        monkeypatch,
    )
    assert report["same_book_n"] == 1
    assert report["in_play_excluded_n"] == 0
    assert report["avg_clv_pct"] is not None


def test_the_in_play_row_is_reported_not_discarded(monkeypatch):
    """Refused by name, the way the book scopes are -- never silently dropped."""
    report = _run(
        [_opening("k1", -186)],
        _history(168, stamp="2026-08-15T20:34:26Z"),
        monkeypatch,
    )
    assert report["by_close_timing"]["in_play"]["n"] == 1
    assert len(report["rows"]) == 1, "the row itself is still returned"
    assert report["rows"][0]["close_timing"] == "in_play"
    assert report["same_book_all_n"] == 1


def test_unknown_timing_does_not_get_the_benefit_of_the_doubt(monkeypatch):
    """Absent must not map onto the permissive branch.

    With no commence_time there is no way to know which side of first pitch the
    close came from, so it is bucketed as unknown rather than counted.
    """
    report = _run(
        [_opening("k1", -186, commence=None)],
        _history(-200, stamp="2026-08-15T18:00:00Z"),
        monkeypatch,
    )
    assert report["same_book_n"] == 0
    assert report["unknown_timing_excluded_n"] == 1
    assert "pregame" not in report["by_close_timing"]


def test_the_headline_is_the_pregame_subset_not_the_whole(monkeypatch):
    """Mixed batch: only the pregame row reaches avg_clv_pct."""
    openings = [_opening("k1", -186, event="evt1"), _opening("k2", -186, event="evt2")]
    history = {"markets": {}}
    history["markets"].update(_history(168, event="evt1", stamp="2026-08-15T20:34:26Z")["markets"])
    history["markets"].update(_history(-200, event="evt2", stamp="2026-08-15T18:00:00Z")["markets"])
    report = _run(openings, history, monkeypatch)
    assert report["same_book_all_n"] == 2
    assert report["same_book_n"] == 1
    assert report["in_play_excluded_n"] == 1
    # The headline equals the pregame row alone, not the average of both.
    assert report["avg_clv_pct"] == report["by_close_timing"]["pregame"]["avg_clv_pct"]


def test_bias_note_states_both_exclusions(monkeypatch):
    report = _run([_opening("k1", -186)], _history(-200, stamp="2026-08-15T18:00:00Z"), monkeypatch)
    note = report["bias_note"].lower()
    assert "first pitch" in note or "commence" in note
    assert "best-of-n" in note
