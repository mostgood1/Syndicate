"""`S3` -- the sim's per-inning run vectors survive to the artifact.

`daily_update.seg_score(r, innings)` SUMS A PREFIX of `GameResult.away_inning_runs`
/ `home_inning_runs`, so the nine-plus element vector the simulation builds on
every run collapses into four cumulative scalars and `r` is dropped at the next
loop iteration. Nothing downstream can price an inning-level or rest-of-game
market off a prefix sum.

These tests are ordered the way the model-engine standard requires:
REACHABILITY FIRST (`off != on`, and the off case unchanged), then the counts,
then the reconciliation against the segment writer that reads the same vectors.

WHAT "RECONSTRUCTS" CAN AND CANNOT MEAN HERE. The accumulator keeps MARGINALS --
per-inning histograms -- and deliberately keeps no per-sim rows, because keeping
rows is the memory cost this package exists to avoid. A joint game-total
distribution cannot be rebuilt from marginals by any arithmetic. Two exact
identities are available and both are asserted with integer equality and no
tolerance:

  * inning "1" IS `segments.first1` -- one inning, no convolution needed, so this
    is a full DISTRIBUTION equality, the strongest check in the file.
  * run MASS (sum of value*count) is additive across innings, so innings 1..9
    plus extras must account for exactly the runs `segments.full.total_runs_dist`
    accounts for, and innings 1..3 for exactly `segments.first3`.

A disagreement in either is a real finding about one of the two writers, not
something to paper over by reshaping the new block.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "vendor", "mlb_bettingv2"))
sys.path.insert(0, os.path.join(_REPO, "vendor", "mlb_bettingv2", "tools"))

from sim_engine.inning_distributions import (  # noqa: E402
    ALL_KEYS,
    ENV_FLAG,
    EXTRAS_KEY,
    INNING_KEYS,
    InningRunAccumulator,
    enabled,
    hist_count,
    hist_mass,
)
from sim_engine.models import (  # noqa: E402
    BatterProfile,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    Player,
    Team,
    TeamRoster,
)

SEED = 90909


def _player(pid: int, name: str) -> Player:
    return Player(
        mlbam_id=pid,
        full_name=name,
        primary_position="OF",
        bat_side=Handedness.R,
        throw_side=Handedness.R,
    )


def _roster(team_id: int, abbr: str, base_pid: int) -> TeamRoster:
    batters = []
    for slot in range(9):
        pid = base_pid + slot
        prof = BatterProfile(player=_player(pid, f"{abbr} Batter {slot}"))
        prof.hr_rate = 0.045 - 0.003 * slot
        prof.k_rate = 0.20 + 0.01 * slot
        prof.inplay_hit_rate = 0.30
        batters.append(prof)
    starter = PitcherProfile(player=_player(base_pid + 50, f"{abbr} Starter"))
    starter.role = "SP"
    bullpen = []
    for idx in range(4):
        arm = PitcherProfile(player=_player(base_pid + 60 + idx, f"{abbr} Arm {idx}"))
        arm.role = "RP"
        bullpen.append(arm)
    return TeamRoster(
        team=Team(team_id=team_id, name=abbr, abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(batters=batters, pitcher=starter, bench=[], bullpen=bullpen),
    )


@pytest.fixture(scope="module")
def rosters():
    return _roster(1, "AWY", 100), _roster(2, "HOM", 200)


def _run(rosters, *, sims: int = 240, workers: int = 1, flag: str | None):
    """One `_sim_many` over the real engine, with the flag set or unset."""
    from daily_update import _sim_many

    prior = os.environ.get(ENV_FLAG)
    if flag is None:
        os.environ.pop(ENV_FLAG, None)
    else:
        os.environ[ENV_FLAG] = flag
    try:
        away, home = rosters
        return _sim_many(
            away_roster=away,
            home_roster=home,
            sims=sims,
            seed=SEED,
            workers=workers,
            hitter_props_top_n=24,
        )
    finally:
        if prior is None:
            os.environ.pop(ENV_FLAG, None)
        else:
            os.environ[ENV_FLAG] = prior


@pytest.fixture(scope="module")
def out_off(rosters):
    return _run(rosters, flag=None)


@pytest.fixture(scope="module")
def out_on(rosters):
    return _run(rosters, flag="on")


# --- (a) REACHABILITY -------------------------------------------------------


def test_flag_absent_means_off(monkeypatch):
    """ABSENT MUST NOT DEFAULT PERMISSIVE.

    The sibling `SYNDICATE_MLB_CONDITIONAL_MIX` in the same file defaults ON and
    is switched OFF, so the idiom alone tells you nothing -- this pins the
    direction, which is the whole basis of the byte-identity claim below.
    """
    monkeypatch.delenv(ENV_FLAG, raising=False)
    assert enabled() is False
    for value in ("", "off", "0", "false", "no", "  "):
        monkeypatch.setenv(ENV_FLAG, value)
        assert enabled() is False, value
    for value in ("on", "1", "true", "YES", " On "):
        monkeypatch.setenv(ENV_FLAG, value)
        assert enabled() is True, value


def test_off_writes_nothing_and_on_writes_a_populated_block(out_off, out_on):
    assert "innings" not in out_off, "flag absent still published sim.innings"
    innings = out_on.get("innings")
    assert innings, "flag on produced no sim.innings -- the accumulator is not reachable"
    assert innings["distribution_version"] == 1
    assert innings["sims"] == 240
    assert set(innings["by_inning"].keys()) == set(ALL_KEYS)


def test_turning_the_flag_ON_changes_NOTHING_ELSE(out_off, out_on):
    """The falsification test for the whole package: it changes no served number.

    Not "the two look similar" -- the ON payload with `innings` removed must
    serialise to the SAME BYTES as the OFF payload, over a fixed seed. Any drift
    in `segments`, `joint`, `aggregate_boxscore` or the prop blocks fails here.
    """
    stripped = {k: v for k, v in out_on.items() if k != "innings"}
    assert json.dumps(stripped, sort_keys=True, default=str) == json.dumps(
        out_off, sort_keys=True, default=str
    )


def test_multiprocessing_path_accumulates_and_MERGES(rosters):
    """`--workers` DEFAULTS TO 4. A producer wired only into the serial loop
    would ship completely inert on every real run. `_merge_seg` merges counts
    only, so a chunk-local accumulator with no explicit merge is discarded --
    that is `#621` Phase 4's bug, checked here rather than rediscovered."""
    out = _run(rosters, sims=240, workers=4, flag="on")
    innings = out.get("innings")
    assert innings, "workers=4 produced no sim.innings -- the merge is missing"
    assert innings["sims"] == 240, f"chunks did not all arrive: sims={innings['sims']}"
    for key in ALL_KEYS:
        block = innings["by_inning"][key]
        assert hist_count(block["total_runs_dist"]) == 240, (key, block["total_runs_dist"])


