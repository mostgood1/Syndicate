"""Backfill the sim-gap x EV study's state from the recorder, with the scorecard cron's own grading.

Lane `sim-gap-ev-study` `[2026-10-15]`. The study rides `publish_model_scorecard.py` (`--simgap`) and
sees only the games the scorecard grades FROM NOW ON -- a game the scorecard already committed is
never regraded. So its first daily report would read one day. This replays the recorder's board
dates for the window through the SAME grader, wrapper and commit rules, into the study's state
only: one instrument, one set of numbers (the `daily-accuracy` rule -- two numbers for one question
from different code is an argument nobody settles).

    python scripts/sim_gap_ev_study.py --out /tmp/simgap            # grade, write state/report there
    python scripts/sim_gap_ev_study.py --write                      # write them under the data root

NEVER writes the scorecard's or the optimizer's files, and refuses when the study's saved state
cannot be read (a fresh state written over a real one would erase it). Games already in the
saved state are skipped, so a rerun adds only what is missing. Run it at idle priority, and not
across the 6:30 AM CT `model-scorecard` run, which writes the same state.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import model_scorecard as msc  # noqa: E402
from syndicate.features.shared import sim_gap_ev_study as sge  # noqa: E402


def load_cron() -> Any:
    """`scripts/publish_model_scorecard.py` as a module: its reader, fetchers and grader signature."""
    source = REPO_ROOT / "scripts" / "publish_model_scorecard.py"
    spec = importlib.util.spec_from_file_location("publish_model_scorecard", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def log(message: str) -> None:
    print(f"[sim_gap_ev_backfill] {message}", flush=True)


def main(argv: list[str] | None = None, *, cron: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=sge.WINDOW_DAYS)
    parser.add_argument("--sports", default="auto", help="comma-separated, or 'auto' (the cron's in-season set)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="write the state, report and markdown under this directory")
    target.add_argument("--write", action="store_true", help="write them under the data root")
    parser.add_argument("--resamples", type=int, default=sge.RESAMPLES)
    args = parser.parse_args(argv)

    pms = cron or load_cron()
    now = datetime.now(timezone.utc)
    token = pms.admin_token()
    if not token:
        log("REFUSING: no ADMIN_TOKEN")
        return 2
    bs = msc.load_bucket_search()
    today = msc.central_today(now, bs.SCORECARD.central_date)
    if args.sports.strip().lower() == "auto":
        sports = list(pms.sports_in_season(date.fromisoformat(today)))
    else:
        sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    reader = pms.WebReader(pms.base_url(), token)
    cache = Path(tempfile.mkdtemp(prefix="sim_gap_backfill_cache_"))

    from syndicate.features.mlb.prop_outcomes import MlbPropGrader
    from syndicate.features.shared.population_outcomes import build_extra_settler

    mlb = MlbPropGrader(cache_dir=cache / "statsapi")
    settler = build_extra_settler(cache_dir=cache / "settlers", fetch_export=reader.text)
    signature, sport_versions, _grader = pms.grader_signature(bs, settler)
    try:
        saved = reader.json(sge.STATE_PATH)
    except pms.FetchError as exc:
        log(f"REFUSING: could not read the study's saved state ({exc}); a fresh one would erase it")
        return 4
    sg_state, reset = sge.load_state(saved, signature, sport_versions=sport_versions, now=now)
    known = set(sg_state["games"])
    log(f"START today={today} days={args.days} sports={','.join(sports)} saved_games={len(known)} reset={reset}")

    base_grade = functools.partial(bs.grade_population, prop_settler=mlb.settle, score_source=mlb.final_score,
                                   extra_settler=settler)
    grade = sge.wrap_grade(base_grade, sg_state, game_key=msc.game_key, base=base_grade)
    chips: dict[str, Any] = {}

    def chips_for(day: str) -> Any:
        if day not in chips:
            chips[day] = pms.fetch_chips_with_retry(bs, day)
        return chips[day]

    days = [(date.fromisoformat(today) - timedelta(days=n)).isoformat() for n in range(args.days, 0, -1)]
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # One sport at a time: a month of one sport's records is held at once, never every sport's.
    for sport in sports:
        scratch = msc.empty_state(signature, sport_versions)
        for day in days:
            try:
                records, _parts = pms.fetch_board_date(reader, bs, day, [sport])
            except pms.FetchError as exc:
                log(f"FETCH_FAILED {sport} {day} {exc}")
                continue
            fresh = [r for r in records if msc.game_key(r) not in known]
            msc.merge_board_date(scratch, day, fresh, today=today, central_date=bs.SCORECARD.central_date,
                                 fetched_at=stamp)
        graded = msc.grade_pending(scratch, today=today, grade=grade, chips_for=chips_for,
                                   central_date=bs.SCORECARD.central_date)
        committed = sge.commit(sg_state, scratch["games"])
        log(f"SPORT {sport} pending_games={len(scratch['pending']) + len(scratch['games'])} graded={graded} "
            f"committed={committed}")
    sge.prune(sg_state, today)
    report = sge.build_report(sg_state, today=today, now=now, run={"backfill": {"days": args.days, "sports": sports}},
                              resamples=args.resamples)
    outputs = {sge.STATE_PATH: sge.dumps_state(sg_state), sge.REPORT_PATH: sge.dumps(report),
               sge.MARKDOWN_PATH: sge.markdown(report)}
    for relative, content in outputs.items():
        path = pms.write(relative, content) if args.write else Path(args.out) / relative
        if not args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        log(f"WROTE {path} bytes={path.stat().st_size}")
    log(f"DONE window_games={report['window']['games']} dates={report['window']['dates']} "
        f"tested={report['betting']['tested']} signals={len(report['betting']['signals'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
