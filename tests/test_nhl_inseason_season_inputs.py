"""In-season team_rates / team_special_teams / player_rates / team_elo (lane `nhl-season-inputs-in-season`).

Fixtures are REAL, not invented:
  * nhl_inseason_season_inputs/*_latest_fleet_2026-10-04*.csv -- production's prior files (fleet, read-only copy,
    2025-26); player_rates trimmed to the players dressed in game 2026020009
  * nhl_inseason_season_inputs/{boxscore,landing}_2026020009.json -- PHI @ NJD 2026-10-01 (3-2), real payloads
  * nhl_inseason_team_xg/{score_2026-10-01,playbyplay_2026020009}.json -- shared with the team-xG test
"""
from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date
from pathlib import Path

import pytest

from syndicate.features.nhl import inseason_season_inputs as M
from syndicate.features.nhl.sim_engine.hockeysim.features import loaders

FX = Path(__file__).parent / "fixtures" / "nhl_inseason_season_inputs"
FX_XG = Path(__file__).parent / "fixtures" / "nhl_inseason_team_xg"
GID = "2026020009"
PRIORS = {
    "team_rates": "team_rates_latest_fleet_2026-10-04.csv",
    "team_special_teams": "team_special_teams_latest_fleet_2026-10-04.csv",
    "team_elo": "team_elo_latest_fleet_2026-10-04.csv",
    "player_rates": f"player_rates_latest_fleet_2026-10-04_game_{GID}.csv",
}


