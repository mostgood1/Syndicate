from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from syndicate.features.shared import basketball_league_rules as rules
from syndicate.features.shared.basketball_league_rules import NBA, NCAAB, WNBA, expected_free_throw_points, rules_for

REPO = Path(__file__).resolve().parents[1]
VENDORED = {
    "nba": REPO / "vendor" / "nba_betting_repo" / "src" / "nba_betting" / "sim" / "events.py",
    "wnba": REPO / "vendor" / "wnba_betting_repo" / "src" / "wnba_betting" / "sim" / "events.py",
}


def _vendored_rotation_windows(league: str):
    """Load ONLY `_rotation_windows` from the vendored source, without importing the package.

    Test-only: this is the P1 parity oracle. Nothing at runtime reads vendor/.
    """
    path = VENDORED[league]
    if not path.is_file():
        pytest.skip(f"vendored engine absent: {path}")
    text = path.read_text(encoding="utf-8")
    start = text.index("def _rotation_windows(")
    end = text.index("\ndef ", start + 1)
    namespace: dict = {"Dict": dict}
    exec(compile(text[start:end], str(path), "exec"), namespace)  # noqa: S102 -- a pure function, read from our own tree
    return namespace["_rotation_windows"]


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_pro_windows_reproduce_the_vendored_function_exactly(league):
    vendored = _vendored_rotation_windows(league)
    lr = rules_for(league)
    checked = 0
    for q in range(0, 8):  # 0 and 5..7 cover the "not regulation" branch
        period_seconds = lr.seconds_in_period(max(1, q))
        for rem in range(-5, period_seconds + 6, 3):
            for margin in (-30, -15, -14, -13, -12, -11, -10, -9, -8, -7, 0, 7, 8, 9, 10, 11, 12, 13, 14, 15, 30):
                want = vendored(q=q, period_seconds=period_seconds, q_remaining=rem, margin=margin)
                got = lr.rotation_window_flags(q, rem, margin)
                assert got == want, (league, q, rem, margin)
                checked += 1
    assert checked > 20_000


def test_ncaab_rulebook():
    assert (NCAAB.periods, NCAAB.period_seconds, NCAAB.overtime_seconds) == (2, 1200, 300)
    assert NCAAB.regulation_seconds == 2400
    assert (NCAAB.shot_clock_seconds, NCAAB.shot_clock_after_offensive_rebound) == (30, 20)
    assert NCAAB.foul_out == 5 and NCAAB.fouled_out(5) and not NCAAB.fouled_out(4)
    assert NBA.foul_out == 6 and not NBA.fouled_out(5)


@pytest.mark.parametrize(
    "fouls,award",
    [(1, "none"), (6, "none"), (7, "one_and_one"), (9, "one_and_one"), (10, "two_shots"), (14, "two_shots")],
)
def test_ncaab_bonus_ladder(fouls, award):
    assert NCAAB.bonus_free_throws(fouls, period=2, remaining_in_period=30) == award


def test_ncaab_overtime_continues_the_second_half_count():
    assert NCAAB.foul_count_resets(1) and NCAAB.foul_count_resets(2)
    assert not NCAAB.foul_count_resets(3) and not NCAAB.foul_count_resets(4)
    # no separate OT threshold: 7 is still a 1-and-1 in overtime
    assert NCAAB.bonus_free_throws(7, period=3, remaining_in_period=100) == "one_and_one"


def test_nba_bonus_quarter_overtime_and_last_two_minutes():
    assert NBA.foul_count_resets(3) and NBA.foul_count_resets(5)
    assert NBA.bonus_free_throws(4, period=2, remaining_in_period=300) == "none"
    assert NBA.bonus_free_throws(5, period=2, remaining_in_period=300) == "two_shots"
    assert NBA.bonus_free_throws(4, period=5, remaining_in_period=200) == "two_shots"
    assert NBA.bonus_free_throws(3, period=4, remaining_in_period=100, fouls_in_late_window=1) == "none"
    assert NBA.bonus_free_throws(3, period=4, remaining_in_period=100, fouls_in_late_window=2) == "two_shots"
    assert NBA.bonus_free_throws(3, period=4, remaining_in_period=130, fouls_in_late_window=2) == "none"


def test_one_and_one_is_not_two_shots():
    assert expected_free_throw_points("one_and_one", 0.70) == pytest.approx(0.70 + 0.49)
    assert expected_free_throw_points("two_shots", 0.70) == pytest.approx(1.40)
    assert expected_free_throw_points("none", 0.70) == 0.0


def test_elapsed_fraction_maps_q4_onto_ten_minutes_left_in_the_second_half():
    # The vendored engine's `q >= 4` blowout gate is 0.75 of regulation.
    assert NBA.regulation_elapsed_fraction(4, 720) == pytest.approx(0.75)
    assert NCAAB.regulation_elapsed_fraction(2, 600) == pytest.approx(0.75)
    assert NCAAB.regulation_elapsed_fraction(1, 1200) == 0.0
    assert NCAAB.regulation_elapsed_fraction(3, 120) == 1.0
    assert NCAAB.elapsed_seconds(3, 120) == pytest.approx(2400 + 180)
    assert NCAAB.remaining_regulation_seconds(2, 300) == pytest.approx(300)


def test_period_share_replaces_the_vendored_quarter_divisor():
    assert NBA.period_share(1) == pytest.approx(0.25)
    assert NCAAB.period_share(1) == pytest.approx(0.5)
    assert NCAAB.period_share(3) == pytest.approx(300 / 2400)


def test_ncaab_windows_are_marked_as_priors_and_cover_both_halves():
    assert NCAAB.rotation_windows_fitted is False
    assert NCAAB.rotation_window_flags(1, 1100, 0)["opening_stint"]
    assert NCAAB.rotation_window_flags(2, 1100, 0)["opening_stint"]
    assert NCAAB.rotation_window_flags(2, 850, 0)["bench_stint"]
    assert NCAAB.rotation_window_flags(2, 120, 5)["crunch_time"]
    assert not NCAAB.rotation_window_flags(1, 120, 5)["crunch_time"]
    assert NCAAB.rotation_window_flags(1, 60, 5)["late_half_push"]
    assert not any(NCAAB.rotation_window_flags(3, 100, 0).values())


def test_unknown_league_refuses():
    with pytest.raises(KeyError):
        rules_for("euroleague")
    assert set(rules.LEAGUES) == {"nba", "wnba", "ncaab"}
    assert WNBA.period_seconds == 600
