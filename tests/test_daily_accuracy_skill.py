"""Tests for the `daily-accuracy` skill driver (lane `daily-accuracy-suite`, 2026-09-20).

The driver's whole value is that it REFUSES to present three specific silences as
health, so each test here is an `off != on` pair: the same function on a payload
that should trip it and one that should not. A checker that always says DEGRADED
is as useless as one that never does, and only the pair distinguishes them.

The fixtures are shaped from the real production payload read on 2026-09-20
(`/api/model-scorecard`, 153,178 B, 263 cells, recorder_start 2026-09-14), not
invented: the degenerate case under test -- `7d` and `28d` holding byte-identical
cells -- is what production was actually serving that day.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / ".claude" / "skills" / "daily-accuracy" / "driver.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location("daily_accuracy_driver", DRIVER_PATH)
    assert spec and spec.loader, f"cannot load {DRIVER_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


driver = _load_driver()
NOW = datetime(2026, 9, 20, 17, 0, 0, tzinfo=timezone.utc)


def _cell(sport="mlb", market="h2h", segment="full", phase="pregame", verdict="insufficient"):
    return {"sport": sport, "market": market, "segment": segment, "phase": phase,
            "verdict": verdict, "brier_diff": 0.001, "games": 10, "dates": 3, "lodo_stable": True}


def _scorecard(*, windows, generated_at="2026-09-20T11:31:56Z", recorder_start="2026-09-14"):
    for window in windows.values():
        window.setdefault("coverage", {})["recorder_start"] = recorder_start
    return {"version": "model_scorecard/1", "today_central": "2026-09-20",
            "generated_at": generated_at, "grader": {"sport_versions": {}}, "windows": windows}


# --------------------------------------------------------------------------------------
# 1. A window label is a claim about how much history backs it.
# --------------------------------------------------------------------------------------


def test_a_window_backed_by_less_history_than_its_label_is_degraded():
    """The production case: 28d over a recorder that started 2026-09-14."""
    card = _scorecard(windows={"28d": {"cells": [_cell()]}})
    degraded, why = driver.window_is_degraded(card, "28d")
    assert degraded is True
    assert "6d" in why and "28d" in why


def test_the_same_check_passes_a_window_its_recorder_can_back():
    """off != on -- without this the checker could be hard-coded to DEGRADED."""
    card = _scorecard(windows={"7d": {"cells": [_cell()]}}, recorder_start="2026-09-01")
    degraded, why = driver.window_is_degraded(card, "7d")
    assert degraded is False
    assert why == ""


def test_the_producers_published_verdict_is_preferred_over_recomputing_it():
    """`model_scorecard.window_span` owns this number. Two independently-computed
    answers to one question is the argument this tool exists to avoid, so a
    published `window_span` must win even when the fallback would disagree."""
    card = _scorecard(windows={"28d": {"cells": [_cell()], "coverage": {
        "window_span": {"nominal_days": 28, "effective_days": 28, "degraded": False,
                        "degraded_reason": None}}}}, recorder_start="2026-09-14")
    # The fallback, left to itself, would call this degraded (recorder started 6d ago).
    assert driver.window_is_degraded(card, "28d") == (False, "")


def test_a_published_degraded_verdict_carries_the_producers_own_reason():
    card = _scorecard(windows={"28d": {"cells": [_cell()], "coverage": {
        "window_span": {"nominal_days": 28, "effective_days": 6, "degraded": True,
                        "degraded_reason": "the recorder started 2026-09-14, so this "
                                           "window is backed by 6d of population, not 28d"}}}})
    degraded, why = driver.window_is_degraded(card, "28d")
    assert degraded is True
    assert why.startswith("the recorder started 2026-09-14")


def test_identical_cells_to_a_shorter_window_are_degraded_even_with_a_long_recorder():
    """The second, independent test: a recorder old enough to back 28d, but the 28d
    window holds nothing the 7d one does not. Recorder age alone would pass this."""
    shared = [_cell(), _cell(market="totals")]
    card = _scorecard(windows={"7d": {"cells": list(shared)}, "28d": {"cells": list(shared)}},
                      recorder_start="2026-01-01")
    assert driver.window_is_degraded(card, "7d")[0] is False
    degraded, why = driver.window_is_degraded(card, "28d")
    assert degraded is True
    assert "identical" in why


def test_a_genuinely_wider_window_is_not_degraded():
    card = _scorecard(windows={"7d": {"cells": [_cell()]},
                               "28d": {"cells": [_cell(), _cell(market="totals")]}},
                      recorder_start="2026-01-01")
    assert driver.window_is_degraded(card, "28d")[0] is False


# --------------------------------------------------------------------------------------
# 2. Ungraded rows are a rate, not a count.
# --------------------------------------------------------------------------------------


def test_ungraded_is_reported_as_a_rate_against_rows_considered():
    window = {"coverage": {
        "by_sport": {"soccer": {"graded_rows": 90}},
        "ungraded_by_sport": {"soccer": {"player_not_in_box": 10}},
    }}
    (sport, reason, count, graded, rate), = driver.ungraded_rates(window)
    assert (sport, reason, count, graded) == ("soccer", "player_not_in_box", 10, 90)
    assert rate == pytest.approx(0.10)  # 10 of (90 graded + 10 ungraded)


def test_the_bigger_count_is_not_always_the_worse_rate():
    """The reason rates exist. A count-sorted report would put mlb first and be wrong."""
    window = {"coverage": {
        "by_sport": {"mlb": {"graded_rows": 57598}, "wnba": {"graded_rows": 1000}},
        "ungraded_by_sport": {"mlb": {"no_boxscore": 2866}, "wnba": {"game_not_final": 900}},
    }}
    rates = driver.ungraded_rates(window)
    assert [row[0] for row in rates] == ["wnba", "mlb"]
    assert rates[0][2] < rates[1][2]  # wnba's COUNT is smaller and its RATE is worse


# --------------------------------------------------------------------------------------
# 3. Off-season and absent must not print the same.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("sport,expected", [("nba", False), ("ncaab", False), ("nfl", True),
                                            ("ncaaf", True), ("nhl", True), ("mlb", True)])
def test_season_labels_on_the_date_this_was_written(sport, expected):
    """2026-09-20: NFL/NCAAF/NHL/MLB in season, NBA and NCAAB not. This is what lets the
    report call NHL's zero a DEFECT and NBA's absence a deliberate cost decision."""
    assert driver.in_season(sport, NOW) is expected


def test_a_sport_with_no_season_window_returns_none_rather_than_guessing():
    assert driver.in_season("kabaddi", NOW) is None


def test_wrapping_season_windows_work_across_the_new_year():
    assert driver.in_season("nfl", datetime(2027, 1, 10, tzinfo=timezone.utc)) is True
    assert driver.in_season("nfl", datetime(2026, 5, 10, tzinfo=timezone.utc)) is False


# --------------------------------------------------------------------------------------
# 4. Freshness is judged on the artifact, and a stale one is a non-zero exit.
# --------------------------------------------------------------------------------------


def test_a_stale_artifact_fails_loudly_rather_than_reporting_its_contents_as_current():
    card = _scorecard(windows={"7d": {"cells": [_cell()]}}, generated_at="2026-09-17T11:31:56Z")
    lines, code = driver.build_report(card, {}, None, max_age_hours=26.0, now=NOW)
    assert code == 2
    assert lines[0].startswith("FAIL stale artifact")


def test_a_fresh_artifact_exits_zero():
    card = _scorecard(windows={"7d": {"cells": [_cell()]}})
    lines, code = driver.build_report(card, {}, None, max_age_hours=26.0, now=NOW)
    assert code == 0
    assert not any(line.startswith("FAIL") for line in lines)


def test_a_sport_that_was_graded_and_is_not_any_more_is_a_regression():
    previous = _scorecard(windows={"7d": {"cells": [_cell(sport="wnba"), _cell(sport="mlb")]}})
    current = _scorecard(windows={"7d": {"cells": [_cell(sport="mlb")]}})
    _lines, code = driver.build_report(current, {}, previous, max_age_hours=26.0, now=NOW)
    assert code == 3
