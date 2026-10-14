"""Why does a board row carry a projection and no `model_edge_pct`? Attribute it.

    python scripts/audit_model_edge_gap.py
    python scripts/audit_model_edge_gap.py --sports nfl,ncaaf
    python scripts/audit_model_edge_gap.py --base-url http://127.0.0.1:10000 --json

WHY THIS EXISTS, and why counting the gap was not enough.

A 2026-09-28 reading found `model_edge_pct` on 5 of 98 rows and filed it as "the
board is full but carries no model opinion". A 2026-10-14 recount found 78.4% of
3,939 rows -- the gap had largely closed -- and the residue, ~426 rows, got filed
again with a guess attached: *"the board already prints
`projection.edge_unavailable_reason`, so the reason is probably already being
recorded and simply not counted."*

MEASURED 2026-10-14 23:26Z: **94.0% of the gap rows carry no
`edge_unavailable_reason` at all** (795 of 846). The guess was wrong, and wrong
in a structural way worth stating once: the PER-SPORT projection builders record
their refusals (`no no-vig fair`, `no probability to price`,
`prob_interval_swamps_edge`), and `layer2_board._model_edge_for` -- the function
that actually decides whether a row gets a top-level `model_edge_pct` -- records
nothing on any of its `return None` paths. A reason field that only upstream
writes cannot explain a drop that happens downstream.

So this attributes the gap by calling the DEPLOYED `_model_edge_for` logic over
the served rows rather than re-deriving the rule. Measured that same minute, all
805 gap rows across six in-season sports resolved into five named branches:

    431  53.5%  CEILING: |edge| > 15.0 points, dropped not clamped
    319  39.6%  no probability at all: nothing to price
     49   6.1%  no market fair probability (model prob present)
      3   0.4%  no model probability (market fair present)
      3   0.4%  NOT AN OPPOSITE: projected side 'home' vs row side 'draw'

100% of NFL's 229, 100% of NCAAF's 158 and 100% of MLB's 9 were the CEILING. So
the gap is not a broken join: it is one deliberate plausibility bound plus one
sport's unpriceable market (soccer `alternate_totals_corners`, which carries
`projected` and neither probability).

AND THE SECOND HALF, which is the part worth acting on. `--skill` grades every
row that DOES contribute a model edge by the verdict the board already stamps in
`projection.model_skill`. Measured the same minute, n=3,011:

    2,184 of 3,011 (72.5%) come from a model whose OWN verdict says it loses to
    the market or was never backtested. ZERO rows come from a model the board
    says beats the market.

The 15-point ceiling therefore is not a skill filter and must not be read as
one: on NFL, 228 of 229 rows it REJECTED and 613 of 670 it ACCEPTED carry the
same `loses_to_market` verdict. It separates large disagreements from small ones
inside one model, which is a different thing from separating models that work
from models that do not.

TWO INSTRUMENT DEFECTS THIS SCRIPT REPORTS RATHER THAN SMOOTHING OVER:

  * `model_skill.verdict_class` IS NOT A SAFE FILTER. 217 rows carry a verdict
    text reading "loses to the closing line ..." under
    `verdict_class: measured` or `parity`. The vocabulary is per-sport: NCAAF
    writes `measured` (a status) where NFL writes `loses_to_market` (a verdict).
    `--skill` grades on the TEXT and prints the disagreement.
  * THE PAYLOAD'S WITHHOLDING COUNTERS ARE GLOBAL, NOT PER-SPORT.
    `rows_uninformative_ev`, `rows_below_value_floor`,
    `opportunities_considered` and `rows_admitted_by_blend` came back
    byte-identical for all six sports on a `?sport=<s>` request. Attributing
    them to the sport you filtered on overstates that sport by the whole board.
    `--counters` checks this every run instead of trusting the last reading.

ROW CAP DISCIPLINE. `rows_truncated` can read 0 while rows are missing, so a
sport is NOT reported unless `rows == total_rows`. A truncated sport is named
and skipped; it never contributes to a share.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from scripts._base_url import default_base_url
except ImportError:  # run as `python scripts/<name>.py`
    from _base_url import default_base_url

DEFAULT_BASE = default_base_url()
SPORTS = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]
LIMIT = 5000

#: Counters the shortlist payload returns that LOOK per-sport and are not.
GLOBAL_COUNTER_KEYS = (
    "rows_uninformative_ev",
    "rows_admitted_by_blend",
    "rows_below_value_floor",
    "opportunities_considered",
)

# Graded on the verdict TEXT, because `verdict_class` is a per-sport vocabulary
# (see the module docstring). Order matters: "never backtested" wins over
# everything, and an explicit loss wins over a bare "parity" mention.
_NEVER = re.compile(r"never backtested|unvalidated", re.I)
_BEATS = re.compile(r"\bbeats\b|\bbetter than\b|\boutperforms\b", re.I)
_LOSES = re.compile(r"\bloses to\b|\bworse than\b|point worse", re.I)
_PARITY = re.compile(r"\bparity\b", re.I)

GRADE_NEVER = "NEVER BACKTESTED"
GRADE_LOSES = "LOSES to the market/close"
GRADE_BEATS = "beats the market"
GRADE_PARITY = "parity with the market"
GRADE_NO_BLOCK = "no model_skill block"
GRADE_NO_TEXT = "no verdict text"

#: Grades that mean the ranking is leaning on a model with no demonstrated edge.
GRADES_WITHOUT_DEMONSTRATED_EDGE = (GRADE_LOSES, GRADE_NEVER)


def blank(value) -> bool:
    return value in (None, "", [], {})


def grade_skill(row) -> tuple[str, str]:
    """(grade from the verdict TEXT, the row's own verdict_class).

    Returned as a pair on purpose: the caller reports the disagreement between
    them rather than picking one, because that disagreement is a finding.
    """
    projection = row.get("projection")
    skill = projection.get("model_skill") if isinstance(projection, dict) else None
    if not isinstance(skill, dict):
        return GRADE_NO_BLOCK, "(none)"
    cls = str(skill.get("verdict_class") or skill.get("status") or "(none)")
    text = str(skill.get("verdict") or "")
    if not text:
        return GRADE_NO_TEXT, cls
    if _NEVER.search(text):
        return GRADE_NEVER, cls
    if _BEATS.search(text) and not _LOSES.search(text):
        return GRADE_BEATS, cls
    if _LOSES.search(text):
        return GRADE_LOSES, cls
    if _PARITY.search(text):
        return GRADE_PARITY, cls
    return "other: " + text[:46], cls


def classify_gap_row(row, board) -> str:
    """Which of `_model_edge_for`'s `return None` paths fires for this row.

    `board` is the imported `layer2_board` module: the constants and the side
    helpers come from the DEPLOYED code, so this cannot drift from the rule it
    is attributing. Only the branch ORDER is restated here, and it is restated
    to match the function top to bottom.
    """
    projection = row.get("projection")
    if not isinstance(projection, dict):
        return "no projection mapping"
    edge = board._as_float(projection.get("edge_vs_market_pct"))
    if edge is None:
        if not blank(projection.get("edge_vs_modelled_fair_pct")):
            return "modelled-fair fallback present (should NOT be a gap row)"
        if blank(projection.get("model_prob_over")) and blank(projection.get("market_fair_prob_over")):
            return "no probability at all: nothing to price"
        if blank(projection.get("model_prob_over")):
            return "no model probability (market fair present)"
        return "no market fair probability (model prob present)"
    if abs(edge) > board._MODEL_EDGE_MAX_POINTS:
        return "CEILING: |edge| > %g points, dropped not clamped" % board._MODEL_EDGE_MAX_POINTS
    side = str(row.get("side") or "").strip().lower()
    try:
        framed = board._projection_side_in_row_frame(row, projection)
    except Exception as exc:  # a served row may lack a field the helper reads
        return "side framing raised %s" % type(exc).__name__
    if framed == board._SIDE_UNPLACEABLE:
        return "SIDE UNPLACEABLE: projection side not resolvable in the row's frame"
    if not framed or framed == side:
        return "would RETURN the edge (something else dropped it)"
    if board._TWO_WAY_OPPOSITE_SIDE.get(framed) != side:
        return "NOT AN OPPOSITE: projected side %r vs row side %r" % (framed, side)
    return "would return -edge (something else dropped it)"


def _fetch(base: str, sport: str, timeout: float = 180.0):
    url = "%s/api/board/layer2-shortlist?%s" % (
        base.rstrip("/"), urllib.parse.urlencode({"sport": sport, "limit": LIMIT}))
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _rows_and_cap(payload):
    """(rows, total_rows, cap_ok). cap_ok is False when the page is truncated."""
    rows = [r for r in (payload.get("rows") or payload.get("shortlist") or []) if isinstance(r, dict)]
    total = payload.get("total_rows")
    if total is None:
        return rows, total, len(rows) < LIMIT
    return rows, total, len(rows) == int(total)


def _pct(part, whole):
    return (100.0 * part / whole) if whole else 0.0


def collect(base, sports, timeout=180.0):
    """Per-sport attribution. Pure enough to test: no printing, no argv."""
    from syndicate.features.shared import layer2_board as board

    out = {"base_url": base, "ceiling_points": board._MODEL_EDGE_MAX_POINTS,
           "sports": {}, "truncated": [], "failed": {}, "counter_signatures": {}}
    for sport in sports:
        try:
            payload = _fetch(base, sport, timeout)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            out["failed"][sport] = repr(exc)[:120]
            continue
        rows, total, cap_ok = _rows_and_cap(payload)
        sig = json.dumps({k: payload.get(k) for k in GLOBAL_COUNTER_KEYS},
                         sort_keys=True, default=str)
        out["counter_signatures"].setdefault(sig, []).append(sport)
        if not cap_ok:
            out["truncated"].append({"sport": sport, "rows": len(rows), "total_rows": total})
            continue
        gap = [r for r in rows
               if not blank(r.get("projection")) and blank(r.get("model_edge_pct"))]
        edged = [r for r in rows if not blank(r.get("model_edge_pct"))]
        branches = collections.Counter(classify_gap_row(r, board) for r in gap)
        reasons = collections.Counter()
        for row in gap:
            projection = row.get("projection")
            reason = projection.get("edge_unavailable_reason") if isinstance(projection, dict) else None
            reasons["(NO REASON RECORDED)" if blank(reason) else str(reason)] += 1
        grades, mismatches = collections.Counter(), collections.Counter()
        for row in edged:
            grade, cls = grade_skill(row)
            grades[grade] += 1
            if grade == GRADE_LOSES and cls != "loses_to_market":
                mismatches[cls] += 1
            elif grade == GRADE_NEVER and cls != "unmeasured":
                mismatches[cls] += 1
        out["sports"][sport] = {
            "rows": len(rows), "gap": len(gap), "edged": len(edged),
            "branches": dict(branches), "reasons": dict(reasons),
            "grades": dict(grades), "class_text_mismatches": dict(mismatches),
            "markets": dict(collections.Counter(
                str(r.get("market") or r.get("market_key") or "?") for r in gap).most_common(10)),
        }
    return out


def _print_report(data, show_skill=True, show_counters=True):
    print("  base %s   ceiling %g points" % (data["base_url"], data["ceiling_points"]))
    for row in data["truncated"]:
        print("  %-8s TRUNCATED %d of %s rows -- NOT REPORTED (no share over a truncated page)"
              % (row["sport"], row["rows"], row["total_rows"]))
    for sport, err in data["failed"].items():
        print("  %-8s FETCH FAILED %s" % (sport, err))

    sports = data["sports"]
    rows = sum(s["rows"] for s in sports.values())
    gap = sum(s["gap"] for s in sports.values())
    print()
    print("  === THE GAP: a projection present, top-level model_edge_pct absent ===")
    print("  %-8s %7s %7s %7s | %s" % ("sport", "rows", "gap", "edged", "no reason recorded"))
    print("  " + "-" * 72)
    for sport, s in sports.items():
        if not s["rows"]:
            continue
        nr = s["reasons"].get("(NO REASON RECORDED)", 0)
        print("  %-8s %7d %7d %7d | %5d (%5.1f%% of gap)"
              % (sport, s["rows"], s["gap"], s["edged"], nr, _pct(nr, s["gap"])))
    no_reason = sum(s["reasons"].get("(NO REASON RECORDED)", 0) for s in sports.values())
    print("  " + "-" * 72)
    print("  POOLED %d rows | gap %d (%.1f%%) | no reason on %d (%.1f%% of the gap)"
          % (rows, gap, _pct(gap, rows), no_reason, _pct(no_reason, gap)))

    pooled_branches = collections.Counter()
    for s in sports.values():
        pooled_branches.update(s["branches"])
    print()
    print("  === BRANCH ATTRIBUTION (the deployed _model_edge_for, over served rows) ===")
    for branch, n in pooled_branches.most_common():
        print("    %5d  %5.1f%%  %s" % (n, _pct(n, gap), branch))

    if show_skill:
        pooled_grades, pooled_mismatch = collections.Counter(), collections.Counter()
        for s in sports.values():
            pooled_grades.update(s["grades"])
            pooled_mismatch.update(s["class_text_mismatches"])
        edged = sum(pooled_grades.values())
        print()
        print("  === WHOSE model opinion the ranking uses (rows WITH a model edge, n=%d) ===" % edged)
        print("  graded on the verdict TEXT, because verdict_class is a per-sport vocabulary")
        for grade, n in pooled_grades.most_common():
            print("    %5d  %5.1f%%  %s" % (n, _pct(n, edged), grade))
        weak = sum(pooled_grades.get(g, 0) for g in GRADES_WITHOUT_DEMONSTRATED_EDGE)
        print()
        print("    -> %d of %d (%.1f%%) come from a model its own verdict says LOSES to the market"
              % (weak, edged, _pct(weak, edged)))
        print("       or was NEVER BACKTESTED.   beats the market: %d (%.1f%%)"
              % (pooled_grades.get(GRADE_BEATS, 0), _pct(pooled_grades.get(GRADE_BEATS, 0), edged)))
        if pooled_mismatch:
            total_mm = sum(pooled_mismatch.values())
            print()
            print("    verdict_class IS NOT A SAFE FILTER: %d row(s) whose verdict TEXT says"
                  % total_mm)
            print("    loses/never-backtested carry a class that does not: %s"
                  % ", ".join("%s=%d" % kv for kv in pooled_mismatch.most_common()))

    if show_counters:
        print()
        print("  === are the payload's withholding counters per-sport? ===")
        sigs = data["counter_signatures"]
        for sig, group in sigs.items():
            print("    %-46s <- %s" % (sig[:46], ", ".join(group)))
        if len(sigs) == 1 and len(next(iter(sigs.values()))) > 1:
            print("    %d distinct signature(s) across %d sports -> GLOBAL, NOT PER-SPORT."
                  % (len(sigs), sum(len(v) for v in sigs.values())))
            print("    Attributing %s to the sport you filtered on overstates it by the whole board."
                  % ", ".join(GLOBAL_COUNTER_KEYS[:2]))
        else:
            print("    %d distinct signature(s) -> they differ by sport." % len(sigs))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or DEFAULT_BASE)
    parser.add_argument("--sports", default=",".join(SPORTS),
                        help="comma-separated; default every sport")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--json", action="store_true", help="emit the raw counts and exit")
    parser.add_argument("--no-skill", action="store_true",
                        help="skip the model-skill grading half")
    parser.add_argument("--no-counters", action="store_true",
                        help="skip the per-sport-counter check")
    args = parser.parse_args(argv)

    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    data = collect(args.base_url, sports, args.timeout)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
        return 0
    _print_report(data, show_skill=not args.no_skill, show_counters=not args.no_counters)
    return 0


if __name__ == "__main__":
    sys.exit(main())
