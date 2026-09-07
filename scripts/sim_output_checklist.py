#!/usr/bin/env python3
"""SIM ENGINE OUTPUT CHECKLIST -- are the numbers the sim PUBLISHES sane?

The other half of `docs/ai_context/model_engine_standard.md`. The five input
checklists (`sim_input_checklist.py` and its per-sport siblings) answer ONE
question: *is every field the engine reads actually fed?* That is necessary and
it is not sufficient.

**EVERY ENGINE COULD PASS ITS INPUT CHECKLIST AND STILL PUBLISH `1.0` AT 10-3 IN
THE SECOND QUARTER.** That is not hypothetical. Measured on production
2026-09-06, WIS @ ND, Q2 with 15:00 on the clock:

    WIS @ ND      10-3, Q2 15:00   published P(home) = 1.0     <- exact certainty
    LOU @ MISS    10-3, Q2 10:38   published P(home) = 0.779   <- the defensible answer

Same score, same quarter, two published probabilities that cannot both be right.
No input checklist can see that, because every input WAS fed.

WHY THIS FILE EXISTS AS A SCRIPT AND NOT A DOC. `[2026-09-06, user: "our #1
priority MUST be verifying sims end to end as functional and our differentiator
for every sport"]` and, on the probability sanity work done by hand that night,
`"that is just one example of what end to end needs to look like"`. Doing it by
hand found seven distinct defects in one session; none of them had a test, and
none would have been found by the suite. So it becomes a gate, like the input
checklists: exits non-zero, runs per sport, reads PRODUCTION.

EVERY CHECK BELOW WAS EARNED BY A REAL DEFECT. None is speculative:

  C1 NO EXACT CERTAINTY      83 of 2,810 MLB h2h rows published exactly 0.0/1.0
                             over 6 days; 59 were PRICED; 2 of 25 distinct games
                             LOST on one. Brier takes its 1.0 ceiling and log
                             loss is INFINITE, so two rows can dominate the
                             series the model is judged on.
  C2 ESTIMATOR AGREEMENT     `prob_std_err` computed Agresti-Coull `(k+2)/(n+4)`
                             for the INTERVAL and the caller published the raw
                             Wald `k/n` as the CENTRE. The correction reached
                             the width and never the middle, for months.
  C3 QUANTISATION            a probability must be expressible as a `k/n` (or
                             its smoothed form) for the `n` the row CLAIMS. A row
                             saying `sims_run=120` and carrying 0.9333 is
                             consistent (112/120); one carrying 0.93 is not, and
                             means `sims_run` is describing a different run than
                             the number beside it.
  C4 RESUME IDENTITY         a live re-sim resumed at kickoff must reproduce the
                             PREGAME number. Verified once by hand on production
                             (+0.0017 at 0-0 with 3:06 elapsed) and never since.
                             This is the single cheapest end-to-end proof that
                             the live path and the pregame path are the same
                             model.
  C5 DISCRIMINATION          NFL across-game `margin_mean` stdev was 2.16 where
                             NCAAF's was 15.37 -- an engine that cannot tell
                             teams apart still produces confident-looking output.
                             Collapsed spread and absurd spread are both faults.
  C6 INTERVAL IS REAL        `se == 0.0` reads as "perfectly precise" and makes
                             every edge clear the gate. Shipped once already
                             (`PHI @ MIN model=0.0 se=0.0` published PRICEABLE).

WHAT THIS DELIBERATELY DOES NOT DO. It does not score the model against
outcomes. Calibration and CLV are a different question with their own machinery
(`intelligence_evaluation`, the accuracy ledgers) and a much longer feedback
loop. This answers the question you can answer TODAY, on the rows already
written: are these numbers internally coherent and physically possible? A model
can pass every check here and still lose money. It cannot fail one of them and
be trusted about anything.

READS PRODUCTION, NOT `data/**`. Per CLAUDE.md the local tree is a lossy
cold-start mirror and says nothing about what production computed. Everything
here goes through `/api/ops/artifacts/export`, and the reading is refused rather
than degraded if production cannot be reached -- an unreachable service must
never read as a pass.

    python scripts/sim_output_checklist.py --sport mlb
    python scripts/sim_output_checklist.py --sport all --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BASE = os.environ.get("SYNDICATE_BASE_URL") or "https://syndicate-an21.onrender.com"
SPORTS = ("mlb", "ncaaf", "wnba", "soccer")

# A published probability this close to the boundary is treated as exact. The
# smoothed estimator's own floor at n=300 is 2/304 = 0.0066, so anything under
# 1e-9 is a true 0.0/1.0 and not a small smoothed value.
_EXACT_EPS = 1e-9
# C5: across-game spread of the published probability. Below the floor the
# engine cannot tell games apart; above the ceiling it is claiming more
# certainty than any game-level model supports.
_DISCRIM_FLOOR = 0.02
_DISCRIM_CEIL = 0.48


def _admin_token() -> str | None:
    """The admin token, or None.

    SEARCHES THE PRIMARY TREE TOO, and that is not incidental. `.env` is
    gitignored, so it does NOT exist inside a session worktree
    (`scripts/session_worktree.py`) -- which is where this script will usually be
    run from. The first version looked only beside the script, got None, 401'd
    every fetch, and the run reported PASS. Caught immediately, but it is the
    exact `unknown -> permissive` substitution this file exists to detect.
    """
    candidates = [
        Path(".env"),
        Path(__file__).resolve().parent.parent / ".env",
        # The primary shared checkout, when running from a worktree.
        Path.home() / "OneDrive" / "Coding" / "Syndicate" / ".env",
    ]
    extra = os.environ.get("SYNDICATE_PRIMARY_TREE")
    if extra:
        candidates.append(Path(extra) / ".env")
    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("ADMIN_TOKEN"):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
        except OSError:
            continue
    return os.environ.get("ADMIN_TOKEN")


def _export(path: str, token: str | None, timeout: int = 120) -> str:
    url = BASE + "/api/ops/artifacts/export?" + urllib.parse.urlencode({"path": path})
    req = urllib.request.Request(url, headers={"X-Admin-Token": token or ""})
    payload = json.load(urllib.request.urlopen(req, timeout=timeout))
    for _name, blob in (payload.get("artifacts") or {}).items():
        if isinstance(blob, str):
            return blob
    return ""


def ledger_records(sport: str, day: str, token: str | None) -> list[dict[str, Any]]:
    blob = _export(
        f"{sport}_source/data/live_gameline_ledger/live_gameline_ledger_{day}.jsonl",
        token,
    )
    out: list[dict[str, Any]] = []
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


class Result:
    def __init__(self, sport: str) -> None:
        self.sport = sport
        self.alarms: list[str] = []
        self.notes: list[str] = []
        self.checks: dict[str, str] = {}

    def alarm(self, check: str, msg: str) -> None:
        self.checks[check] = "ALARM"
        self.alarms.append(f"[{self.sport}] {check}: {msg}")

    def ok(self, check: str, msg: str) -> None:
        self.checks[check] = "ok"
        self.notes.append(f"[{self.sport}] {check}: {msg}")

    def skip(self, check: str, msg: str) -> None:
        # UNMEASURED IS NOT A PASS. It is reported and it does not fail the run,
        # but it must never be silently rendered as `ok` -- that substitution is
        # the one this whole standard exists to prevent.
        self.checks[check] = "UNMEASURED"
        self.notes.append(f"[{self.sport}] {check}: UNMEASURED -- {msg}")


def check_sport(sport: str, rows: list[dict[str, Any]]) -> Result:
    res = Result(sport)
    h2h = [r for r in rows if str(r.get("market") or "").lower() in {"h2h", "h2h_3_way"}]
    probs = [(r, _f(r.get("model_home_win_prob"))) for r in h2h]
    probs = [(r, p) for r, p in probs if p is not None]
    if not probs:
        for c in ("C1", "C2", "C3", "C4", "C5", "C6"):
            res.skip(c, f"no h2h rows carrying a model probability in {len(rows)} records")
        return res

    # ---- C1: no exact certainty -------------------------------------------
    cert = [(r, p) for r, p in probs if p <= _EXACT_EPS or p >= 1.0 - _EXACT_EPS]
    priced = [(r, p) for r, p in cert if r.get("priceable")]
    if cert:
        eg = cert[0][0]
        res.alarm(
            "C1_no_exact_certainty",
            f"{len(cert)} of {len(probs)} h2h rows published exactly 0.0/1.0 "
            f"({100.0 * len(cert) / len(probs):.2f}%), {len(priced)} of them PRICED. "
            f"e.g. {eg.get('away_team')} @ {eg.get('home_team')} p={cert[0][1]} "
            f"at {eg.get('recorded_at')}. Brier ceiling 1.0, log loss infinite.",
        )
    else:
        res.ok("C1_no_exact_certainty", f"0 of {len(probs)} rows at the boundary")

    # ---- C2: the centre uses the interval's estimator ----------------------
    tagged = [(r, p) for r, p in probs if r.get("point_estimator")]
    if not tagged:
        res.skip(
            "C2_estimator_agreement",
            "no row carries `point_estimator`; either the fix predates these rows "
            "or the field is not being written",
        )
    else:
        bad = []
        for r, p in tagged:
            raw = _f(r.get("model_home_win_prob_raw"))
            n = _f(r.get("sims_run"))
            if raw is None or n is None or n <= 0:
                continue
            expect = (raw * n + 2.0) / (n + 4.0)
            if abs(expect - p) > 5e-4:
                bad.append((r, p, expect))
        if bad:
            r, p, expect = bad[0]
            res.alarm(
                "C2_estimator_agreement",
                f"{len(bad)} of {len(tagged)} rows tagged `agresti_coull` do not MATCH "
                f"that estimator. e.g. published {p}, estimator says {expect:.6f} "
                f"from raw={r.get('model_home_win_prob_raw')} n={r.get('sims_run')}",
            )
        else:
            res.ok(
                "C2_estimator_agreement",
                f"{len(tagged)} tagged rows all reproduce their stated estimator",
            )

    # ---- C3: quantisation matches the claimed sim count -------------------
    checked = mismatched = 0
    example = None
    for r, p in probs:
        n = _f(r.get("sims_run"))
        if n is None or n <= 0 or n > 100000:
            continue
        raw = _f(r.get("model_home_win_prob_raw"))
        candidate = raw if raw is not None else p
        k = candidate * n
        checked += 1
        # HALF-INTEGER NUMERATORS ARE LEGAL, and assuming otherwise made this
        # check fire on CORRECT behaviour the first time it ran against
        # production. `ncaaf/live_resim.py:437` is
        # `(home_wins + 0.5 * ties) / ran` -- a tie counts as HALF a win, because
        # the engine's two-round overtime cap leaves a small share of simulated
        # games level and scoring those as losses would bias every probability
        # downward. So 115 wins + 1 tie over 120 sims is 115.5/120 = 0.9625,
        # which is exactly the value flagged. Soccer (draws) and NHL have the
        # same shape.
        #
        # A CHECK THAT FIRES ON CORRECT OUTPUT IS WORSE THAN NO CHECK: it trains
        # the reader to skip the alarm, and the next one will be real.
        grid = k * 2.0
        if abs(grid - round(grid)) > 0.04 * max(1.0, n / 120.0) + 1e-6:
            mismatched += 1
            if example is None:
                example = (r, candidate, n, k)
    if not checked:
        res.skip("C3_quantisation", "no row carries a usable `sims_run`")
    elif mismatched:
        r, candidate, n, k = example
        res.alarm(
            "C3_quantisation",
            f"{mismatched} of {checked} rows carry a probability that is not a k/n "
            f"for their OWN stated sims_run. e.g. p={candidate} n={n:.0f} -> k={k:.3f}. "
            f"`sims_run` is describing a different run than the number beside it.",
        )
    else:
        res.ok("C3_quantisation", f"{checked} rows consistent with their stated sims_run")

    # ---- C4: resume identity at kickoff -----------------------------------
    early = []
    for r, p in probs:
        frac = _f(r.get("progress_fraction"))
        pre = _f(r.get("pregame_home_win_prob"))
        if frac is None or pre is None or frac > 0.05:
            continue
        early.append((r, p, pre, abs(p - pre)))
    if not early:
        res.skip(
            "C4_resume_identity",
            "no row with progress_fraction<=0.05 AND a pregame baseline (needs v4 records)",
        )
    else:
        worst = max(early, key=lambda t: t[3])
        gaps = [t[3] for t in early]
        if worst[3] > 0.10:
            res.alarm(
                "C4_resume_identity",
                f"live and pregame disagree by {worst[3]:.4f} at kickoff "
                f"({worst[0].get('away_team')} @ {worst[0].get('home_team')}: live {worst[1]}, "
                f"pregame {worst[2]}). A re-sim resumed at t=0 must reproduce the pregame model; "
                f"n={len(early)} median gap {statistics.median(gaps):.4f}",
            )
        else:
            res.ok(
                "C4_resume_identity",
                f"n={len(early)} kickoff rows, median gap {statistics.median(gaps):.4f}, "
                f"worst {worst[3]:.4f}",
            )

    # ---- C5: does the engine tell games apart? ----------------------------
    by_game: dict[Any, list[float]] = defaultdict(list)
    for r, p in probs:
        by_game[r.get("game_pk") or r.get("event_id")].append(p)
    per_game = [statistics.mean(v) for v in by_game.values() if v]
    if len(per_game) < 4:
        res.skip("C5_discrimination", f"only {len(per_game)} distinct games")
    else:
        sd = statistics.pstdev(per_game)
        if sd < _DISCRIM_FLOOR:
            res.alarm(
                "C5_discrimination",
                f"across-game stdev {sd:.4f} over {len(per_game)} games is below "
                f"{_DISCRIM_FLOOR} -- the engine barely distinguishes matchups, which is "
                f"the shape NFL showed at margin stdev 2.16 against NCAAF's 15.37",
            )
        elif sd > _DISCRIM_CEIL:
            res.alarm(
                "C5_discrimination",
                f"across-game stdev {sd:.4f} over {len(per_game)} games exceeds "
                f"{_DISCRIM_CEIL} -- more spread than a game-level model supports",
            )
        else:
            res.ok("C5_discrimination", f"across-game stdev {sd:.4f} over {len(per_game)} games")

    # ---- C6: the interval is real -----------------------------------------
    ses = [(r, _f(r.get("prob_std_err"))) for r, _p in probs]
    zero = [r for r, se in ses if se is not None and se <= 0.0]
    present = [se for _r, se in ses if se is not None]
    if not present:
        res.skip("C6_interval_is_real", "no row carries prob_std_err")
    elif zero:
        res.alarm(
            "C6_interval_is_real",
            f"{len(zero)} rows carry prob_std_err == 0.0, which reads as perfect "
            f"precision and makes every edge clear the gate (shipped once already: "
            f"PHI @ MIN model=0.0 se=0.0 published PRICEABLE)",
        )
    else:
        res.ok(
            "C6_interval_is_real",
            f"{len(present)} rows, min se {min(present):.6f}",
        )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sport", default="all", help="mlb | ncaaf | wnba | soccer | all")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today, then yesterday)")
    ap.add_argument("--json", default=None, help="write the full result here")
    ap.add_argument("--warn-only", action="store_true", help="report alarms but exit 0")
    args = ap.parse_args()

    token = _admin_token()
    sports = SPORTS if args.sport == "all" else tuple(s.strip() for s in args.sport.split(","))
    days = [args.date] if args.date else [date.today().isoformat(),
                                          (date.today() - timedelta(days=1)).isoformat()]

    print("SIM ENGINE OUTPUT CHECKLIST -- are the published numbers coherent?")
    print(f"  source: {BASE}  (PRODUCTION -- never data/**)\n")

    results: list[Result] = []
    unreachable: list[str] = []
    for sport in sports:
        rows: list[dict[str, Any]] = []
        used_day = None
        for day in days:
            try:
                rows = ledger_records(sport, day, token)
            except Exception as exc:  # noqa: BLE001
                # AN UNREACHABLE SERVICE MUST NEVER READ AS A PASS.
                unreachable.append(f"{sport} {day}: {type(exc).__name__}")
                continue
            if rows:
                used_day = day
                break
        if not rows:
            print(f"=== {sport}: NO LEDGER ROWS READ (days tried: {', '.join(days)}) ===\n")
            continue
        res = check_sport(sport, rows)
        results.append(res)
        print(f"=== {sport}  {used_day}  {len(rows)} ledger records ===")
        for line in res.notes:
            print("  " + line)
        for line in res.alarms:
            print("  ALARM " + line)
        print()

    total_alarms = sum(len(r.alarms) for r in results)
    if unreachable:
        print("COULD NOT READ (reported, never counted as a pass):")
        for u in unreachable:
            print("  " + u)
        print()
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "base": BASE,
                    "sports": {r.sport: {"checks": r.checks, "alarms": r.alarms} for r in results},
                    "unreachable": unreachable,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    counts = Counter(v for r in results for v in r.checks.values())
    print(f"SUMMARY: {dict(counts)}")

    # A RUN THAT READ NOTHING IS NOT A PASS. The first version of this function
    # returned 0 here, because "no rows" produced "no alarms" -- so a bad token,
    # a 502, or a wrong host all rendered as success. That is the same
    # `unknown -> permissive` substitution every check in this file is written to
    # catch, and it shipped in the file that catches it. Read nothing, fail
    # LOUDLY: the caller must be able to tell "the engine is coherent" from
    # "I could not look".
    if not results:
        print("\nFAIL -- NOTHING WAS READ. This is not a pass.")
        if unreachable:
            print("        Every fetch failed; check ADMIN_TOKEN and SYNDICATE_BASE_URL.")
        else:
            print("        No ledger rows exist for the days tried.")
        return 2
    if total_alarms and not args.warn_only:
        print(f"\nFAIL -- {total_alarms} alarm(s)")
        return 1
    if unreachable:
        # Partial coverage is reported at the top level too, so a green run on
        # two sports is never mistaken for a green run on all of them.
        print(f"\nPARTIAL -- {len(results)} sport(s) checked, {len(unreachable)} fetch(es) failed")
        return 0 if not total_alarms else 1
    print("\nPASS" if not total_alarms else f"\nWARN -- {total_alarms} alarm(s) (--warn-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
