"""One-off: grade the paper rows the record cap moved to the archive ungraded (`#744`).

DRY RUN BY DEFAULT. `--apply` appends graded copies to the execution-ledger
archive, which is a fleet write and a USER decision under the deploy locks.

WHAT IT DOES. Runs `paper_settlement.settle_archived_orders` -- the same
resolver binding, `_our_verdict` and `grade_order` that `settle_orders` uses --
over every archived slate from `--since` to `--today`, with no per-pass date
cap. Then it reports, for the STALE population (filled paper rows with no
outcome whose game started more than `--stale-hours` ago, read from
`full_history_orders()` exactly as the 2026-10-27 16:06Z count was):

  * where each stale row sits: the live document (`settle_orders`' job) or the
    archive only (this pass's);
  * of the archive-only rows, how many WOULD grade, by sport and Central game
    date, and the named reason for every one that would not;
  * the pre-registered verdict (`.syndicate/findings_2026-10-27_paper_evicted_
    ungraded.md`): eviction is confirmed as the dominant cause at >= 50%
    would-grade, falsified below it.

`--probe-kickoff-date` adds the DIAGNOSTIC arm, never part of the verdict and
never written: each refused row re-asked with the resolver bound to its game's
Central kickoff date instead of its slate date.

READ-ONLY IN A DRY RUN, ENFORCED, NOT ASSUMED. The pass itself appends nothing
and takes no lock file in a dry run, and the archive append is replaced by a
raise. Resolvers can write as a side effect, so those writes are suppressed and
COUNTED: soccer's `_remember_finals`, the NFL/NCAAF lazy capture (forced to
`persist=False`), and any `refresh_state_store` write. External GETs still
happen (ESPN scoreboards on a capture miss, NHL api-web): settlement's own reads.

    nice -n 19 python scripts/backfill_archived_paper_grades.py --since 2026-10-02 \\
        --fleet-home /home/amyn/syndicate-prod --probe-kickoff-date --json out.json
    ... --apply        # USER decision, under the deploy locks

Exit codes: 0 ok, 2 bad arguments, 3 the archived pass refused (lock held,
live document unreadable), 4 the live ledger read failed (a failed read would
make every archived row look archive-only).
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FALSIFICATION_THRESHOLD = 0.5


def _central():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/Chicago")
    except Exception:  # no tz database: CDT holds through 2026-11-01
        return timezone(timedelta(hours=-5))


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def game_start(order: dict[str, Any]) -> datetime | None:
    """`commence_time`, else the END of the slate's Central day (the latest a
    game on it can start) -- the 16:06Z count's own fallback."""
    start = _parse_utc(order.get("commence_time"))
    if start is not None:
        return start
    slate = str(order.get("selected_date") or "")[:10]
    try:
        day = date.fromisoformat(slate)
    except ValueError:
        return None
    return datetime(day.year, day.month, day.day, 23, 59, tzinfo=_central())


def game_date_central(order: dict[str, Any]) -> str:
    start = game_start(order)
    return start.astimezone(_central()).date().isoformat() if start else "unknown"


def _load_fleet_env(home: str) -> None:
    """The refresh-worker's state env, the way the 10-27 probe loaded it, so the
    live document is read from the store the worker writes."""
    from scripts import execution_watchdog as ew
    from scripts import local_production as lp

    settings = lp.Settings(home=Path(home))
    pidfile = settings.run_dir / lp.PIDFILE_NAME
    pid = (json.loads(pidfile.read_text()).get("roles") or {}).get(ew.WORKER_ROLE)
    os.environ.update(ew.worker_state_env(settings, pid))


