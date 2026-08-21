"""Tests for the NFL fantasy projection engine.

Structured around what ``docs/ai_context/model_engine_standard.md`` says a test
suite CAN and CANNOT prove. It cannot prove an input is fed -- it supplies the
data itself (s6), which is what ``scripts/nfl_fantasy_input_checklist.py`` is
for. So what is tested here is the part that IS testable: scoring arithmetic,
the structural invariants of the opportunity system, and REACHABILITY --
``off != on`` for every flag, written before any correctness test (s4.3),
because four features in this repo shipped built, tested and inert and were
caught by exactly this and by nothing else.

Tests needing real play-by-play skip cleanly when it is not on this substrate,
rather than asserting against a degenerate empty load and reporting a fact
about the checkout as a fact about the engine (s3b).
"""

from __future__ import annotations

import dataclasses

import pytest

from syndicate.features.nfl import fantasy_projection as engine
from syndicate.features.nfl.fantasy_draft_board import DEFAULT_LEAGUE
from syndicate.features.nfl.fantasy_draft_board import LeagueSettings
from syndicate.features.nfl.fantasy_draft_board import build_draft_board
from syndicate.features.nfl.fantasy_draft_board import replacement_levels
from syndicate.features.nfl.fantasy_news import NewsAdjustments
from syndicate.features.nfl.fantasy_news import classify_headline
from syndicate.features.nfl.fantasy_scoring import ESPN_HALF_PPR
from syndicate.features.nfl.fantasy_scoring import ESPN_PPR
from syndicate.features.nfl.fantasy_scoring import ESPN_STANDARD
from syndicate.features.nfl.fantasy_scoring import dst_points_allowed_score
from syndicate.features.nfl.fantasy_scoring import resolve_scoring
from syndicate.features.nfl.fantasy_scoring import score_stat_line
from syndicate.features.nfl.fantasy_usage import _PLAYER_SUM_FIELDS
from syndicate.features.nfl.fantasy_usage import _TEAM_SUM_FIELDS
from syndicate.features.nfl.fantasy_usage import load_season_game_lines
from syndicate.features.nfl.fantasy_usage import load_season_usage
from syndicate.features.nfl.fantasy_usage import usage_substrate


SEASON = 2026
HISTORY_SEASON = 2025


def _has_usage(season: int) -> bool:
    from syndicate.features.nfl.fantasy_usage import usage_artifact_path

    return usage_artifact_path(season).is_file() or usage_substrate(season)["exists"]


requires_usage = pytest.mark.skipif(
    not _has_usage(HISTORY_SEASON),
    reason="no NFL usage on this substrate -- UNMEASURED, not a failing engine",
)


# ---------------------------------------------------------------------------
# Scoring: pure arithmetic, always runnable
# ---------------------------------------------------------------------------

def test_ppr_reception_is_the_only_difference_between_profiles():
    line = {"receptions": 6, "receiving_yards": 84, "receiving_tds": 1}
    ppr = score_stat_line(line, ESPN_PPR)
    half = score_stat_line(line, ESPN_HALF_PPR)
    standard = score_stat_line(line, ESPN_STANDARD)
    assert ppr - half == pytest.approx(3.0)
    assert half - standard == pytest.approx(3.0)
    assert standard == pytest.approx(8.4 + 6.0)


def test_espn_passing_rules():
    # 300 yards / 25 = 12, two passing TDs = 8, one interception = -2
    line = {"passing_yards": 300, "passing_tds": 2, "interceptions": 1}
    assert score_stat_line(line, ESPN_PPR) == pytest.approx(12 + 8 - 2)


def test_kicker_distance_bands():
    line = {"fg_made_0_39": 1, "fg_made_40_49": 1, "fg_made_50_plus": 1, "pat_made": 2, "fg_missed": 1}
    assert score_stat_line(line, ESPN_PPR) == pytest.approx(3 + 4 + 5 + 2 - 1)


