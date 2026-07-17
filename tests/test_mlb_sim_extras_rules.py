"""Extra-innings placed runner (Manfred rule) + walk-off termination in the MLB sim engine."""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.models import (
    BatterProfile,
    GameConfig,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    Player,
    Team,
    TeamRoster,
)
from vendor.mlb_bettingv2.sim_engine.simulate import simulate_game


def _make_roster(team_id: int, name: str) -> TeamRoster:
    batters = [
        BatterProfile(
            player=Player(
                mlbam_id=team_id * 1000 + i,
                full_name=f"{name} Batter {i}",
                primary_position="OF",
                bat_side=Handedness.R,
                throw_side=Handedness.R,
            )
        )
        for i in range(1, 10)
    ]
    pitcher = PitcherProfile(
        player=Player(
            mlbam_id=team_id * 1000 + 500,
            full_name=f"{name} Starter",
            primary_position="P",
            bat_side=Handedness.R,
            throw_side=Handedness.R,
        ),
        stamina_pitches=250,
        role="SP",
    )
    return TeamRoster(
        team=Team(team_id=team_id, name=name, abbreviation=name[:3].upper()),
        manager=ManagerProfile(),
        lineup=Lineup(batters=batters, pitcher=pitcher),
    )


def _run_games(seeds, **cfg_kwargs):
    away = _make_roster(1, "Aways")
    home = _make_roster(2, "Homes")
    results = []
    for seed in seeds:
        cfg = GameConfig(rng_seed=seed, manager_pitching="off", pbp="pitch", pbp_max_events=0, **cfg_kwargs)
        results.append(simulate_game(away, home, cfg))
    return results


def _running_score_before_each_pa(result):
    """Yield (event, home_score_before, away_score_before) for PA events.

    The engine folds half-inning runs into the game score only when the half
    ends, so PA events' score_before fields lag mid-inning. Reconstruct the
    effective score by carrying the previous PA's runs_in_half.
    """
    half_key = None
    runs_in_half_so_far = 0
    for ev in result.pbp:
        if ev.get("type") != "PA":
            continue
        key = (int(ev.get("inning") or 0), str(ev.get("half") or ""))
        if key != half_key:
            half_key = key
            runs_in_half_so_far = 0
        score = ev.get("score_before") or {}
        home_before = int(score.get("home") or 0)
        away_before = int(score.get("away") or 0)
        if str(ev.get("half") or "") == "bottom":
            home_before += runs_in_half_so_far
        else:
            away_before += runs_in_half_so_far
        yield ev, home_before, away_before
        runs_in_half_so_far = int(ev.get("runs_in_half") or 0)


class ExtrasPlacedRunnerTests(unittest.TestCase):
    def test_every_extra_half_inning_starts_with_runner_on_second(self) -> None:
        results = _run_games(range(1, 250))
        extras_games = [r for r in results if r.innings_played > 9]
        self.assertGreater(len(extras_games), 0, "expected at least one extra-innings game in seed sweep")
        for result in extras_games:
            placed_events = [ev for ev in result.pbp if ev.get("type") == "PLACED_RUNNER"]
            extra_half_starts = [
                ev for ev in result.pbp if ev.get("type") == "HALF_START" and int(ev.get("inning") or 0) > 9
            ]
            self.assertEqual(
                len(placed_events),
                len(extra_half_starts),
                "each extra half-inning should place exactly one runner",
            )
            for ev in placed_events:
                self.assertGreater(int(ev.get("inning") or 0), 9)
                self.assertEqual(ev.get("base"), "2B")
                self.assertGreater(int(ev.get("runner_id") or 0), 0)

    def test_no_placed_runner_in_regulation(self) -> None:
        results = _run_games(range(1, 60))
        for result in results:
            for ev in result.pbp:
                if ev.get("type") == "PLACED_RUNNER":
                    self.assertGreater(int(ev.get("inning") or 0), 9)

    def test_flag_off_restores_bases_empty_extras(self) -> None:
        results = _run_games(range(1, 250), extras_placed_runner=False)
        for result in results:
            placed = [ev for ev in result.pbp if ev.get("type") == "PLACED_RUNNER"]
            self.assertEqual(placed, [])


class WalkoffTerminationTests(unittest.TestCase):
    def test_no_pa_after_home_takes_lead_in_bottom_of_ninth_or_later(self) -> None:
        results = _run_games(range(1, 250))
        checked = 0
        for result in results:
            for ev, home_before, away_before in _running_score_before_each_pa(result):
                if ev.get("half") == "bottom" and int(ev.get("inning") or 0) >= 9:
                    self.assertLessEqual(
                        home_before,
                        away_before,
                        "a PA began after the home team already led in the bottom of the 9th or later "
                        f"(inning {ev.get('inning')}, seed game {result.home_score}-{result.away_score})",
                    )
                    checked += 1
        self.assertGreater(checked, 0, "expected bottom-9th-or-later PAs in seed sweep")

    def test_games_never_end_tied_by_default(self) -> None:
        results = _run_games(range(1, 250))
        for result in results:
            self.assertNotEqual(result.home_score, result.away_score)

    def test_game_never_ends_after_top_half_unless_home_leads(self) -> None:
        """Regression: away taking the lead in the top of an extra inning must not
        end the game before the home team bats in the bottom half."""
        results = _run_games(range(1, 400))
        top_half_endings = 0
        for result in results:
            half_ends = [ev for ev in result.pbp if ev.get("type") == "HALF_END"]
            self.assertTrue(half_ends)
            last = half_ends[-1]
            if last.get("half") == "top":
                top_half_endings += 1
                score = last.get("score") or {}
                self.assertGreater(
                    int(score.get("home") or 0),
                    int(score.get("away") or 0),
                    f"game ended after a top half without a home lead (inning {last.get('inning')})",
                )
        self.assertGreater(top_half_endings, 0, "expected some games to end after a top half (home led)")

    def test_flag_off_allows_pa_after_go_ahead_run(self) -> None:
        results = _run_games(range(1, 250), end_on_walkoff=False)
        violations = 0
        for result in results:
            for ev, home_before, away_before in _running_score_before_each_pa(result):
                if ev.get("half") == "bottom" and int(ev.get("inning") or 0) >= 9 and home_before > away_before:
                    violations += 1
        self.assertGreater(
            violations,
            0,
            "with end_on_walkoff=False, legacy behavior should keep batting after the go-ahead run",
        )


if __name__ == "__main__":
    unittest.main()
