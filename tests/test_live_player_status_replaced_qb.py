"""A quarterback who leaves with NO injury line is caught by his replacement (lane live-player-exit-gate).

Built on the real BUF @ NYJ final of 2026-11-15 (ESPN 401873054). Geno Smith: hurt 19:25:37Z ("was injured
during the play"), "has returned to the game" 20:06:37Z, last pass 20:10:09Z. Then C.Klubnik takes every snap
from 20:18:35Z with no injury text; ESPN's injuries list posted Smith only at ~20:30Z, and on the fleet the
gate refused at the 20:38:26Z tick. The replacement rule marks him out after Klubnik's 2nd snap (20:19:52Z).
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from syndicate.features.shared import live_player_status as lps

FIX = Path(__file__).parent / "fixtures" / "live_player_status" / "nfl_401873054_final_qb_returned_then_replaced_2026-11-15.json.gz"


@pytest.fixture(scope="module")
def full():
    with gzip.open(FIX, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _at(full, cutoff):
    """The summary as a live tick at `cutoff` would have read it."""
    s = copy.deepcopy(full)
    s["header"]["competitions"][0]["status"]["type"]["state"] = "in"
    for drive in s["drives"]["previous"]:
        drive["plays"] = [p for p in drive["plays"] if (p.get("wallclock") or "") <= cutoff]
    for team in s.get("injuries") or []:
        team["injuries"] = [i for i in team["injuries"] if (i.get("date") or "") <= cutoff]
    return s


def _key(full, cutoff):
    st = lps.exits_from_espn_summary("nfl", _at(full, cutoff), game_id="401873054")
    return [(p.team, p.player, p.reason, p.since) for p in st.key_players_out]


def test_the_whole_smith_timeline(full):
    assert _key(full, "2026-11-15T19:20:00Z") == []
    assert _key(full, "2026-11-15T19:31:00Z") == [("NYJ", "Geno Smith", "injured_in_play", "2026-11-15T19:25:37Z")]
    # He came back: the hold lifts, and his BACKUP going to the bench is not an exit.
    assert _key(full, "2026-11-15T20:12:00Z") == []
    # One Klubnik snap is not enough (trick plays, package QBs) ...
    assert _key(full, "2026-11-15T19:00:00Z") == [] and _key(full, "2026-11-15T20:19:00Z") == []
    # ... the second is: 18 min before ESPN's injuries list (the fleet refused at 20:38:26Z).
    assert _key(full, "2026-11-15T20:20:50Z") == [("NYJ", "Geno Smith", "replaced", "2026-11-15T20:19:52Z")]
    assert lps.gameline_refusal(lps.exits_from_espn_summary("nfl", _at(full, "2026-11-15T20:20:50Z"), game_id="x"))[
        "players"] == ["NYJ:Geno Smith:replaced"]


def _game(plays, box):
    return {
        "header": {"competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]},
        "boxscore": {"players": [{"team": {"abbreviation": t}, "statistics": [{"name": "passing", "athletes": [
            {"athlete": {"firstName": f, "lastName": l, "displayName": f"{f} {l}"}} for f, l in names]}]}
            for t, names in box.items()]},
        "drives": {"previous": [{"plays": [{"id": str(i), "text": txt, "wallclock": f"2026-11-14T18:{i:02d}:00Z"}
                                           for i, txt in enumerate(plays)]}]},
    }


BOX = {"AAA": [("Sam", "Starter"), ("Bob", "Backup")]}


def test_a_returning_starter_clears_himself_on_his_next_snap():
    plays = ["S.Starter pass short", "B.Backup pass short", "B.Backup sacked", "S.Starter pass deep"]
    assert [p.player for p in lps.exits_from_espn_summary("ncaaf", _game(plays[:3], BOX)).players_out] == ["Sam Starter"]
    assert lps.exits_from_espn_summary("ncaaf", _game(plays, BOX)).players_out == ()


def test_a_rotating_team_stops_firing_after_the_first_rotation():
    plays = ["S.Starter pass short", "B.Backup pass short", "B.Backup pass short", "S.Starter pass deep",
             "B.Backup pass short", "B.Backup pass short", "B.Backup pass short"]
    # Healthy starter came back from a backup spell -> rotating; the later spell does not refuse.
    assert lps.exits_from_espn_summary("ncaaf", _game(plays, BOX)).players_out == ()


def test_the_college_form_and_the_off_switch_of_the_rule():
    plays = ["(10:11) Shotgun #10 S.Starter pass complete", "(09:00) Shotgun #2 B.Backup pass complete",
             "(08:30) No Huddle-Shotgun #2 B.Backup scrambles up the middle"]
    out = lps.exits_from_espn_summary("ncaaf", _game(plays, BOX)).players_out
    assert [(p.player, p.reason, p.key) for p in out] == [("Sam Starter", "replaced", True)]
    # A receiver's trick-play pass is one snap: nobody is replaced.
    trick = ["S.Starter pass short", "B.Backup pass short", "S.Starter pass deep"]
    assert lps.exits_from_espn_summary("ncaaf", _game(trick, BOX)).players_out == ()
