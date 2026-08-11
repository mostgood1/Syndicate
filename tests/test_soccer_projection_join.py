"""`#346` — soccer projections existed and never reached the board.

Measured on production 2026-08-11, primeira_liga:

    source  event_id '401885486'  (ESPN)     home 'Santa Clara'  away 'C.D. Nacional'
    board   event_id 'abbf3c5f…'  (OddsAPI)  home 'Santa Clara'  away 'Nacional'

Two id schemes, so `by_event` can never hit across the feeds, and the exact
name tuple missed on `nacional` vs `c d nacional`. The coverage report said it
plainly and nobody read it: `unmatched_match_rows: 9` of 9 rows considered,
`rows_with_projection: 0`, on a slate where the sim had the only fixture.
"""

from __future__ import annotations

from syndicate.features.shared.soccer_projections import SoccerProjectionIndex, _norm_team

SIM = {"event_id": "401885486", "matchup": {"home_team": "Santa Clara", "away_team": "C.D. Nacional"}}


def _index(*pairs):
    idx = SoccerProjectionIndex()
    for home, away, payload in pairs:
        idx.by_teams[(_norm_team(home), _norm_team(away))] = payload
        if payload.get("event_id"):
            idx.by_event[str(payload["event_id"])] = payload
    return idx


def test_the_real_production_miss_now_joins():
    idx = _index(("Santa Clara", "C.D. Nacional", SIM))
    row = {"event_id": "abbf3c5f0a0beb14f04044e30eca207a", "home_team": "Santa Clara", "away_team": "Nacional"}
    assert idx.match_for(row) is SIM


def test_exact_names_still_win_without_touching_aliases():
    idx = _index(("Santa Clara", "Nacional", SIM))
    assert idx.match_for({"home_team": "Santa Clara", "away_team": "Nacional"}) is SIM


def test_event_id_wins_when_the_schemes_do_agree():
    idx = _index(("Santa Clara", "C.D. Nacional", SIM))
    assert idx.match_for({"event_id": "401885486", "home_team": "x", "away_team": "y"}) is SIM


def test_common_club_prefixes_resolve():
    for board_name, sim_name in (("Porto", "FC Porto"), ("Benfica", "S.L. Benfica")):
        payload = {"matchup": {"home_team": sim_name, "away_team": "Rival"}}
        idx = _index((sim_name, "Rival", payload))
        assert idx.match_for({"home_team": board_name, "away_team": "Rival"}) is payload


def test_both_sides_must_match():
    # Matching only the home side would attach one fixture's projection to
    # another fixture's prices.
    idx = _index(("Santa Clara", "C.D. Nacional", SIM))
    assert idx.match_for({"home_team": "Santa Clara", "away_team": "Braga"}) is None


def test_an_ambiguous_alias_match_returns_nothing():
    # If two indexed fixtures both alias-match, the join cannot know which. A
    # wrong projection is worse than a blank one: it puts a real number next to
    # the wrong bet.
    a = {"matchup": {"home_team": "FC Porto", "away_team": "Rival"}}
    b = {"matchup": {"home_team": "Porto", "away_team": "Rival"}}
    idx = _index(("FC Porto", "Rival", a), ("Porto", "Rival", b))
    assert idx.match_for({"home_team": "Porto FC", "away_team": "Rival"}) is None


def test_a_shortened_club_name_matches_when_it_is_the_ONLY_candidate():
    """`Sporting` -> `Sporting CP` DOES match, and the guard is candidate count.

    I first asserted this stayed unmatched, from a probe that called
    `teams_match` with the arguments reversed and unnormalized. In the direction
    `match_for` actually uses -- normalized row name against normalized index
    key -- it matches.

    That is the right behaviour HERE because the index is loaded per league, so
    a Primeira Liga index containing one `Sporting CP` has no other club the
    name could mean. The protection against `Sporting Gijón` / `Sporting KC`
    is not this matcher refusing; it is
    `test_an_ambiguous_alias_match_returns_nothing` above -- two candidates and
    the join declines.
    """
    payload = {"matchup": {"home_team": "Sporting CP", "away_team": "Rival"}}
    idx = _index(("Sporting CP", "Rival", payload))
    assert idx.match_for({"home_team": "Sporting", "away_team": "Rival"}) is payload