# --- (b) every bucket accounts for every simulation -------------------------


def test_every_per_inning_histogram_sums_to_the_sim_count(out_on):
    innings = out_on["innings"]
    sims = innings["sims"]
    for key in ALL_KEYS:
        block = innings["by_inning"][key]
        for field in ("away_runs_dist", "home_runs_dist", "total_runs_dist", "run_margin_dist"):
            assert hist_count(block[field]) == sims, (key, field, block[field])


# --- (c) reconciliation against the existing segment writer -----------------


def test_inning_1_IS_segments_first1_exactly(out_on):
    """A full distribution equality, not a moment match.

    `segments.first1` is `seg_score(r, 1)` -- the first element of the same two
    vectors. No convolution stands between the two blocks, so any difference at
    all means the two readers disagree about the same simulation.
    """
    inning_1 = out_on["innings"]["by_inning"]["1"]
    first1 = out_on["segments"]["first1"]
    assert dict(inning_1["total_runs_dist"]) == dict(first1["total_runs_dist"])
    assert dict(inning_1["run_margin_dist"]) == dict(first1["run_margin_dist"])
    assert inning_1["away_runs_mean"] == pytest.approx(first1["away_runs_mean"], abs=0.0)
    assert inning_1["home_runs_mean"] == pytest.approx(first1["home_runs_mean"], abs=0.0)


def test_innings_1_to_9_PLUS_EXTRAS_account_for_the_full_game_run_mass(out_on):
    """(c). Integer equality, no tolerance.

    Run mass is additive across innings even though the distributions are not,
    so this is the exact statement available from marginals. It is also the
    check that catches a dropped extras bucket: a 10th-inning run is in
    `segments.full` and would leave the two sides unequal.
    """
    by_inning = out_on["innings"]["by_inning"]
    inning_mass = sum(hist_mass(by_inning[key]["total_runs_dist"]) for key in ALL_KEYS)
    full_mass = hist_mass(out_on["segments"]["full"]["total_runs_dist"])
    assert inning_mass == full_mass, (inning_mass, full_mass)
    assert int(inning_mass) == inning_mass