def test_points_allowed_ladder_is_monotone_decreasing():
    previous = None
    for allowed in range(0, 60):
        value = dst_points_allowed_score(float(allowed), ESPN_PPR)
        if previous is not None:
            assert value <= previous + 1e-9, f"ladder rose at {allowed} points allowed"
        previous = value
    assert dst_points_allowed_score(0.0, ESPN_PPR) == pytest.approx(10.0)
    assert dst_points_allowed_score(60.0, ESPN_PPR) == pytest.approx(-5.0)


def test_unknown_scoring_key_falls_back_to_ppr_not_to_zero():
    assert resolve_scoring("nonsense").key == "ppr"
    assert resolve_scoring(None).key == "ppr"
    assert resolve_scoring("Half-PPR").key == "half_ppr"


def test_missing_stat_keys_score_zero_rather_than_raising():
    assert score_stat_line({}, ESPN_PPR) == pytest.approx(0.0)
    assert score_stat_line({"receptions": None}, ESPN_PPR) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Usage: the structural invariant
# ---------------------------------------------------------------------------

@requires_usage
def test_game_lines_sum_exactly_to_season_totals():
    """The one invariant that makes two accumulation paths safe to have.

    Season totals are derived by summing per-game lines, so if this ever fails
    the two have drifted and every rate built on them is suspect.
    """
    players, teams = load_season_usage(HISTORY_SEASON)
    player_lines, team_lines = load_season_game_lines(HISTORY_SEASON)

    summed: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for line in player_lines:
        bucket = summed.setdefault(line.player_id, {name: 0.0 for name in _PLAYER_SUM_FIELDS})
        counts[line.player_id] = counts.get(line.player_id, 0) + 1
        for name in _PLAYER_SUM_FIELDS:
            bucket[name] += getattr(line, name)

    assert summed, "no per-game player lines"
    for player_id, usage in players.items():
        assert counts.get(player_id) == usage.games, player_id
        for name in _PLAYER_SUM_FIELDS:
            assert summed[player_id][name] == pytest.approx(getattr(usage, name)), (
                player_id,
                name,
            )

    team_summed: dict[str, dict[str, float]] = {}
    for line in team_lines:
        bucket = team_summed.setdefault(line.team, {name: 0.0 for name in _TEAM_SUM_FIELDS})
        for name in _TEAM_SUM_FIELDS:
            bucket[name] += getattr(line, name)
    for team, usage in teams.items():
        for name in _TEAM_SUM_FIELDS:
            assert team_summed[team][name] == pytest.approx(getattr(usage, name)), (team, name)


@requires_usage
def test_every_team_has_a_full_season_of_games():
    _, teams = load_season_usage(HISTORY_SEASON)
    assert len(teams) == 32
    for team, usage in teams.items():
        assert usage.games == 17, f"{team} has {usage.games} games"
        assert usage.points_for > 0, team


# ---------------------------------------------------------------------------
# REACHABILITY -- written first, per s4.3. off != on, or the flag is inert.
# ---------------------------------------------------------------------------

@requires_usage
def test_reachability_market_environment_changes_the_projection():
    on = engine.project_team(SEASON, "KC", ESPN_PPR)
    off = engine.project_team(
        SEASON, "KC", ESPN_PPR, config=dataclasses.replace(engine.DEFAULT_CONFIG, use_market_environment=False)
    )
    assert on and off
    assert {row.player_id: round(row.fantasy_points, 3) for row in on} != {
        row.player_id: round(row.fantasy_points, 3) for row in off
    }, "use_market_environment is INERT -- the market is not reaching the projection"


@requires_usage
def test_reachability_red_zone_touchdown_share_changes_the_projection():
    on = engine.project_team(SEASON, "KC", ESPN_PPR)
    off = engine.project_team(
        SEASON,
        "KC",
        ESPN_PPR,
        config=dataclasses.replace(engine.DEFAULT_CONFIG, use_red_zone_touchdown_share=False),
    )
    assert {row.player_id: round(row.fantasy_points, 3) for row in on} != {
        row.player_id: round(row.fantasy_points, 3) for row in off
    }, "use_red_zone_touchdown_share is INERT"


