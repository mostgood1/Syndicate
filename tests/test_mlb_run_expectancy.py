"""Tests for `scripts/mlb_run_expectancy.py` (`#454`).

Fixtures are shaped from the real `feed_live` payload measured 2026-08-16,
including the duplicate-runner case (14 of 219 plays in the first three games).
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
from typing import Any

_SPEC = importlib.util.spec_from_file_location(
    "mlb_run_expectancy",
    Path(__file__).resolve().parents[1] / "scripts" / "mlb_run_expectancy.py",
)
mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(mod)


def _runner(runner_id: int, start: Any, end: Any, is_out: bool = False) -> dict[str, Any]:
    return {
        "movement": {"originBase": start, "start": start, "end": end, "isOut": is_out},
        "details": {"runner": {"id": runner_id}},
    }


def _play(*, outs_after: int, runners: list[dict[str, Any]], inning: int = 1,
          half: str = "top", away: int = 0, home: int = 0) -> dict[str, Any]:
    return {
        "about": {"inning": inning, "halfInning": half},
        "count": {"balls": 0, "strikes": 0, "outs": outs_after},
        "result": {"type": "atBat", "awayScore": away, "homeScore": home},
        "runners": runners,
    }


# --------------------------------------------------------------------------
# state reconstruction
# --------------------------------------------------------------------------


def test_bases_key_encodes_occupancy_in_order():
    assert mod._bases_key(set()) == "---"
    assert mod._bases_key({"1B"}) == "1--"
    assert mod._bases_key({"2B"}) == "-2-"
    assert mod._bases_key({"3B"}) == "--3"
    assert mod._bases_key({"1B", "3B"}) == "1-3"
    assert mod._bases_key({"1B", "2B", "3B"}) == "123"


def test_a_batter_single_puts_a_runner_on_first():
    after, runs = mod._apply(_play(outs_after=0, runners=[_runner(1, None, "1B")]), set())
    assert after == {"1B"} and runs == 0


def test_a_runner_advancing_vacates_the_base_it_left():
    """Guards against adding the destination without removing the origin.

    Without the removal a single with a man on first reads as `12-` plus a
    phantom runner still on first, and every downstream cell is wrong.
    """
    play = _play(outs_after=0, runners=[_runner(7, "1B", "2B"), _runner(9, None, "1B")])
    after, runs = mod._apply(play, {"1B"})
    assert after == {"1B", "2B"} and runs == 0


def test_scoring_is_counted_and_removes_the_runner():
    play = _play(outs_after=0, runners=[_runner(7, "3B", "score"), _runner(9, None, "1B")])
    after, runs = mod._apply(play, {"3B"})
    assert after == {"1B"}
    assert runs == 1


def test_an_out_removes_the_runner_without_scoring():
    play = _play(outs_after=1, runners=[_runner(7, "1B", None, is_out=True)])
    after, runs = mod._apply(play, {"1B"})
    assert after == set() and runs == 0


def test_duplicate_runner_entries_are_applied_once():
    """MEASURED: 14 of 219 plays carry more than one entry for the same runner.

    Applying both would move the runner twice — here, off first, onto second,
    then off second onto third — inventing an advance that did not happen.
    """
    play = _play(outs_after=0, runners=[
        _runner(7, "1B", "2B"),
        _runner(7, "2B", "3B"),   # same runner id, later movement
    ])
    after, _ = mod._apply(play, {"1B"})
    assert after == {"3B"}, "vacate the FIRST origin, land on the LAST end"


def test_the_real_two_movement_shape_does_not_strand_a_phantom_runner():
    """THE BUG THIS SUITE CAUGHT, in the exact shape the payload produces.

    `originBase` stays constant across a runner's entries while `start`
    advances. Reading `start` off the LAST entry vacates a base the runner never
    occupied when the play began, leaving the original base occupied forever —
    inflating every occupied-base cell for the rest of the half-inning.

    Measured effect of the fix on the real corpus: `--3|0` n went 107 -> 229 and
    `1-3|0` went 217 -> 90. The bug was not cosmetic.
    """
    play = {"runners": [
        {"movement": {"originBase": "2B", "start": "2B", "end": "3B"},
         "details": {"runner": {"id": 547180}}},
        {"movement": {"originBase": "2B", "start": "3B", "end": "score"},
         "details": {"runner": {"id": 547180}}},
        {"movement": {"originBase": None, "start": None, "end": "1B"},
         "details": {"runner": {"id": 999}}},
    ]}
    after, runs = mod._apply(play, {"2B"})
    assert after == {"1B"}, "2B must be vacated; a phantom runner there is the bug"
    assert runs == 1


def test_runners_without_an_id_are_still_applied():
    """Falling back to positional identity, so an unidentified runner is not dropped."""
    play = {"movement": None}
    p = _play(outs_after=0, runners=[
        {"movement": {"start": None, "end": "1B"}, "details": {}},
        {"movement": {"start": None, "end": "2B"}, "details": {}},
    ])
    after, _ = mod._apply(p, set())
    assert after == {"1B", "2B"}


# --------------------------------------------------------------------------
# the exclusion that changes the answer
# --------------------------------------------------------------------------


def _write_game(root: Path, name: str, plays: list[dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"gameData": {"datetime": {"officialDate": "2026-06-04"}},
               "liveData": {"plays": {"allPlays": plays}}}
    with gzip.open(root / name, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_an_incomplete_half_inning_is_excluded(tmp_path):
    """A walk-off truncates the runs that follow, biasing every cell DOWN."""
    _write_game(tmp_path, "walkoff.json.gz", [
        _play(outs_after=0, runners=[_runner(1, None, "1B")]),
        _play(outs_after=1, runners=[_runner(1, "1B", "score")]),  # ends at 1 out
    ])
    result = mod.scan([tmp_path])
    assert result["coverage"]["half_innings"] == 1
    assert result["coverage"]["half_innings_incomplete_excluded"] == 1
    assert result["matrix"] == {}


def test_a_complete_half_inning_is_counted(tmp_path):
    _write_game(tmp_path, "clean.json.gz", [
        _play(outs_after=1, runners=[_runner(1, None, None, is_out=True)]),
        _play(outs_after=2, runners=[_runner(2, None, None, is_out=True)]),
        _play(outs_after=3, runners=[_runner(3, None, None, is_out=True)]),
    ])
    result = mod.scan([tmp_path])
    assert result["coverage"]["half_innings_incomplete_excluded"] == 0
    assert result["coverage"]["plate_appearances"] == 3
    assert result["matrix"][("---", 0)]["re"] == 0.0
    assert result["matrix"][("---", 2)]["n"] == 1


def test_runs_rest_of_inning_decreases_as_runs_are_banked(tmp_path):
    """The core quantity: runs from THIS state to the end of the half-inning."""
    _write_game(tmp_path, "two_runs.json.gz", [
        _play(outs_after=0, runners=[_runner(1, None, "3B")]),                    # PA1: 2 runs follow
        _play(outs_after=0, runners=[_runner(1, "3B", "score"), _runner(2, None, "3B")]),
        _play(outs_after=1, runners=[_runner(2, "3B", "score"), _runner(3, None, None, is_out=True)]),
        _play(outs_after=2, runners=[_runner(4, None, None, is_out=True)]),
        _play(outs_after=3, runners=[_runner(5, None, None, is_out=True)]),
    ])
    matrix = mod.scan([tmp_path])["matrix"]
    assert matrix[("---", 0)]["re"] == 2.0     # both runs still to come
    # `--3|0` occurs TWICE in this half-inning -- after the leadoff triple (2
    # runs follow) and again after the first run scores with the next batter on
    # third (1 run follows). Mean 1.5, not 2.0. My first expectation here was
    # wrong and the code was right; kept as a worked example because the
    # quantity is easy to mis-state.
    assert matrix[("--3", 0)]["n"] == 2
    assert matrix[("--3", 0)]["re"] == 1.5
    assert matrix[("---", 2)]["re"] == 0.0     # nothing left


def test_scan_on_a_missing_root_returns_empty(tmp_path):
    result = mod.scan([tmp_path / "nope"])
    assert result["matrix"] == {}
    assert result["coverage"]["games"] == 0


# --------------------------------------------------------------------------
# the comparison, which had the wrong model first
# --------------------------------------------------------------------------


def _matrix(factor: float, *, n: int = 5000, se: float = 0.01) -> dict:
    return {(s, o): {"n": n, "re": round(factor * ref, 4), "se": se}
            for (s, o), ref in mod._REFERENCE.items()}


def test_a_pure_scale_of_the_reference_fits_with_no_residual():
    """A 13% livelier run environment must read as a CLEAN reproduction."""
    out = mod.compare(_matrix(1.13), min_n=100)
    assert out["summary"]["cells_compared"] == 24
    assert abs(out["summary"]["run_environment_factor"] - 1.13) < 0.001
    assert out["summary"]["max_abs_z"] < 1.0
    assert out["summary"]["cells_beyond_3se"] == 0
    assert out["summary"]["verdict"].startswith("REPRODUCES")


def test_an_additive_shift_does_NOT_fit_and_is_reported_as_a_failure():
    """The model correction, pinned.

    Adding a constant to every cell is what a genuinely broken join could look
    like; it must NOT be absorbed by a scale factor. The first version of
    `compare` fitted an ADDITIVE offset and would have called this clean.
    """
    matrix = {(s, o): {"n": 5000, "re": round(ref + 0.30, 4), "se": 0.01}
              for (s, o), ref in mod._REFERENCE.items()}
    out = mod.compare(matrix, min_n=100)
    assert out["summary"]["cells_beyond_3se"] > 1
    assert out["summary"]["verdict"].startswith("DOES NOT")


def test_thin_cells_are_reported_rather_than_silently_compared():
    matrix = _matrix(1.13)
    matrix[("--3", 0)]["n"] = 12
    out = mod.compare(matrix, min_n=100)
    assert out["summary"]["cells_thin"] == 1
    thin = [r for r in out["rows"] if r["thin"]]
    assert thin and thin[0]["state"] == "--3" and thin[0]["re"] is None


def test_the_fit_is_n_weighted_so_rare_cells_cannot_drag_it():
    """`--3|0` has ~100 observations against `---|0`'s ~13,000.

    An unweighted fit would let the rarest, noisiest cell move the factor.
    """
    matrix = _matrix(1.13)
    matrix[("--3", 0)] = {"n": 100, "re": 5.0, "se": 0.5}   # wild outlier, tiny n
    out = mod.compare(matrix, min_n=50)
    assert abs(out["summary"]["run_environment_factor"] - 1.13) < 0.02
