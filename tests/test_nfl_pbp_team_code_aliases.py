"""Washington and the LA Rams must resolve against the nflverse play-by-play.

MEASURED 2026-08-13 by diffing the two code sets on real files:

    schedule_preseason_2026.csv  ... LAC LAR ... WSH   (32 codes)
    nflverse pbp_2025.csv        ... LA  LAC ... WAS   (32 codes)
    in schedule, absent from pbp: ['LAR', 'WSH']
    in pbp, absent from schedule: ['LA',  'WAS']

`team_rating` matches `posteam`/`defteam` by exact string, so those two clubs
found zero plays in either season and fell to the `neutral_no_data` branch --
a real 0.0/0.0 rating producing a confident-looking projection that carries no
team information. Production confirmed it the same day: every club reported
`prior_season_fallback` EXCEPT exactly these two.

The failure is silent by construction, which is why it needs a test: a
league-average projection is shaped exactly like a real one.
"""

from __future__ import annotations

import pytest

from scripts.generate_smartsim2_nfl_projections import pbp_team_code, team_rating


def _plays(team: str):
    """Minimal (week, posteam, defteam, play_type, epa) rows for one team."""
    return [
        (1, team, "OPP", "pass", 0.25),
        (1, "OPP", team, "run", -0.10),
        (2, team, "OPP", "run", 0.15),
        (2, "OPP", team, "pass", -0.20),
    ]


@pytest.mark.parametrize("schedule_code,pbp_code", [("LAR", "LA"), ("WSH", "WAS")])
def test_the_two_mismatched_clubs_translate(schedule_code, pbp_code):
    assert pbp_team_code(schedule_code) == pbp_code


@pytest.mark.parametrize("code", ["KC", "CIN", "DET", "GB", "LAC", "NYG", "NYJ", "SF", "TEN"])
def test_every_other_code_is_left_alone(code):
    """Narrow by design. A general alias table here would pull display-name
    resolution into a numeric ratings path."""
    assert pbp_team_code(code) == code


def test_case_and_whitespace_do_not_defeat_the_translation():
    assert pbp_team_code(" lar ") == "LA"
    assert pbp_team_code("wsh") == "WAS"


@pytest.mark.parametrize("schedule_code,pbp_code", [("LAR", "LA"), ("WSH", "WAS")])
def test_rating_resolves_for_the_mismatched_clubs(schedule_code, pbp_code):
    """The behaviour that actually matters: asking for the SCHEDULE's code
    must find the pbp's plays instead of falling through to neutral."""
    offense, defense, source = team_rating(
        schedule_code, week=1, current_plays=[], prior_plays=_plays(pbp_code)
    )
    assert source == "prior_season_fallback", "must not land on the neutral branch"
    assert offense != 0.0 or defense != 0.0


def test_pre_fix_control_a_genuinely_absent_team_still_reads_neutral():
    """The neutral branch must still work -- otherwise this test proves the
    alias fires, not that it fires for the right reason."""
    _, _, source = team_rating("LAR", week=1, current_plays=[], prior_plays=_plays("KC"))
    assert source == "neutral_no_data"


def test_an_unaliased_club_resolves_exactly_as_before():
    _, _, source = team_rating("KC", week=1, current_plays=[], prior_plays=_plays("KC"))
    assert source == "prior_season_fallback"


def test_current_season_branch_also_benefits_from_the_alias():
    _, _, source = team_rating("WSH", week=3, current_plays=_plays("WAS"), prior_plays=None)
    assert source == "current_season_rolling"
