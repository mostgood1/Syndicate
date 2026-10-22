"""scripts/nba_sim_minutes_audit.py: the per-side minutes numbers and the pre-registered rule's arithmetic
(lane nba-sim-minutes-allocation)."""
from __future__ import annotations

import pytest

from scripts import nba_sim_minutes_audit as a


def test_spliced_match_finds_a_name_with_reason_words_spliced_in():
    # What the official-PDF parse produced on 2026-10-21 (props refresh log, SMART_SIM_REUSE_STALE_EXCLUSIONS).
    assert a.spliced_match("isaiah stewart", ["ISAIAH WAY STEWART"]) == "ISAIAH WAY STEWART"
    assert a.spliced_match("ben simmons", ["BEN SUBLUXATION SIMMONS"]) == "BEN SUBLUXATION SIMMONS"
    assert a.spliced_match("isaiah stewart", ["ISAIAH STEWART"]) is None          # same length: a plain match
    assert a.spliced_match("jalen wilson", ["JALEN TEAR WILSON", "JALEN BRUNSON"]) == "JALEN TEAR WILSON"
    assert a.spliced_match("mark williams", ["MARK SMITH JONES"]) is None
    assert a.spliced_match("nene", ["NENE X"]) is None                             # one token: never guessed


def _sim(rows, excluded=None):
    return {"players": {"home": rows}, "context": {"excluded_players": {"BOS": excluded or []}}}


def test_audit_side_splits_dnp_mass_bias_and_outside_minutes():
    sim = _sim([
        {"player_name": "A Starter", "min_mean": 30.0, "pts_mean": 20.0},
        {"player_name": "B Bench", "min_mean": 20.0, "pts_mean": 8.0},
        {"player_name": "C Hurt", "min_mean": 15.0, "pts_mean": 6.0},
        {"player_name": "D Deep", "min_mean": 10.0, "pts_mean": 3.0},
    ], excluded=["C WAY HURT"])
    box = {"a starter": {"min": 36.0, "starter": True, "name": "A Starter"},
           "b bench": {"min": 18.0, "starter": False, "name": "B Bench"},
           "e rookie": {"min": 12.0, "starter": False, "name": "E Rookie"}}
    s = a.audit_side(sim, "home", "BOS", box, lines={"a starter": 22.5}, priced={"a starter", "e rookie"}, listed=set())
    assert s["dnp_n"] == 2 and s["dnp_sim_min"] == pytest.approx(25.0)
    assert s["dnp_by_cause"] == {"injury_listed_unmatched": 15.0, "unlisted": 10.0}
    assert s["starter_bias"] == pytest.approx(-6.0) and s["bench_bias"] == pytest.approx(2.0)
    assert s["outside_min"] == pytest.approx(12.0) and s["outside"][0]["priced"] is True
    row = next(r for r in s["rows"] if r["key"] == "a starter")
    assert row["line_min"] == pytest.approx(30.0 * 22.5 / 20.0)


def test_cluster_ci_is_the_pooled_mean_and_brackets_it():
    m, lo, hi, n = a.cluster_ci({"s1": [1.0, 2.0], "s2": [3.0], "s3": [2.0, 2.0]}, n_boot=2000)
    assert m == pytest.approx(2.0) and n == 5 and lo <= m <= hi


def _side(name, diffs, engaged=True):
    rows = [{"played": True, "priced": True, "box_starter": True, "actual_min": 30.0, "off": 30.0, "on": 30.0 + d}
            for d in diffs]
    return {"date": "2026-10-23", "team": name, "engaged": engaged, "rows": rows}


def test_replay_rule_verdicts():
    worse = [_side(f"T{i}", [2.0, 3.0, 2.5]) for i in range(6)]
    assert a.replay_rule(worse)["verdict"] == "FAIL"
    better = [{**s, "rows": [{**r, "off": 34.0, "on": 31.0} for r in s["rows"]]} for s in worse]
    assert a.replay_rule(better)["verdict"] == "PASS"
    assert a.replay_rule(better, min_rows=500)["verdict"] == "INCONCLUSIVE"
    # Sides where ON did not engage never enter the primary.
    assert a.replay_rule([_side("X", [5.0], engaged=False)])["primary"][3] == 0
