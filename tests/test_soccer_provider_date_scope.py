"""Soccer's multi-league fan-out resolves each league against the REQUESTED
date, not the wall clock.

THE DEFECT, measured 2026-08-16. `build_game_chips` returned the **identical 90
soccer chips** for 2026-08-16, 08-17, 08-20 and 08-22, although `default_week`
maps 08-16 to week 1 and 08-22 to week 2 for epl / la_liga / ligue_1. The board
consequence: **17 soccer games in `state: "unknown"` holding 1,628 rows**, 15 of
them with no matching chip at any date, and for epl and ligue_1 the clubs were
absent from the chip set entirely (1 epl chip against 6 epl fixtures on the
board).

`resolve_context(requested_date=...)` had always resolved the PRIMARY league
correctly. `games()` then opened with `today = central_today_iso()` and threw
that away, re-resolving every league -- primary included, via `_active_leagues`
-- against the wall clock.

These tests pin the CALL, not the fixture data: they record which
`(league, week, season)` the fan-out asks for. A test that asserted on real
schedule contents would go red every time a season rolled, and would not
actually distinguish "resolved from the context" from "resolved from today".
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.sport_data_provider import SportContext


def test_sport_context_carries_the_requested_date_and_defaults_to_none():
    """Additive and optional: the seven providers that ignore it are untouched."""
    assert SportContext(slug="x", context_label="y").requested_date is None
    assert SportContext(slug="x", context_label="y", requested_date="2026-08-22").requested_date == "2026-08-22"


def _provider():
    import syndicate.blueprints.home as home
    return home._SoccerDataProvider()


def _record_calls(monkeypatch):
    """Capture every (league, week, season) the fan-out requests."""
    import syndicate.features.soccer.cards as cards
    calls = []

    def fake(league, week, season):
        calls.append((league, int(week), int(season)))
        return {"games": []}

    monkeypatch.setattr(cards, "build_cards_page_context", fake)
    return calls


def test_the_fan_out_uses_the_context_date_not_today(monkeypatch):
    """The regression in one assertion.

    Two dates that `default_week` separates must produce DIFFERENT week
    requests. Before the fix both produced the same set, because `games()`
    re-derived the date from the wall clock.
    """
    from syndicate.features.soccer.sources import default_season, default_week

    provider = _provider()

    calls_early = _record_calls(monkeypatch)
    provider.games(provider.resolve_context(requested_date="2026-08-16"), is_active_today=True)
    early = dict((lg, wk) for lg, wk, _ in calls_early)

    calls_late = _record_calls(monkeypatch)
    provider.games(provider.resolve_context(requested_date="2026-08-22"), is_active_today=True)
    late = dict((lg, wk) for lg, wk, _ in calls_late)

    assert early and late, "the fan-out requested no leagues at all"

    # Only assert on leagues the schedule itself says differ between the two
    # dates -- deriving the expectation from `default_week` rather than
    # hardcoding a week number, so a season roll cannot make this lie.
    moved = [
        lg for lg in early
        if lg in late
        and default_week(lg, default_season(lg), reference_date="2026-08-16")
        != default_week(lg, default_season(lg), reference_date="2026-08-22")
    ]
    assert moved, "no league changes week across these dates; pick dates that straddle one"
    for lg in moved:
        assert early[lg] != late[lg], f"{lg} was resolved against the wall clock, not the context"
        assert late[lg] == default_week(lg, default_season(lg), reference_date="2026-08-22")


def test_each_league_gets_its_own_week_not_the_primary_leagues(monkeypatch):
    """The fan-out is per-league on purpose.

    `SportContext` carries ONE league's season/week for labels and links; the
    other nine resolve themselves. Collapsing them onto the primary league's
    week is the other way this could be wrong and would be invisible on a
    Saturday when every league happens to align.
    """
    from syndicate.features.soccer.sources import default_season, default_week

    provider = _provider()
    calls = _record_calls(monkeypatch)
    provider.games(provider.resolve_context(requested_date="2026-08-22"), is_active_today=True)

    assert len({wk for _, wk, _ in calls}) >= 1
    for league, week, season in calls:
        assert week == default_week(league, season, reference_date="2026-08-22"), (
            f"{league} did not get its OWN week for the requested date"
        )


def test_a_context_without_a_date_still_works(monkeypatch):
    """Back-compat: a hand-built context falls back to the wall clock.

    The fallback is what makes this change safe for any caller that constructs
    a SportContext directly rather than through `resolve_context`.
    """
    provider = _provider()
    calls = _record_calls(monkeypatch)
    provider.games(SportContext(slug="soccer", context_label="x", season=2026, week=1,
                                league="mls"), is_active_today=True)
    assert calls, "a dateless context produced no league calls at all"
