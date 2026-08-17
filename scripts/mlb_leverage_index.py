"""Compute MLB leverage index and GENERATE the lookup table `game_shape` imports.

`#454`, third step. `mlb_run_expectancy.py` gave the RE half, `mlb_win_expectancy.py`
the WE half; leverage is the swing in WE across the outcomes a plate appearance
can produce, which needs both plus a transition matrix.

    LI(state) = E|dWE| from that state  /  E|dWE| averaged over all plate appearances

so LI = 1.0 is an average situation, 2.0 twice as swingy, 0.3 nearly dead.

**THE TRANSITION MATRIX IS THE NEW PIECE, AND IT IS ESTIMABLE.** The same
half-inning replay that produced RE already observes, for every plate
appearance, `(state_before -> runs scored, state_after)`. That is ~53,000
transitions over 24 states, ~2,200 per state -- the same order as the run
distributions and nowhere near the 4-per-cell that made an empirical WE table
impossible.

WHAT `game_shape` GETS, AND WHAT IT DOES NOT. This script writes a generated
module of plain literals. `game_shape` imports it and does a dict lookup, so
that module stays pure -- no I/O, no fitted model at import, nothing to load at
request time on a memory-constrained worker.

**THE CAVEAT TRAVELS WITH THE NUMBER.** Every leverage value inherits the WE
composition's assumptions: i.i.d. innings, one league-average run distribution
for both sides, no team or park term, extra innings as a constant. A leverage
index is therefore a LEAGUE-AVERAGE description of a situation's swinginess, and
is wrong for a specific matchup. The generated module carries that text so it
cannot be read off the value alone.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_MARGIN_CLIP = 6
_STATE_ORDER = ["---", "1--", "-2-", "--3", "12-", "1-3", "-23", "123"]


def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def scan_transitions(roots: list[Path]) -> dict[str, Any]:
    """(bases, outs) -> Counter of (runs, bases_after, outs_after).

    `outs_after == 3` means the half-inning ended on this play.
    """
    re_mod = _load_sibling("mlb_run_expectancy")
    transitions: dict[tuple[str, int], dict[tuple[int, str, int], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # HOW OFTEN EACH FULL CELL ACTUALLY OCCURS. Needed for the normalisation:
    # weighting every (inning, half, margin) combination equally would let
    # blowouts and extra-inning margins count as much as the close middle
    # innings where most plate appearances really happen, which deflates the
    # mean swing and inflates every leverage value.
    cell_counts: dict[tuple, int] = defaultdict(int)
    coverage = {"games": 0, "plate_appearances": 0, "half_innings_excluded": 0, "dates": set()}

    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.json*")))

    for path in files:
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
        for play in plays:
            if not isinstance(play, dict) or ((play.get("result") or {}).get("type")) != "atBat":
                continue
            about = play.get("about") or {}
            halves[(about.get("inning"), about.get("halfInning"))].append(play)

        for _, half_plays in halves.items():
            if ((half_plays[-1].get("count") or {}).get("outs")) != 3:
                coverage["half_innings_excluded"] += 1
                continue
            occupied: set[str] = set()
            outs = 0
            for play in half_plays:
                if outs > 2:
                    break
                before = (re_mod._bases_key(occupied), outs)
                result_block = play.get("result") or {}
                try:
                    margin_now = _clip(int(result_block.get("homeScore") or 0)
                                       - int(result_block.get("awayScore") or 0))
                except Exception:
                    margin_now = 0
                inning_now = min(9, int((play.get("about") or {}).get("inning") or 1))
                half_now = (play.get("about") or {}).get("halfInning")
                cell_counts[(inning_now, half_now, before[0], before[1], margin_now)] += 1
                occupied, runs = re_mod._apply(play, occupied)
                next_outs = ((play.get("count") or {}).get("outs"))
                outs_after = next_outs if isinstance(next_outs, int) else outs
                after_bases = re_mod._bases_key(occupied) if outs_after < 3 else "---"
                transitions[before][(runs, after_bases, outs_after)] += 1
                coverage["plate_appearances"] += 1
                outs = outs_after

    coverage["dates"] = sorted(coverage["dates"])
    return {"coverage": coverage,
            "transitions": {k: dict(v) for k, v in transitions.items()},
            "cell_counts": dict(cell_counts)}


def _we_lookup(rows: list[dict[str, Any]]) -> dict[tuple, float]:
    return {(r["inning"], r["half"], r["state"], r["outs"], r["margin"]): r["we"] for r in rows}


def _clip(margin: int) -> int:
    return max(-_MARGIN_CLIP, min(_MARGIN_CLIP, margin))


def _we(lookup: dict[tuple, float], inning: int, half: str, state: str, outs: int,
        margin: int) -> float | None:
    """WE at a state, with end-of-game handled explicitly.

    After the bottom of the 9th the game is over: the margin alone decides it,
    and looking up a 10th inning would silently read a state the table does not
    model.
    """
    if inning > 9:
        margin = _clip(margin)
        if margin > 0:
            return 1.0
        if margin < 0:
            return 0.0
        return None  # tied into extras -- the composition's constant applies
    return lookup.get((inning, half, state, outs, _clip(margin)))


def compute_leverage(transitions: dict, we_rows: list[dict[str, Any]], *,
                     min_n: int, cell_counts: dict | None = None) -> dict[str, Any]:
    lookup = _we_lookup(we_rows)
    raw: dict[tuple, float] = {}
    weights: dict[tuple, int] = {}

    for inning in range(1, 10):
        for half in ("top", "bottom"):
            for state in _STATE_ORDER:
                for outs in (0, 1, 2):
                    outcomes = transitions.get((state, outs))
                    if not outcomes:
                        continue
                    total = sum(outcomes.values())
                    if total < min_n:
                        continue
                    for margin in range(-_MARGIN_CLIP, _MARGIN_CLIP + 1):
                        before = _we(lookup, inning, half, state, outs, margin)
                        if before is None:
                            continue
                        swing = 0.0
                        seen = 0
                        for (runs, after_bases, outs_after), count in outcomes.items():
                            # The batting side's runs move the margin.
                            new_margin = margin + runs if half == "bottom" else margin - runs
                            if outs_after >= 3:
                                # Half-inning over: next half, bases empty, no outs.
                                if half == "top":
                                    after = _we(lookup, inning, "bottom", "---", 0, new_margin)
                                else:
                                    after = _we(lookup, inning + 1, "top", "---", 0, new_margin)
                            else:
                                after = _we(lookup, inning, half, after_bases, outs_after, new_margin)
                            if after is None:
                                continue
                            swing += count * abs(after - before)
                            seen += count
                        if seen:
                            raw[(inning, half, state, outs, margin)] = swing / seen
                            weights[(inning, half, state, outs, margin)] = seen

    if not raw:
        return {"error": "no leverage cells computed", "table": {}}

    # Normalise so that 1.0 is an average plate appearance.
    #
    # **THE FIRST VERSION WEIGHTED BY STATE FREQUENCY ONLY AND THAT WAS WRONG.**
    # It treated every (inning, half, margin) combination as equally likely, so
    # 6-run blowouts counted as heavily as tied middle innings. That deflates
    # the mean swing and inflates every leverage value -- start-of-game read
    # 1.14 when an average plate appearance is 1.00 by definition.
    #
    # The fix is to weight by how often the FULL cell actually occurs, which the
    # scan now counts directly.
    if cell_counts:
        observed = {k: cell_counts.get(k, 0) for k in raw}
        total_weight = sum(observed.values())
        if total_weight:
            mean_swing = sum(raw[k] * observed[k] for k in raw) / total_weight
        else:
            total_weight = sum(weights.values())
            mean_swing = sum(raw[k] * weights[k] for k in raw) / total_weight
    else:
        total_weight = sum(weights.values())
        mean_swing = sum(raw[k] * weights[k] for k in raw) / total_weight
    table = {k: round(v / mean_swing, 3) for k, v in raw.items()} if mean_swing else {}
    return {"table": table, "mean_swing": mean_swing, "cells": len(table)}


def _render_module(table: dict[tuple, float], provenance: dict[str, Any]) -> str:
    lines = [
        '"""GENERATED -- do not edit by hand. Regenerate with:',
        "",
        "    py -3 scripts/mlb_leverage_index.py --write",
        "",
        "MLB leverage index by (inning, half, bases, outs, home margin).",
        "LI = 1.0 is an average plate appearance; 2.0 swings win probability twice",
        "as much; 0.3 is nearly dead.",
        "",
        "PROVENANCE, and it is not optional context:",
        f"  corpus            : statsapi feed_live, {provenance['games']} games,",
        f"                      {provenance['dates']} dates {provenance['date_min']} .. {provenance['date_max']}",
        f"  plate appearances : {provenance['plate_appearances']}",
        f"  cells             : {provenance['cells']}",
        "",
        "**ASSUMPTIONS INHERITED FROM THE WIN-EXPECTANCY COMPOSITION.** These values",
        "are NOT an empirical win probability. They rest on: i.i.d. innings, ONE",
        "league-average run distribution for BOTH sides, no team or park term, and",
        "extra innings collapsed to a constant. So a leverage value here describes a",
        "LEAGUE-AVERAGE situation and is wrong for a specific matchup. Do not present",
        "it as a property of the game in front of you.",
        "",
        "Start-of-game win expectancy in the underlying table is 0.500, where",
        "published tables show ~0.540; that gap IS the omitted home-field advantage.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"LEVERAGE_SOURCE = {provenance['source']!r}",
        f"LEVERAGE_CORPUS_GAMES = {provenance['games']}",
        f"LEVERAGE_CORPUS_DATES = {provenance['dates']}",
        "",
        "# (inning, half, bases, outs, home_margin) -> leverage index",
        "MLB_LEVERAGE_INDEX: dict[tuple[int, str, str, int, int], float] = {",
    ]
    for key in sorted(table):
        inning, half, state, outs, margin = key
        lines.append(f"    ({inning}, {half!r}, {state!r}, {outs}, {margin}): {table[key]},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=None)
    parser.add_argument("--min-n", type=int, default=100)
    parser.add_argument("--write", action="store_true",
                        help="Generate syndicate/features/shared/mlb_leverage_table.py")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    roots = [Path(r) for r in args.root] if args.root else [
        repo / "data" / "mlb_source" / "raw" / "statsapi" / "feed_live",
        repo / "data" / "mlb_source" / "source_artifacts" / "data" / "raw" / "statsapi" / "feed_live",
    ]

    we_mod = _load_sibling("mlb_win_expectancy")
    scanned = we_mod.scan_distributions(roots)
    we_table = we_mod.build_table(scanned["distributions"], extra_p=0.5, min_n=args.min_n)
    trans = scan_transitions(roots)
    result = compute_leverage(trans["transitions"], we_table.get("rows", []),
                              min_n=args.min_n, cell_counts=trans.get("cell_counts"))

    cov = trans["coverage"]
    print("MLB LEVERAGE INDEX -- COVERAGE FIRST")
    print(f"  games                 : {cov['games']}")
    print(f"  dates                 : {len(cov['dates'])}")
    print(f"  plate appearances     : {cov['plate_appearances']}")
    print(f"  transition states     : {len(trans['transitions'])}/24")
    print(f"  leverage cells        : {result.get('cells', 0)}")
    print(f"  mean |dWE| per PA     : {result.get('mean_swing', 0):.4f}")
    print()
    table = result.get("table") or {}
    checks = [
        ("start of game", (1, "top", "---", 0, 0)),
        ("bottom 9, tied, bases empty", (9, "bottom", "---", 0, 0)),
        ("bottom 9, tied, bases loaded, 2 out", (9, "bottom", "123", 2, 0)),
        ("bottom 9, down 1, runner 2nd, 2 out", (9, "bottom", "-2-", 2, -1)),
        ("top 1, bases empty, 2 out", (1, "top", "---", 2, 0)),
        ("bottom 9, up 6, bases empty", (9, "bottom", "---", 0, 6)),
        ("top 9, down 6, 2 out", (9, "top", "---", 2, -6)),
    ]
    print("  SANITY CHECKS -- high leverage late and close, dead in a blowout")
    for label, key in checks:
        value = table.get(key)
        print(f"    {label:<40} {('%.2f' % value) if value is not None else '(absent)'}")

    if args.write and table:
        dates = cov["dates"]
        provenance = {
            "games": cov["games"], "dates": len(dates),
            "date_min": dates[0] if dates else "", "date_max": dates[-1] if dates else "",
            "plate_appearances": cov["plate_appearances"], "cells": len(table),
            "source": "statsapi feed_live via scripts/mlb_leverage_index.py",
        }
        out = repo / "syndicate" / "features" / "shared" / "mlb_leverage_table.py"
        out.write_text(_render_module(table, provenance), encoding="utf-8")
        print(f"\n  WROTE {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