def _j(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "nhl_source"
    proc = root / "data" / "processed"
    proc.mkdir(parents=True)
    for stem, name in PRIORS.items():
        shutil.copy(FX / name, proc / f"{stem}_latest.csv")
    return root


def _fetch(calls: list):
    payloads = {
        "/score/2026-10-01": _j(FX_XG / "score_2026-10-01.json"),
        f"/gamecenter/{GID}/play-by-play": _j(FX_XG / f"playbyplay_{GID}.json"),
        f"/gamecenter/{GID}/boxscore": _j(FX / f"boxscore_{GID}.json"),
        f"/gamecenter/{GID}/landing": _j(FX / f"landing_{GID}.json"),
    }

    def fetch(url: str):
        calls.append(url)
        for suffix, payload in payloads.items():
            if url.endswith(suffix):
                return payload
        if "/score/" in url:
            return {"games": []}
        return None  # the other 7 games' payloads are not in the fixture -> counted as failed, game skipped
    return fetch


def _rows(path: Path, key: str = "abbr"):
    return {r[key]: r for r in csv.DictReader(path.open(encoding="utf-8"))}


@pytest.fixture(autouse=True)
def trimmed_player_prior(monkeypatch):
    # the player fixture is trimmed to one game's 35 dressed players; production's floor is 300 rows
    monkeypatch.setitem(M.MIN_PRIOR_ROWS, "player_rates", 30)


@pytest.fixture
def finite_w(monkeypatch):
    monkeypatch.setattr(M, "BLEND_W", {k: 10.0 for k in M.BLEND_W})


def _refresh(tmp_path: Path, calls: list) -> tuple:
    root = _root(tmp_path)
    status = M.refresh_inseason_season_inputs(root, today=date(2026, 10, 4), fetch=_fetch(calls),
                                              season_start=date(2026, 9, 30))
    return root, root / "data" / "processed", status


def test_writes_all_four_season_files_from_one_real_game(tmp_path):
    root, proc, status = _refresh(tmp_path, [])
    assert sorted(status["wrote"]) == sorted(f"{s}_2026-2027.csv" for s in M.STEMS)
    assert status["games_used"] == 1
    assert "reason" not in status


def test_infinite_w_leaves_every_rate_column_at_the_prior(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "BLEND_W", {k: math.inf for k in M.BLEND_W})
    _root_, proc, _ = _refresh(tmp_path, [])
    for stem, key in (("team_rates", "abbr"), ("team_special_teams", "abbr"), ("player_rates", "player_id")):
        assert _rows(proc / f"{stem}_2026-2027.csv", key) == _rows(proc / f"{stem}_latest.csv", key), stem


def test_team_rates_count_blend_matches_the_boxscore(tmp_path, finite_w):
    _root_, proc, _ = _refresh(tmp_path, [])
    box = _j(FX / f"boxscore_{GID}.json")
    prior, out = _rows(proc / "team_rates_latest.csv"), _rows(proc / "team_rates_2026-2027.csv")
    for side in ("homeTeam", "awayTeam"):
        ab, sog = box[side]["abbrev"], box[side]["sog"]
        assert float(out[ab]["shots_per_60"]) == pytest.approx((10 * float(prior[ab]["shots_per_60"]) + sog) / 11, abs=1e-4)
        assert out[ab]["games"] == prior[ab]["games"]          # metadata carried, never overwritten
    assert out["BOS"] == prior["BOS"]                          # a team that has not played is untouched


def test_special_teams_pp_and_pk_blend_at_the_count_level(tmp_path, finite_w):
    _root_, proc, _ = _refresh(tmp_path, [])
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import parse_landing
    rec = parse_landing(_j(FX / f"landing_{GID}.json"))
    prior, out = _rows(proc / "team_special_teams_latest.csv"), _rows(proc / "team_special_teams_2026-2027.csv")
    p, g = prior["NJD"], float(prior["NJD"]["games"])
    pp = (10 * float(p["pp_goals"]) / g + rec.pp_goals_home) / (10 * float(p["pp_opportunities"]) / g + rec.penalties_committed_away)
    ga = (10 * float(p["pp_goals_against"]) / g + rec.pp_goals_away) / (10 * float(p["pk_opportunities"]) / g + rec.penalties_committed_home)
    assert float(out["NJD"]["pp_pct"]) == pytest.approx(pp, abs=1e-4)
    assert float(out["NJD"]["pk_pct"]) == pytest.approx(1 - ga, abs=1e-4)
    for carried in ("pp_shot_index", "faceoff_ev_index", "faceoff_pk_role_index", "pp_opportunities"):
        assert out["NJD"][carried] == p[carried]


def test_player_rates_blend_only_players_with_a_prior_row(tmp_path, finite_w):
    _root_, proc, _ = _refresh(tmp_path, [])
    box = _j(FX / f"boxscore_{GID}.json")
    prior, out = _rows(proc / "player_rates_latest.csv", "player_id"), _rows(proc / "player_rates_2026-2027.csv", "player_id")
    assert set(out) == set(prior)
    checked = 0
    for side in ("homeTeam", "awayTeam"):
        for grp in ("forwards", "defense"):
            for p in box["playerByGameStats"][side][grp]:
                pid = str(p["playerId"])
                if pid in prior:
                    want = (10 * float(prior[pid]["shot_weight"]) + p["sog"]) / 11
                    assert float(out[pid]["shot_weight"]) == pytest.approx(want, abs=1e-4)
                    checked += 1
    assert checked >= 30


def test_elo_regresses_then_updates_zero_sum(tmp_path):
    _root_, proc, _ = _refresh(tmp_path, [])
    prior, out = _rows(proc / "team_elo_latest.csv"), _rows(proc / "team_elo_2026-2027.csv")
    reg = {t: 1500 + (1 - M.ELO_REGRESSION) * (float(r["elo"]) - 1500) for t, r in prior.items()}
    assert float(out["BOS"]["elo"]) == pytest.approx(reg["BOS"], abs=0.01)
    assert float(out["NJD"]["elo"]) > reg["NJD"] and float(out["PHI"]["elo"]) < reg["PHI"]   # NJD won 3-2
    assert float(out["NJD"]["elo"]) - reg["NJD"] == pytest.approx(reg["PHI"] - float(out["PHI"]["elo"]), abs=0.02)


def test_payloads_are_cached_and_never_refetched(tmp_path):
    calls: list = []
    root, _proc, _ = _refresh(tmp_path, calls)
    first = [c for c in calls if GID in c]
    assert len(first) == 3   # boxscore, landing, play-by-play -- once each
    calls.clear()
    M.refresh_inseason_season_inputs(root, today=date(2026, 10, 4), fetch=_fetch(calls), season_start=date(2026, 9, 30))
    assert not [c for c in calls if GID in c]


def test_loaders_read_the_season_file(tmp_path, finite_w):
    root, proc, _ = _refresh(tmp_path, [])
    seasonal = loaders.load_team_rates_map("2026-10-05", root=root)
    (proc / "team_rates_2026-2027.csv").unlink()
    latest = loaders.load_team_rates_map("2026-10-05", root=root)
    assert seasonal["NJD"]["shots_per_60"] != latest["NJD"]["shots_per_60"]
    assert seasonal["BOS"] == latest["BOS"]


def test_never_raises_and_writes_nothing_without_priors(tmp_path):
    root = tmp_path / "nhl_source"
    (root / "data" / "processed").mkdir(parents=True)
    calls: list = []
    status = M.refresh_inseason_season_inputs(root, today=date(2026, 10, 4), fetch=_fetch(calls), season_start=date(2026, 9, 30))
    assert status["wrote"] == [] and calls == []   # no prior -> no network at all (test and replay roots)
    assert not list((root / "data" / "processed").glob("*_2026-2027.csv"))

    def boom(url):
        raise RuntimeError("network down")
    status = M.refresh_inseason_season_inputs(_root(tmp_path / "b"), today=date(2026, 10, 4), fetch=boom,
                                              season_start=date(2026, 9, 30))
    assert status["reason"].startswith("error=")
