"""Build MLB win expectancy from `feed_live` — by COMPOSITION, not by counting.

`#454`, second half. `scripts/mlb_run_expectancy.py` produced the run-expectancy
half; this produces the win-probability half that `shared/game_shape.py`'s
leverage-index refusal actually needs.

**THE EMPIRICAL TABLE CANNOT BE BUILT FROM THIS SAMPLE, AND THAT IS MEASURED,
NOT ASSUMED.** Counting win rates per (inning, half, base-out, score band) over
the 47 dates on disk gives:

    occupied cells                4,039
    median observations / cell        4
    cells with < 10 obs           2,775  (68.7%)
    cells with >= 100 obs            46  (1.1%)
    cells with >= 1000 obs            0

A win probability estimated from four games is noise with a decimal point.
Publishing that table would be `#377` committed by the script written to enable
measurement — the same failure `game_shape.py` refuses the leverage index to
avoid.

**SO THIS COMPOSES INSTEAD.** The quantity that IS estimable from 53k plate
appearances is the distribution of runs scored in the remainder of a half-inning
from each of the 24 base-out states — ~2,200 observations per state rather than
4. Win expectancy is then assembled from those distributions rather than
counted directly. That is the standard construction and it is the one the sample
supports.

    P(win) = P(home's remaining runs > away's remaining runs)
             + P(tie) * P(home wins an extra-innings game)

THE ASSUMPTIONS, STATED BECAUSE THEY ARE REAL AND NOT ALL HARMLESS:

1. **Innings are independent and identically distributed.** False in detail —
   a lineup turns over, bullpens differ, the leadoff hitter of an inning is not
   random. It is the standard simplification, and it is why this is labelled a
   composition rather than a measurement.
2. **Both teams share one run distribution.** No team-quality or park term. A
   real WE model conditions on both; this does not, so it describes a league-
   average matchup and nothing more.
3. **Extra innings collapse to a single constant**, estimated from the corpus
   where possible rather than assumed to be 0.500.
4. **Regulation only.** Innings past the 9th are handled by the extra-innings
   constant, not modelled.

Every one of those makes this table WRONG for a specific game and USEFUL as a
baseline. It must not be presented as an empirical win probability.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_MAX_RUNS = 12  # tail bucket: P(>= _MAX_RUNS) folded into the last cell
_STATE_ORDER = ["---", "1--", "-2-", "--3", "12-", "1-3", "-23", "123"]


def _re_module():
    """Reuse the run-expectancy replay rather than writing a second one.

    Two implementations of base-state reconstruction would drift, and the one
    over there is the one whose phantom-runner bug was already found and fixed.
    """
    spec = importlib.util.spec_from_file_location(
        "mlb_run_expectancy", Path(__file__).resolve().parent / "mlb_run_expectancy.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def scan_distributions(roots: list[Path]) -> dict[str, Any]:
    """P(k runs in the rest of the half-inning) for each base-out state."""
    re_mod = _re_module()
    counts: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0] * (_MAX_RUNS + 1))
    coverage = {
        "files": 0, "games": 0, "half_innings": 0,
        "half_innings_incomplete_excluded": 0, "plate_appearances": 0,
        "extra_inning_games": 0, "extra_inning_home_wins": 0,
        "regulation_games_scored": 0, "dates": set(),
    }

    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.json*")))

    for path in files:
        coverage["files"] += 1
        payload = re_mod._load(path)
        if payload is None:
            continue
        plays = (((payload.get("liveData") or {}).get("plays")) or {}).get("allPlays")
        if not isinstance(plays, list) or not plays:
            continue
        coverage["games"] += 1
        date = str(((payload.get("gameData") or {}).get("datetime") or {}).get("officialDate") or "")
        if date:
            coverage["dates"].add(date)

        halves: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
        max_inning = 0
        for play in plays:
            if not isinstance(play, dict):
                continue
            if ((play.get("result") or {}).get("type")) != "atBat":
                continue
            about = play.get("about") or {}
            inning = about.get("inning") or 0
            max_inning = max(max_inning, int(inning))
            halves[(inning, about.get("halfInning"))].append(play)

        # Final score, for the extra-innings constant.
        last_play = plays[-1] if isinstance(plays[-1], dict) else {}
        final = last_play.get("result") or {}
        try:
            home_final = int(final.get("homeScore") or 0)
            away_final = int(final.get("awayScore") or 0)
            if max_inning > 9:
                coverage["extra_inning_games"] += 1
                if home_final > away_final:
                    coverage["extra_inning_home_wins"] += 1
            else:
                coverage["regulation_games_scored"] += 1
        except Exception:
            pass

        for _, half_plays in halves.items():
            coverage["half_innings"] += 1
            if ((half_plays[-1].get("count") or {}).get("outs")) != 3:
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
                states.append((re_mod._bases_key(occupied), outs))
                occupied, runs = re_mod._apply(play, occupied)
                runs_on_play.append(runs)
                next_outs = ((play.get("count") or {}).get("outs"))
                outs = next_outs if isinstance(next_outs, int) else outs
            if not ok or not states:
                continue
            total = sum(runs_on_play)
            cumulative = 0
            for index, state in enumerate(states):
                rest = min(_MAX_RUNS, total - cumulative)
                counts[state][rest] += 1
                cumulative += runs_on_play[index]
                coverage["plate_appearances"] += 1

    coverage["dates"] = sorted(coverage["dates"])
    distributions = {}
    for state, bucket in counts.items():
        n = sum(bucket)
        if n:
            distributions[state] = {"n": n, "p": [c / n for c in bucket]}
    return {"coverage": coverage, "distributions": distributions}


def _convolve(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, pa in enumerate(a):
        if pa == 0.0:
            continue
        for j, pb in enumerate(b):
            if pb:
                out[i + j] += pa * pb
    return out


def _win_probability(home_runs: list[float], away_runs: list[float], margin: int,
                     extra_p: float) -> float:
    """P(home wins) given each side's remaining-run distribution and the margin.

    `margin` is the CURRENT home lead (home - away). Home wins when
    `margin + home_remaining - away_remaining > 0`; a zero total goes to the
    extra-innings constant.
    """
    win = 0.0
    tie = 0.0
    for h, ph in enumerate(home_runs):
        if ph == 0.0:
            continue
        for a, pa in enumerate(away_runs):
            if pa == 0.0:
                continue
            final = margin + h - a
            if final > 0:
                win += ph * pa
            elif final == 0:
                tie += ph * pa
    return win + tie * extra_p


def build_table(distributions: dict, *, extra_p: float, min_n: int) -> dict[str, Any]:
    """Win expectancy for the batting side's state, composed forward."""
    fresh = distributions.get(("---", 0))
    if not fresh or fresh["n"] < min_n:
        return {"error": "no usable fresh-inning distribution", "rows": []}
    fresh_p = fresh["p"]

    # Distribution of runs over N further full innings, precomputed.
    innings_dist: list[list[float]] = [[1.0]]
    for _ in range(9):
        innings_dist.append(_convolve(innings_dist[-1], fresh_p))

    rows = []
    for inning in range(1, 10):
        for half in ("top", "bottom"):
            for state in _STATE_ORDER:
                for outs in (0, 1, 2):
                    cell = distributions.get((state, outs))
                    if not cell or cell["n"] < min_n:
                        continue
                    current = cell["p"]
                    # Full innings each side still gets AFTER the current half.
                    if half == "top":
                        away_rest = innings_dist[max(0, 9 - inning)]
                        home_rest = innings_dist[max(0, 9 - inning + 1)]
                        away_runs = _convolve(current, away_rest)
                        home_runs = home_rest
                    else:
                        away_rest = innings_dist[max(0, 9 - inning)]
                        home_runs = _convolve(current, innings_dist[max(0, 9 - inning)])
                        away_runs = away_rest
                        # The away side has already batted this inning.
                        away_runs = innings_dist[max(0, 9 - inning)]
                    for margin in range(-6, 7):
                        rows.append({
                            "inning": inning, "half": half, "state": state, "outs": outs,
                            "margin": margin,
                            "we": round(_win_probability(home_runs, away_runs, margin, extra_p), 4),
                            "n_state": cell["n"],
                        })
    return {"rows": rows, "fresh_inning_n": fresh["n"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=None)
    parser.add_argument("--min-n", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    roots = [Path(r) for r in args.root] if args.root else [
        repo / "data" / "mlb_source" / "raw" / "statsapi" / "feed_live",
        repo / "data" / "mlb_source" / "source_artifacts" / "data" / "raw" / "statsapi" / "feed_live",
    ]
    scanned = scan_distributions(roots)
    cov = scanned["coverage"]

    # THE FLOOR WAS 30 AND THAT WAS TOO PERMISSIVE. Measured: 18 home wins in
    # 43 extra-inning games = 0.419, SE ~= 0.076. That is within ~1.3 SE of the
    # true value but it moves every tied state by several points, and a
    # composed table should not wobble on 43 games. A binomial needs a few
    # hundred before it beats a flat prior here.
    extra_games = cov["extra_inning_games"]
    extra_wins = cov["extra_inning_home_wins"]
    measured = (extra_wins / extra_games) if extra_games else None
    se = ((measured * (1 - measured) / extra_games) ** 0.5) if measured is not None and extra_games else None
    if extra_games >= 200:
        extra_p = measured
        extra_src = f"measured on {extra_games} extra-inning games (SE {se:.3f})"
    else:
        extra_p = 0.5
        extra_src = (
            f"DEFAULTED to 0.500 -- {extra_games} extra-inning games is too thin"
            + (f" (measured {measured:.3f}, SE {se:.3f})" if measured is not None else "")
        )

    table = build_table(scanned["distributions"], extra_p=extra_p, min_n=args.min_n)

    if args.json:
        print(json.dumps({"coverage": cov, "extra_innings_home_win_p": extra_p,
                          "table": table}, indent=2, default=str))
        return 0

    print("MLB WIN EXPECTANCY (composed, not counted) -- COVERAGE FIRST")
    print(f"  games                  : {cov['games']}")
    print(f"  distinct dates         : {len(cov['dates'])}")
    print(f"  plate appearances      : {cov['plate_appearances']}")
    print(f"  half-innings excluded  : {cov['half_innings_incomplete_excluded']}")
    print(f"  extra-inning games     : {extra_games}")
    print(f"  P(home wins | tied)    : {extra_p:.3f}   ({extra_src})")
    print()
    print("  run distribution by base-out state (rest of half-inning):")
    print("  state  outs        n    P(0)   P(1)   P(2)   P(3+)")
    for state in _STATE_ORDER:
        for outs in (0, 1, 2):
            cell = scanned["distributions"].get((state, outs))
            if not cell:
                continue
            p = cell["p"]
            print(f"  {state:>5}  {outs:>4}  {cell['n']:>7}  {p[0]:>5.3f}  {p[1]:>5.3f}  "
                  f"{p[2]:>5.3f}  {sum(p[3:]):>5.3f}")
    print()
    rows = {(r["inning"], r["half"], r["state"], r["outs"], r["margin"]): r["we"]
            for r in table.get("rows", [])}
    print("  SANITY CHECKS (these are what say whether the composition is sane)")
    checks = [
        ("start of game, tied", (1, "top", "---", 0, 0)),
        ("home up 1, top 1", (1, "top", "---", 0, 1)),
        ("home down 1, top 1", (1, "top", "---", 0, -1)),
        ("tied, bottom 9, bases empty", (9, "bottom", "---", 0, 0)),
        ("home up 3, top 9, 2 out", (9, "top", "---", 2, 3)),
        ("home down 3, bottom 9, 2 out", (9, "bottom", "---", 2, -3)),
        ("home down 1, bottom 9, runner 3rd, 1 out", (9, "bottom", "--3", 1, -1)),
    ]
    for label, key in checks:
        value = rows.get(key)
        print(f"    {label:<42} {('%.3f' % value) if value is not None else '(thin)'}")
    print()
    start = rows.get((1, "top", "---", 0, 0))
    if start is not None:
        print("  THE KNOWN GAP, stated rather than fudged:")
        print(f"    start-of-game WE here is {start:.3f}; published tables show ~0.540.")
        print("    That difference IS the home-field advantage this model does not")
        print("    contain -- assumption 2 gives both sides one league-average run")
        print("    distribution, so the only asymmetry left is batting last. Do not")
        print("    close the gap with a fudge factor; condition on the teams.")
        print()
    print(f"  rows produced: {len(table.get('rows', []))}")
    print("  NOTE: composed under i.i.d. innings and one league-average run")
    print("        distribution for both sides. NOT an empirical win probability.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
