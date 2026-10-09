"""Hermetic tests for scripts/basketball_live_checkpoint_backtest.py (lane nba-native-live-resim).

A synthetic ESPN summary drives parsing, checkpoint state, truth, the vendored-formula replay and grading.
No network, no data/ (worktrees have none)."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "basketball_live_checkpoint_backtest",
    Path(__file__).resolve().parents[1] / "scripts" / "basketball_live_checkpoint_backtest.py",
)
bt = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
import sys

sys.modules[_SPEC.name] = bt
_SPEC.loader.exec_module(bt)

NBA = bt.LEAGUES["nba"]


def _play(pid, period, clock, home, away, typ, team="", scoring=False, value=0, parts=(), shooting=False, text=""):
    return {
        "id": str(pid), "type": {"text": typ}, "text": text or typ, "homeScore": home, "awayScore": away,
        "period": {"number": period}, "clock": {"displayValue": clock}, "scoringPlay": scoring,
        "scoreValue": value, "team": {"id": team} if team else {}, "shootingPlay": shooting,
        "participants": [{"athlete": {"id": p}} for p in parts], "wallclock": f"2026-01-01T00:{pid % 60:02d}:00Z",
    }


def _summary(q=((30, 25), (28, 27), (20, 30), (25, 22)), extra_plays=()):
    """Home team id 1 ('HOM'), away id 2 ('AWY'); one scoring play per team per quarter closes each period."""
    plays, pid, h, a = [], 1, 0, 0
    for i, (qh, qa) in enumerate(q, start=1):
        plays.append(_play(pid, i, "12:00" if i <= 4 else "5:00", h, a, "Jump Shot", "1", parts=("h1",), shooting=True)); pid += 1
        if i == 4:
            # a foul + FTs exactly at 5:00 of Q4 (must be INSIDE the q4_5min state)
            plays.append(_play(pid, 4, "5:00", h, a, "Shooting Foul", "2", parts=("a1", "h1"))); pid += 1
            h += 2
            plays.append(_play(pid, 4, "5:00", h, a, "Free Throw - 2 of 2", "1", scoring=True, value=1, parts=("h1",))); pid += 1
            plays.append(_play(pid, 4, "4:59", h, a, "Substitution", "1", parts=("h6", "h1"))); pid += 1
            qh -= 2
        h += qh
        plays.append(_play(pid, i, "0:30", h, a, "Jump Shot", "1", scoring=True, value=2, parts=("h1",), shooting=True)); pid += 1
        a += qa
        plays.append(_play(pid, i, "0:00", h, a, "Jump Shot", "2", scoring=True, value=2, parts=("a1",), shooting=True)); pid += 1
        plays.append(_play(pid, i, "0:00", h, a, "End Period", "")); pid += 1
    plays.extend(extra_plays)
    ls = list(zip(*q))
    return {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1", "abbreviation": "HOM"}, "score": str(sum(ls[0])),
             "linescores": [{"displayValue": str(x)} for x in ls[0]]},
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "AWY"}, "score": str(sum(ls[1])),
             "linescores": [{"displayValue": str(x)} for x in ls[1]]},
        ]}]},
        "boxscore": {"players": [
            {"team": {"id": "1"}, "statistics": [{"names": ["MIN", "PTS"], "athletes": [
                {"athlete": {"id": "h1"}, "starter": True, "stats": ["36", "20"]},
                {"athlete": {"id": "h6"}, "starter": False, "stats": ["12", "2"]}]}]},
            {"team": {"id": "2"}, "statistics": [{"names": ["MIN", "PTS"], "athletes": [
                {"athlete": {"id": "a1"}, "starter": True, "stats": ["40", "22"]}]}]},
        ]},
        "plays": plays,
        "winprobability": [{"playId": str(plays[2]["id"]), "homeWinPercentage": 0.61}],
        "pickcenter": [{"spread": -4.5, "overUnder": 220.5}],
    }


def _game(**kw):
    g = bt.parse_summary(_summary(**kw), "nba", {"id": "999", "date": "2026-01-01", "season_type": 2})
    assert g is not None
    return g


def test_elapsed_seconds_regulation_and_ot():
    assert bt.elapsed_seconds(NBA, 1, 720) == 0
    assert bt.elapsed_seconds(NBA, 4, 300) == 2580
    assert bt.elapsed_seconds(NBA, 5, 300) == 2880
    assert bt.elapsed_seconds(NBA, 6, 0) == 2880 + 600


def test_parse_summary_fields():
    g = _game()
    assert (g.home, g.away, g.final_home, g.final_away) == ("HOM", "AWY", 103, 104)
    assert g.population == "regular"
    assert g.starters == {"home": ["h1"], "away": ["a1"]}
    assert g.box_minutes["h6"] == 12.0
    assert g.pickcenter == {"spread": -4.5, "total": 220.5}
    kinds = {p.kind for p in g.plays}
    assert {"shot", "foul", "ft", "sub", "end_period"} <= kinds
    sub = next(p for p in g.plays if p.kind == "sub")
    assert (sub.p1, sub.p2) == ("h6", "h1")  # entering, leaving


def test_season_types_are_separate_populations():
    s = _summary()
    pops = {bt.parse_summary(s, "nba", {"id": "1", "date": "2026-01-01", "season_type": t}).population for t in (1, 2, 3, 5)}
    assert pops == {"preseason", "regular", "postseason"}


def test_state_at_end_of_quarter_matches_linescore():
    g = _game()
    st = bt.state_at(g, "end_q2")
    assert (st.home, st.away) == (58, 52)
    assert st.period_points_so_far == [(30, 25), (28, 27)]
    assert st.remaining_regulation_s == 1440
    assert bt.state_is_consistent(g, st)


def test_state_at_q4_5min_includes_plays_at_exactly_5_00_only():
    g = _game()
    st = bt.state_at(g, "q4_5min")
    # Q1-Q3 = 78-82; FT trip at 5:00 adds 2 to home; the 4:59 sub is excluded
    assert (st.home, st.away) == (80, 82)
    assert st.player_fouls == {"a1": 1}
    assert st.team_fouls_period == {"home": 0, "away": 1}
    assert st.remaining_regulation_s == 300
    assert g.plays[st.last_play_index].clock_s == 300


def test_inconsistent_pbp_is_excluded_not_graded():
    s = _summary()
    s["header"]["competitions"][0]["competitors"][0]["linescores"][0]["displayValue"] = "31"
    g = bt.parse_summary(s, "nba", {"id": "9", "date": "2026-01-01", "season_type": 2})
    rep = bt.grade([g], [bt.PregameRateProjector()], lines={}, sims={}, live_close={}, baseline=None,
                   checkpoints=["end_q1"])
    assert rep["n_rows"] == 0
    assert rep["excluded"] == {"end_q1:pbp_linescore_mismatch": 1}


def test_truth_next_period_and_second_half():
    g = _game()
    tr = bt.truth_for(g, bt.state_at(g, "end_q1"), NBA)
    assert tr.next_period_total == 55
    assert tr.second_half_total == 97
    assert tr.final_margin == -1 and tr.home_win == 0
    assert bt.truth_for(g, bt.state_at(g, "q4_5min"), NBA).next_period_total is None


def _sim(**over):
    base = dict(total_mean=220.0, margin_mean=4.0, p_home_win=0.62,
                cum_p50_by_quarter_end=[55.0, 110.0, 165.0, 220.0], quarter_p50=[55.0] * 4, n_draws=200)
    base.update(over)
    return bt.SimSummary(**base)


def test_vendored_replay_formulas_at_quarter_boundary():
    g = _game()
    st = bt.state_at(g, "end_q2")  # 58-52, elapsed 24 min
    pre = bt.Pregame(spread_home=-4.5, total=220.5, p_home_ml=0.64, source="t", sim=_sim())
    pr = bt.VendoredReplayProjector().project(g, st, pre, NBA)
    assert pr.total == pytest.approx(110 + (220 - 110))
    assert pr.margin == pytest.approx(0.5 * 4.0 + 0.5 * 6)
    p_score = 1 / (1 + math.exp(-6 / (6 + 0.35 * 24)))
    assert pr.p_home == pytest.approx(0.5 * 0.62 + 0.5 * p_score)
    assert pr.next_period_total == pytest.approx(55.0)
    assert pr.fidelity.startswith("exact")


def test_vendored_replay_never_projects_below_actual():
    g = _game()
    st = bt.state_at(g, "end_q3")
    pr = bt.VendoredReplayProjector().project(g, st, bt.Pregame(None, None, None, "t", _sim(cum_p50_by_quarter_end=[1, 2, 3, 3])), NBA)
    assert pr.total == st.total


def test_vendored_replay_refuses_by_name_without_sim():
    g = _game()
    pr = bt.VendoredReplayProjector().project(g, bt.state_at(g, "end_q1"), bt.Pregame(-4.5, 220.5, None, "t"), NBA)
    assert pr.refusal == "no_sim_draws" and pr.total is None


def test_pregame_rate_projection_and_refusal():
    g = _game()
    st = bt.state_at(g, "end_q2")
    pr = bt.PregameRateProjector().project(g, st, bt.Pregame(-4.0, 220.0, None, "t"), NBA)
    assert pr.total == pytest.approx(110 + 110)
    assert pr.margin == pytest.approx(6 + 2)
    assert 0.5 < pr.p_home < 1
    assert bt.PregameRateProjector().project(g, st, bt.Pregame(None, None, None, "t"), NBA).refusal == "no_pregame_line"


def test_espn_wp_reads_latest_point_at_or_before_checkpoint():
    g = _game()
    pr = bt.EspnWinProbProjector().project(g, bt.state_at(g, "end_q1"), bt.Pregame(None, None, None, "t"), NBA)
    assert pr.p_home == 0.61


def test_summarize_draws_ladder():
    s = bt.summarize_draws([{"hq": [30, 30, 30, 30], "aq": [25, 25, 25, 25]}, {"hq": [20, 20, 20, 20], "aq": [30, 30, 30, 30]}])
    # draw 1: 120-100 (total 220, +20); draw 2: 80-120 (total 200, -40)
    assert s.total_mean == 210 and s.margin_mean == -10 and s.p_home_win == 0.5
    assert s.cum_p50_by_quarter_end == [52.5, 105.0, 157.5, 210.0]


def test_paired_bootstrap_is_deterministic_and_brackets_mean():
    d = [0.5, -0.2, 0.1, 0.3, -0.1, 0.4]
    a, b = bt.paired_bootstrap(d), bt.paired_bootstrap(d)
    assert a == b
    assert a[1] <= a[0] <= a[2]


def test_grade_pairs_against_baseline_and_counts_refusals():
    g = _game()
    sims = {("2026-01-01", "HOM", "AWY"): _sim()}
    rep = bt.grade([g], [bt.PregameRateProjector(), bt.VendoredReplayProjector()], lines={}, sims=sims,
                   live_close={}, baseline="vendored_replay")
    cell = next(c for c in rep["cells"] if c["checkpoint"] == "end_q2" and c["market"] == "total")
    assert cell["n_games"] == 1
    assert cell["projectors"]["pregame_rate"]["vs_vendored_replay"]["n_paired"] == 1
    rep2 = bt.grade([g], [bt.VendoredReplayProjector()], lines={}, sims={}, live_close={}, baseline=None)
    assert rep2["cells"] == []  # every projection refused -> nothing graded, nothing imputed


def test_live_close_grading_side_hits():
    g = _game()
    lc = {("999", "end_q2"): {"event_id": "999", "checkpoint": "end_q2", "total": 205.5, "spread_home": -2.5, "p_home_ml": 0.6}}
    rep = bt.grade([g], [bt.PregameRateProjector()], lines={}, sims={}, live_close=lc, baseline=None, checkpoints=["end_q2"])
    cell = next(c for c in rep["cells"] if c["market"] == "total")
    # proj 220.25 > 205.5 and final 207 > 205.5 -> hit
    assert cell["live_close"]["pregame_rate"]["side_hit_rate"] == 1.0
    assert cell["live_close"]["line_error"] == pytest.approx(1.5)


def test_trivial_truths_are_suppressed_not_graded_as_zero():
    g = _game()
    assert bt.truth_for(g, bt.state_at(g, "end_q1"), NBA).current_period_total is None
    assert bt.truth_for(g, bt.state_at(g, "end_q2"), NBA).second_half_total is None
    tr = bt.truth_for(g, bt.state_at(g, "q4_5min"), NBA)
    assert tr.current_period_total == 47 and tr.second_half_total is None


def test_live_close_rows_on_a_different_score_are_dropped(tmp_path):
    f = tmp_path / "lc.jsonl"
    f.write_text(
        '{"event_id": "1", "checkpoint": "end_q1", "score_at_snapshot_matches": false, "total": 200}\n'
        '{"event_id": "1", "checkpoint": "end_q2", "score_at_snapshot_matches": true, "total": 210}\n',
        encoding="utf-8")
    assert set(bt.load_live_close(f)) == {("1", "end_q2")}
    assert len(bt.load_live_close(f, same_score_only=False)) == 2


def test_live_close_request_never_after_the_next_period_starts():
    g = _game()
    reqs = bt.checkpoint_request_times(g, NBA)
    assert set(reqs) == set(bt.CHECKPOINTS)
    ts_q1, idx = reqs["end_q1"]
    first_q2 = next(p for p in g.plays if p.period == 2)
    assert bt._parse_iso(ts_q1) < bt._parse_iso(first_q2.wallclock)
    assert g.plays[idx].period == 1


def test_snapshot_cache_resolves_by_validity_interval(tmp_path):
    c = bt._SnapshotCache(tmp_path)
    c.add({"timestamp": "2026-01-01T00:00:00Z", "next_timestamp": "2026-01-01T00:05:00Z", "data": []})
    assert c.lookup("2026-01-01T00:04:59Z") is not None
    assert c.lookup("2026-01-01T00:05:00Z") is None
    assert bt._SnapshotCache(tmp_path).lookup("2026-01-01T00:02:00Z") is not None  # re-indexed from disk
