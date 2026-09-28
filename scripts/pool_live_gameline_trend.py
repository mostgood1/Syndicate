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

PUBLICATION WAS SWITCHED BACK ON 2026-09-16, so `priceable_only` is populated
again -- as a SECOND series, not a continuation of the first. By user decision,
lane `board-category-gates` deleted `SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS=mlb`
from refresh-worker, live with deploy `b59887db` at 18:50:42Z (`deploys.md`
18:45:03Z). On the 09-16 per-record ledger (1,805 records) the last
`model_edge_publishing_disabled_for_sport` row is 18:42:37Z and the first
`priceable=True` row is 19:16:11Z; no build mixes the two. So 09-16 is a SPLIT
date, and 09-11..09-15 are a gap in that cut. This tool does not know about the
gap: pooling `priceable_only` across it splices two publication regimes into one
number. Pool it only from 2026-09-16 on. `fresh_quotes_only` has no such gap,
which is one more reason it stays the headline.

So `coverage_gap()` below names every date that HAS outcomes and contributes
nothing to the requested cut, and `main` exits non-zero when the newest such
date is the most recent in the history. A frozen headline must announce itself.
Note that `fresh_quotes_only` is the age-conditioned cut, which `priceable_only`
is not -- `learnings.md:854` FORBIDS comparing model against market without
conditioning on quote age, because staleness flatters the model.

