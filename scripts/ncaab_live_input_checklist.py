"""Gating input checklist for the NCAAB live tier's team model (model engine standard section 1).

Lane `ncaab-native-live-tier`, phase P4 of
`docs/ai_context/basketball_live_native_plan.md`.

For every field of `NcaabTeamRating` (enumerated with `dataclasses.fields()`,
never a name list) it asks the two questions together:

  CONSUMED   -- does `live_team_model.game_prior` read it? (attribute access in
                its source, `.<field>`)
  POPULATED  -- over the REAL table the live tier would use for `--date`, what
                share of rated teams hold a usable value (finite, and for the
                rate fields not the dataclass/producer neutral)?

CONSUMED + under the floor is the alarm and exits 1. It also gates COVERAGE:
the share of the D-I registry (`shared/ncaab_team_registry.csv`) the table
rates, because an unrated team refuses its games -- correct, but a table that
rates half the league is a broken input, not a quiet one.

No table at all exits 2 (`no_ratings_table`): unknown is not healthy.

    py -3 scripts/ncaab_live_input_checklist.py --date 2026-11-04 [--json-out report.json]

Name the substrate: the table path is printed and written to the report. A
local read answers for the local tree only (CLAUDE.md, "Render is the source
of truth"); run it on the fleet for a production claim.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import inspect
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.ncaab import live_team_model as tm  # noqa: E402

REGISTRY = REPO / "syndicate" / "features" / "shared" / "ncaab_team_registry.csv"
POPULATED_FLOOR = 0.98
COVERAGE_FLOOR = 0.95
# Legitimately sparse, with the reason. Anything consumed and not listed must clear the floor.
EXPECTED_SPARSE = {
    "games": "0 for every team before its first game; the prior-season fallback sets 0 by design",
    "prior_weight": "0.0 once a team has enough games that last season no longer weighs in",
}


def _usable(value: object, name: str) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    if name in {"adj_off", "adj_def", "tempo"} and float(value) <= 0:  # type: ignore[arg-type]
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def run(day: dt.date) -> tuple[int, dict]:
    table = tm.table_for_game(day)
    if isinstance(table, tm.NcaabPriorRefusal):
        return 2, {"date": day.isoformat(), "verdict": "NO_TABLE", "refusal": dataclasses.asdict(table)}
    source = inspect.getsource(tm.game_prior)
    teams = list(table.teams.values())
    rows = []
    failed = []
    for f in dataclasses.fields(tm.NcaabTeamRating):
        consumed = re.search(rf"\.{re.escape(f.name)}\b", source) is not None
        share = sum(1 for t in teams if _usable(getattr(t, f.name), f.name)) / len(teams) if teams else 0.0
        sparse = f.name in EXPECTED_SPARSE
        ok = (not consumed) or sparse or share >= POPULATED_FLOOR
        rows.append({"field": f.name, "consumed": consumed, "populated_share": round(share, 4), "expected_sparse": EXPECTED_SPARSE.get(f.name), "ok": ok})
        if not ok:
            failed.append(f.name)
    with REGISTRY.open(encoding="utf-8", newline="") as handle:
        d1 = {row["espn_id"] for row in csv.DictReader(handle) if row.get("espn_id")}
    rated = d1 & set(table.teams)
    coverage = len(rated) / len(d1) if d1 else 0.0
    coverage_ok = coverage >= COVERAGE_FLOOR
    verdict = "PASS" if not failed and coverage_ok else "FAIL"
    report = {
        "date": day.isoformat(),
        "verdict": verdict,
        "table": table.source,
        "table_season": table.season,
        "table_as_of": table.as_of.isoformat(),
        "prior_season_fallback": table.prior_season_fallback,
        "teams_rated": len(teams),
        "d1_registry": len(d1),
        "d1_coverage": round(coverage, 4),
        "coverage_floor": COVERAGE_FLOOR,
        "fields": rows,
        "failed_fields": failed,
    }
    return (0 if verdict == "PASS" else 1), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    code, report = run(args.date)
    for row in report.get("fields", []):
        flag = "ok " if row["ok"] else "BAD"
        print(f"  {flag} {row['field']:<14} consumed={str(row['consumed']):<5} populated={row['populated_share']:.3f}" + (f"  (sparse: {row['expected_sparse']})" if row["expected_sparse"] else ""))
    print(f"[ncaab_live_input_checklist] {report['verdict']} " + " ".join(f"{k}={report[k]}" for k in ("date", "table", "table_as_of", "teams_rated", "d1_coverage") if k in report), flush=True)
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
