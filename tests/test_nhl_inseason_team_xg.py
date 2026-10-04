"""In-season team xG builder (lane `nhl-season-inputs-in-season`).

Fixtures are REAL, not invented:
  * team_xg_latest_fleet_2026-10-03.csv -- production's prior file (fleet, read-only copy; 2025-26, 82 games/team)
  * score_2026-10-01.json -- the NHL score feed for 2026-10-01 (8 finished regular-season games)
  * playbyplay_2026020009.json -- PHI @ NJD 2026-10-01 (3-2), its real play-by-play
"""
from __future__ import annotations

import csv
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from syndicate.features.nhl import inseason_team_xg as M

FX = Path(__file__).parent / "fixtures" / "nhl_inseason_team_xg"


def _root(tmp_path: Path, with_prior: bool = True) -> Path:
    root = tmp_path / "nhl_source"
    proc = root / "data" / "processed"
    proc.mkdir(parents=True)
    (root / "data" / "odds" / "games").mkdir(parents=True)
    if with_prior:
        shutil.copy(FX / "team_xg_latest_fleet_2026-10-03.csv", proc / "team_xg_latest.csv")
    return root


def _fetch(calls: list):
    score = json.loads((FX / "score_2026-10-01.json").read_text(encoding="utf-8"))
    pbp = json.loads((FX / "playbyplay_2026020009.json").read_text(encoding="utf-8"))

    def fetch(url: str):
        calls.append(url)
        if url.endswith("/score/2026-10-01"):
            return score
        if "/score/" in url:
            return {"games": []}
        if url.endswith("/gamecenter/2026020009/play-by-play"):
            return pbp
        return None  # the other 7 games' play-by-play: not in the fixture -> counted as failed
    return fetch


def _rows(path: Path):
    return {r["abbr"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}


def test_season_code():
    assert M.season_code(date(2026, 10, 4)) == "2026-2027"
    assert M.season_code(date(2027, 4, 10)) == "2026-2027"
    assert M.season_code(date(2026, 8, 31)) == "2025-2026"


def test_frozen_xg_on_a_real_game():
    pbp = json.loads((FX / "playbyplay_2026020009.json").read_text(encoding="utf-8"))
    home, away, hx, ax = M.game_xg(pbp)
    assert (home, away) == ("NJD", "PHI")
    assert 3.0 < hx + ax < 9.0          # a real NHL game's total xG
    assert hx > ax                       # NJD outshot PHI on quality in this game


def test_blend_math():
    prior = {"AAA": (3.0, 3.0)}
    assert M.blend(prior, {})["AAA"] == (3.0, 3.0, 0)                      # n = 0 -> prior exactly
    f, a, n = M.blend(prior, {"AAA": (10, 40.0, 20.0)}, w=10.0)["AAA"]      # current 4.0 / 2.0 per game
    assert (f, a, n) == pytest.approx((3.5, 2.5, 10))


def test_writes_the_season_file_the_loaders_prefer(tmp_path):
    root = _root(tmp_path)
    calls: list = []
    st = M.refresh_inseason_team_xg(root, today=date(2026, 10, 2), fetch=_fetch(calls), season_start=date(2026, 9, 28))
    assert st["wrote"] and st["season"] == "2026-2027"
    assert st["finished_regular_games"] == 8 and st["pbp_fetched"] == 1 and st["pbp_failed"] == 7
    rows = _rows(root / "data" / "processed" / "team_xg_2026-2027.csv")
    prior = _rows(root / "data" / "processed" / "team_xg_latest.csv")
    assert len(rows) == 32
    # teams with no current game keep the prior exactly
    assert rows["BOS"]["xgf60"] == prior["BOS"]["xgf60"] and rows["BOS"]["games"] == "0"
    # NJD played once: (10 * prior + 1 * current) / 11, current on the prior's scale
    pbp = json.loads((FX / "playbyplay_2026020009.json").read_text(encoding="utf-8"))
    _h, _a, hx, ax = M.game_xg(pbp)
    exp = (10 * float(prior["NJD"]["xgf60"]) + hx * M.CURRENT_TO_PRIOR_SCALE) / 11
    assert float(rows["NJD"]["xgf60"]) == pytest.approx(exp, abs=1e-4) and rows["NJD"]["games"] == "1"
    # reachability: the production loader now reads the season file, not _latest
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import load_team_xg_map
    xg = load_team_xg_map("2026-10-05", root=root)
    assert xg["NJD"]["xgf60"] == pytest.approx(float(rows["NJD"]["xgf60"]), abs=1e-4)
    assert xg["NJD"]["xgf60"] != pytest.approx(float(prior["NJD"]["xgf60"]), abs=1e-4)


def test_play_by_play_is_cached_and_not_refetched(tmp_path):
    root = _root(tmp_path)
    calls: list = []
    M.refresh_inseason_team_xg(root, today=date(2026, 10, 2), fetch=_fetch(calls), season_start=date(2026, 9, 28))
    calls2: list = []
    st = M.refresh_inseason_team_xg(root, today=date(2026, 10, 2), fetch=_fetch(calls2), season_start=date(2026, 9, 28))
    assert st["pbp_cached"] == 1 and st["pbp_fetched"] == 0
    assert not any("2026020009/play-by-play" in u for u in calls2)


def test_settled_score_days_are_cached(tmp_path):
    root = _root(tmp_path)
    calls: list = []
    M.refresh_inseason_team_xg(root, today=date(2026, 10, 6), fetch=_fetch(calls), season_start=date(2026, 9, 28))
    calls2: list = []
    M.refresh_inseason_team_xg(root, today=date(2026, 10, 6), fetch=_fetch(calls2), season_start=date(2026, 9, 28))
    score_calls = [u for u in calls2 if "/score/" in u]
    # only the two unsettled days (today and yesterday) are re-read; 09-28..10-04 come from the cache
    assert sorted(u.rsplit("/", 1)[1] for u in score_calls) == ["2026-10-05", "2026-10-06"]


def test_missing_prior_writes_nothing(tmp_path):
    root = _root(tmp_path, with_prior=False)
    st = M.refresh_inseason_team_xg(root, today=date(2026, 10, 2), fetch=_fetch([]), season_start=date(2026, 9, 28))
    assert not st["wrote"]
    assert not (root / "data" / "processed" / "team_xg_2026-2027.csv").exists()


def test_never_raises(tmp_path):
    root = _root(tmp_path)

    def boom(url):
        raise RuntimeError("feed down")
    st = M.refresh_inseason_team_xg(root, today=date(2026, 10, 2), fetch=boom, season_start=date(2026, 9, 28))
    assert not st["wrote"] and "error=" in st["reason"]
