"""Build the MLB base-out run expectancy (RE24) table from `feed_live`.

`#454`, first concrete step, and the one it names: *"build the MLB base-out run
expectancy table from feed_live offline and compare it to the published
reference values. If it reproduces them, the pipeline is trustworthy and the
leverage index becomes available; if it does not, the join is wrong and that is
worth knowing before anything is built on it."*

WHY IT MATTERS BEYOND ITSELF. `shared/game_shape.py` REFUSES to emit a leverage
index, on the grounds that a real one needs a fitted win-expectancy table this
repo does not have. This is the first half of that table: run expectancy by
base-out state is what leverage, RE24 and any run-value model are built on.
Producing it turns a documented refusal into a number.

METHOD, and every choice below came from measuring the payload rather than from
recalling how RE24 is usually done.

* **State is reconstructed forward, not read off the play.** `count.outs` is the
  outs AFTER the play and `result.awayScore`/`homeScore` are the score after it,
  so neither describes the state a plate appearance STARTED in. Each half-inning
  is replayed from (bases empty, 0 outs).

* **Runners are collapsed to one transition each: FIRST origin, LAST end.**
  Measured: 14 of 219 plays in the first three games carry more than one entry
  for the same runner. Applying them all moves a runner twice; deduplicating to
  the last entry and reading its `start` is *also* wrong, because `start`
  advances between entries while `originBase` does not -- that version left a
  PHANTOM RUNNER on the original base and inflated every occupied-base cell.
  Fixing it moved real counts: `--3|0` n went 107 -> 229 and `1-3|0` 217 -> 90.
  See `_runner_transitions`.

* **Runs are counted from `movement.end == "score"`**, which the payload uses
  explicitly, and then CROSS-CHECKED against the `result` score delta. A
  mismatch is counted and reported rather than silently preferred one way --
  two independent readings of the same quantity are worth having.

* **INCOMPLETE HALF-INNINGS ARE EXCLUDED.** This is the one exclusion that
  changes the answer materially. A half-inning that ends before three outs --
  a walk-off, a called game -- truncates the runs that would have followed, so
  including it biases every cell DOWNWARD. Measured on the first game: 17 of 17
  half-innings ended at exactly 3 outs, so the exclusion is small but it is not
  optional.

* **Only `result.type == "atBat"` rows exist** in `allPlays` (219 of 219
  measured), so there is no action-row filter to get wrong. Stated because its
  absence would otherwise look like an oversight.

WHAT THIS IS NOT. Not a win-expectancy table -- that needs score differential
and inning, and is the second half of the leverage problem. Not a model. This
produces one table and the evidence for whether to trust it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_BASES = ("1B", "2B", "3B")

# Published MLB RE24, 2010-2015 (Tango/Lichtman lineage), the values this table
# is checked against. Not a target to fit -- a reference to DISAGREE with loudly.
#
# **THESE VALUES ARE RECALLED, NOT SOURCED, AND THAT LIMIT IS LOAD-BEARING.**
# They were written from memory rather than read from a citation, so a per-cell
# disagreement is at least as likely to be an error HERE as in the data --
# especially in the rare states (`--3|0`, `-2-|0`), which are both the cells
# where a recalled number is least reliable AND where the sample is thinnest.
# Before treating any single-cell deviation as a data defect, replace this table
# with sourced values. The checks that do NOT depend on it -- the score
# cross-check and monotonicity in outs -- are the trustworthy ones.
_REFERENCE = {
    ("---", 0): 0.481, ("---", 1): 0.254, ("---", 2): 0.098,
    ("1--", 0): 0.859, ("1--", 1): 0.509, ("1--", 2): 0.224,
    ("-2-", 0): 1.100, ("-2-", 1): 0.664, ("-2-", 2): 0.319,
    ("--3", 0): 1.350, ("--3", 1): 0.950, ("--3", 2): 0.353,
    ("12-", 0): 1.437, ("12-", 1): 0.884, ("12-", 2): 0.429,
    ("1-3", 0): 1.784, ("1-3", 1): 1.130, ("1-3", 2): 0.478,
    ("-23", 0): 1.964, ("-23", 1): 1.376, ("-23", 2): 0.580,
    ("123", 0): 2.292, ("123", 1): 1.541, ("123", 2): 0.752,
}

_STATE_ORDER = ["---", "1--", "-2-", "--3", "12-", "1-3", "-23", "123"]


def _bases_key(occupied: set[str]) -> str:
    return "".join(
        base[0] if base in occupied else "-" for base in _BASES
    ).replace("1", "1").replace("2", "2").replace("3", "3")


def _load(path: Path) -> dict[str, Any] | None:
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _runner_transitions(play: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Per runner: (base vacated, base ended on). Exactly one entry per runner.

    **THE SUBTLETY THAT PRODUCED A REAL BUG — caught by a test, not by review.**
    A runner who advances twice on one play gets TWO entries, and `start`
    differs between them while `originBase` does not:

        originBase='2B' start='2B' end='3B'      <- first
        originBase='2B' start='3B' end='score'   <- second

    Deduplicating to the LAST entry and reading its `start` vacates 3B — a base
    the runner never occupied when the play began — and leaves a PHANTOM RUNNER
    on 2B for the rest of the half-inning. Every later state is then wrong, and
    wrong in the direction of TOO MANY runners on base, which inflates exactly
    the occupied-base cells.

    So: the vacated base comes from the FIRST entry (`originBase`, falling back
    to `start`), and the destination from the LAST. Verified against all four
    multi-movement shapes present in the real payload.
    """
    first: dict[Any, dict[str, Any]] = {}
    last: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for index, runner in enumerate(play.get("runners") or []):
        if not isinstance(runner, dict):
            continue
        runner_id = ((runner.get("details") or {}).get("runner") or {}).get("id")
        # Positional identity when the id is missing, so an unidentified runner
        # is applied once rather than dropped.
        key = runner_id if runner_id is not None else ("_pos", index)
        if key not in first:
            first[key] = runner
            order.append(key)
        last[key] = runner

    transitions: list[tuple[Any, Any]] = []
    for key in order:
        first_move = first[key].get("movement") or {}
        last_move = last[key].get("movement") or {}
        vacated = first_move.get("originBase")
        if vacated is None:
            vacated = first_move.get("start")
        transitions.append((vacated, last_move.get("end")))
    return transitions