@contextlib.contextmanager
def suppressed_writes(counter: collections.Counter):
    """Every write path a dry run could reach, replaced and counted."""
    import scripts.poll_ncaaf_live_state as ncaaf_poll
    import scripts.poll_nfl_live_state as nfl_poll
    from syndicate.features.shared import bet_status_soccer, execution_ledger, refresh_state_store

    saved = []

    def patch(module, name, replacement):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, replacement)

    def counted(label):
        def _noop(*_args, **_kwargs):
            counter[label] += 1
            return None

        return _noop

    def no_persist(original, label):
        def _poll(iso_date, *, persist=True):
            if persist:
                counter[label] += 1
            return original(iso_date, persist=False)

        return _poll

    def refuse_archive(_rows):
        raise RuntimeError("dry run: the archive append was reached")

    patch(bet_status_soccer, "_remember_finals", counted("soccer_remember_finals"))
    patch(ncaaf_poll, "poll_ncaaf_live_state", no_persist(ncaaf_poll.poll_ncaaf_live_state, "ncaaf_capture_persist"))
    patch(nfl_poll, "poll_nfl_live_state", no_persist(nfl_poll.poll_nfl_live_state, "nfl_capture_persist"))
    patch(refresh_state_store, "write_json_file", counted("refresh_state_store_write"))
    patch(refresh_state_store, "compare_and_swap_json_file", counted("refresh_state_store_cas"))
    patch(execution_ledger, "_archive_rows", refuse_archive)
    try:
        yield
    finally:
        for module, name, original in reversed(saved):
            setattr(module, name, original)


def stale_population(now: datetime, stale_hours: float) -> tuple[list[dict], set[str]]:
    """(stale paper rows from the full history, identities in the live document)."""
    from syndicate.features.shared.execution_ledger import (
        PAPER,
        _order_identity,
        _read_for_merge,
        full_history_orders,
    )

    live_ids = {_order_identity(o) for o in (_read_for_merge().get("orders") or [])}
    cutoff = now - timedelta(hours=stale_hours)
    stale = []
    for order in full_history_orders():
        if not isinstance(order, dict) or str(order.get("mode") or "") != PAPER:
            continue
        if str(order.get("status") or "") != "filled" or order.get("outcome"):
            continue
        start = game_start(order)
        if start is not None and start < cutoff:
            stale.append(order)
    return stale, live_ids


