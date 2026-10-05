"""Daily Faceoff confirmed starters overlaid onto starting_goalies_<date>.csv (lane `nhl-confirmed-goalies`).

Fixtures are REAL:
  * dfo_2026-10-06_live.json -- the live Daily Faceoff page for 2026-10-06, parsed 2026-10-05 (statuses not yet posted)
  * lineups_ / starting_goalies_2026-10-06_fleet_BUF_MIN.csv -- production's collector output for BUF and MIN
Confirmations are applied to copies of the live record with the status/time fields set, which is how the page
reads once a starter is posted.
"""
from __future__ import annotations

import copy
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.nhl import confirmed_goalies as C
from syndicate.features.nhl.sim_engine.hockeysim.features import loaders

FX = Path(__file__).parent / "fixtures" / "nhl_confirmed_goalies"
LIVE = json.loads((FX / "dfo_2026-10-06_live.json").read_text(encoding="utf-8"))["games"]
DAY = "2026-10-06"
NOW = datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)  # before the 23:00Z puck drop


def _proc(tmp_path: Path) -> Path:
    proc = tmp_path / "nhl_source" / "data" / "processed"
    proc.mkdir(parents=True)
    shutil.copy(FX / "lineups_2026-10-06_fleet_BUF_MIN.csv", proc / f"lineups_{DAY}.csv")
    shutil.copy(FX / "starting_goalies_2026-10-06_fleet_BUF_MIN.csv", proc / f"starting_goalies_{DAY}.csv")
    return proc


def _buf_min(home_goalie=None, home_status="Confirmed", home_at="2026-10-06T17:00:00.000Z",
             away_status=None, away_at=None):
    g = copy.deepcopy(next(x for x in LIVE if x["home_team"] == "Buffalo Sabres"))
    if home_goalie:
        g["home_goalie"] = home_goalie
    g.update(home_status=home_status, home_news_at=home_at, away_status=away_status, away_news_at=away_at)
    return [g]


def _starters(proc: Path):
    return {r["team"]: r for r in csv.DictReader((proc / f"starting_goalies_{DAY}.csv").open(encoding="utf-8"))}


def test_live_page_parses_and_unposted_statuses_change_nothing(tmp_path):
    assert len(LIVE) == 9 and all(g["game_time"] for g in LIVE)
    proc = _proc(tmp_path)
    before = (proc / f"starting_goalies_{DAY}.csv").read_bytes()
    st = C.overlay(proc, DAY, LIVE, now=NOW)
    assert st["applied"] == 0 and st["wrote"] is False and st["not_confirmed"] == 18
    assert (proc / f"starting_goalies_{DAY}.csv").read_bytes() == before


def test_confirmed_backup_replaces_the_projection_with_the_lineup_name(tmp_path):
    proc = _proc(tmp_path)
    st = C.overlay(proc, DAY, _buf_min(home_goalie="Alex Lyon"), now=NOW)
    assert st["applied"] == 1 and st["changed_starter"] == 1
    s = _starters(proc)
    assert s["Buffalo Sabres"]["goalie"] == "Alex Lyon" and s["Buffalo Sabres"]["source"] == "dailyfaceoff"
    assert s["Minnesota Wild"]["source"] == "hockeysim_toi"            # not confirmed: projection stands
    # the loader marks the confirmed goalie as the starter
    rows = loaders.load_starting_goalies(DAY, root=proc.parent.parent)
    assert rows["BUF"]["goalie"] == "Alex Lyon"


@pytest.mark.parametrize("why, kwargs", [
    ("likely is not confirmed", dict(home_goalie="Alex Lyon", home_status="Likely")),
    ("posted after puck drop", dict(home_goalie="Alex Lyon", home_at="2026-10-06T23:05:00.000Z")),
    ("an undressed goalie never overrides", dict(home_goalie="Dominik Hasek")),
])
def test_guards(tmp_path, why, kwargs):
    proc = _proc(tmp_path)
    st = C.overlay(proc, DAY, _buf_min(**kwargs), now=datetime(2026, 10, 7, tzinfo=timezone.utc))
    assert st["applied"] == 0, why
    assert _starters(proc)["Buffalo Sabres"]["source"] == "hockeysim_toi"


def test_not_yet_posted_relative_to_now(tmp_path):
    proc = _proc(tmp_path)
    st = C.overlay(proc, DAY, _buf_min(home_goalie="Alex Lyon", home_at="2026-10-06T22:00:00.000Z"), now=NOW)
    assert st["applied"] == 0 and st["posted_after_start"] == 1


def test_name_key_matches_initials_accents_and_hyphens():
    assert C.name_key("Ukko-Pekka Luukkonen") == C.name_key("U. Luukkonen")
    assert C.name_key("Andrei Vasilevskiy") == C.name_key("A. Vasilevskiy")
    assert C.name_key("Samuel Montembeault") == C.name_key("Samuel Montembeault")
    assert C.name_key("Alex Lyon") != C.name_key("Ukko-Pekka Luukkonen")


def test_refresh_never_raises_and_has_an_off_switch(tmp_path, monkeypatch):
    root = _proc(tmp_path).parent.parent

    def boom(url):
        raise OSError("network down")
    assert C.refresh_confirmed_goalies(root, DAY, fetch_html=boom)["reason"].startswith("error=")
    assert C.refresh_confirmed_goalies(root, DAY, fetch_html=lambda u: "<html>no data</html>")["reason"].startswith("error=")
    monkeypatch.setenv(C.ENV, "off")
    calls = []
    st = C.refresh_confirmed_goalies(root, DAY, fetch_html=lambda u: calls.append(u))
    assert calls == [] and st["reason"] == f"{C.ENV}=off"


def test_never_applied_to_a_rebuilt_past_slate(tmp_path):
    root = _proc(tmp_path).parent.parent
    calls = []
    st = C.refresh_confirmed_goalies(root, DAY, fetch_html=lambda u: calls.append(u),
                                     now=datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert calls == [] and "outside" in st["reason"]