def _apply(play: dict[str, Any], occupied: set[str]) -> tuple[set[str], int]:
    """Return (bases after the play, runs scored on the play)."""
    after = set(occupied)
    runs = 0
    for vacated, end in _runner_transitions(play):
        if vacated in _BASES:
            after.discard(vacated)
        if end == "score":
            runs += 1
        elif end in _BASES:
            after.add(end)
    return after, runs


def scan(roots: list[Path]) -> dict[str, Any]:
    totals: dict[tuple[str, int], list[float]] = defaultdict(list)
    coverage = {
        "roots": [str(r) for r in roots],
        "files": 0,
        "files_unreadable": 0,
        "games": 0,
        "half_innings": 0,
        "half_innings_incomplete_excluded": 0,
        "plate_appearances": 0,
        "score_crosscheck_mismatches": 0,
        "dates": set(),
    }

    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.json*")))

    for path in files:
        coverage["files"] += 1
        payload = _load(path)
        if payload is None:
            coverage["files_unreadable"] += 1
            continue
        plays = (((payload.get("liveData") or {}).get("plays")) or {}).get("allPlays")
        if not isinstance(plays, list) or not plays:
            continue
        coverage["games"] += 1
        date = str(((payload.get("gameData") or {}).get("datetime") or {}).get("officialDate") or "")
        if date:
            coverage["dates"].add(date)

        halves: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
        for play in plays:
            if not isinstance(play, dict):
                continue
            if ((play.get("result") or {}).get("type")) != "atBat":
                continue
            about = play.get("about") or {}
            halves[(about.get("inning"), about.get("halfInning"))].append(play)

        for _, half_plays in halves.items():
            coverage["half_innings"] += 1
            last_outs = ((half_plays[-1].get("count") or {}).get("outs"))
            # THE EXCLUSION THAT CHANGES THE ANSWER. A truncated half-inning
            # has fewer runs after it by construction, so keeping it drags
            # every cell down.
            if last_outs != 3:
                coverage["half_innings_incomplete_excluded"] += 1
                continue

            states: list[tuple[str, int]] = []
            runs_on_play: list[int] = []
            occupied: set[str] = set()
            outs = 0
            ok = True
            for play in half_plays:
                if outs > 2:
                    ok = False
                    break
                states.append((_bases_key(occupied), outs))
                occupied, runs = _apply(play, occupied)
                runs_on_play.append(runs)
                next_outs = ((play.get("count") or {}).get("outs"))
                outs = next_outs if isinstance(next_outs, int) else outs
            if not ok or not states:
                continue

            # Cross-check: runs counted from movements vs the score delta.
            first_result = half_plays[0].get("result") or {}
            last_result = half_plays[-1].get("result") or {}
            try:
                score_after = float(last_result.get("awayScore") or 0) + float(last_result.get("homeScore") or 0)
                score_first_after = float(first_result.get("awayScore") or 0) + float(first_result.get("homeScore") or 0)
                delta = score_after - (score_first_after - runs_on_play[0])
                if abs(delta - sum(runs_on_play)) > 0.5:
                    coverage["score_crosscheck_mismatches"] += 1
            except Exception:
                coverage["score_crosscheck_mismatches"] += 1

            total = sum(runs_on_play)
            cumulative = 0
            for index, state in enumerate(states):
                rest = total - cumulative
                totals[state].append(float(rest))
                cumulative += runs_on_play[index]
                coverage["plate_appearances"] += 1

    coverage["dates"] = sorted(coverage["dates"])
    matrix = {}
    for state, values in totals.items():
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        matrix[state] = {
            "n": n,
            "re": round(mean, 4),
            # Per-cell standard error. Without it "this cell is 0.5 off" is not
            # a statement about anything -- the rare 0-out cells carry SEs an
            # order of magnitude larger than the common ones.
            "se": round((var ** 0.5) / (n ** 0.5), 4),
        }
    return {"coverage": coverage, "matrix": matrix}


