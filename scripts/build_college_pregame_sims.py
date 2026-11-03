"""Build the college basketball PREGAME sim artifact for one or more dates (lane wncaab-module, Phase 3).

    python scripts/build_college_pregame_sims.py --league ncaab,wncaab --dates 2026-11-02,2026-11-03 --budget-seconds 600

`--refresh-inputs` brings the WOMEN'S team ratings and player priors up to date once a day (after 11:00Z, the
men's scheduled-job hour) before simming: the women have no `local_production` job, so the pregame child --
already launched every 15 minutes -- owns that refresh. A marker file per date makes it once a day. It also
refits each league's PRIOR CALIBRATION once a day (`college_basketball/prior_calibration.py`): the file for
today's games is its own marker.

Launched by the live-odds-worker (`ncaab/inplay_lane.maybe_launch_pregame_sims`) so it inherits the live
tier's engine switches; see `syndicate/features/college_basketball/pregame_sim.py`. Stops at the budget and
writes what it has; the next launch re-sims only games whose inputs changed. Exit 0 unless the run raised.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def refresh_womens_inputs(now: dt.datetime | None = None, *, run: object = subprocess.run) -> str:
    """Once a day after 11:00Z: the women's ratings (incremental) then player priors. Returns what it did."""
    from syndicate.features.shared.refresh_state_store import data_root

    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.hour < 11:
        return "before_11z"
    marker = Path(data_root()) / "wncaab_source" / "data" / "processed" / f".inputs_refreshed_{moment.date().isoformat()}"
    if marker.exists():
        return "already_today"
    for script in ("build_ncaab_team_ratings.py", "build_ncaab_player_priors.py"):
        proc = run([sys.executable, str(REPO / "scripts" / script), "--league", "wncaab", "--rate", "4"], cwd=str(REPO))  # type: ignore[operator]
        print(f"[college_pregame_sim] WNCAAB_INPUTS {script} rc={getattr(proc, 'returncode', None)}", flush=True)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(moment.isoformat(), encoding="utf-8")
    return "refreshed"


def refresh_prior_calibrations(leagues: list[str], now: dt.datetime | None = None, *, refit: object = None) -> dict[str, str]:
    """Once a day after 11:00Z per league: refit the prior calibration on the trailing window. Never raises: a failed
    fit leaves yesterday's file in force (it applies to every later date) and says so."""
    from syndicate.features.college_basketball import prior_calibration as pc
    from syndicate.features.ncaab import live_team_model as tm

    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.hour < 11:
        return {league: "before_11z" for league in leagues}
    today = moment.date()
    out: dict[str, str] = {}
    for league in leagues:
        if pc.calibration_path(league, tm.espn_season_for(today), today - dt.timedelta(days=1)).exists():
            out[league] = "already_today"
            continue
        try:
            (refit or pc.refresh_calibration)(league, today=today, now=moment)  # type: ignore[operator]
            out[league] = "refitted"
        except Exception as exc:  # noqa: BLE001 -- one league's failed fit must not stop the sims
            print(f"[college_prior_calibration] FIT_FAILED league={league} {type(exc).__name__}: {exc}"[:300], flush=True)
            out[league] = "failed"
    return out


def main(argv: list[str] | None = None) -> int:
    from syndicate.features.college_basketball.pregame_sim import LEAGUES, default_sims, run_pregame_sims

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="ncaab", help="comma-separated: ncaab, wncaab")
    parser.add_argument("--refresh-inputs", action="store_true", help="refresh the women's ratings/priors once a day first")
    parser.add_argument("--dates", required=True, help="comma-separated ISO dates (Central slate dates)")
    parser.add_argument("--sims", type=int, default=None, help=f"draws per game (default {default_sims()})")
    parser.add_argument("--budget-seconds", type=float, default=600.0, help="stop starting new games after this long")
    args = parser.parse_args(argv)
    leagues = [x.strip() for x in args.league.split(",") if x.strip()]
    unknown = [x for x in leagues if x not in LEAGUES]
    if unknown:
        parser.error(f"unknown league(s) {unknown}; expected {list(LEAGUES)}")
    if args.refresh_inputs and "wncaab" in leagues:
        refresh_womens_inputs()
    if args.refresh_inputs:
        refresh_prior_calibrations(leagues)
    deadline = time.monotonic() + max(1.0, float(args.budget_seconds))
    for date_iso in [d.strip() for d in args.dates.split(",") if d.strip()]:
        for league in leagues:
            run_pregame_sims(date_iso, league, sims=args.sims, deadline=deadline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