def test_dropping_extras_would_FAIL_the_reconciliation_when_extras_happened(out_on):
    """The negative control for the test above.

    Without it, a run in which no game reached the 10th would let a silently
    dropped extras bucket pass -- a null result proving nothing. This skips
    explicitly rather than passing vacuously.
    """
    innings = out_on["innings"]
    if not innings["extras_populated"]:
        pytest.skip(f"no game reached the 10th in this seed (max_inning_seen={innings['max_inning_seen']})")
    assert innings["max_inning_seen"] > 9
    assert innings["extras_games"] > 0
    by_inning = out_on["innings"]["by_inning"]
    regulation_only = sum(hist_mass(by_inning[key]["total_runs_dist"]) for key in INNING_KEYS)
    full_mass = hist_mass(out_on["segments"]["full"]["total_runs_dist"])
    assert regulation_only < full_mass, (
        "extras games happened but dropping the extras bucket changed nothing -- "
        "the bucket is not being fed"
    )
    assert hist_mass(by_inning[EXTRAS_KEY]["total_runs_dist"]) == full_mass - regulation_only


# --- (d) prefixes reproduce the cumulative segments -------------------------


@pytest.mark.parametrize("prefix,segment", [(1, "first1"), (3, "first3"), (5, "first5")])
def test_inning_prefixes_reproduce_the_cumulative_segments(out_on, prefix, segment):
    """(d). `seg_score(r, N)` sums the first N innings, so a prefix of the
    per-inning marginals must carry exactly that segment's run mass -- and its
    margin mass, which is signed and so a stronger check than totals alone."""
    by_inning = out_on["innings"]["by_inning"]
    keys = INNING_KEYS[:prefix]
    seg = out_on["segments"][segment]
    total_mass = sum(hist_mass(by_inning[k]["total_runs_dist"]) for k in keys)
    assert total_mass == hist_mass(seg["total_runs_dist"]), (segment, total_mass)
    margin_mass = sum(hist_mass(by_inning[k]["run_margin_dist"]) for k in keys)
    assert margin_mass == hist_mass(seg["run_margin_dist"]), (segment, margin_mass)
    sims = float(out_on["innings"]["sims"])
    away_mean = sum(by_inning[k]["away_runs_mean"] for k in keys)
    assert away_mean == pytest.approx(seg["away_runs_mean"], rel=1e-12, abs=1e-12)


def test_full_game_margin_mass_is_NOT_asserted_against_the_widened_segment(out_on):
    """A guard on the test above, recording WHY `full` is excluded from it.

    `finalize(seg_full, margin_dispersion=...)` widens `segments.full`'s margin
    distribution before publishing it (`prob_calibration`'s measured
    under-dispersion correction). `first1/3/5` pass no factor. Asserting the
    per-inning margin mass against a widened `full` would compare a raw sum to a
    corrected one, and the correct response would be to weaken the assertion --
    which is how a real disagreement gets hidden. It is excluded on purpose, and
    the totals identity (untouched by the widening) covers `full` instead.
    """
    assert "run_margin_dist" in out_on["segments"]["full"]
    assert hist_count(out_on["segments"]["full"]["total_runs_dist"]) == out_on["innings"]["sims"]


# --- (e) a shutout inning is a populated zero -------------------------------


def test_a_shutout_inning_is_a_POPULATED_zero_bucket(out_on):
    """Absent and zero must not be the same reading.

    Most innings in most games are scoreless, so 0 is the modal value; a block
    whose 0 bucket were missing would look like a low-scoring inning rather than
    an unfed field.
    """
    by_inning = out_on["innings"]["by_inning"]
    for key in INNING_KEYS:
        block = by_inning[key]
        for field in ("away_runs_dist", "home_runs_dist", "total_runs_dist"):
            assert 0 in block[field] or "0" in block[field], (key, field, block[field])
            zero = block[field].get(0, block[field].get("0", 0))
            assert int(zero) > 0, (key, field, zero)


# --- the accumulator itself, over vectors chosen to be hostile --------------