THE POOLED DIFFERENCE IS PAIRED. `live_gameline_score._paired` is explicit
that a difference must not use `model`: a record carries a model probability
whenever it is scored, but `market_fair_prob` can be absent, so `model` spans
MORE rows than `market` and subtracting them compares two populations. Rows
from scorer contract 2 on carry `model_paired` -- the model scored on exactly
the market's rows -- and `cut_values` uses it whenever it is present. Until
2026-09-12 it did not, and the POOLED line disagreed with the per-date `diff`
column printed above it: `fresh_quotes_only` pooled to +0.00571 unpaired
against +0.00460 paired, the whole gap from 2026-09-01..09-04 (model n
497/293/67/66 vs market n 452/263/61/56). `priceable_only` was immune only
because priceable rows happen to carry a price -- the scorer's own words.
Older rows with no `model_paired` fall back to `model` and are still flagged
NOT LIKE-FOR-LIKE when the two n differ.

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
    """The per-date briers a pool may combine -- PAIRED whenever the row allows.

    `model` is the model's score over every row it scored; `model_paired` is
    the same model restricted to the rows that also carry a market price. Only
    the second may be subtracted from `market`. See the module docstring.
    """
    block = row.get(cut) or {}
    model = block.get("model") or {}
    market = block.get("market") or {}
    paired = block.get("model_paired") or {}
    if model.get("brier") is None or market.get("brier") is None:
        return None
    use_paired = paired.get("brier") is not None
    src = paired if use_paired else model
    return {
        "model": src["brier"],
        "market": market["brier"],
        "model_n": src.get("n"),
        "market_n": market.get("n"),
        "model_all_n": model.get("n"),
        "paired": use_paired,
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


def row_population(row):
    """Which selection of GAMES this row's brier was computed over.

    `board` is every ordinary capture: the games the board's own finals index
    resolved at build time. `statsapi` appears only on rows re-scored from a
    ledger for a date whose board population could not be reconstructed (the
    pre-fix window -- see `rescore_live_gameline_date.py`), and is the sport's
    own record instead.

    ABSENT MEANS `board`, and that is not a permissive default: every row
    without the field was written by a capture reading a board build, so it IS
    a board population by construction. Only a re-score can be anything else,
    and a re-score always stamps it.

    The two are NOT interchangeable. `score_live_gameline_offline.py` measured
    the board's index at 143 games over 08-20..08-31 where StatsAPI gives 157,
    and the shortfall lands on whichever games upstream score-nulling touched
    -- so it is a biased selection, not a random sample of the same thing.
    """
    return str(row.get("finals_population") or "board")


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
    paired_exclusions = []
    for date, row in best.items():
        vals = cut_values(row, cut)
        n = row["games_with_outcome"]
        games += n
        model += vals["model"] * n
        market += vals["market"] * n
        if vals["model_n"] != vals["market_n"]:
            mismatched.append((date, vals["model_n"], vals["market_n"]))
        extra = (vals["model_all_n"] or 0) - (vals["model_n"] or 0)
        if vals["paired"] and extra > 0:
            # Rows the model scored with no market price. Pairing drops them
            # from the comparison, correctly -- but COUNT the drop, because an
            # exclusion nobody counts is how "n 94 vs 90" had to be spotted by
            # eye (live_gameline_score._paired).
            paired_exclusions.append((date, extra))
    if not games:
        return {"era": eras.pop() if eras else None, "cut": cut,
                "dates": 0, "games": 0, "per_date": {},
                "population_mismatch": [], "paired_exclusions": [],
                "by_population": {}}
    # THE SAME POOL, SPLIT BY WHICH GAMES IT SELECTED. Reported always, so a
    # headline can never quietly average two selections: the era split already
    # exists for the same reason one layer up.
    by_population = {}
    for date, row in best.items():
        vals = cut_values(row, cut)
        n = row["games_with_outcome"]
        acc = by_population.setdefault(
            row_population(row),
            {"dates": 0, "games": 0, "_m": 0.0, "_k": 0.0, "date_list": []})
        acc["dates"] += 1
        acc["games"] += n
        acc["_m"] += vals["model"] * n
        acc["_k"] += vals["market"] * n
        acc["date_list"].append(date)
    for acc in by_population.values():
        acc["model"] = acc.pop("_m") / acc["games"]
        acc["market"] = acc.pop("_k") / acc["games"]
        acc["diff"] = acc["model"] - acc["market"]
        acc["date_list"].sort()
    return {
        "era": eras.pop() if eras else None,
        "cut": cut,
        "dates": len(best),
        "games": games,
        "model": model / games,
        "market": market / games,
        "diff": (model - market) / games,
        "population_mismatch": mismatched,
        "paired_exclusions": paired_exclusions,
        "by_population": by_population,
        "per_date": dict(
            (d, dict(games=r["games_with_outcome"], **cut_values(r, cut)))
            for d, r in sorted(best.items())
        ),
    }


# ---------------------------------------------------------------------------
# THE LINE-PRICED MARKETS (totals, spreads) -- scorer contract 3.
#
# WHY THIS SECTION EXISTS. The scorer has scored totals and spreads on every
# build since 2026-09-08 (the model's POINT FORECAST against the LINE, which is
# the market's own forecast for a -110/-110 market), and the history has kept
# it since 2026-09-24 -- but this tool pooled only the h2h Brier. So the nightly
# report never mentioned them, and on 2026-09-28 a session told the user they
# were "not scored" off a printout that labelled them `(refused)`.
#
# THE HEADLINE IS THE POINT ERROR, NOT THE HIT RATE. `model_minus_line_mae`
# compares two forecasts of the same number on the same rows: NEGATIVE means
# the model's mean sat closer to the actual than the line did. The hit rate
# against 0.50 is printed beside it but is NOT a market comparison --
# `bucket_realised_performance.py` measured "always back the over" and "side
# with the current score" winning 12-22pp above 0.50 on this same ledger, so a
# model that copies either looks skilled against a coin.
#
# SAME DISCIPLINE AS THE BRIER POOL: games are the independent unit (a date's
# figure is weighted by that family's own game count, never by rows); per date
# the capture with the MOST games is kept, and on a tie a board capture is
# preferred over a ledger re-score (the board's measurement is the reference a
# re-score is checked against, not the other way round); a date with outcomes
# and no point-forecast data is named, not skipped.
# ---------------------------------------------------------------------------
PF_FAMILIES = ("totals", "spreads")


def pf_cut(row, family, cut):
    """The per-date point-forecast figures for one family, or None."""
    block = ((row.get("point_forecast") or {}).get(family) or {}).get(cut) or {}
    if not block.get("n") or block.get("model_mae") is None or block.get("line_mae") is None:
        return None
    return block


def best_pf_per_date(rows, family, cut):
    best = {}
    for row in rows:
        vals = pf_cut(row, family, cut)
        if vals is None or not vals.get("games"):
            continue
        prior = best.get(row["date"])
        if prior is None:
            best[row["date"]] = row
            continue
        prior_games = pf_cut(prior, family, cut)["games"]
        if vals["games"] > prior_games or (
            vals["games"] == prior_games
            and prior.get("rescored_from_ledger") and not row.get("rescored_from_ledger")
        ):
            best[row["date"]] = row
    return best


def pool_point_forecast(rows, family, cut):
    """Game-weighted pool of one family's point-forecast figures over ONE era."""
    eras = {row_era(r) for r in rows}
    if len(eras) > 1:
        raise ValueError("refusing to pool across scorer eras %s" % sorted(eras))
    best = best_pf_per_date(rows, family, cut)
    games = 0
    acc = {"model_mae": 0.0, "line_mae": 0.0, "hit_rate": 0.0}
    se_sq = 0.0
    per_date = {}
    for date in sorted(best):
        vals = pf_cut(best[date], family, cut)
        g = vals["games"]
        games += g
        for key in acc:
            acc[key] += vals[key] * g
        if vals.get("se_pp_on_games") is not None:
            se_sq += (vals["se_pp_on_games"] * g) ** 2
        per_date[date] = {
            "games": g, "n": vals["n"], "model_mae": vals["model_mae"],
            "line_mae": vals["line_mae"],
            "model_minus_line_mae": vals["model_mae"] - vals["line_mae"],
            "hit_rate": vals["hit_rate"],
            "rescored": bool(best[date].get("rescored_from_ledger")),
            "population": row_population(best[date]),
        }
    if not games:
        return {"family": family, "cut": cut, "dates": 0, "games": 0, "per_date": {}}
    model_mae = acc["model_mae"] / games
    line_mae = acc["line_mae"] / games
    return {
        "family": family, "cut": cut, "dates": len(best), "games": games,
        "model_mae": model_mae, "line_mae": line_mae,
        "model_minus_line_mae": model_mae - line_mae,
        "hit_rate": acc["hit_rate"] / games,
        # Treats dates as independent, which they are (different games).
        "se_pp_on_games": (se_sq ** 0.5) / games,
        "per_date": per_date,
    }


def pf_coverage_gap(rows, family, cut):
    """Dates with outcomes, on or after the first date this family was scored,
    that contribute nothing to it. Before the first scored date the family did
    not exist (ledger v5, 2026-09-06 late) -- that is structural, not a gap."""
    covered, games_by_date = set(), {}
    for row in rows:
        date, games = row.get("date"), row.get("games_with_outcome") or 0
        if not date or not games:
            continue
        games_by_date[date] = max(games_by_date.get(date, 0), games)
        if pf_cut(row, family, cut) is not None:
            covered.add(date)
    if not covered:
        return []
    first = min(covered)
    return sorted((d, g) for d, g in games_by_date.items() if d >= first and d not in covered)


def pool_segment_h2h(rows, segment):
    """Game-weighted PAIRED Brier pool of one segment's h2h observations.

    `all_records` is the cut: first5 observation rows carry no quote age and
    are never priceable, so the fresh and priceable cuts are empty by
    construction (not a gap). Rows are written only when the rounded
    probability moves, so n counts probability CHANGES, not builds.
    """
    best = {}
    for row in rows:
        block = (((row.get("segments") or {}).get("by_segment") or {}).get(segment) or {})
        allr = block.get("all_records") or {}
        mp, mk = allr.get("model_paired") or {}, allr.get("market") or {}
        g = block.get("games_with_outcome") or 0
        if not g or mp.get("brier") is None or mk.get("brier") is None:
            continue
        prior = best.get(row["date"])
        if prior is None or g > prior[0] or (
            g == prior[0] and prior[1].get("rescored_from_ledger")
            and not row.get("rescored_from_ledger")
        ):
            best[row["date"]] = (g, row, mp, mk)
    games = 0
    model = market = 0.0
    per_date = {}
    for date in sorted(best):
        g, row, mp, mk = best[date]
        games += g
        model += mp["brier"] * g
        market += mk["brier"] * g
        per_date[date] = {"games": g, "model": mp["brier"], "market": mk["brier"],
                          "diff": mp["brier"] - mk["brier"], "n": mk.get("n"),
                          "rescored": bool(row.get("rescored_from_ledger"))}
    if not games:
        return {"segment": segment, "dates": 0, "games": 0, "per_date": {}}
    return {"segment": segment, "dates": len(best), "games": games,
            "model": model / games, "market": market / games,
            "diff": (model - market) / games, "per_date": per_date}


def print_point_forecast(rows, cut):
    """The totals/spreads and segment section. Returns (json block, stale)."""
    post = [r for r in rows if row_era(r) == POST]
    out = {}
    stale = False
    newest = latest_dated(post)
    for family in PF_FAMILIES:
        res = pool_point_forecast(post, family, cut)
        gap = pf_coverage_gap(post, family, cut)
        res["coverage_gap"] = [{"date": d, "games": g} for d, g in gap]
        out[family] = res
        print("\n=== point-forecast | %s | cut=%s | %d dates, %d games ==="
              % (family, cut, res["dates"], res["games"]))
        if not res["games"]:
            print("  No row carries point_forecast.%s.%s. Nothing to pool." % (family, cut))
            continue
        print("%-12s%6s%7s%11s%10s%13s%9s"
              % ("date", "games", "n", "model_mae", "line_mae", "model-line", "hit"))
        for date, d in res["per_date"].items():
            print("%-12s%6d%7d%11.3f%10.3f%+13.3f%9.3f%s"
                  % (date, d["games"], d["n"], d["model_mae"], d["line_mae"],
                     d["model_minus_line_mae"], d["hit_rate"],
                     "  (rescored)" if d["rescored"] else ""))
        print("%-12s%6d%7s%11.3f%10.3f%+13.3f%9.3f"
              % ("POOLED", res["games"], "", res["model_mae"], res["line_mae"],
                 res["model_minus_line_mae"], res["hit_rate"]))
        print("  model-line = model mean's error MINUS the line's, in runs; NEGATIVE = "
              "the model was closer to the actual than the market's line. GAMES are "
              "the unit (%d)." % res["games"])
        print("  hit = share of rows where the actual landed on the model's side of "
              "the line (se ~%.1fpp on games). NOT a market comparison: 'always over' "
              "and 'side with the current score' also beat 0.50 "
              "(bucket_realised_performance.py)." % res["se_pp_on_games"])
        if gap:
            print("  ** COVERAGE GAP -- dates with outcomes and no %s point-forecast "
                  "data: %s **" % (family, ", ".join("%s (%d games)" % x for x in gap)))
            if newest in {d for d, _ in gap}:
                stale = True
                print("  ** STALE: the most recent date with outcomes (%s) carries no "
                      "%s point-forecast data. **" % (newest, family))
    seg = pool_segment_h2h(post, "first5")
    out["segments"] = {"first5_h2h": seg}
    print("\n=== segment first5 h2h (observation rows, all_records, PAIRED) | "
          "%d dates, %d games ===" % (seg["dates"], seg["games"]))
    if seg["games"]:
        print("%-12s%6s%7s%10s%10s%11s" % ("date", "games", "n", "model", "market", "diff"))
        for date, d in seg["per_date"].items():
            print("%-12s%6d%7s%10.5f%10.5f%+11.5f%s"
                  % (date, d["games"], d["n"], d["model"], d["market"], d["diff"],
                     "  (rescored)" if d["rescored"] else ""))
        print("%-12s%6d%7s%10.5f%10.5f%+11.5f"
              % ("POOLED", seg["games"], "", seg["model"], seg["market"], seg["diff"]))
        print("  Brier, NEGATIVE diff = model beat the market. first5 is NOT published "
              "(recorded as an observation only), so this is its only skill reading. "
              "A level first five is a push and is not scored.")
    else:
        print("  No row carries segments.by_segment.first5 yet.")
    return out, stale


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
        pops = res.get("by_population") or {}
        if len(pops) > 1:
            print("  ** THIS POOL SPANS %d GAME POPULATIONS -- the figure above "
                  "averages two different selections of games, so read the "
                  "split, not the headline: **" % len(pops))
            for name in sorted(pops):
                acc = pops[name]
                print("       %-9s %3d dates %4d games  model %.5f  market "
                      "%.5f  diff %+0.5f"
                      % (name, acc["dates"], acc["games"], acc["model"],
                         acc["market"], acc["diff"]))
                print("                   %s..%s"
                      % (acc["date_list"][0], acc["date_list"][-1]))
            print("       `board` is the games the board's own finals index "
                  "resolved; `statsapi` is the sport's record, used where the "
                  "board population could not be reconstructed. The board's "
                  "index is LOSSY and not randomly so (143 games vs 157 over "
                  "08-20..08-31), so neither is a superset of the other.")
        if res["population_mismatch"]:
            print("  ** NOT LIKE-FOR-LIKE on these dates -- the model and "
                  "market briers span DIFFERENT row sets, so their difference "
                  "is not a comparison: **")
            for date, mn, kn in res["population_mismatch"]:
                print("       %s  model n=%s  market n=%s" % (date, mn, kn))
        if res.get("paired_exclusions"):
            print("  The model column is PAIRED -- scored only on rows that also "
                  "carry a market price, so both columns span the same rows. "
                  "Rows the model scored with NO market price, excluded from "
                  "the comparison:")
            for date, extra in res["paired_exclusions"]:
                print("       %s  %d row(s)" % (date, extra))

    if len(wanted) > 1:
        print("\nThe eras are reported SEPARATELY and are never combined: a "
              "pooled number across the boundary measures the scorer fix, not "
              "the model (learnings.md:3430).")

    pf_stale = False
    if POST in wanted:
        out["point_forecast"], pf_stale = print_point_forecast(rows, args.cut)

    # Scope the gap to the eras being REPORTED, and WITHIN those, to eras that
    # actually carry the cut. A post-fix query listing pre-fix dates -- which
    # legitimately predate the cut -- buries the one date that matters under
    # ten that do not, and a block the reader learns to skip is the same as no
    # block. An era carrying the cut on NO date is a structural absence, not a
    # gap, and `main` has already said "Nothing to pool" for it.
    scoped = [r for r in rows if row_era(r) in set(wanted)]
    gap = []
    for era in wanted:
        if not (out.get(era) or {}).get("games"):
            continue
        gap.extend(coverage_gap(by_era.get(era) or [], args.cut))
    gap.sort()
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
    if (stale or pf_stale) and not args.allow_stale_cut:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
