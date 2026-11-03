"""Gating input checklist for the college live tier's inputs (model engine standard section 1).

Lane `ncaab-native-live-tier`, phase P4 of
`docs/ai_context/basketball_live_native_plan.md`; `--league wncaab` since
2026-11-03 (lane `wncaab-module`), the same checks on the women's tables.

For every field of `NcaabTeamRating` (enumerated with `dataclasses.fields()`,
never a name list) it asks the two questions together:

  CONSUMED   -- does `live_team_model.game_prior` read it? (attribute access in
                its source, `.<field>`)
  POPULATED  -- over the REAL table the live tier would use for `--date`, what
                share of rated teams hold a usable value (finite, and for the
                rate fields not the dataclass/producer neutral)?

CONSUMED + under the floor is the alarm and exits 1. Both tables a game can be
priced from are checked: this season's, and last season's regressed table that
`prior_for_game` falls back to per game.

It also gates COVERAGE of the D-I registry, measured the way the live tier
prices a game:

  * RATINGS: a team rated this season OR last season. Since 2026-11-02 the
    fallback is PER GAME (`prior_for_game`), so early in the season a team
    with no game yet is still priced from last season. Counting this season's
    table alone read 65% on the fleet on 2026-11-03 for a tier that priced
    every D-I-vs-D-I game -- a false alarm is still a broken instrument.
  * PLAYER PRIORS: a team with at least `MIN_ROTATION` projected players in
    the newest player-priors table (in-season rows, else preseason rows --
    `load_player_priors`). A team without them refuses every game
    (`team_has_no_player_priors` / `thin_rotation`).

An unrated team or one without player priors refuses its games -- correct per
game, but an input that covers half the league is broken, not quiet.

No ratings table at all exits 2 (`no_ratings_table`), and so does no player-
priors table (`no_player_priors`): unknown is not healthy.

    py -3 scripts/ncaab_live_input_checklist.py --date 2026-11-04 [--league wncaab] [--json-out report.json]

Name the substrate: the table paths are printed and written to the report. A
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

from syndicate.features.ncaab import live_resim as lr  # noqa: E402
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


def _registry(league: str) -> Path:
    if league == "ncaab":
        return REGISTRY
    from syndicate.features.college_basketball.league import league_for

    return league_for(league).registry_csv


def _dirs(league: str):
    # NCAAB passes None so `table_for_game` / `load_player_priors` resolve their own default directories.
    return None if league == "ncaab" else tm.ratings_dirs(league)


def _field_rows(table, source: str) -> tuple[list[dict], list[str]]:
    teams = list(table.teams.values())
    rows, failed = [], []
    for f in dataclasses.fields(tm.NcaabTeamRating):
        consumed = re.search(rf"\.{re.escape(f.name)}\b", source) is not None
        share = sum(1 for t in teams if _usable(getattr(t, f.name), f.name)) / len(teams) if teams else 0.0
        sparse = f.name in EXPECTED_SPARSE
        ok = (not consumed) or sparse or share >= POPULATED_FLOOR
        rows.append({"field": f.name, "consumed": consumed, "populated_share": round(share, 4), "expected_sparse": EXPECTED_SPARSE.get(f.name), "ok": ok})
        if not ok:
            failed.append(f.name)
    return rows, failed


def run(day: dt.date, league: str = "ncaab") -> tuple[int, dict]:
    dirs = _dirs(league)
    table = tm.table_for_game(day, dirs=dirs)
    if isinstance(table, tm.NcaabPriorRefusal):
        return 2, {"league": league, "date": day.isoformat(), "verdict": "NO_TABLE", "refusal": dataclasses.asdict(table)}
    source = inspect.getsource(tm.game_prior)
    rows, failed = _field_rows(table, source)
    fallback = None if table.prior_season_fallback else tm._prior_season_table(day, dirs=dirs)
    fallback_rows: list[dict] = []
    if fallback is not None:
        fallback_rows, fallback_failed = _field_rows(fallback, source)
        failed += [f"fallback:{name}" for name in fallback_failed]
    with _registry(league).open(encoding="utf-8", newline="") as handle:
        d1 = {row["espn_id"] for row in csv.DictReader(handle) if row.get("espn_id")}
    in_season = d1 & set(table.teams)
    rated = in_season | (d1 & set(fallback.teams) if fallback is not None else set())
    coverage = len(rated) / len(d1) if d1 else 0.0
    report = {
        "league": league,
        "date": day.isoformat(),
        "table": table.source,
        "table_season": table.season,
        "table_as_of": table.as_of.isoformat(),
        "prior_season_fallback": table.prior_season_fallback,
        "fallback_table": fallback.source if fallback is not None else None,
        "teams_rated": len(table.teams),
        "d1_registry": len(d1),
        "d1_coverage": round(coverage, 4),
        "d1_coverage_this_table": round(len(in_season) / len(d1), 4) if d1 else 0.0,
        "d1_unrated": sorted(d1 - rated),
        "coverage_floor": COVERAGE_FLOOR,
        "fields": rows,
        "fallback_fields": fallback_rows,
        "failed_fields": failed,
    }
    priors = lr.load_player_priors(day, dirs=dirs)
    if isinstance(priors, lr.NcaabResimRefusal):
        report.update(verdict="NO_PLAYER_PRIORS", player_priors_refusal=dataclasses.asdict(priors))
        return 2, report
    fielded = {tid for tid, prows in priors.by_team.items()
               if sum(1 for r in prows if lr._num(r.get("min_proj")) > 0) >= lr.MIN_ROTATION}
    priors_coverage = len(d1 & fielded) / len(d1) if d1 else 0.0
    report.update(
        player_priors=priors.source,
        player_priors_as_of=priors.as_of.isoformat(),
        player_priors_coverage=round(priors_coverage, 4),
        d1_without_player_priors=sorted(d1 - fielded),
    )
    ok = not failed and coverage >= COVERAGE_FLOOR and priors_coverage >= COVERAGE_FLOOR
    report["verdict"] = "PASS" if ok else "FAIL"
    return (0 if ok else 1), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--league", default="ncaab", choices=("ncaab", "wncaab"))
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    code, report = run(args.date, args.league)
    for label, key in (("", "fields"), ("fallback ", "fallback_fields")):
        for row in report.get(key, []):
            flag = "ok " if row["ok"] else "BAD"
            print(f"  {flag} {label}{row['field']:<14} consumed={str(row['consumed']):<5} populated={row['populated_share']:.3f}" + (f"  (sparse: {row['expected_sparse']})" if row["expected_sparse"] else ""))
    keys = ("league", "date", "table", "table_as_of", "fallback_table", "teams_rated", "d1_coverage", "d1_coverage_this_table",
            "player_priors", "player_priors_coverage")
    print(f"[ncaab_live_input_checklist] {report['verdict']} " + " ".join(f"{k}={report[k]}" for k in keys if k in report), flush=True)
    for key in ("d1_unrated", "d1_without_player_priors"):
        if report.get(key):
            print(f"  {key} ({len(report[key])}): {', '.join(report[key][:25])}{' ...' if len(report[key]) > 25 else ''}", flush=True)
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
