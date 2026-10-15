"""Lane `sim-gap-ev-study` [2026-10-15]: the daily sim-gap x EV study that rides the scorecard cron."""

from __future__ import annotations

import collections
import json
import random
from datetime import datetime, timezone

import pytest

from syndicate.features.shared import model_scorecard as msc
from syndicate.features.shared import sim_gap_ev_study as sge
from syndicate.features.shared.opportunity_population_ledger import population_key, population_record

bs = msc.load_bucket_search()
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
CELL = "mlb|totals|full|pregame"


def _candidate(**overrides):
    row = {
        "sport": "mlb", "event_id": "evt-1", "kind": "game", "market": "totals", "segment": "full",
        "side": "over", "line": 8.5, "home_team": "Home Team", "away_team": "Away Team",
        "commence_time": "2026-09-01T23:00:00Z", "game_state": "pregame", "model_edge_pct": 6.0,
        "ev_pct": 1.0, "board_lane": "opportunity",
        "quote": {"price": 100, "fair_probability": 0.5, "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 60.0},
        "score": {"score": 1.0, "value_pct": 1.0},
    }
    row.update(overrides)
    return row


def _record(candidate, t="2026-09-01T18:00:00Z"):
    return population_record(candidate, population_key(candidate), t, sport=candidate["sport"])


def _chip(home, away, away_score, home_score, sport="mlb", state="final"):
    return {"sport": sport, "state": state, "matchup": f"{away} @ {home}",
            "away": {"name": away, "key": away.lower(), "score": away_score},
            "home": {"name": home, "key": home.lower(), "score": home_score}}


CHIPS = {"2026-09-01": [_chip("Home Team", "Away Team", 4, 6)]}   # total 10: the over wins, the home side wins


# ---------------------------------------------------------------------------
# accumulation, on rows from the REAL grader
# ---------------------------------------------------------------------------


def test_real_graded_rows_carry_every_field_the_study_reads():
    over = _record(_candidate(model_edge_pct=6.0))
    under = _record(_candidate(side="under", model_edge_pct=-6.0))
    graded, ungraded = bs.grade_population([over, under], CHIPS)
    assert ungraded == {} and len(graded) == 2
    for row in graded:
        assert {"buckets", "y", "p_market", "p_model", "model_edge_pct", "pnl", "price"} <= set(row)
    sums = sge.accumulate(graded)
    # +100 against a 0.5 fair is EV 0 -> the 0-2 band (lower bound inclusive).
    assert sums["bet"] == {f"{CELL}|gap5-10|for|ev0-2": [1, 1, 1.0, 0.0],
                           f"{CELL}|gap5-10|against|ev0-2": [1, 0, -1.0, 0.0]}
    rows, dd, dr = sums["cal"][f"{CELL}|gap5-10"]
    assert rows == 2 and dd == pytest.approx(2 * 0.06 ** 2) and dr == pytest.approx(2 * 0.06 * 0.5)
    assert sums["fit"][CELL][0] == 2 and sums["fit"][CELL][8] == 2, "both sims sit in the 0.40-0.60 mid band"


def test_a_row_without_a_sim_is_a_nosim_bet_and_never_a_calibration_row():
    row = {"buckets": [f"{CELL}|x=y"], "y": 1.0, "p_market": 0.5, "p_model": None, "model_edge_pct": None,
           "pnl": 1.0, "price": 100}
    sums = sge.accumulate([row])
    assert sums["bet"] == {f"{CELL}|nosim|none|ev0-2": [1, 1, 1.0, 0.0]}
    assert sums["cal"] == {} and sums["fit"] == {}


@pytest.mark.parametrize("edge, band", [(0.0, "gap0-2"), (1.99, "gap0-2"), (2.0, "gap2-5"), (-7.5, "gap5-10"),
                                        (10.0, "gap10-15"), (14.99, "gap10-15"), (15.0, "gap15+")])
def test_gap_bands_cover_every_value_once(edge, band):
    assert sge.gap_band(edge) == band


# ---------------------------------------------------------------------------
# the wrapper: exact pass-through, extra grading only through the bare grader
# ---------------------------------------------------------------------------


def test_wrap_grade_returns_exactly_what_grade_returns_and_regrades_only_through_base():
    over = _record(_candidate(model_edge_pct=12.0))                    # sim FOR the over, and the over won
    under = _record(_candidate(side="under", model_edge_pct=11.0))     # sim FOR the under, and the under lost
    home = _record(_candidate(market="h2h", side="home", line=None, model_edge_pct=3.0))
    calls = {"outer": 0, "base": []}

    def outer(records, chips, **kw):
        calls["outer"] += 1
        return bs.grade_population(records, chips, **kw)

    def base(records, chips, **kw):
        calls["base"].append(len(records))
        return bs.grade_population(records, chips, **kw)

    state: dict = {}
    wrapped = sge.wrap_grade(outer, state, game_key=msc.game_key, base=base)
    got = wrapped([over, under, home], CHIPS, today="2026-09-02", ungraded_by_sport={})
    assert got == bs.grade_population([over, under, home], CHIPS, today="2026-09-02")
    assert calls["outer"] == 1, "the scorecard's grader is called once, as before"
    # one lead band (all three first priced 300 minutes out), then the two big sides regraded alone
    assert calls["base"] == [3, 1, 1]
    entry = state["candidates"]["mlb|evt-1"]
    assert set(entry["lead"]) == {f"{CELL}|lead2-6h", "mlb|h2h|full|pregame|lead2-6h"}
    assert entry["bigc"] == {CELL: [2, 1]}
    assert [m["k"] for m in entry["big"]] == [under["k"]], "only the disagreement the MARKET won is listed"
    assert entry["big"][0]["gap_pts"] == pytest.approx(11.0)


def test_wrap_grade_never_breaks_the_scorecard_when_the_study_fails():
    state: dict = {}
    wrapped = sge.wrap_grade(lambda records, chips, **kw: ([{"buckets": 5}], {}), state, game_key=lambda r: "x|1")
    assert wrapped([{"k": "a"}], {}) == ([{"buckets": 5}], {})


def test_the_extra_grading_leaves_the_settler_counts_as_the_scorecard_left_them():
    class Settler:
        def __init__(self):
            self.handled = collections.Counter()

    settler = Settler()

    def grade(records, chips, **kw):
        settler.handled["calls"] += 1
        return bs.grade_population(records, chips, **kw)

    state: dict = {}
    wrapped = sge.wrap_grade(grade, state, game_key=msc.game_key, base=grade,
                             quiet=lambda: sge.keep_counters(settler, "handled"))
    wrapped([_record(_candidate(model_edge_pct=12.0))], CHIPS, today="2026-09-02", ungraded_by_sport={})
    assert settler.handled == {"calls": 1}, "the lead and big-miss regrades are not the scorecard's grading"
    assert state["candidates"]["mlb|evt-1"]["lead"], "and they did run"


def test_lead_bands_partition_pregame_sightings_and_skip_live_ones():
    seen: list[list[str]] = []

    def base(records, chips, **kw):
        seen.append(sorted(r["t"] for r in records))
        return [], {}

    start = "2026-09-03T23:00:00Z"
    records = [
        _record(_candidate(commence_time=start), t="2026-09-03T22:30:00Z"),                   # 30 min
        _record(_candidate(commence_time=start, side="under"), t="2026-09-03T19:40:00Z"),     # 200 min
        _record(_candidate(commence_time=start, market="h2h", side="home", line=None),
                t="2026-09-02T09:00:00Z"),                                                    # 38 h
        _record(_candidate(commence_time=start, game_state="live"), t="2026-09-03T23:30:00Z"),
    ]
    sge.lead_sums(records, {}, base, {})
    assert seen == [["2026-09-03T19:40:00Z"], ["2026-09-02T09:00:00Z"], ["2026-09-03T22:30:00Z"]]


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def test_commit_keeps_only_games_the_scorecard_committed():
    state = sge.empty_state("sig")
    state["candidates"] = {"mlb|a": {"sport": "mlb"}, "mlb|b": {"sport": "mlb"}}
    assert sge.commit(state, {"mlb|a": {"date": "2026-10-10"}}) == {"committed": 1, "not_committed": 1}
    assert state["games"] == {"mlb|a": {"sport": "mlb", "date": "2026-10-10"}} and "candidates" not in state


def test_state_resets_on_a_new_grader_and_drops_only_the_changed_sport():
    saved = sge.empty_state("sig", {"mlb": "1", "nhl": "1"})
    saved["games"] = {"mlb|a": {"sport": "mlb"}, "nhl|b": {"sport": "nhl"}}
    state, reason = sge.load_state(json.loads(json.dumps(saved)), "sig2", sport_versions={"mlb": "1", "nhl": "1"})
    assert reason == "grader_signature_changed" and state["games"] == {}
    state, reason = sge.load_state(json.loads(json.dumps(saved)), "sig", sport_versions={"mlb": "1", "nhl": "2"})
    assert reason == "sport_versions_changed:nhl" and set(state["games"]) == {"mlb|a"}
    assert sge.load_state(None, "sig") == (sge.empty_state("sig"), None)


# ---------------------------------------------------------------------------
# statistics, on synthetic graded games
# ---------------------------------------------------------------------------


def _row(p_market, p_model, y, price=100):
    edge = None if p_model is None else 100.0 * (p_model - p_market)
    pnl = (sge._decimal_odds(price) - 1.0) if y else -1.0
    return {"buckets": [f"{CELL}|x=y"], "y": float(y), "p_market": p_market, "p_model": p_model,
            "model_edge_pct": edge, "pnl": pnl, "price": price}


def _state(make_rows, *, n_games=60, seed=3):
    rng = random.Random(seed)
    state = sge.empty_state("sig")
    for i in range(n_games):
        day = f"2026-10-{1 + i % 12:02d}"
        state["games"][f"mlb|g{i:03d}"] = {"sport": "mlb", "date": day, **sge.accumulate(make_rows(rng))}
    return state


def test_h1_finds_for_beating_against_when_it_does_and_says_insufficient_below_the_floor():
    def rows(rng):
        return [_row(0.5, 0.56, 1), _row(0.5, 0.44, 0)]     # FOR always wins, AGAINST always loses, both EV 0

    report = sge.build_report(_state(rows), today="2026-10-15", now=NOW, resamples=200)
    (h1,) = report["betting"]["h1"]
    assert h1["verdict"] == "for_beats_against" and h1["diff"] == pytest.approx(2.0)
    thin = sge.build_report(_state(rows, n_games=sge.MIN_GAMES - 1), today="2026-10-15", now=NOW, resamples=200)
    assert thin["betting"]["h1"][0]["verdict"] == "insufficient" and thin["betting"]["h1"][0]["ci95"] is None


def test_h2_reads_a_sim_whose_small_gaps_are_right_and_whose_large_gaps_are_noise():
    def rows(rng):
        q = 0.5
        out = []
        for _ in range(40):
            small = q + rng.choice((-0.04, 0.04))
            out.append(_row(q, small, rng.random() < small))       # small gaps: the truth is the sim
        for _ in range(20):
            large = q + rng.choice((-0.12, 0.12))
            out.append(_row(q, large, rng.random() < q))           # large gaps: the truth is the market
        return out

    report = sge.build_report(_state(rows, n_games=80), today="2026-10-15", now=NOW, resamples=300)
    (h2,) = report["engine"]["trust"]["h2"]
    assert h2["verdict"] == "w_falls", h2
    by_gap = {r["gap"]: r for r in report["engine"]["trust"]["by_sport"]}
    assert by_gap["gap10-15"]["w"] == pytest.approx(0.0, abs=0.3)


def test_calibration_slope_flags_a_sim_that_is_twice_as_sure_as_the_outcomes():
    def rows(rng):
        out = []
        for _ in range(25):
            p = rng.uniform(0.2, 0.8)
            truth = 0.5 + 0.5 * (p - 0.5)
            out.append(_row(0.5, p, rng.random() < truth))
        return out

    report = sge.build_report(_state(rows, n_games=90), today="2026-10-15", now=NOW, resamples=300)
    (row,) = report["engine"]["calibration"]["by_sport"]
    assert row["verdict"] == "overconfident" and 0.2 < row["slope_sim"] < 0.8


def test_every_cell_is_counted_as_tested_and_signals_come_with_their_chance_rate():
    def rows(rng):
        return [_row(0.5, 0.53, rng.random() < 0.5) for _ in range(6)]

    report = sge.build_report(_state(rows), today="2026-10-15", now=NOW, resamples=200)
    bet = report["betting"]
    assert bet["tested"] >= 1 and bet["expected_false_signals"] == pytest.approx(0.05 * bet["tested"], abs=0.05)
    assert all(r["tested"] == (r["games"] >= sge.MIN_GAMES) for r in bet["cross"])


def test_the_report_is_json_and_order_independent_and_says_what_it_cannot_compute():
    def rows(rng):
        return [_row(0.5, 0.5 + rng.uniform(-0.12, 0.12), rng.random() < 0.5) for _ in range(5)]

    state = _state(rows)
    shuffled = dict(state, games=dict(reversed(list(state["games"].items()))))
    one = sge.build_report(state, today="2026-10-15", now=NOW, resamples=100)
    two = sge.build_report(shuffled, today="2026-10-15", now=NOW, resamples=100)
    assert sge.dumps(one) == sge.dumps(two)
    assert json.loads(sge.dumps(one))["h3"]["computable"] is False
    text = sge.markdown(one)
    for heading in ("## (A) Betting", "### H1", "### Trust in the sim", "### Mean vs spread", "### Lead time",
                    "### Big disagreements", "## Not computable"):
        assert heading in text


def test_the_window_excludes_today_and_games_older_than_the_window():
    state = sge.empty_state("sig")
    for key, day in (("mlb|old", "2026-09-10"), ("mlb|in", "2026-10-01"), ("mlb|today", "2026-10-15")):
        state["games"][key] = {"sport": "mlb", "date": day}
    assert [g["key"] for g in sge.window_games(state, "2026-10-15")] == ["mlb|in"]