def probe_kickoff_date(rows: list[dict]) -> dict[str, Any]:
    """The diagnostic arm: refused rows re-asked with a kickoff-date binding."""
    from syndicate.features.shared import paper_settlement as settle

    by_kickoff: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_kickoff[game_date_central(row)].append(row)
    would = collections.Counter()
    reasons = collections.Counter()
    for kickoff, group in sorted(by_kickoff.items()):
        resolver = settle._default_resolver(kickoff)
        for row in group:
            verdict, _resolved, refusal = settle._our_verdict(dict(row), resolver)
            sport = str(row.get("sport") or "").lower()
            if verdict is not None:
                would[sport] += 1
            else:
                reasons[(sport, refusal)] += 1
    return {
        "asked": len(rows),
        "would_grade": sum(would.values()),
        "would_grade_by_sport": dict(would),
        "still_refused": {f"{s}:{r}": n for (s, r), n in reasons.most_common()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", default="2026-10-02", help="oldest slate (selected_date) to grade")
    parser.add_argument("--today", default=None, help="newest slate; default today in Central time")
    parser.add_argument("--stale-hours", type=float, default=48.0)
    parser.add_argument("--apply", action="store_true", help="append graded copies (USER decision)")
    parser.add_argument("--probe-kickoff-date", action="store_true")
    parser.add_argument("--fleet-home", default=None, help="load the refresh-worker's state env from this fleet home")
    parser.add_argument("--json", default=None, help="write the full report here")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    today = args.today or now.astimezone(_central()).date().isoformat()
    try:
        span = (date.fromisoformat(today) - date.fromisoformat(args.since)).days
    except ValueError as exc:
        print(f"bad date: {exc}", file=sys.stderr)
        return 2
    if span < 0:
        print("--since is after --today", file=sys.stderr)
        return 2

    if args.fleet_home:
        _load_fleet_env(args.fleet_home)

    from syndicate.features.shared import paper_settlement as settle
    from syndicate.features.shared.execution_ledger import _ledger_path, _order_identity, archived_orders
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    # `learnings.md` 2026-10-22: a failed store read returns an EMPTY live
    # document, and every archived row would then read as archive-only.
    if read_json_file_result(_ledger_path())[1] is not True:
        print("REFUSED: the live execution ledger read failed", file=sys.stderr)
        return 4

    writes: collections.Counter = collections.Counter()
    guard = contextlib.nullcontext() if args.apply else suppressed_writes(writes)
    with guard:
        stale, live_ids = stale_population(now, args.stale_hours)
        if args.apply:
            print(
                f"APPLY: graded copies will be APPENDED to {_ledger_path().parent / 'execution_ledger_archive'}"
                f" for slates {args.since}..{today}",
                flush=True,
            )
        result = settle.settle_archived_orders(
            today=today,
            enabled=True,
            dry_run=not args.apply,
            max_age_days=span,
            max_dates=None,
            now=now,
            include_rows=True,
        )
        if result.get("status") == "skipped":
            print(f"REFUSED: the archived pass skipped: {result.get('reason')}", file=sys.stderr)
            return 3

        verdicts = {row["identity"]: row for row in result.get("rows") or []}
        archive_only = [o for o in stale if _order_identity(o) not in live_ids]
        in_live = len(stale) - len(archive_only)

        by_sport: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        by_game_date: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
        reasons: collections.Counter = collections.Counter()
        refused_rows: list[dict] = []
        would = 0
        for order in archive_only:
            row = verdicts.get(_order_identity(order))
            if row is None:
                slate = str(order.get("selected_date") or "")
                key = "outside_window" if slate < args.since or slate > today else "not_a_candidate"
            elif row.get("outcome"):
                key = "would_grade"
            else:
                key = str(row.get("reason"))
            sport = str(order.get("sport") or "").lower() or "unknown"
            by_sport[sport][key] += 1
            by_game_date[(sport, game_date_central(order))][key] += 1
            if key == "would_grade":
                would += 1
            else:
                reasons[(sport, key)] += 1
                refused_rows.append(order)

        share = (would / len(archive_only)) if archive_only else None
        verdict = (
            "no_archive_only_stale_rows"
            if share is None
            else "CONFIRMED (eviction is the dominant cause)"
            if share >= FALSIFICATION_THRESHOLD
            else "FALSIFIED (most archive-only rows do not grade; re-scope to the named reasons)"
        )
        probe = None
        if args.probe_kickoff_date and refused_rows:
            archived_by_id = {_order_identity(o): o for o in archived_orders()}
            probe = probe_kickoff_date(
                [dict(archived_by_id.get(_order_identity(o), o)) for o in refused_rows]
            )

    report = {
        "read_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "apply" if args.apply else "dry_run",
        "window": {"since": args.since, "today": today},
        "stale_hours": args.stale_hours,
        "stale_total": len(stale),
        "stale_in_live_document": in_live,
        "stale_archive_only": len(archive_only),
        "would_grade": would,
        "would_grade_share": None if share is None else round(share, 4),
        "verdict": verdict,
        "refused_by_reason": {f"{s}:{r}": n for (s, r), n in reasons.most_common()},
        "by_sport": {s: dict(c) for s, c in sorted(by_sport.items())},
        "by_sport_game_date": {f"{s} {d}": dict(c) for (s, d), c in sorted(by_game_date.items())},
        "pass": {k: v for k, v in result.items() if k != "rows"},
        "suppressed_writes": dict(writes),
        "kickoff_date_probe": probe,
    }
    print(json.dumps({k: report[k] for k in (
        "read_at", "mode", "stale_total", "stale_in_live_document", "stale_archive_only",
        "would_grade", "would_grade_share", "verdict", "refused_by_reason", "by_sport",
        "suppressed_writes", "kickoff_date_probe")}, indent=1, default=str))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        print(f"full report: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
