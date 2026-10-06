"""nba_sim_availability: off != on, regular season only, this season only, K skip, prop-line re-admit, add-only."""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import nba_season_phase as ph
from syndicate.features.shared import nba_sim_availability as av
from tests.test_nba_prop_calibration import write_season_types

KEY = lambda n: str(n or "").strip().upper()  # noqa: E731


def _logs(root, rows):
    with (root / av.HISTORY).open("w", encoding="utf-8") as fh:
        fh.write("PLAYER_NAME,TEAM_ABBREVIATION,GAME_ID,GAME_DATE,MIN\n")
        for name, team, gid, d, mins in rows:
            fh.write(f"{name},{team},{gid},{d},{mins}\n")


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "_fetch_types", lambda year, timeout=10.0: None)
    write_season_types(tmp_path)
    _logs(tmp_path, [
        # NYK this season: games on 10-20, 10-22, 10-24. Starter plays all; Hurt played only 10-20; Bench never.
        ("Starter", "NYK", "0022600001", "2026-10-20", 34), ("Hurt", "NYK", "0022600001", "2026-10-20", 20),
        ("Starter", "NYK", "0022600010", "2026-10-22", 33), ("Starter", "NYK", "0022600020", "2026-10-24", 35),
        ("Priced", "NYK", "0022600001", "2026-10-20", 25),                      # missed 10-22/24 but has a prop line
        ("Lastyear", "NYK", "0022501200", "2026-04-10", 30),                    # last season only: never "seen" now
        ("Pre", "NYK", "0012600005", "2026-10-15", 30),                         # a preseason id: ignored
        # BOS has only one game this season: fewer than K -> skipped
        ("Solo", "BOS", "0022600002", "2026-10-21", 30),
    ])
    (tmp_path / "oddsapi_player_props_2026-10-26.csv").write_text(
        "market,player_name,point,price\nplayer_points,Priced,12.5,-110\nh2h,,,-150\n", encoding="utf-8")
    return tmp_path


def _run(root, date="2026-10-26", env=None, doc={"enabled": True}):
    (root / av.FILE).write_text(json.dumps(doc), encoding="utf-8")
    ex = {"NYK": {"INJURED"}}
    s = av.add_nba_recency_exclusions(ex, processed_root=root, date_str=date, league_code="nba", name_key=KEY, env=env or {})
    return ex, s


def test_reachability_off_differs_from_on(root):
    on, s_on = _run(root)
    off, s_off = _run(root, env={av.FLAG: "0"})
    assert on != off and s_on["applied"] and "off" in s_off["reason"]
    assert on["NYK"] == {"INJURED", "HURT"}                       # Hurt missed the last 2 games -> out
    assert off == {"NYK": {"INJURED"}}


def test_readmit_this_season_only_and_k_skip(root):
    ex, s = _run(root)
    assert "PRICED" not in ex["NYK"] and s["readmitted_with_prop_line"] == 1   # posted prop line -> stays in the pool
    assert "LASTYEAR" not in ex["NYK"] and "PRE" not in ex["NYK"]               # last season / preseason never count
    assert "BOS" not in ex and s["added"] == 1                                  # BOS: 1 game < K=2 -> skipped
    ex2, _ = _run(root, doc={"enabled": True, "readmit_with_prop_line": False})
    assert "PRICED" in ex2["NYK"]


def test_injury_exclusions_are_never_removed_and_add_only(root):
    ex, _ = _run(root)
    assert "INJURED" in ex["NYK"]


def test_not_applied_off_the_regular_season_or_by_default(root, tmp_path):
    _, s = _run(root, date="2026-10-10")
    assert not s["applied"] and "preseason" in s["reason"]
    (root / av.FILE).unlink()
    ex = {}
    s = av.add_nba_recency_exclusions(ex, processed_root=root, date_str="2026-10-26", league_code="nba", name_key=KEY, env={})
    assert not s["applied"] and ex == {} and "not enabled" in s["reason"]           # default OFF
    s = av.add_nba_recency_exclusions(ex, processed_root=root, date_str="2026-10-26", league_code="wnba", name_key=KEY, env={})
    assert s["reason"] == "not nba"


def test_bad_k_is_refused(root):
    _, s = _run(root, doc={"enabled": True, "k": 9})
    assert not s["applied"] and "outside" in s["reason"]
