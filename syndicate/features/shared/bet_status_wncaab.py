"""Resolve a women's college basketball (WNCAAB) bet's CURRENT value from ESPN's scoreboard.

`bet_status_ncaab`'s resolver with the women's league table -- read that module's
docstring for the feed, the join, the state rules and the overtime rule. Two things
differ, and both are the league's:

    ESPN path   basketball/womens-college-basketball (same `groups=50&limit=500`:
                measured 2026-11-02, 16 events without `groups=50`, 164 with it)
    periods     FOUR 10-minute quarters, not halves: q1..q4 that period alone,
                h1 = Q1+Q2, h2 = Q3+Q4. Overtime joins `q4` and `h2` per book.

THE TEAM MAP is `team_aliases.canonical_team("wncaab", ...)`, built from the women's
registry `wncaab_team_registry.csv` by lane `wncaab-module`. Until that map exists every
WNCAAB order refuses as `wncaab_team_not_in_registry_or_ambiguous` -- a named registry
gap, never a guess off the men's list.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from syndicate.features.shared.bet_status_ncaab import (
    CollegeBasketballLeague,
    college_basketball_status_resolver,
)

__all__ = ["WNCAAB", "wncaab_status_resolver"]

WNCAAB = CollegeBasketballLeague(
    sport="wncaab",
    espn_path="womens-college-basketball",
    regulation_periods=4,
    segments={"q1": (1,), "q2": (2,), "q3": (3,), "q4": (4,), "h1": (1, 2), "h2": (3, 4)},
)


def wncaab_status_resolver(selected_date: str, *, fetch_json: Callable[[str], Any] | None = None):
    """A resolver `bet_status`/`paper_settlement` can inject, for WNCAAB orders."""
    return college_basketball_status_resolver(WNCAAB, selected_date, fetch_json=fetch_json)