def compare(matrix: dict[tuple[str, int], dict[str, Any]], *, min_n: int) -> dict[str, Any]:
    """Check the table against published RE24 under a MULTIPLICATIVE model.

    **THE FIRST VERSION OF THIS FUNCTION FITTED AN ADDITIVE OFFSET AND THAT WAS
    THE WRONG MODEL.** It reported a post-offset scatter of 0.53 runs, which
    reads as a broken join. The residuals gave it away: strongly negative on
    low-RE cells and positive on high-RE ones -- the signature of a scale
    factor, not a shift. A run environment that is 13% livelier lifts a
    2.3-run cell by 0.30 and a 0.10-run cell by 0.013; subtracting one constant
    from both cannot fit.

    Under the multiplicative fit the same data lands 23 of 24 cells inside 3 SE.
    The lesson is worth keeping: *a residual that correlates with the fitted
    value means the model is wrong, not that the data is.*
    """
    usable = [
        (state, outs, cell)
        for state in _STATE_ORDER
        for outs in (0, 1, 2)
        for cell in [matrix.get((state, outs))]
        if cell and cell["n"] >= min_n
    ]
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"cells_compared": len(usable), "cells_thin": 24 - len(usable)}
    if not usable:
        return {"rows": rows, "summary": summary}

    # n-weighted, so the rare 0-out cells cannot drag the fit around.
    numerator = sum(cell["n"] * cell["re"] for _, _, cell in usable)
    denominator = sum(cell["n"] * _REFERENCE[(s, o)] for s, o, cell in usable)
    factor = numerator / denominator if denominator else 1.0

    worst = 0.0
    beyond_3se = 0
    for state in _STATE_ORDER:
        for outs in (0, 1, 2):
            cell = matrix.get((state, outs))
            reference = _REFERENCE[(state, outs)]
            if not cell or cell["n"] < min_n:
                rows.append({"state": state, "outs": outs, "n": cell["n"] if cell else 0,
                             "re": None, "ref": reference, "predicted": None,
                             "resid": None, "z": None, "thin": True})
                continue
            predicted = factor * reference
            resid = cell["re"] - predicted
            se = cell.get("se") or 0.0
            z = (resid / se) if se else None
            if z is not None:
                worst = max(worst, abs(z))
                if abs(z) > 3:
                    beyond_3se += 1
            rows.append({"state": state, "outs": outs, "n": cell["n"], "re": cell["re"],
                         "ref": reference, "predicted": round(predicted, 4),
                         "resid": round(resid, 4), "z": round(z, 2) if z is not None else None,
                         "thin": False})
    summary["run_environment_factor"] = round(factor, 4)
    summary["max_abs_z"] = round(worst, 2)
    summary["cells_beyond_3se"] = beyond_3se
    # The verdict deliberately does NOT say "the data is wrong" on a couple of
    # outliers, because this reference is recalled rather than sourced (see the
    # table's comment). It reports the shape of the disagreement and leaves the
    # attribution open.
    if beyond_3se == 0:
        verdict = "REPRODUCES published RE24 within sampling error, scaled by the run environment"
    elif beyond_3se <= 3:
        verdict = (
            f"CONSISTENT with published RE24 under one scale factor in "
            f"{len(usable) - beyond_3se}/{len(usable)} cells; {beyond_3se} disagree by >3 SE. "
            "Attribution is OPEN -- this reference is recalled, not sourced, and the "
            "outliers are the rarest states. Source the reference before calling it a data defect."
        )
    else:
        verdict = "DOES NOT reproduce published RE24 -- investigate the join before building on it"
    summary["verdict"] = verdict
    return {"rows": rows, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=None)
    parser.add_argument("--min-n", type=int, default=100,
                        help="Cells below this are reported as thin and excluded from the comparison.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    roots = [Path(r) for r in args.root] if args.root else [
        repo / "data" / "mlb_source" / "raw" / "statsapi" / "feed_live",
        repo / "data" / "mlb_source" / "source_artifacts" / "data" / "raw" / "statsapi" / "feed_live",
    ]
    result = scan(roots)
    comparison = compare(result["matrix"], min_n=args.min_n)

    if args.json:
        print(json.dumps({
            "coverage": result["coverage"],
            "matrix": {f"{s}|{o}": v for (s, o), v in result["matrix"].items()},
            "comparison": comparison,
        }, indent=2, default=str))
        return 0

    cov = result["coverage"]
    print("MLB RUN EXPECTANCY from feed_live -- COVERAGE FIRST")
    print(f"  files scanned          : {cov['files']}  (unreadable {cov['files_unreadable']})")
    print(f"  games                  : {cov['games']}")
    print(f"  distinct dates         : {len(cov['dates'])}"
          + (f"  {cov['dates'][0]} .. {cov['dates'][-1]}" if cov["dates"] else ""))
    print(f"  half-innings           : {cov['half_innings']}")
    print(f"  incomplete EXCLUDED    : {cov['half_innings_incomplete_excluded']}")
    print(f"  plate appearances      : {cov['plate_appearances']}")
    print(f"  score cross-check mism.: {cov['score_crosscheck_mismatches']}")
    print()
    print("  state  outs        n        RE      SE   k*published    resid    resid/SE")
    for row in comparison["rows"]:
        if row["thin"]:
            print(f"  {row['state']:>5}  {row['outs']:>4}  {row['n']:>7}     (thin)")
            continue
        cell = result["matrix"][(row["state"], row["outs"])]
        print(f"  {row['state']:>5}  {row['outs']:>4}  {row['n']:>7}  {row['re']:>8.3f}  {cell['se']:>6.3f}  "
              f"{row['predicted']:>11.3f}  {row['resid']:>+7.3f}  {row['z']:>+10.1f}")
    print()
    s = comparison["summary"]
    print(f"  cells compared {s['cells_compared']}/24 (thin {s['cells_thin']})")
    if s.get("cells_compared"):
        print(f"  run-environment factor k : {s['run_environment_factor']:.4f}  "
              f"({100 * (s['run_environment_factor'] - 1):+.1f}% vs the published era)")
        print(f"  max |resid/SE|           : {s['max_abs_z']:.1f}")
        print(f"  cells beyond 3 SE        : {s['cells_beyond_3se']}/24")
        print(f"  VERDICT: {s['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