@requires_usage
def test_reachability_news_share_promotion_is_paid_for_by_team_mates():
    """News ships OFF, so this is the only thing standing between it and
    becoming quietly inert the next time someone touches the engine.

    Share and availability are tested SEPARATELY, and that separation is not
    cosmetic. Applied together they can cancel exactly: the opportunity pool is
    normalised so that ``sum(share * games)`` equals the team's season, so a
    player whose share rises 1.25x while his availability falls 0.8x finishes
    on precisely the same season total, and so does everyone else on his team.
    That is CORRECT -- 25% more usage across 20% fewer games is the same
    accumulation -- but a test that multiplies by both reads as "the feature is
    inert" when the feature is working. This test first failed exactly that
    way.
    """
    off = engine.project_team(SEASON, "ATL", ESPN_PPR)
    assert off
    target = max(off, key=lambda row: row.fantasy_points)
    news = NewsAdjustments(
        season=SEASON,
        generated_at="test",
        share_multipliers={target.player_id: 1.4},
    )
    on = engine.project_team(
        SEASON,
        "ATL",
        ESPN_PPR,
        config=dataclasses.replace(engine.DEFAULT_CONFIG, use_news_adjustments=True),
        news=news,
    )
    before = {row.player_id: row for row in off}
    after = {row.player_id: row for row in on}
    assert after[target.player_id].basis["target_share"] > before[target.player_id].basis["target_share"]
    assert after[target.player_id].fantasy_points > before[target.player_id].fantasy_points

    # The pool is closed: the promotion comes out of team-mates, not from thin
    # air. D/ST is excluded -- it does not draw on the offensive pool.
    def offensive_total(rows):
        return sum(
            row.fantasy_points
            for key, row in rows.items()
            if key != target.player_id and row.position != "DST"
        )

    assert offensive_total(after) < offensive_total(before), "share promotion invented volume"


@requires_usage
def test_reachability_injury_availability_cuts_games():
    off = engine.project_team(SEASON, "ATL", ESPN_PPR)
    target = max(off, key=lambda row: row.fantasy_points)
    news = NewsAdjustments(
        season=SEASON,
        generated_at="test",
        availability_multipliers={target.player_id: 0.5},
    )
    on = engine.project_team(
        SEASON,
        "ATL",
        ESPN_PPR,
        config=dataclasses.replace(engine.DEFAULT_CONFIG, use_news_adjustments=True),
        news=news,
    )
    before = {row.player_id: row for row in off}[target.player_id]
    after = {row.player_id: row for row in on}[target.player_id]
    assert after.games == pytest.approx(before.games * 0.5, rel=0.02)
    assert after.fantasy_points < before.fantasy_points


@requires_usage
def test_news_flag_off_means_news_object_is_ignored():
    """The inverse of reachability: passing news with the flag off must be a
    no-op, or the flag is not actually the switch."""
    plain = engine.project_team(SEASON, "ATL", ESPN_PPR)
    target = max(plain, key=lambda row: row.fantasy_points)
    news = NewsAdjustments(
        season=SEASON,
        generated_at="test",
        share_multipliers={target.player_id: 2.0},
        availability_multipliers={target.player_id: 0.1},
    )
    with_news = engine.project_team(SEASON, "ATL", ESPN_PPR, news=news)
    assert {row.player_id: round(row.fantasy_points, 6) for row in plain} == {
        row.player_id: round(row.fantasy_points, 6) for row in with_news
    }


# ---------------------------------------------------------------------------
# The opportunity system's closed-pool property
# ---------------------------------------------------------------------------

@requires_usage
def test_team_opportunity_shares_are_conserved():
    """Every team's projected targets and carries must add back up to roughly
    the team's own season pool. This is what makes the engine react correctly
    to roster change instead of inventing volume."""
    league = engine.league_rates(engine._history_seasons(SEASON, 3))
    for team in ("KC", "BUF", "PHI"):
        volume = engine.team_volume(SEASON, team, league)
        rows = engine.project_team(SEASON, team, ESPN_PPR, league)
        season_targets = sum(row.stat_line.get("targets", 0.0) for row in rows)
        expected = volume.targets_per_game * volume.games
        # Rows projecting to essentially nothing are dropped after
        # normalisation, so a small shortfall is expected; a large one means
        # the pool is leaking.
        assert 0.9 <= season_targets / expected <= 1.02, (team, season_targets, expected)


