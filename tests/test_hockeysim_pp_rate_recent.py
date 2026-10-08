"""Recency-weighted committed rate ("C20") for per_minor PP time (lane nhl-pp-time, 2026-10-08).

Builder math on synthetic games, the loader's stale-file guard, and engine reachability: "recent" must change
PP time under per_minor when the special-teams dict carries the field, and must be a no-op otherwise.
"""
from __future__ import annotations

import csv
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from syndicate.features.nhl.sim_engine.hockeysim import NHL_CALIBRATION_PROFILE, RateModels, TeamRates, run_hockeysim_game
from syndicate.features.nhl.sim_engine.hockeysim.engine import SimConfig
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import load_team_special_teams_map
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.contracts import HistoricalGameRecord
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.special_teams_builder import (
    RECENT_HALF_LIFE_GAMES,
    compute_special_teams_rates,
)


def _game(d: date, home: str, away: str, pen_h: int, pen_a: int) -> HistoricalGameRecord:
    return HistoricalGameRecord(game_id=f"{d}{home}", date=d.isoformat(), season="20252026", game_type=2,
                                home_abbr=home, away_abbr=away, home_goals=3, away_goals=2, home_sog=30, away_sog=28,
                                penalties_committed_home=pen_h, penalties_committed_away=pen_a)


class BuilderTest(unittest.TestCase):
    def test_recent_tracks_a_late_drop(self) -> None:
        start = date(2025, 10, 7)
        games = []
        # 40 games each: AAA commits 4 early and 2 over its last 10; BBB a flat 3
        for i in range(40):
            d = start + timedelta(days=2 * i)
            games.append(_game(d, "AAA", "BBB", 4 if i < 30 else 2, 3))
        r = compute_special_teams_rates(games)
        self.assertAlmostEqual(r["AAA"].committed_per_game, 3.5, places=4)
        self.assertLess(r["AAA"].committed_per_game_recent, r["AAA"].committed_per_game)
        self.assertEqual(r["AAA"].recent_asof, (start + timedelta(days=78)).isoformat())
        self.assertEqual(RECENT_HALF_LIFE_GAMES, 20.0)

    def test_too_few_games_has_no_recent(self) -> None:
        g = [_game(date(2025, 10, 7) + timedelta(days=i), "AAA", "BBB", 3, 3) for i in range(3)]
        self.assertIsNone(compute_special_teams_rates(g)["AAA"].committed_per_game_recent)


class LoaderGuardTest(unittest.TestCase):
    def _write(self, root: Path, asof: str) -> None:
        proc = root / "data" / "processed"
        proc.mkdir(parents=True)
        with open(proc / "team_special_teams_latest.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["abbr", "pp_pct", "pk_pct", "committed_per_game", "committed_per_game_recent", "recent_asof"])
            w.writerow(["BOS", 0.2, 0.8, 3.4, 2.9, asof])

    def test_current_file_passes_recent(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            self._write(Path(t), "2026-01-10")
            m = load_team_special_teams_map("2026-01-15", root=Path(t))
            self.assertEqual(m["BOS"]["committed_per_game_recent"], 2.9)

    def test_stale_file_drops_recent(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            self._write(Path(t), "2026-04-16")  # last season's April, read in October
            m = load_team_special_teams_map("2026-10-08", root=Path(t))
            self.assertNotIn("committed_per_game_recent", m["BOS"])
            self.assertEqual(m["BOS"]["committed_per_game"], 3.4)


def _roster(team, base):
    rows = [{"player_id": base + i, "full_name": f"{team}F{i}", "position": "F", "proj_toi": 18.0 - i * 0.7} for i in range(12)]
    rows += [{"player_id": base + 20 + i, "full_name": f"{team}D{i}", "position": "D", "proj_toi": 21.0 - i * 1.5} for i in range(6)]
    rows.append({"player_id": base + 30, "full_name": f"{team}G", "position": "G", "proj_toi": 60.0})
    return rows


def _lineup(base):
    rows = [{"player_id": base + l * 3 + k, "line_slot": f"L{l + 1}", "pp_unit": 1 if l == 0 else (2 if l == 1 else None)} for l in range(4) for k in range(3)]
    rows += [{"player_id": base + 20 + p * 2 + k, "line_slot": f"D{p + 1}", "pp_unit": 1 if p == 0 else None} for p in range(3) for k in range(2)]
    return rows


def _pp_seconds(profile, st, seeds):
    rates = RateModels(home=TeamRates(shots_per_60=30.0, goals_per_60=3.0, faceoff_win_pct=0.5),
                       away=TeamRates(shots_per_60=30.0, goals_per_60=3.0, faceoff_win_pct=0.5), player_rates={})
    tot = 0.0
    for s in seeds:
        _gs, ev = run_hockeysim_game("HOME", "AWAY", _roster("HOME", 1000), _roster("AWAY", 2000), rates,
                                     st_home=dict(st), st_away=dict(st), lineup_home=_lineup(1000), lineup_away=_lineup(2000),
                                     profile=profile, seed=s)
        tot += sum(float(e.meta.get("dur", 0)) for e in ev
                   if e.kind == "shift" and e.player_id in (1030, 2030) and (e.meta or {}).get("strength") == "PP")
    return tot / len(seeds)


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        p = mock.patch.dict(os.environ, {"SYNDICATE_NHL_PP_TIME_MODEL": ""})
        p.start()
        self.addCleanup(p.stop)

    def test_default_source_is_season(self) -> None:
        self.assertEqual(SimConfig().pp_rate_source, "season")

    def test_recent_is_reachable_under_per_minor(self) -> None:
        st = {"pp_pct": 0.2, "pk_pct": 0.8, "committed_per_game": 3.6, "committed_per_game_recent": 2.4}
        base = replace(NHL_CALIBRATION_PROFILE, pp_time_model="per_minor", pp_seconds_per_minor=88.9)
        seeds = range(25)
        season = _pp_seconds(base, st, seeds)
        recent = _pp_seconds(replace(base, pp_rate_source="recent"), st, seeds)
        self.assertLess(recent, season * 0.8)  # 2.4 vs 3.6 per side -> ~0.67x
        # without the field, "recent" falls back to the season rate exactly
        st2 = {k: v for k, v in st.items() if k != "committed_per_game_recent"}
        self.assertEqual(_pp_seconds(replace(base, pp_rate_source="recent"), st2, seeds), _pp_seconds(base, st2, seeds))


if __name__ == "__main__":
    unittest.main()
