# -*- coding: utf-8 -*-
"""`#636`'s reading: the shot divisor against each player's OWN season rate.

This is the composition-invariant check the soccer-shot-shrinkage lane
specified and could never run, because its denominator -- `shots_per90` in
`soccer_source/<league>/players/players_<season>.csv` -- was not in
`HOT_ARTIFACT_PATTERNS` and so could not be read from web at all.

  ratio = expected_shots / (shots_per90 * expected_minutes_share)

Every player is his own denominator, so the slate's composition cannot move
it -- which matters because the soccer sim runs 4-hourly while the slate
rotates faster, and any top-N or slate-mean reading would be measuring the
slate instead of the model.

The lane recorded this at **1.19 before the divisor shipped**; with a divisor
of ~1.393 applied at the `expected_shots` choke point it must land near
**1.19 / 1.393 = 0.85**.

NOTE ON THE POISSON INVERSION. The lane described backing the mean out of a
served row's `model_prob_over`. That was the route available when only
probabilities were readable. The prediction archive carries `expected_shots`
directly -- the same quantity, before it is turned into a probability -- so
this reads it rather than inverting `1 - exp(-lambda)` and inheriting the
line-rounding of whatever market line the row happened to carry.

Inputs:
  %TEMP%/prod_recs      the production recommendation archive
  --csv-dir             players CSVs, one file per <league>__players__*.csv
                        as written by the export endpoint
"""
import argparse, collections, csv, glob, io, json, os, statistics, sys, unicodedata

sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS

RECS = os.path.join(os.environ.get("TEMP", "."), "prod_recs")


def fold(n):
    return "".join(c for c in unicodedata.normalize("NFKD", str(n))
                   if not unicodedata.combining(c)).lower().strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", required=True,
                    help="directory of exported players CSVs (<path with / as __>)")
    ap.add_argument("--since", default="",
                    help="only fixtures on/after this date (use the divisor ship date)")
    # WITHOUT AN UPPER BOUND THE 'BEFORE' WINDOW SILENTLY INCLUDES 'AFTER'.
    # Ran it that way once: the control came back 0.793 having pooled both
    # regimes, which is not a control, it is the average of the thing and its
    # own baseline.
    ap.add_argument("--until", default="",
                    help="only fixtures strictly BEFORE this date")
    args = ap.parse_args()

    # --- denominator: each player's own season shots_per90 -------------------
    # Keyed (league, folded name). When a player has more than one season file
    # the LATEST season wins, matching what the engine itself reads.
    rate: dict[tuple[str, str], tuple[str, float]] = {}
    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    for f in files:
        base = os.path.basename(f).replace("__", "/")
        parts = base.split("/")
        league = parts[1] if len(parts) > 2 else ""
        season = os.path.splitext(parts[-1])[0].split("_")[-1]
        if league not in LEAGUE_ESPN_SLUGS:
            continue
        with io.open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                nm = (row.get("player_name") or "").strip()
                raw = (row.get("shots_per90") or "").strip()
                if not nm or not raw:
                    continue
                try:
                    v = float(raw)
                except ValueError:
                    continue
                if v <= 0:
                    continue
                k = (league, fold(nm))
                if k not in rate or season > rate[k][0]:
                    rate[k] = (season, v)
    print("season rates loaded: %d players over %d csv file(s), %d league(s)"
          % (len(rate), len(files), len({k[0] for k in rate})))
    if not rate:
        print("NO DENOMINATOR -- export the players CSVs first.")
        return 2

    # --- numerator: the engine's own expected_shots ---------------------------
    ratios: list[float] = []
    per_league = collections.defaultdict(list)
    rows = matched = 0
    for f in sorted(glob.glob(os.path.join(RECS, "*.json"))):
        try:
            j = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        lg, dt = j.get("league"), str(j.get("date") or "")
        if lg not in LEAGUE_ESPN_SLUGS or not dt:
            continue
        if args.since and dt < args.since:
            continue
        if args.until and dt >= args.until:
            continue
        for r in (j.get("player_props") or []):
            nm, es = r.get("player_name"), r.get("expected_shots")
            ms = r.get("expected_minutes_share")
            if not nm or es is None or not ms:
                continue
            rows += 1
            got = rate.get((lg, fold(nm)))
            if not got or float(ms) <= 0.05:
                continue
            denom = got[1] * float(ms)
            if denom <= 0:
                continue
            matched += 1
            v = float(es) / denom
            ratios.append(v)
            per_league[lg].append(v)

    print("prop rows considered %d | joined to a season rate %d (%.1f%%)"
          % (rows, matched, 100.0 * matched / max(rows, 1)))
    if matched < 100:
        print("TOO FEW JOINED ROWS to read -- reporting nothing rather than a noisy median.")
        return 3

    ratios.sort()
    print("")
    print("  ratio = expected_shots / (shots_per90 * expected_minutes_share)")
    print("  median %.3f | mean %.3f | p25 %.3f | p75 %.3f | n=%d"
          % (statistics.median(ratios), statistics.mean(ratios),
             ratios[len(ratios) // 4], ratios[3 * len(ratios) // 4], len(ratios)))
    print("")
    print("  1.19  measured BEFORE the divisor shipped")
    print("  0.85  expected with a ~1.393 divisor applied  (1.19 / 1.393)")
    print("")
    print("  per league (a pooled reading driven by one league is not a reading)")
    for lg, vs in sorted(per_league.items(), key=lambda kv: -len(kv[1])):
        if len(vs) < 50:
            continue
        print("    %-20s n=%-5d median %.3f" % (lg, len(vs), statistics.median(vs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