def test_accumulator_handles_extras_and_a_home_team_that_never_batted():
    """Two shapes the real engine produces that a naive `zip` would mangle.

    A home team ahead after the top of the 9th never bats, so its vector is
    SHORT -- those innings must count as 0 runs (so the counts still sum to the
    sim count) while the fact that they were not played stays readable. And a
    12-inning game must put its 10th-12th inning runs in `extras`, not on the
    floor.
    """
    acc = InningRunAccumulator()
    # Walk-off shape: home led, never batted in the 9th.
    acc.record([0, 1, 0, 0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0, 0, 0])
    # A 12-inning game: 1 run in the 11th for away, 2 in the 12th for home.
    acc.record([0] * 9 + [0, 1, 0], [0] * 9 + [0, 0, 2])
    # A shutout that ended in nine.
    acc.record([0] * 9, [0] * 8 + [1])

    payload = acc.to_payload()
    assert payload["sims"] == 3
    assert payload["extras_games"] == 1
    assert payload["extras_populated"] is True
    assert payload["max_inning_seen"] == 12

    by_inning = payload["by_inning"]
    for key in ALL_KEYS:
        for field in ("away_runs_dist", "home_runs_dist", "total_runs_dist", "run_margin_dist"):
            assert hist_count(by_inning[key][field]) == 3, (key, field)

    # The unplayed bottom of the 9th: recorded as 0 runs, and counted as unplayed.
    assert by_inning["9"]["home_not_batted"] == 1
    assert by_inning["9"]["away_not_batted"] == 0
    assert by_inning["9"]["home_runs_dist"][0] == 2
    assert by_inning["9"]["home_runs_dist"][1] == 1

    # Extras: away 1, home 2, in ONE game; the other two contribute 0.
    assert by_inning[EXTRAS_KEY]["away_runs_dist"] == {0: 2, 1: 1}
    assert by_inning[EXTRAS_KEY]["home_runs_dist"] == {0: 2, 2: 1}
    assert by_inning[EXTRAS_KEY]["total_runs_dist"] == {0: 2, 3: 1}

    # Mass reconciles against the scores those vectors imply.
    away_total = (0 + 1) + (1) + 0
    home_total = 2 + 2 + 1
    mass = sum(hist_mass(by_inning[k]["total_runs_dist"]) for k in ALL_KEYS)
    assert mass == float(away_total + home_total)


def test_merge_of_two_chunks_equals_one_accumulator_over_the_same_games():
    """`extend` is the only thing standing between the worker path and an empty
    block, so it is tested as an equality, not a smoke check."""
    games = [
        ([0, 1, 0, 0, 2, 0, 0, 0, 0], [0, 0, 0, 1, 0, 0, 0, 0, 0]),
        ([0] * 9 + [1], [0] * 9 + [0]),
        ([1] * 9, [0] * 8),
    ]
    whole = InningRunAccumulator()
    for a, h in games:
        whole.record(a, h)

    left = InningRunAccumulator()
    left.record(*games[0])
    right = InningRunAccumulator()
    for a, h in games[1:]:
        right.record(a, h)
    merged = InningRunAccumulator()
    merged.extend(left.to_transport())
    merged.extend(right.to_transport())

    assert merged.to_payload() == whole.to_payload()


def test_the_accumulator_retains_no_vector_and_no_game_result():
    """The memory question, as an assertion rather than a promise.

    `__slots__` is the mechanism: the instance cannot grow an attribute holding
    a `GameResult`, and every declared slot is a counter or a dict of ints. A
    future edit that stashed rows would have to change this list.
    """
    acc = InningRunAccumulator()
    vec = [0, 1, 0, 0, 0, 0, 0, 0, 0]
    acc.record(vec, vec)
    assert not hasattr(acc, "__dict__"), "__slots__ was dropped -- rows can now be retained"
    for slot in InningRunAccumulator.__slots__:
        value = getattr(acc, slot)
        assert isinstance(value, (int, dict)), (slot, type(value))
        if isinstance(value, dict):
            for inner in value.values():
                assert isinstance(inner, (int, dict)), (slot, type(inner))
                if isinstance(inner, dict):
                    for k, v in inner.items():
                        assert isinstance(k, int) and isinstance(v, int), (slot, k, v)
    # Mutating the vector after the fact must not change what was recorded.
    snapshot = copy.deepcopy(acc.to_transport())
    vec[1] = 99
    assert acc.to_transport() == snapshot
