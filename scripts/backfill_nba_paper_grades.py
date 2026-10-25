"""Backfill-grade NBA PAPER orders that nothing will ever grade: 2026-10-20..10-22.

Lane `live-cell-scorecard`. USER DECISION 2026-10-24 (relayed by the coordinator 332cb014): "Yes, backfill" --
backfill-grade the stuck NBA paper orders from final box scores. Paper only.

WHY THEY ARE STUCK. The NBA resolver (`bet_status_nba`) grades from `nba_source/data/live/live_player_box_<date>
.json`, which the live-lens loop captures during a slate. It shipped 10-22, so 10-20 / 10-21 have no box at all and
10-22's is partial; and most of those orders have since been trimmed out of the live ledger document into the disk
archive, which `dates_needing_settlement` never reads (it walks `_load()` only). Findings: lane findings s4c L2.

TWO STEPS, EACH PREVIEW-FIRST (nothing is written without --commit):

  boxes    `live_player_box.capture(date)` -- the live loop's own capture, pointed at a past date: ESPN's scoreboard
           for the date, then each final game's /summary, through the same extractor. It merges with any existing
           artifact (a final game already held is carried, never refetched).  Once a date has its box, the
           refresh-worker's own straggler pass (`settle_orders` over the 6 newest dates with ungraded rows) grades
           the rows still in the LIVE document -- this script never writes the live document, because the worker
           writes it too and a second writer risks a lost update.

  archive  For rows ONLY in the archive (not in the live document): grade each with `paper_settlement._our_verdict`
           -- the one reading `settle_orders` itself uses -- under `_default_resolver(date)`, and APPEND the graded
           copy to the archive (`execution_ledger._archive_rows`, flock'd). The archive's readers keep the LAST copy
           per identity (`archived_orders`), so the graded copy supersedes the ungraded one; nothing is rewritten.
           Paper rows only (`mode != live`); a row that already has an outcome anywhere is skipped.

Run on the fleet with the refresh-worker's state env, the fleet venv, at nice 19:

    python scripts/backfill_nba_paper_grades.py boxes   --dates 2026-10-20,2026-10-21,2026-10-22 [--commit]
    python scripts/backfill_nba_paper_grades.py archive --dates 2026-10-20,2026-10-21,2026-10-22 [--commit]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SPORT = "nba"
BACKFILL_TAG = "archive_backfill/live-cell-scorecard/2026-10-24"


def grade_archived(
    archived: Iterable[Mapping[str, Any]],
    live_identities: set,
    dates: Sequence[str],
    *,
    resolver_for: Callable[[str], Callable[[Mapping[str, Any]], dict[str, Any]]],
    verdict_fn: Callable[..., tuple[dict[str, Any] | None, dict[str, Any], str]],
    identity_fn: Callable[[Mapping[str, Any]], Any],
    now: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Graded COPIES of the archive-only, ungraded, filled NBA paper rows on `dates`, plus a census. Pure."""
    wanted = set(dates)
    resolvers: dict[str, Any] = {}
    graded: list[dict[str, Any]] = []
    census: dict[str, Any] = {"considered": 0, "graded": 0, "outcomes": Counter(), "refused": Counter(),
                              "skipped_live_document": 0, "by_date": Counter()}
    for row in archived:
        if str(row.get("sport") or "").lower() != SPORT or str(row.get("selected_date")) not in wanted:
            continue
        if str(row.get("mode") or "") == "live" or not str(row.get("venue") or "").startswith("paper"):
            continue
        if row.get("outcome") or str(row.get("status") or "") != "filled":
            continue
        if identity_fn(row) in live_identities:
            census["skipped_live_document"] += 1   # the worker's straggler pass owns it
            continue
        census["considered"] += 1
        date = str(row["selected_date"])
        if date not in resolvers:
            resolvers[date] = resolver_for(date)
        verdict, resolved, refusal = verdict_fn(row, resolvers[date])
        if verdict is None:
            census["refused"][refusal] += 1
            continue
        out = dict(row)
        out["outcome"] = verdict["outcome"]
        out["pnl_dollars"] = verdict["pnl_dollars"]
        out["pnl_gross_dollars"] = verdict["pnl_gross_dollars"]
        out["settled_value"] = verdict["settled_value"]
        for field in ("home_score", "away_score", "home_name", "away_name"):
            if resolved.get(field) is not None:
                out[field] = resolved[field]
        out["graded_at"] = now
        out["graded_by"] = BACKFILL_TAG
        graded.append(out)
        census["graded"] += 1
        census["outcomes"][verdict["outcome"]] += 1
        census["by_date"][date] += 1
    for key in ("outcomes", "refused", "by_date"):
        census[key] = dict(census[key])
    return graded, census


def _nice() -> None:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass


def cmd_boxes(args) -> int:
    from syndicate.features.nba import live_player_box

    for date in args.dates:
        kwargs: dict[str, Any] = {}
        if not args.commit:
            kwargs["write"] = lambda record: None   # preview: fetch and count, write nothing
        result = live_player_box.capture(date, **kwargs)
        print(f"NBA_BOX_BACKFILL date={date} commit={args.commit} {json.dumps(result, sort_keys=True)}", flush=True)
    return 0


def cmd_archive(args) -> int:
    from syndicate.features.shared import execution_ledger as el
    from syndicate.features.shared import paper_settlement as ps
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    if read_json_file_result(el._ledger_path())[1] is not True:
        print("REFUSED: the live ledger document did not read, so live-document rows cannot be told apart (#658)")
        return 2
    live_identities = {el._order_identity(o) for o in (el._load().get("orders") or []) if isinstance(o, Mapping)}
    months = sorted({d[:7] for d in args.dates})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    graded, census = grade_archived(
        el.archived_orders(months), live_identities, args.dates,
        resolver_for=ps._default_resolver, verdict_fn=ps._our_verdict, identity_fn=el._order_identity, now=now)
    staked = sum(float(g.get("fill_stake_dollars") or 0) for g in graded)
    pnl = sum(float(g.get("pnl_dollars") or 0) for g in graded)
    print(f"NBA_ARCHIVE_BACKFILL commit={args.commit} {json.dumps(census, sort_keys=True)} "
          f"staked={staked:.2f} pnl={pnl:+.2f}", flush=True)
    if args.commit and graded:
        el._archive_rows(graded)
        print(f"NBA_ARCHIVE_BACKFILL appended={len(graded)} -> {el._archive_dir()}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("boxes", "archive"):
        p = sub.add_parser(name)
        p.add_argument("--dates", required=True, type=lambda s: [d.strip() for d in s.split(",") if d.strip()])
        p.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    _nice()
    return cmd_boxes(args) if args.cmd == "boxes" else cmd_archive(args)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
