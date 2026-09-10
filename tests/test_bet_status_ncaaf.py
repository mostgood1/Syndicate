"""NCAAF settlement: the resolver, its wiring, and the ambiguity refusal.

NCAAF is the first sport wired BEFORE its orders reached the ledger. Soccer
(`#547`) and NFL (2026-08-28) were both found only after months of ungradeable
bets showed up in a counter. NCAAF reaches the board today -- measured
2026-08-28T02:10Z, kalshi offered 524 ncaaf quotes, 52 selected -- so the gap
was fixed while it was still cheap.

THE LOAD-BEARING DIFFERENCE FROM NFL IS THE JOIN. `team_aliases` has no NCAAF
map, so `teams_match` falls through to a prefix heuristic that matches
"Michigan" to "Michigan State". These tests pin the refusal, because a resolver
that grades the wrong game is worse than one that grades nothing.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import bet_status_ncaaf
from syndicate.features.shared.bet_status_ncaaf import ncaaf_status_resolver
from syndicate.features.shared.ncaaf_team_registry import (
    resolve_ncaaf_team_id,
    unambiguous_team_index,
)


def _order(**over):
    row = {
        "sport": "ncaaf",
        "market": "h2h",
        "side": "home",
        "line": None,
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
    }
    row.update(over)
    return row


def _game(**over):
    row = {
        "event_id": "401752000",
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
        "home_abbr": "TCU",
        "away_abbr": "UNC",
        "home_score": 31,
        "away_score": 24,
        "in_progress": False,
        "final": True,
        "status": "Final",
    }
    row.update(over)
    return row


@pytest.fixture
def _games(monkeypatch):
    def install(*games):
        monkeypatch.setattr(bet_status_ncaaf, "_load_games", lambda _d: list(games))
    return install


# ---------------------------------------------------------------------------
# 1. Reachability
# ---------------------------------------------------------------------------


def test_paper_settlement_DISPATCHES_ncaaf_to_a_real_resolver():
    """Fails with the one-line `paper_settlement` wiring removed, and only then."""
    from syndicate.features.shared.paper_settlement import _default_resolver

    verdict = _default_resolver("2026-08-29")(
        _order(market="player_pass_yds", player_name="Josh Hoover")
    )

    assert verdict.get("unavailable_reason") != "no_resolver_for_ncaaf"


# ---------------------------------------------------------------------------
# 2. The ambiguity refusal -- the reason this resolver is not NFL's
# ---------------------------------------------------------------------------


def test_an_AMBIGUOUS_team_name_is_REFUSED_not_resolved_to_the_first_row():
    """`ncaaf/cards.py::_team_registry_index` uses `setdefault`, so it answers
    "Tigers" with whichever of ~25 Tigers is first in the CSV, and "Wildcats"
    with Abilene Christian. Measured 2026-08-28: 128 of 2,342 keys are owned by
    more than one team_id.

    The fixture IS the registry, so this cannot pass by omission -- if the
    ambiguity drop were removed these names would resolve.
    """
    assert resolve_ncaaf_team_id("Tigers") is None
    assert resolve_ncaaf_team_id("Wildcats") is None


def test_a_SPECIFIC_name_still_resolves_so_the_guard_is_not_a_blanket_refusal():
    """Paired with the test above deliberately: a resolver that refused
    everything would satisfy it and take every real join down with it."""
    assert resolve_ncaaf_team_id("TCU Horned Frogs") is not None
    assert resolve_ncaaf_team_id("Michigan State") is not None
    assert resolve_ncaaf_team_id("Michigan") is not None


def test_michigan_and_michigan_state_are_DIFFERENT_teams():
    """The exact pair `teams_match`'s prefix heuristic collapses:
    `any(word.startswith("michigan"))` is True for "Michigan State"."""
    assert resolve_ncaaf_team_id("Michigan") != resolve_ncaaf_team_id("Michigan State")


def test_an_unresolvable_order_team_refuses_BEFORE_any_game_is_compared(_games):
    """And with its OWN reason. A registry gap and a poller gap need different
    fixes, so they must not share a counter."""
    _games(_game())

    view = ncaaf_status_resolver("2026-08-29")(_order(home_team="Tigers"))

    assert view["unavailable_reason"] == bet_status_ncaaf.REASON_TEAM_UNRESOLVED


def test_a_pair_resolving_to_the_SAME_team_is_refused(_games):
    """Two names collapsing onto one id means the vocabulary is wrong. Grading
    it would compare a team against itself."""
    _games(_game())

    view = ncaaf_status_resolver("2026-08-29")(
        _order(home_team="TCU Horned Frogs", away_team="TCU")
    )

    assert view["unavailable_reason"] == bet_status_ncaaf.REASON_TEAM_UNRESOLVED


# ---------------------------------------------------------------------------
# 3. Grading
# ---------------------------------------------------------------------------


def test_a_moneyline_reads_the_margin(_games):
    _games(_game())

    view = ncaaf_status_resolver("2026-08-29")(_order())

    assert view["current_value"] == 7.0
    assert view["is_final"] is True


def test_a_LOSING_moneyline_reads_a_NEGATIVE_margin(_games):
    """The negative case, so this suite cannot pass with an always-win grader."""
    _games(_game())

    view = ncaaf_status_resolver("2026-08-29")(_order(side="away"))

    assert view["current_value"] == -7.0
    assert view["line"] == 0.0


def test_a_total_is_graded_off_the_COMBINED_points(_games):
    _games(_game())

    view = ncaaf_status_resolver("2026-08-29")(_order(market="totals", side="over", line=52.5))

    assert view["current_value"] == 55.0


def test_the_join_resolves_the_ABBREVIATION_form_too(_games):
    _games(_game(home_team="", away_team=""))

    view = ncaaf_status_resolver("2026-08-29")(_order())

    assert view["current_value"] == 7.0


# ---------------------------------------------------------------------------
# 4. The refusals, and their order
# ---------------------------------------------------------------------------


def test_the_MARKET_check_runs_BEFORE_the_artifact_read(monkeypatch):
    monkeypatch.setattr(bet_status_ncaaf, "_load_games", lambda _d: None)

    view = ncaaf_status_resolver("2026-08-29")(
        _order(market="player_rush_yds", player_name="Cam Cook")
    )

    assert view["unavailable_reason"] == bet_status_ncaaf.REASON_PROPS


def test_a_pregame_game_does_not_settle_a_total(_games):
    _games(_game(home_score=None, away_score=None, final=False, in_progress=False))

    view = ncaaf_status_resolver("2026-08-29")(_order(market="totals", side="over", line=52.5))

    assert view["unavailable_reason"] == bet_status_ncaaf.REASON_NO_SCORES


def test_a_missing_fixture_and_an_unreadable_capture_are_different_reasons(monkeypatch, _games):
    monkeypatch.setattr(bet_status_ncaaf, "_load_games", lambda _d: None)
    assert ncaaf_status_resolver("2026-08-29")(_order())["unavailable_reason"] == (
        bet_status_ncaaf.REASON_NO_LIVE_STATE
    )

    _games(_game(home_team="USC Trojans", away_team="San Jose State Spartans",
                 home_abbr="USC", away_abbr="SJSU"))
    assert ncaaf_status_resolver("2026-08-29")(_order())["unavailable_reason"] == (
        bet_status_ncaaf.REASON_GAME_NOT_FOUND
    )


def test_a_non_ncaaf_order_is_not_reported_as_an_NCAAF_failure(_games):
    _games(_game())

    assert ncaaf_status_resolver("2026-08-29")(_order(sport="nfl"))["unavailable_reason"] == (
        bet_status_ncaaf.REASON_NOT_NCAAF
    )


# ---------------------------------------------------------------------------
# 5. The registry itself
# ---------------------------------------------------------------------------


def test_the_index_is_populated_and_drops_a_measurable_number_of_keys():
    """Guards against the registry silently going missing -- an empty index
    makes every join refuse, which is safe but would look like a poller
    problem. If this fails, the artifact is gone, not the logic."""
    index = unambiguous_team_index()

    assert len(index) > 1500, f"registry index looks empty or truncated: {len(index)}"


# ---------------------------------------------------------------------------
# THE GAME IS FOUND UNDER ITS KICKOFF DATE, NOT THE PLAN DATE (2026-09-10)
# ---------------------------------------------------------------------------
# Measured 2026-09-10: 281 NCAAF orders dated 09-10 read
# `game_not_in_ncaaf_live_state` against a 09-10 capture holding ONE FBS game
# (FAMU @ MIA). Saturday games on a Thursday plan, looked up under Thursday.
# The registry is stubbed so these run without the mirrored team data.

_KICKOFF_IDS = {
    "Georgia Bulldogs": "61",
    "UGA": "61",
    "Clemson Tigers": "228",
    "CLEM": "228",
    "Miami Hurricanes": "2390",
    "MIA": "2390",
    "Florida A&M Rattlers": "50",
    "FAMU": "50",
}


def _kickoff_setup(monkeypatch, by_date):
    from syndicate.features.shared import bet_status_ncaaf, ncaaf_team_registry

    monkeypatch.setattr(ncaaf_team_registry, "resolve_ncaaf_team_id", lambda name: _KICKOFF_IDS.get(str(name)))
    calls: list[str] = []

    def load(capture_date):
        calls.append(capture_date)
        games = by_date.get(capture_date)
        return None if games is None else list(games)

    monkeypatch.setattr(bet_status_ncaaf, "_load_games", load)
    return bet_status_ncaaf, calls


def _famu_mia_pregame():
    return {
        "home_team": "Miami Hurricanes", "away_team": "Florida A&M Rattlers",
        "home_abbr": "MIA", "away_abbr": "FAMU",
        "home_score": None, "away_score": None,
        "in_progress": False, "final": False,
    }


def _uga_clem_final():
    return {
        "home_team": "Georgia Bulldogs", "away_team": "Clemson Tigers",
        "home_abbr": "UGA", "away_abbr": "CLEM",
        "home_score": 24, "away_score": 17,
        "in_progress": False, "final": True,
    }


def _saturday_total(**over):
    row = {
        "sport": "ncaaf",
        "home_team": "Georgia Bulldogs",
        "away_team": "Clemson Tigers",
        "market": "totals",
        "side": "over",
        "line": 40.5,
        "selected_date": "2026-09-10",
        "commence_time": "2026-09-12T19:30:00Z",
    }
    row.update(over)
    return row


def test_ncaaf_a_SATURDAY_order_on_a_THURSDAY_plan_finds_its_game(monkeypatch):
    module, calls = _kickoff_setup(
        monkeypatch, {"2026-09-10": [_famu_mia_pregame()], "2026-09-12": [_uga_clem_final()]}
    )
    resolved = module.ncaaf_status_resolver("2026-09-10")(_saturday_total())
    assert resolved == {"current_value": 41.0, "is_final": True, "started": True}
    assert calls == ["2026-09-12"]


def test_ncaaf_WITHOUT_a_kickoff_stamp_the_same_order_still_cannot_find_it(monkeypatch):
    module, _ = _kickoff_setup(
        monkeypatch, {"2026-09-10": [_famu_mia_pregame()], "2026-09-12": [_uga_clem_final()]}
    )
    resolved = module.ncaaf_status_resolver("2026-09-10")(_saturday_total(commence_time=None))
    assert resolved == {"unavailable_reason": module.REASON_GAME_NOT_FOUND}


def test_ncaaf_an_UNREADABLE_kickoff_capture_is_no_live_state(monkeypatch):
    module, _ = _kickoff_setup(monkeypatch, {"2026-09-10": [_famu_mia_pregame()]})
    resolved = module.ncaaf_status_resolver("2026-09-10")(_saturday_total())
    assert resolved == {"unavailable_reason": module.REASON_NO_LIVE_STATE}


def test_ncaaf_the_plan_date_still_grades_a_same_day_order(monkeypatch):
    module, _ = _kickoff_setup(monkeypatch, {"2026-09-12": [_uga_clem_final()]})
    order = _saturday_total(selected_date="2026-09-12", commence_time=None)
    assert module.ncaaf_status_resolver("2026-09-12")(order)["current_value"] == 41.0
