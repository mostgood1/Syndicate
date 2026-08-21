"""GATING input checklist for the NFL fantasy projection engine.

Required by ``docs/ai_context/model_engine_standard.md`` s1. It exists because
a sim engine can be completely broken and completely silent: an input the
engine READS that nothing POPULATES produces output identical to a build where
the feature does not exist. Unit tests cannot see it -- they supply the very
data that is missing (s6).

So this cross-references two questions per field, and neither alone is enough:

    CONSUMED?    does the engine's source actually read this field
    POPULATED?   over REAL artifacts, does it hold something other than its default

CONSUMED + UNPOPULATED is the alarm, and the only combination that is both
broken and invisible.

Enumerates ``dataclasses.fields()``. Never greps for names -- s4.1: a name
search proves only that your own vocabulary is absent, which is how an audit
published "no batted-ball model" about an engine that had four such fields.

    python scripts/nfl_fantasy_input_checklist.py --season 2026
    python scripts/nfl_fantasy_input_checklist.py --season 2026 --write

Exits non-zero on failure so it can gate /preflight or migration_gate.py.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy_players import roster_substrate  # noqa: E402
from syndicate.features.nfl.fantasy_projection import DEFAULT_CONFIG  # noqa: E402
from syndicate.features.nfl.fantasy_projection import _history_seasons  # noqa: E402
from syndicate.features.nfl.fantasy_schedule import schedule_substrate  # noqa: E402
from syndicate.features.nfl.fantasy_usage import PlayerSeasonUsage  # noqa: E402
from syndicate.features.nfl.fantasy_usage import TeamSeasonUsage  # noqa: E402
from syndicate.features.nfl.fantasy_usage import load_season_usage  # noqa: E402
from syndicate.features.nfl.fantasy_usage import usage_substrate  # noqa: E402


#: Fields that are legitimately sparse, with a REASON each. Anything consumed
#: and not listed here has to clear the floor. s1 requires the reason to be
#: written down, because "known sparse" with no reason is indistinguishable
#: from "broken and excused".
EXPECTED_SPARSE: dict[str, str] = {
    "pass_2pt": "two-point conversions are rare league-wide; ~0.4 attempts per team-game",
    "rush_2pt": "as above",
    "rec_2pt": "as above",
    "def_safeties": "a safety is a genuinely rare event; most team-seasons have 0 or 1",
    "def_blocked_kicks": "rare by nature",
    "fg_att_50_plus": "only kickers, and only a quarter of their attempts",
    "fg_made_50_plus": "as above, and only the made ones",
    "fg_att_40_49": "only kickers",
    "fg_made_40_49": "only kickers",
    "fg_att_0_39": "only kickers",
    "fg_made_0_39": "only kickers",
    "fg_att": "only kickers -- ~1.5% of rostered players",
    "pat_att": "only kickers",
    "pat_made": "only kickers",
    "fg_made": "team-level, but still a small count per game",
    "fg_att": "only kickers",
    "week": "0 on a summed season record by design; meaningful only on a per-game line",
    "games": "a count, always 1 on a per-game line",
    "rec_air_yards": "receivers only",
    "sacks_taken": "quarterbacks only",
    "interceptions": "quarterbacks only",
    "pass_completions": "quarterbacks only",
    "pass_attempts": "quarterbacks only -- ~4% of rostered players",
    "pass_yards": "quarterbacks only",
    "pass_tds": "quarterbacks only",
    "gl_carries": "goal-line carries concentrate in very few players",
    "gl_targets": "as above",
    "fumbles_lost": "a fumble lost is rare per player-season",
}

#: A consumed field must be populated on at least this share of records to pass.
POPULATION_FLOOR = 0.10


def _consumed_fields(dataclass_type: type) -> dict[str, bool]:
    """Which of a dataclass's fields the ENGINE source actually reads.

    Reads the engine modules as text and asks whether each declared field name
    appears. This is the one place a text search is correct, and it is the
    inverse of the s4.1 mistake: the field names come from
    ``dataclasses.fields()``, not from a list someone guessed, so a field
    cannot be missed because it was named something unexpected.
    """
    source = "\n".join(
        (Path(__file__).resolve().parents[1] / "syndicate" / "features" / "nfl" / name).read_text(
            encoding="utf-8"
        )
        for name in (
            "fantasy_projection.py",
            "fantasy_draft_board.py",
            "fantasy_scoring.py",
            "fantasy.py",
            "fantasy_news.py",
        )
    )
    return {spec.name: (spec.name in source) for spec in dataclasses.fields(dataclass_type)}


def _population(records, dataclass_type: type) -> dict[str, float]:
    """Share of records where each field differs from its dataclass DEFAULT.

    Compared against the DEFAULT, not against ``None`` -- s1. A field sitting
    at its default is unfed even though it holds a number, and that is exactly
    the case a ``!= None`` test declares healthy.
    """
    defaults = {}
    for spec in dataclasses.fields(dataclass_type):
        if spec.default is not dataclasses.MISSING:
            defaults[spec.name] = spec.default
        elif spec.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            defaults[spec.name] = spec.default_factory()  # type: ignore[misc]
        else:
            defaults[spec.name] = None
    total = len(records) or 1
    counts = {name: 0 for name in defaults}
    for record in records:
        for name, default in defaults.items():
            if getattr(record, name, default) != default:
                counts[name] += 1
    return {name: counts[name] / total for name in counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--write", action="store_true", help="publish the report artifact")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    season = args.season
    history = _history_seasons(season, len(DEFAULT_CONFIG.season_recency_weights))

    substrates = {
        "usage": [usage_substrate(value) for value in history],
        "schedule": schedule_substrate(season),
        "roster": roster_substrate(season),
    }

    # ---- s3b: a local checkout must report UNMEASURED, never 0%.
    reachable = [entry for entry in substrates["usage"] if entry["exists"]]
    if not reachable:
        print("UNMEASURED -- no NFL play-by-play on this substrate.", flush=True)
        print(
            "  FROM THIS CHECKOUT: `data/**` is a lossy mirror and `tracking/` is\n"
            "  gitignored, so a zero here says nothing about production. Read\n"
            "  /api/ops/artifacts/export?pattern=nfl_source/fantasy/* instead.",
            flush=True,
        )
        return 1

    players: list[PlayerSeasonUsage] = []
    teams: list[TeamSeasonUsage] = []
    for value in history:
        season_players, season_teams = load_season_usage(value)
        players.extend(season_players.values())
        teams.extend(season_teams.values())

    findings: list[dict[str, object]] = []
    failures = 0
    for label, dataclass_type, records in (
        ("PlayerSeasonUsage", PlayerSeasonUsage, players),
        ("TeamSeasonUsage", TeamSeasonUsage, teams),
    ):
        consumed = _consumed_fields(dataclass_type)
        population = _population(records, dataclass_type)
        for name in sorted(consumed):
            if name == "game_ids":
                continue
            is_consumed = consumed[name]
            share = population.get(name, 0.0)
            sparse_reason = EXPECTED_SPARSE.get(name)
            if not is_consumed:
                verdict = "unused"
            elif share >= POPULATION_FLOOR:
                verdict = "ok"
            elif sparse_reason:
                verdict = "sparse_expected"
            else:
                verdict = "FAIL"
                failures += 1
            findings.append(
                {
                    "record": label,
                    "field": name,
                    "consumed": is_consumed,
                    "populated_share": round(share, 4),
                    "verdict": verdict,
                    "reason": sparse_reason,
                }
            )

    print(f"=== NFL fantasy input checklist: season {season} ===")
    print(f"substrate: usage seasons {history}, {len(players)} player-seasons, {len(teams)} team-seasons")
    print(f"           schedule {substrates['schedule']['regular_season_games']} games, "
          f"{substrates['schedule']['games_with_market_line']} with a market line")
    print(f"           roster {substrates['roster']['fantasy_players']} players, "
          f"depth chart {substrates['roster']['depth_chart_as_of']}")
    print()
    for verdict in ("FAIL", "sparse_expected", "unused", "ok"):
        rows = [entry for entry in findings if entry["verdict"] == verdict]
        if not rows:
            continue
        print(f"-- {verdict} ({len(rows)}) --")
        for entry in rows if verdict != "ok" else rows[:0]:
            print(
                f"   {entry['record']:<18} {entry['field']:<24} "
                f"consumed={str(entry['consumed']):<5} populated={entry['populated_share']:.1%}"
                + (f"  ({entry['reason']})" if entry["reason"] else "")
            )
        if verdict == "ok":
            print(f"   {', '.join(str(entry['field']) for entry in rows)}")
        print()

    unused = [entry for entry in findings if entry["verdict"] == "unused"]
    if unused:
        print(
            "NOTE: 'unused' fields are POPULATED BUT NOT READ by the engine -- dead\n"
            "weight, not a defect. They are not failures and do not gate.\n"
        )

    if args.write:
        from syndicate.features.nfl.sources import nfl_artifact_output_root

        target = (
            nfl_artifact_output_root()
            / "fantasy"
            / f"nfl_fantasy_input_report_{season}.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "season": season,
                    "history_seasons": list(history),
                    "substrates": substrates,
                    "population_floor": POPULATION_FLOOR,
                    "failures": failures,
                    "findings": findings,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"wrote {target}")

    if failures:
        print(f"FAILED: {failures} field(s) are CONSUMED but not POPULATED.")
        return 1
    print("PASS: every consumed field is populated or documented sparse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
