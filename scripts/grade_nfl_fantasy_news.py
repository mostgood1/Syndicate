"""Grade the news/injury layer. Does it earn its place, or is it decoration?

`fantasy_news.py` ships OFF with weights that were REASONED rather than fitted,
and an ungraded multiplier moving a draft board is worse than no multiplier.
This is the harness that decides.

THE TWO HALVES ARE NOT EQUALLY GRADEABLE, and pretending otherwise would be the
whole failure this file exists to avoid:

* **INJURY STATUS -> AVAILABILITY is fully gradeable.** nflverse archives the
  weekly injury report (2022-2025 locally): season, week, `gsis_id`,
  `report_status`. It is published BEFORE the game it describes, so using week
  W's report to predict week W is walk-forward by construction, with no
  lookahead. And the thing it predicts -- did he play, and how much -- is
  directly observable in the per-game usage lines.

* **PRACTICE PARTICIPATION is the same story, and it is the important one.**
  Most fantasy "news" is a beat reporter transcribing the practice report and
  the coach's remarks around it -- did not practice, limited, full participant,
  "resting player". `practice_status` IS that, in structured form, archived
  weekly since 2009. So the coach-quote signal is gradeable even though the
  quotes themselves are not, because the thing the quotes are ABOUT is
  recorded. `practice_primary_injury` even distinguishes a veteran rest day
  ("Not injury related - resting player") from a knee.

  This matters because the shipped model keys ONLY on `report_status`, and that
  collapses situations the practice report separates: Questionable + full
  participation and Questionable + did-not-practice are the same designation
  and very different players. Measured 2025: 321 of the first, 171 of the
  second, and 297 players who did not practice at all while carrying NO game
  designation. This script grades `report_status` alone, `practice_status`
  alone, and the pair, so "does the practice signal add anything" is answered
  with a number.

* **FREE-TEXT SENTIMENT is NOT gradeable here, and this script says so rather
  than inventing a number.** ESPN's endpoint serves CURRENT headlines; nothing
  archives what was written before a week-6 2023 game. A keyword rule needs the
  text as it stood, and that text is not on this substrate.

DISCIPLINE: constants are SELECTED on 2022-2023 and only ever REPORTED on
2024-2025, matching every other tuned value in this engine.

    python scripts/grade_nfl_fantasy_news.py
    python scripts/grade_nfl_fantasy_news.py --json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy_news import INJURY_AVAILABILITY  # noqa: E402
from syndicate.features.nfl.fantasy_news import injuries_path  # noqa: E402
from syndicate.features.nfl.fantasy_projection import _usage_to_stat_line  # noqa: E402
from syndicate.features.nfl.fantasy_scoring import resolve_scoring  # noqa: E402
from syndicate.features.nfl.fantasy_scoring import score_stat_line  # noqa: E402
from syndicate.features.nfl.fantasy_usage import load_season_game_lines  # noqa: E402
from syndicate.features.nfl.fantasy_usage import load_season_usage  # noqa: E402

FIT_SEASONS = (2022, 2023)
REPORT_SEASONS = (2024, 2025)

#: A player needs some real involvement before "did he play" is a meaningful
#: question -- a deep bench player is absent for reasons unrelated to health.
MIN_SEASON_TOUCHES = 40


#: nflverse spells practice participation out in full; these are the three
#: real values, mapped to something a table can hold.
_PRACTICE = {
    "did not participate in practice": "dnp",
    "limited participation in practice": "limited",
    "full participation in practice": "full",
}


def _load_reports(season: int) -> dict[tuple[str, int], dict[str, str]]:
    """``(gsis_id, week) -> {report, practice, rest}`` for one season.

    Carries BOTH designations. A row with a practice status and no game
    designation is kept: 297 such players in 2025 did not practice at all while
    the team listed nothing, and dropping them would discard exactly the cases
    the game designation misses.
    """
    path = injuries_path(season)
    if not path.is_file():
        return {}
    out: dict[tuple[str, int], dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            player = (row.get("gsis_id") or "").strip()
            report = (row.get("report_status") or "").strip().lower()
            practice_raw = (row.get("practice_status") or "").strip().lower()
            practice = _PRACTICE.get(practice_raw, "")
            reason = (row.get("practice_primary_injury") or "").strip().lower()
            try:
                week = int(row.get("week") or 0)
            except ValueError:
                continue
            if player and week and (report or practice):
                out[(player, week)] = {
                    "report": report or "none",
                    "practice": practice or "none",
                    # A coach resting a healthy veteran is a different event
                    # from an injury, and the feed says which.
                    "rest": "yes" if "not injury related" in reason else "no",
                }
    return out


def _season_observations(season: int, scoring) -> list[dict]:
    """One row per (player, week) that carried an injury designation.

    ``played`` and ``points`` come from the per-game usage lines, so they are
    the settled truth rather than anything the engine produced.
    """
    reports = _load_reports(season)
    if not reports:
        return []
    players, _ = load_season_usage(season)
    lines, _ = load_season_game_lines(season)

    active = {
        player_id
        for player_id, usage in players.items()
        if (usage.targets + usage.carries + usage.pass_attempts) >= MIN_SEASON_TOUCHES
    }
    if not active:
        return []

    by_player_week: dict[tuple[str, int], float] = {}
    for line in lines:
        by_player_week[(line.player_id, int(line.week))] = score_stat_line(
            _usage_to_stat_line(line), scoring
        )

    # A player's own baseline: his mean points in the games he DID play. The
    # question is what the designation costs relative to himself, not to the
    # league.
    baseline: dict[str, float] = {}
    for player_id in active:
        values = [
            points
            for (pid, _), points in by_player_week.items()
            if pid == player_id
        ]
        if values:
            baseline[player_id] = statistics.fmean(values)

    weeks = sorted({week for _, week in by_player_week}) or [0]
    observations: list[dict] = []
    for (player_id, week), status in reports.items():
        if player_id not in active or week not in weeks:
            continue
        points = by_player_week.get((player_id, week))
        observations.append(
            {
                "season": season,
                "player_id": player_id,
                "week": week,
                "status": status["report"],
                "practice": status["practice"],
                "rest": status["rest"],
                "combined": f"{status['report']}/{status['practice']}",
                "played": points is not None,
                "points": points or 0.0,
                "baseline": baseline.get(player_id, 0.0),
            }
        )
    return observations


def _calibrate(observations: list[dict], key: str = "status") -> dict[str, dict]:
    """Empirical availability per designation.

    The multiplier the engine applies is meant to be E[points | designation] as
    a fraction of the player's own baseline. That is directly measurable, and
    it is measured here rather than reasoned about.
    """
    grouped: dict[str, list[dict]] = {}
    for row in observations:
        grouped.setdefault(row[key], []).append(row)

    table: dict[str, dict] = {}
    for status, rows in sorted(grouped.items()):
        if len(rows) < 25:
            continue
        played = [row for row in rows if row["played"]]
        with_baseline = [row for row in rows if row["baseline"] > 0]
        share = (
            statistics.fmean(row["points"] / row["baseline"] for row in with_baseline)
            if with_baseline
            else 0.0
        )
        table[status] = {
            "n": len(rows),
            "played_rate": round(len(played) / len(rows), 4),
            "empirical_multiplier": round(share, 4),
            "shipped_multiplier": INJURY_AVAILABILITY.get(status) if key == "status" else None,
            "mean_points": round(statistics.fmean(row["points"] for row in rows), 2),
        }
    return table


def _grade(observations: list[dict], multipliers: dict[str, float], key: str = "status") -> dict:
    """Weekly points error with the multiplier applied vs not applied.

    The comparison is deliberately narrow: for a player with a designation, is
    `baseline * multiplier` closer to what he actually scored than `baseline`
    alone? That isolates the ONE thing the injury layer does.
    """
    rows = [row for row in observations if row["baseline"] > 0]
    if not rows:
        return {"n": 0}
    without = statistics.fmean(abs(row["baseline"] - row["points"]) for row in rows)
    with_adjustment = statistics.fmean(
        abs(row["baseline"] * multipliers.get(row[key], 1.0) - row["points"])
        for row in rows
    )
    return {
        "n": len(rows),
        "mae_without": round(without, 3),
        "mae_with": round(with_adjustment, 3),
        "improvement": round(without - with_adjustment, 3),
        "improvement_pct": round(100.0 * (without - with_adjustment) / without, 2) if without else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default="reports/nfl_fantasy_news_grade.json")
    args = parser.parse_args()
    scoring = resolve_scoring(args.scoring)

    fit = [row for season in FIT_SEASONS for row in _season_observations(season, scoring)]
    report = [row for season in REPORT_SEASONS for row in _season_observations(season, scoring)]

    if not fit or not report:
        print(
            "UNMEASURED -- injury reports or usage are not on this substrate for\n"
            f"  fit {FIT_SEASONS} ({len(fit)} rows) / report {REPORT_SEASONS} ({len(report)} rows).\n"
            "  This says nothing about the layer; run scripts/fetch_nfl_injuries.py.",
            flush=True,
        )
        return 1

    scheme_labels = {
        "status": "game designation only (what ships)",
        "practice": "practice participation only",
        "combined": "designation x practice",
    }

    results: dict[str, dict] = {}
    for key, label in scheme_labels.items():
        fitted = _calibrate(fit, key)
        selected = {name: values["empirical_multiplier"] for name, values in fitted.items()}
        results[key] = {
            "label": label,
            "cells": len(fitted),
            "fitted_on_fit_seasons": selected,
            "grade": _grade(report, selected, key),
            "calibration_report": _calibrate(report, key),
        }

    shipped_grade = _grade(report, INJURY_AVAILABILITY, "status")

    print(f"=== NFL fantasy INJURY / PRACTICE layer, graded ({scoring.label}) ===")
    print(f"fit {FIT_SEASONS} n={len(fit)}   report {REPORT_SEASONS} n={len(report)}")
    print()

    print("--- what each GAME DESIGNATION is actually worth (report seasons) ---")
    print(f"  {'status':<14}{'n':>6}{'played':>9}{'empirical':>11}{'shipped':>9}  verdict")
    for name, values in sorted(
        results["status"]["calibration_report"].items(), key=lambda item: -item[1]["n"]
    ):
        shipped = values["shipped_multiplier"]
        empirical = values["empirical_multiplier"]
        if shipped is None:
            verdict = "NOT MODELLED -- the engine ignores this designation"
        else:
            gap = empirical - shipped
            verdict = "ok" if abs(gap) <= 0.10 else f"OFF BY {gap:+.2f}"
        shown = f"{shipped:.2f}" if shipped is not None else "--"
        print(
            f"  {name:<14}{values['n']:>6}{values['played_rate']:>9.2f}"
            f"{empirical:>11.2f}{shown:>9}  {verdict}"
        )
    print()

    print("--- what PRACTICE PARTICIPATION is worth (the coach-quote signal) ---")
    print(f"  {'practice':<14}{'n':>6}{'played':>9}{'empirical':>11}")
    for name, values in sorted(
        results["practice"]["calibration_report"].items(), key=lambda item: -item[1]["n"]
    ):
        print(
            f"  {name:<14}{values['n']:>6}{values['played_rate']:>9.2f}"
            f"{values['empirical_multiplier']:>11.2f}"
        )
    print()

    print("--- does practice ADD anything beyond the designation? ---")
    print(f"  {'scheme':<34}{'cells':>7}{'MAE':>9}{'vs none':>10}")
    baseline_mae = results["status"]["grade"].get("mae_without", 0.0)
    print(f"  {'no adjustment at all':<34}{'-':>7}{baseline_mae:>9.3f}{'--':>10}")
    print(
        f"  {'shipped constants':<34}{len(INJURY_AVAILABILITY):>7}"
        f"{shipped_grade['mae_with']:>9.3f}{shipped_grade['improvement_pct']:>9.1f}%"
    )
    for key in ("status", "practice", "combined"):
        entry = results[key]
        grade = entry["grade"]
        print(
            f"  {'fitted: ' + entry['label']:<34}{entry['cells']:>7}"
            f"{grade['mae_with']:>9.3f}{grade['improvement_pct']:>9.1f}%"
        )
    print()

    best = max(results.items(), key=lambda item: item[1]["grade"]["improvement"])
    helps = shipped_grade["improvement"] > 0
    print(f"VERDICT: the SHIPPED multipliers {'HELP' if helps else 'DO NOT HELP'} on held-out seasons "
          f"({shipped_grade['improvement_pct']:+.1f}% MAE).")
    print(f"         the best keying is '{best[0]}' ({best[1]['label']}) at "
          f"{best[1]['grade']['improvement_pct']:+.1f}%.")
    print()
    print("FREE-TEXT SENTIMENT: **UNGRADEABLE ON THIS SUBSTRATE.**")
    print("  ESPN's endpoint serves CURRENT headlines; nothing archives what was")
    print("  written before a past game, so a keyword rule cannot be graded. What")
    print("  IS graded above is the thing most of those quotes are ABOUT -- the")
    print("  practice report -- which nflverse has archived weekly since 2009.")

    payload = {
        "scoring": scoring.key,
        "fit_seasons": list(FIT_SEASONS),
        "report_seasons": list(REPORT_SEASONS),
        "schemes": results,
        "grade_shipped": shipped_grade,
        "verdict_injury_helps": helps,
        "best_scheme": best[0],
        "free_text_sentiment": {
            "gradeable": False,
            "reason": (
                "ESPN serves current headlines only; no archive of pre-game text "
                "exists on this substrate, so a keyword rule cannot be graded. The "
                "practice report -- what most such quotes are about -- IS archived "
                "and is graded above."
            ),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    if args.json:
        print(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