@requires_usage
def test_projection_rows_name_their_own_basis():
    rows = engine.project_team(SEASON, "KC", ESPN_PPR)
    assert rows
    for row in rows:
        assert row.basis.get("environment") in {"market_line", "fitted_rating", "history_no_market"}
        assert "share_source" in row.basis
        assert row.floor <= row.fantasy_points <= row.ceiling


@requires_usage
def test_bye_week_produces_no_rows_rather_than_zeroes():
    from syndicate.features.nfl.fantasy_schedule import bye_week

    team = "KC"
    bye = bye_week(SEASON, team)
    assert bye, "expected a bye week in the 2026 schedule"
    assert engine.project_team(SEASON, team, ESPN_PPR, week=bye) == []
    assert engine.project_team(SEASON, team, ESPN_PPR, week=bye + 1)


# ---------------------------------------------------------------------------
# Draft board
# ---------------------------------------------------------------------------

def _fake(player_id: str, position: str, points: float) -> engine.PlayerProjection:
    return engine.PlayerProjection(
        player_id=player_id,
        name=player_id,
        team="XX",
        position=position,
        season=SEASON,
        games=17.0,
        stat_line={},
        fantasy_points=points,
        points_per_game=points / 17.0,
        points_per_game_sd=1.0,
        season_points_sd=10.0,
        floor=points - 10,
        ceiling=points + 10,
        basis={},
    )


def test_replacement_level_reflects_starting_slots_including_flex():
    projections = [_fake(f"rb{i}", "RB", 300 - i) for i in range(60)]
    projections += [_fake(f"wr{i}", "WR", 250 - i) for i in range(60)]
    projections += [_fake(f"qb{i}", "QB", 400 - i * 5) for i in range(30)]
    projections += [_fake(f"te{i}", "TE", 200 - i * 4) for i in range(30)]

    settings = LeagueSettings(teams=12, flex=1)
    levels = replacement_levels(projections, settings)
    # 12 QB starters -> replacement is the 13th, worth 400 - 12*5.
    assert levels["QB"] == pytest.approx(400 - 12 * 5)
    # RB/WR take 24 each, and the 12 flex slots go to whichever is better at
    # the margin -- here RB, which is strictly higher scoring.
    assert levels["RB"] < 300 - 24
    assert levels["RB"] <= levels["WR"] or levels["WR"] <= 250 - 24


def test_draft_board_orders_by_value_over_replacement_not_points():
    """The whole point of a board: a lower-scoring player at a scarce position
    can and should outrank a higher-scoring one at a deep position."""
    projections = [_fake(f"qb{i}", "QB", 400 - i) for i in range(30)]
    projections += [_fake(f"te{i}", "TE", 300 - i * 12) for i in range(30)]
    board = build_draft_board(projections, LeagueSettings(teams=12, flex=0))
    top = board[0]
    assert top.position == "TE", "a replacement-flat QB pool should not top the board"
    assert top.value_over_replacement > 0
    assert [row.rank for row in board] == sorted(row.rank for row in board)


def test_draft_board_is_empty_for_empty_projections():
    assert build_draft_board([], DEFAULT_LEAGUE) == []
    assert replacement_levels([], DEFAULT_LEAGUE) == {}


# ---------------------------------------------------------------------------
# News classifier
# ---------------------------------------------------------------------------

def test_news_classifier_signals_and_neutrality():
    up, matched_up = classify_headline("Coach says he will start and handle a workhorse role")
    down, matched_down = classify_headline("Slides to backup duty after being benched")
    neutral, matched_neutral = classify_headline("Quarterback discusses his offseason routine")
    assert up > 1.0 and matched_up
    assert down < 1.0 and matched_down
    assert neutral == pytest.approx(1.0) and not matched_neutral
