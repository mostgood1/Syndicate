"""Layer 2 score backtest: row-level grading keeps the record, and the analysis statistics are sound."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    source = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BT = _load("score_ranking_backtest")
A = _load("score_ranking_analysis")


def _record(k: str, t: str, **extra):
    base = {"k": k, "t": t, "sport": "wnba", "ct": "2026-09-19T23:00:00Z", "gs": "pregame",
            "px": -110, "fp": 0.5, "ev": -4.5, "sc": -4.5, "bq": 5, "ln": "opportunity"}
    base.update(extra)
    return base


KEY = "evt1|totals||full|over|170.5"
PROP = "evt1|player_points|jane doe|full|over|19.5"


def test_market_family_splits_main_alt_and_props():
    assert BT.market_family("totals", False) == "game_main"
    assert BT.market_family("spreads_alt", False) == "game_alt"
    assert BT.market_family("alternate_totals_corners", False) == "game_alt"
    assert BT.market_family("player_points", True) == "prop"
    assert BT.market_family("team_totals", False) == "game_other"


def test_earliest_per_phase_keeps_one_pregame_and_one_live_sighting():
    records = [
        _record(KEY, "2026-09-19T15:00:00Z"),
        _record(KEY, "2026-09-19T12:00:00Z"),
        _record(KEY, "2026-09-19T23:30:00Z", gs="live"),
        _record(KEY, "2026-09-19T23:40:00Z", gs="live"),
    ]
    chosen = BT.earliest_per_phase(records)
    assert sorted(r["t"] for r in chosen) == ["2026-09-19T12:00:00Z", "2026-09-19T23:30:00Z"]


def test_grade_rows_carries_the_record_beside_its_outcome_and_counts_skips():
    calls = []

    def fake_grade(records, chips_by_date, named, *, today):
        calls.append(records[0]["k"])
        if records[0]["k"] == PROP:
            return [], {"player_prop": 1}
        return [{"date": "2026-09-19", "sport": "wnba", "game": "wnba|evt1", "y": 1.0, "pnl": 0.909}], {}

    records = [
        _record(KEY, "2026-09-19T12:00:00Z", sc=3.2, ev=4.0, ht="NYL", at="ATL"),
        _record(PROP, "2026-09-19T12:00:00Z"),
        _record("evt2|totals||full|over|160.5", "2026-09-20T12:00:00Z", ct="2026-09-22T23:00:00Z"),
    ]
    rows, reasons = BT.grade_rows(records, grade=fake_grade, chips_for=lambda day: [{"x": 1}],
                                  central_date=lambda ct: str(ct)[:10], today="2026-09-21")
    assert len(rows) == 1
    row = rows[0]
    assert (row["sc"], row["ev"], row["y"], row["pnl"], row["family"], row["phase"]) == (3.2, 4.0, 1.0, 0.909, "game_main", "pregame")
    assert reasons["graded"] == 1 and reasons["player_prop"] == 1 and reasons["not_yet"] == 1
    assert "evt2|totals||full|over|160.5" not in calls  # not started: never reaches the grader


def test_unreadable_scoreboard_is_counted_not_graded_as_missing():
    def boom(day):
        raise RuntimeError("502")

    rows, reasons = BT.grade_rows([_record(KEY, "2026-09-19T12:00:00Z")],
                                  grade=lambda *a, **k: pytest.fail("must not grade"),
                                  chips_for=boom, central_date=lambda ct: str(ct)[:10], today="2026-09-21")
    assert rows == [] and reasons["chips_unavailable"] == 1


def test_break_even_and_served_equivalence():
    assert A.break_even(-110) == pytest.approx(110 / 210)
    assert A.break_even(200) == pytest.approx(1 / 3)
    assert A.served_equivalent({"ln": "opportunity", "sc": 1.0, "ev": 5.0})
    assert not A.served_equivalent({"ln": "opportunity", "sc": 1.0, "ev": 5.3})  # implausible-book gate
    assert not A.served_equivalent({"ln": "dead", "sc": 1.0, "ev": 1.0})
    assert A.bet_window({"ln": "opportunity", "sc": 1.0, "ev": 2.0})
    assert not A.bet_window({"ln": "opportunity", "sc": 1.0, "ev": 1.99})


def test_kelly_growth_prefers_the_likelier_bet_at_equal_ev():
    # Two bets with the same +4% EV: an even-money shot and a +400 longshot.
    even = A.kelly_growth(0.52, 100)          # EV = 0.52*2 - 1 = +4%
    longshot = A.kelly_growth(0.208, 400)     # EV = 0.208*5 - 1 = +4%
    assert even > longshot > 0
    # Negative EV sorts below every positive-EV bet.
    assert A.kelly_growth(0.45, 100) < 0 < longshot


def test_game_bootstrap_resamples_games_not_rows():
    # Game A: 50 winning rows; games B-F: one losing row each. By ROW the mean is strongly
    # positive; by GAME the interval must straddle a much lower value.
    rows = [{"game": "A", "pnl": 1.0, "y": 1.0, "px": 100} for _ in range(50)]
    rows += [{"game": g, "pnl": -1.0, "y": 0.0, "px": 100} for g in "BCDEF"]
    lo, hi = A.game_bootstrap(rows, A.roi_of, resamples=400)
    assert lo < 0 < hi
    assert A.game_bootstrap(rows[:3], A.roi_of) is None


def test_top_k_per_date_respects_per_game_cap():
    rows = [{"date": "d1", "game": "g1", "sc": 10 - i} for i in range(5)]
    rows += [{"date": "d1", "game": "g2", "sc": 1.0}]
    picked = A.top_k_per_date(rows, lambda r: r["sc"], 3, per_game=2)
    assert [r["sc"] for r in picked] == [10, 9, 1.0]


def test_book_features_measures_the_priced_book_against_the_field():
    row = {"px": 113, "bk": "prophetx",
           "bp": {"a": -110, "b": -108, "c": -105, "prophetx": 113, "d": -112}}
    feats = A.book_features(row)
    assert feats["exchange"] is True
    assert feats["n_at_or_better"] == 1
    # median of the five implieds is the -108 book
    assert feats["gap_to_median_pp"] == pytest.approx((108 / 208 - 100 / 213) * 100, rel=1e-6)


def test_chip_index_cache_keys_on_chip_objects_not_the_temporary_list():
    calls = []

    def index(chips):
        calls.append(len(chips))
        return {"day": chips[0]["day"]}

    cached = BT.stable_chip_index(index)
    day1 = [{"day": "09-19"}, {"day": "09-19"}]
    day2 = [{"day": "09-20"}, {"day": "09-20"}]
    # grade_population passes a FRESH list(chips) on every call: same chips must hit the cache ...
    for _ in range(50):
        assert cached(list(day1)) == {"day": "09-19"}
    assert calls == [2]
    # ... and a different day's chips must never be served the first day's index.
    for _ in range(50):
        assert cached(list(day2)) == {"day": "09-20"}
    assert calls == [2, 2] and len(cached.cache) == 2
