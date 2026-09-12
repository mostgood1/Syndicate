"""Pool the accumulated live game-line accuracy trend, SPLIT BY SCORER ERA.

WHY THIS EXISTS. The trend used to be an ad-hoc one-liner pasted into a
scheduled-task brief. That is fine for printing rows and useless for the one
question the history exists to answer, because `history.jsonl` spans a
SCORER-VERSION BOUNDARY and a pooled number across it measures a bug fix rather
than the model (`learnings.md:3430`). Splitting on provenance BEFORE the first
statistic is the standing rule (`learnings.md:3235`), so this tool does it in
code instead of leaving it to whoever reads the file next.

HOW AN ERA IS DECIDED, and why NOT by the obvious field. `scored_markets` looks
like the scorer marker and is not: it is emitted by
`snapshot_live_gameline_score.py` -- the OBSERVER -- which gained the field days
AFTER the scorer fix `75cf9aec` (2026-08-30T16:59:02Z). Reading "stamp absent"
as "pre-fix" therefore misclassified 2026-08-30 and 2026-08-31 and silently
halved the usable sample. Established 2026-09-03 (`d9fb0b43`) on two independent
axes:

  * RATIO, with a same-ledger control. The pre-fix scorer folded totals P(over)
    and spreads P(home covers) into the scored population, so it scores many
    times more rows than h2h-only. Re-running the h2h-only scorer against
    production gave production/h2h-only of 14.74x (08-26), 7.46x (08-27), 7.46x
    (08-29) versus 1.17x (08-30) and 1.01x (08-31) -- no overlap. The control is
    what makes the ratio mean anything: `records_considered` matched EXACTLY on
    all five dates, so both read the same ledger and only the SCORED SUBSET
    differed.
  * CAPTURE TIME, an axis not used to derive the above. Every capture before the
    fix commit shows the pre-fix ratio and every capture after shows ~1x; the
    last pre-fix reading predates the commit by 22 minutes.

So era is decided by `scored_markets` OR capture time against the fix commit.

THE CAVEAT ON CAPTURE TIME. It is a proxy for when the score was COMPUTED, and
it holds only because the board re-scores over the retained ledger at request
time rather than replaying a stored verdict -- corroborated by
`records_considered` matching an independent offline run exactly. A future board
that serves a cached score would break the proxy, and the ratio check above is
how you would notice.

THE INDEPENDENT UNIT IS GAMES. The record counts are repeated snapshots of the
same few games across builds, so a date with 1,449 rows and 3 games carries
three games of evidence. Every pooled figure here is game-weighted and printed
with its game count.

A CUT CAN GO PERMANENTLY EMPTY, AND THAT USED TO BE SILENT. `best_per_date`
skips any date whose cut carries no brier, so a cut that stops being populated
does not shrink the pool -- it FREEZES it, and the tool keeps printing the same
total while new dates vanish. Measured 2026-09-12: MLB `priceable_only` went to
`model.n == 0` on 2026-09-11 and the pool still read "12 dates, 146 games",
unchanged and unmarked. `priceable` is a PUBLICATION verdict, not a
measurement-validity one -- the per-record ledger for 09-11 has 13,187 records,
`priceable=True` on ZERO, with `model_edge_publishing_disabled_for_sport` on 245
(09-09, before the switch: 41 priceable, that reason absent). The forecasts were
still recorded; only publication stopped.

So `coverage_gap()` below names every date that HAS outcomes and contributes
nothing to the requested cut, and `main` exits non-zero when the newest such
date is the most recent in the history. A frozen headline must announce itself.
Note that `fresh_quotes_only` is the age-conditioned cut, which `priceable_only`
is not -- `learnings.md:854` FORBIDS comparing model against market without
conditioning on quote age, because staleness flatters the model.

THIS TOOL NEVER WRITES to the history. It is append-only and concurrently
written by other sessions; rewriting it to tidy or dedupe destroys their rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

# 75cf9aec -- "the gameline scorer compared P(over) against did the home team win"
FIX_COMMIT_UTC = "2026-08-30T16:59:02"
PRE = "pre-fix"
POST = "post-fix"
DEFAULT_HISTORY = "reports/live_gameline_accuracy/history.jsonl"


def row_era(row):
    """Which scorer produced this row. See the module docstring."""
    if row.get("scored_markets"):
        return POST
    captured = (row.get("captured_at") or "")[:19]
    if captured and captured > FIX_COMMIT_UTC:
        return POST
    return PRE


def cut_values(row, cut):
    block = row.get(cut) or {}
    model = block.get("model") or {}
    market = block.get("market") or {}
    if model.get("brier") is None or market.get("brier") is None:
        return None
    return {
        "model": model["brier"],
        "market": market["brier"],
        "model_n": model.get("n"),
        "market_n": market.get("n"),
        "diff": block.get("model_minus_market_brier"),
    }


def best_per_date(rows, cut):
    """Per date keep the row with the most games -- the most complete capture.

    Never average briers across dates unweighted: a 3-game day would otherwise
    count the same as a 15-game day.
    """
    best = {}
    for row in rows:
        games = row.get("games_with_outcome") or 0
        if not games or cut_values(row, cut) is None:
            continue
        prior = best.get(row["date"])
        if prior is None or games > (prior.get("games_with_outcome") or 0):
            best[row["date"]] = row
    return best


def coverage_gap(rows, cut):
    """Dates that HAVE outcomes but contribute NOTHING to `cut`.

    A date counts as covered if ANY capture of it carries a brier for the cut
    with a non-zero model n, so a single thin snapshot does not mask a date that
    a later, fuller capture did measure. Returns [(date, games), ...] sorted.
    """
    seen = {}
    for row in rows:
        date = row.get("date")
        games = row.get("games_with_outcome") or 0
        if not date or not games:
            continue
        vals = cut_values(row, cut)
        covered = vals is not None and (vals.get("model_n") or 0) > 0
        prior = seen.get(date)
        if prior is None:
            seen[date] = {"games": games, "covered": covered}
        else:
            prior["games"] = max(prior["games"], games)
            prior["covered"] = prior["covered"] or covered
    return sorted((d, v["games"]) for d, v in seen.items() if not v["covered"])


def latest_dated(rows):
    """Most recent date in the history that actually has outcomes."""
    dates = [r["date"] for r in rows
             if r.get("date") and (r.get("games_with_outcome") or 0)]
    return max(dates) if dates else None


def pool(rows, cut):
    """Game-weighted pool over ONE era. Refuses a mixed-era set."""
    eras = {row_era(r) for r in rows}
    if len(eras) > 1:
        raise ValueError(
            "refusing to pool across scorer eras %s -- a number spanning the "
            "boundary measures the fix, not the model (learnings.md:3430)"
            % sorted(eras)
        )
    best = best_per_date(rows, cut)
    games = 0
    model = 0.0
    market = 0.0
    mismatched = []
    for date, row in best.items():
        vals = cut_values(row, cut)
        n = row["games_with_outcome"]
        games += n
        model += vals["model"] * n
        market += vals["market"] * n
        if vals["model_n"] != vals["market_n"]:
            mismatched.append((date, vals["model_n"], vals["market_n"]))
    if not games:
        return {"era": eras.pop() if eras else None, "cut": cut,
                "dates": 0, "games": 0, "per_date": {},
                "population_mismatch": []}
    return {
        "era": eras.pop() if eras else None,
        "cut": cut,
        "dates": len(best),
        "games": games,
        "model": model / games,
        "market": market / games,
        "diff": (model - market) / games,
        "population_mismatch": mismatched,
        "per_date": dict(
            (d, dict(games=r["games_with_outcome"], **cut_values(r, cut)))
            for d, r in sorted(best.items())
        ),
    }


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pool the live game-line trend, split by scorer era."
    )
    ap.add_argument("--history", default=DEFAULT_HISTORY)
    ap.add_argument(
        "--cut", default="priceable_only",
        choices=["priceable_only", "fresh_quotes_only", "all_records"],
    )
    ap.add_argument("--era", default=POST, choices=[PRE, POST, "each"])
    ap.add_argument("--json-out", default="")
    ap.add_argument(
        "--allow-stale-cut", action="store_true",
        help="Exit 0 even when the most recent date in the history carries no "
             "data for --cut. Off by default: a headline cut that has stopped "
             "being populated otherwise re-prints an unchanged pool forever.",
    )
    args = ap.parse_args(argv)

    try:
        rows = load(args.history)
    except FileNotFoundError:
        print("no history at %s" % args.history, file=sys.stderr)
        return 2
    if not rows:
        print("history is empty", file=sys.stderr)
        return 2

    by_era = defaultdict(list)
    for row in rows:
        by_era[row_era(row)].append(row)

    wanted = [PRE, POST] if args.era == "each" else [args.era]
    out = {}
    for era in wanted:
        if not by_era.get(era):
            print("\n=== %s: no rows ===" % era)
            continue
        res = pool(by_era[era], args.cut)
        out[era] = res
        print("\n=== %s | cut=%s | %d dates, %d games ==="
              % (era, args.cut, res["dates"], res["games"]))
        if not res["games"]:
            # No date in this era carries this cut. Normal, not an error:
            # pre-fix rows predate `fresh_quotes_only` entirely. Say so and
            # move on -- the pooled keys are absent from `res` here.
            print("  No date in this era carries cut=%s. Nothing to pool."
                  % args.cut)
            continue
        print("%-12s%6s%10s%10s%11s%18s"
              % ("date", "games", "model", "market", "diff", "n model/market"))
        for date, d in res["per_date"].items():
            print("%-12s%6d%10.5f%10.5f%+11.5f%18s"
                  % (date, d["games"], d["model"], d["market"], d["diff"],
                     "%s/%s" % (d["model_n"], d["market_n"])))
        print("%-12s%6d%10.5f%10.5f%+11.5f"
              % ("POOLED", res["games"], res["model"], res["market"],
                 res["diff"]))
        print("  NEGATIVE diff = the model beat the market. Independent unit "
              "is GAMES (%d), not records." % res["games"])
        if res["population_mismatch"]:
            print("  ** NOT LIKE-FOR-LIKE on these dates -- the model and "
                  "market briers span DIFFERENT row sets, so their difference "
                  "is not a comparison: **")
            for date, mn, kn in res["population_mismatch"]:
                print("       %s  model n=%s  market n=%s" % (date, mn, kn))

    if len(wanted) > 1:
        print("\nThe eras are reported SEPARATELY and are never combined: a "
              "pooled number across the boundary measures the scorer fix, not "
              "the model (learnings.md:3430).")

    # Scope the gap to the eras being REPORTED. A post-fix query that
    # lists pre-fix dates -- which legitimately predate the cut -- buries
    # the one date that matters under ten that do not, and a block the
    # reader learns to skip is the same as no block.
    scoped = [r for r in rows if row_era(r) in set(wanted)]
    gap = coverage_gap(scoped, args.cut)
    newest = latest_dated(scoped)
    stale = bool(gap) and newest is not None and newest in {d for d, _ in gap}
    out["coverage_gap"] = {"cut": args.cut, "newest_date": newest,
                           "stale": stale,
                           "dates": [{"date": d, "games": g} for d, g in gap]}
    if gap:
        missed = sum(g for _, g in gap)
        print("\n** COVERAGE GAP -- %d date(s) / %d game(s) have outcomes but "
              "contribute NOTHING to cut=%s: **" % (len(gap), missed, args.cut))
        for date, games in gap:
            print("       %s  games=%-3d  (no brier for this cut)" % (date, games))
        print("  These dates are NOT in the pool above. The pooled total does "
              "not shrink when a cut stops being populated -- it FREEZES.")
    if stale:
        print("\n** HEADLINE CUT IS STALE: the most recent date with outcomes "
              "(%s) carries no data for cut=%s. **" % (newest, args.cut))
        print("  The pool above describes an era that has STOPPED accumulating. "
              "Do not report it as current.")
        print("  `priceable` is a PUBLICATION verdict, not a measurement one: "
              "it goes to zero when edge publishing is switched off for the "
              "sport, while the forecasts are still recorded.")
        print("  Try --cut fresh_quotes_only (age-conditioned, per "
              "learnings.md:854), or --allow-stale-cut to accept a frozen pool.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
        print("\nwrote %s" % args.json_out)
    if stale and not args.allow_stale_cut:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
