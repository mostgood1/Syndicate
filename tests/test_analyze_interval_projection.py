"""The interval error curve, its fitted rates, and the split that keeps it honest.

**THIS SCRIPT HAD NO TESTS AND ITS OUTPUT WAS REPORTED AS A RESULT.** The error
curve (5.43 -> 1.76 points) and the finding that game-to-date pace HURTS both
came out of it, and nothing pinned either. Worse, it now FITS constants before
scoring them, which is exactly where leakage hides: a train/test split that
silently includes the test games makes any model look like it learned the season
when it only memorised it.

So the tests below check the machinery that could lie, not the arithmetic that
cannot: that the split is temporal and disjoint, that the fit RECOVERS an
injected late-minute lift rather than inventing one, and that `league_late`
beats the flat model when the lift is real and does not when it is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.analyze_interval_projection as interval
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path

PERIOD = 600.0
PERIODS = 4
BASE_STEP = 15.0          # one possession every 15s == 4.0 possessions/min


def _game(late_multiplier: float) -> dict:
    """Constant pace, two points every possession, EXCEPT the final minute of
    each period where possessions arrive `late_multiplier` times as fast.

    Points per possession is held at exactly 2.0 everywhere so the fit is
    measuring pace and only pace. A fixture that moved both at once could not
    tell which one the code recovered.
    """
    pressure, scoring = [], []
    poss = t = 0.0
    while t < PERIOD * PERIODS:
        left = PERIOD - (t % PERIOD)
        step = BASE_STEP / late_multiplier if left <= interval.LATE_WINDOW else BASE_STEP
        poss += 1.0
        sign = 1.0 if int(poss) % 2 else -1.0
        pressure.append({"clock_seconds": t, "possession_index": poss, "sign": sign,
                         "weight": 1.0, "type": "shot_attempt_2",
                         "team": "IND" if sign > 0 else "NYL"})
        scoring.append({"clock_seconds": t, "possession_index": poss,
                        "team": "IND" if sign > 0 else "NYL",
                        "sign": sign, "weight": 2.0})
        t += step
    return {"pressure": pressure, "narrator": scoring,
            "home_tri": "IND", "away_tri": "NYL"}


def _write(root: Path, days: list[str], late_multiplier: float, per_day: int = 4) -> Path:
    for day in days:
        path = momentum_events_path(root, league_code="wnba", date_str=day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"games": {f"g{i}": _game(late_multiplier) for i in range(per_day)}}))
    return root


def _days(n: int) -> list[str]:
    return [f"2026-05-{d:02d}" for d in range(1, n + 1)]


def _run(root: Path, capsys, *extra: str) -> str:
    days = _days(10)
    interval.main(["--league", "wnba", "--start", days[0], "--end", days[-1],
                   "--data-root", str(root), *extra])
    return capsys.readouterr().out


def _field(out: str, marker: str, key: str) -> float:
    for line in out.splitlines():
        if marker in line and f"{key}=" in line:
            return float(line.split(f"{key}=")[1].split()[0].rstrip("x"))
    raise AssertionError(f"no {marker} line carrying {key} in:\n{out}")


# --------------------------------------------------------------------------
# The split


def test_train_and_test_are_disjoint_and_temporal(tmp_path, capsys) -> None:
    """**THE LEAKAGE GUARD.** 10 days at 0.7 must train on the FIRST 7 and score
    on the last 3 -- never overlapping, never shuffled."""
    out = _run(_write(tmp_path, _days(10), late_multiplier=1.0), capsys)
    assert "train_days=7/10" in out, out
    train = _field(out, "SEASON", "train_games")
    test = _field(out, "SEASON", "test_games")
    total = _field(out, "SEASON", "games")
    assert (train, test, total) == (28.0, 12.0, 40.0), (train, test, total)
    assert "SPLIT_DEGENERATE" not in out


def test_a_single_day_says_so_instead_of_silently_scoring_itself(tmp_path, capsys) -> None:
    """One day cannot be split. Reporting in-sample numbers is acceptable; doing
    it WITHOUT SAYING SO is not, and is the failure this line exists to prevent."""
    root = _write(tmp_path, ["2026-05-01"], late_multiplier=1.0)
    interval.main(["--league", "wnba", "--start", "2026-05-01", "--end", "2026-05-01",
                   "--data-root", str(root)])
    out = capsys.readouterr().out
    assert "SPLIT_DEGENERATE" in out, out


def test_no_games_exits_three(tmp_path, capsys) -> None:
    assert interval.main(["--league", "wnba", "--start", "2026-05-01",
                          "--end", "2026-05-02", "--data-root", str(tmp_path)]) == 3


# --------------------------------------------------------------------------
# The fit


def test_period_segments_clamp_both_halves_to_the_last_play(tmp_path) -> None:
    """A game ending mid-period must not contribute unplayed NORMAL seconds --
    that would deflate `pace_normal` and inflate the late lift measured against
    it, manufacturing the very effect the script is testing for."""
    full = interval._period_segments("wnba", 2400.0)
    assert full[-1] == (1800.0, 2340.0, 2340.0, 2400.0)

    mid = interval._period_segments("wnba", 1450.0)
    n_lo, n_hi, l_lo, l_hi = mid[-1]
    assert n_hi == 1450.0, "normal half must stop at the last play"
    assert l_hi <= l_lo, "and the late half of an unplayed minute must be empty"


def test_fit_recovers_an_injected_late_lift(tmp_path, capsys) -> None:
    """**THE FALSIFICATION.** Doubling final-minute pace must read as ~2x, and
    flat pace must read as ~1x. A fit that always reports a lift is as useless
    as one that never does."""
    lifted = _run(_write(tmp_path / "lift", _days(10), late_multiplier=2.0), capsys)
    assert _field(lifted, "FITTED_RATES", "pace_lift") == pytest.approx(2.0, abs=0.15)

    flat = _run(_write(tmp_path / "flat", _days(10), late_multiplier=1.0), capsys)
    assert _field(flat, "FITTED_RATES", "pace_lift") == pytest.approx(1.0, abs=0.15)


def test_fit_separates_pace_from_efficiency(tmp_path, capsys) -> None:
    """The fixture scores exactly 2.0 per possession everywhere, so a lift in
    pace must NOT show up as a lift in points-per-possession. If it does, the
    two are being conflated and the mechanism is not what it claims."""
    out = _run(_write(tmp_path, _days(10), late_multiplier=2.0), capsys)
    assert _field(out, "FITTED_RATES", "ppp_normal") == pytest.approx(2.0, abs=0.05)
    assert _field(out, "FITTED_RATES", "ppp_late") == pytest.approx(2.0, abs=0.05)


# --------------------------------------------------------------------------
# The model


def test_late_split_reduces_to_the_flat_model_when_the_rates_agree() -> None:
    rates = {"pace_normal": 4.0, "ppp_normal": 1.1, "pace_late": 4.0, "ppp_late": 1.1,
             "league_ppp": 1.1}
    for left in (30.0, 60.0, 120.0, 599.0):
        assert interval._league_late_projection(left, rates) == pytest.approx(
            4.0 * (left / 60.0) * 1.1)


def test_late_split_prices_only_the_final_minute_differently() -> None:
    rates = {"pace_normal": 4.0, "ppp_normal": 1.0, "pace_late": 8.0, "ppp_late": 1.0,
             "league_ppp": 1.0}
    # 30s left: entirely inside the late window.
    assert interval._league_late_projection(30.0, rates) == pytest.approx(8.0 * 0.5)
    # 120s left: one late minute plus one normal minute.
    assert interval._league_late_projection(120.0, rates) == pytest.approx(8.0 + 4.0)
    # And it never runs backwards.
    assert interval._league_late_projection(0.0, rates) == 0.0


def test_league_late_is_reported_and_can_win(tmp_path, capsys) -> None:
    """**REACHABILITY BEFORE CORRECTNESS.** A model that is computed but never
    compared is indistinguishable from one that is broken.

    Judged against `LATE_SPLIT_VS_FLAT`, never `..._CONFOUNDED` -- the confounded
    line moves the pace source and the mechanism together, so a win there is not
    evidence about the mechanism."""
    out = _run(_write(tmp_path, _days(10), late_multiplier=3.0), capsys)
    assert "league_flat=" in out and "league_late=" in out, out
    assert "LATE_SPLIT_VS_FLAT" in out, out
    assert _field(out, "LATE_SPLIT_VS_FLAT", "improvement") > 0.0, (
        "with pace tripled in the final minute, pricing it separately must beat "
        "a single blended league rate")


def test_the_control_differs_from_the_mechanism_by_the_mechanism_alone() -> None:
    """**THE WHOLE POINT OF `league_flat`.** With no late lift the control and
    the mechanism must agree exactly; with one they must not. If they agreed
    always, the comparison would be vacuous -- and if they differed even when
    the rates are identical, it would be measuring something else."""
    flat = {"pace_normal": 4.0, "ppp_normal": 1.1, "pace_late": 4.0, "ppp_late": 1.1,
            "pace_all": 4.0, "league_ppp": 1.1}
    for left in (30.0, 90.0, 300.0, 599.0):
        assert interval._league_flat_projection(left, flat) == pytest.approx(
            interval._league_late_projection(left, flat)), left

    lifted = dict(flat, pace_late=8.0, pace_all=4.4)
    assert interval._league_flat_projection(30.0, lifted) != pytest.approx(
        interval._league_late_projection(30.0, lifted))


def test_the_control_uses_the_BLENDED_pace_not_the_normal_one() -> None:
    """**A MUTATION THAT SURVIVED THE FIRST DRAFT OF THESE TESTS.** Swapping
    `pace_all` for `pace_normal` inside the control passed everything -- and it
    is the worst possible bug here, because it makes the control under-project
    the final minute and hands the mechanism a win by construction.

    Pinned against an explicit expected value, with all three rates distinct so
    picking the wrong one cannot coincide with the right answer."""
    rates = {"pace_normal": 3.0, "ppp_normal": 1.0, "pace_late": 9.0, "ppp_late": 1.0,
             "pace_all": 4.0, "league_ppp": 2.0}
    assert interval._league_flat_projection(120.0, rates) == pytest.approx(
        4.0 * 2.0 * 2.0), "must be pace_all x minutes x league_ppp"
    assert interval._league_flat_projection(120.0, rates) != pytest.approx(
        3.0 * 2.0 * 2.0), "and must NOT be pace_normal"
    assert interval._league_flat_projection(120.0, rates) != pytest.approx(
        9.0 * 2.0 * 2.0), "nor pace_late"


def test_blended_pace_sits_between_the_normal_and_late_rates(tmp_path, capsys) -> None:
    """`pace_all` is what a single-rate model would use. If it did not lie
    between the two it is not a blend of them, and the control is not a control."""
    out = _run(_write(tmp_path, _days(10), late_multiplier=2.0), capsys)
    normal = _field(out, "FITTED_RATES", "pace_normal")
    late = _field(out, "FITTED_RATES", "pace_late")
    blended = _field(out, "FITTED_RATES", "pace_all")
    assert normal < blended < late, (normal, blended, late)


def test_the_pace_source_knob_is_reported_separately(tmp_path, capsys) -> None:
    """Two knobs, two lines. A single number covering both is what made the
    first held-out result unreadable."""
    out = _run(_write(tmp_path, _days(10), late_multiplier=2.0), capsys)
    assert "PACE_SOURCE" in out, out
    assert "LATE_SPLIT_VS_FLAT" in out, out
    assert "LATE_SPLIT_VS_LEAGUE_RATE_CONFOUNDED" in out, (
        "the confounded comparison stays, but must be NAMED as confounded")
