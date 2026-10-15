"""Reconcile the cheat sheets (lane `cheat-sheets`, user 2026-10-15: "can we reconcile the historical cheat sheets?
Have a button that toggles between pregame sheets and reconciled sheets").

For each day's sheets (`<data root>/cheatsheets/<sport>/<date>.json`), grade every prop and game line through
PRODUCTION'S OWN GRADER -- `score_ranking_backtest.py pull --source recorder`, the path the nightly scorecard and
`grade_play_cards.py` use -- and write `<sport>/<date>.reconciled.json` beside the sheet. The page reads it and toggles
between the sheet as published and the sheet with its results; the sheet itself is never changed.

    props  matched on the grader's own key: player, market, side, line (`cheat_sheets.prop_result_key`)
    lines  matched on event, market, side (home / away / over / under) and line (`cheat_sheets.line_result_key`)
    y      1 won, 0 lost; a push, a void (did not play) or a game not final carries no result and shows as "--"

Units are computed by the page at the sheet's best price, 1 unit a bet. A day is re-graded on every run until it is
complete, so a late final fills in. No OddsAPI: the grader reads the recorder through the web's ops API and settles
from free box scores, cached under `cheatsheets/.reconcile_cache/`.

    python scripts/reconcile_cheat_sheets.py --data-root ~/syndicate-prod/data            # today and the 2 days before
    python scripts/reconcile_cheat_sheets.py --data-root ~/syndicate-prod/data --date 2026-10-14
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import cheat_sheets as cs  # noqa: E402
from syndicate.features.shared import play_cards as pc  # noqa: E402

DAYS_BACK = 2
SOURCE = "score_ranking_backtest pull --source recorder (production's grader)"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def central_today() -> str:
    return pc.central(datetime.now(timezone.utc)).date().isoformat()


def graded_index(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Graded population rows -> (props by prop key, lines by line key); full game only, graded only."""
    props: dict[str, dict[str, Any]] = {}
    lines: dict[str, dict[str, Any]] = {}
    for g in rows:
        if str(g.get("segment") or "full") not in ("full", "full_game") or g.get("y") is None:
            continue
        if g.get("player"):
            props.setdefault(cs.prop_result_key(g), {"y": float(g["y"])})
        else:
            event = str(g.get("game") or "").split("|", 1)[-1]
            lines.setdefault(cs.line_result_key({**g, "event_id": event}), {"y": float(g["y"])})
    return props, lines


def reconcile(sheet: dict[str, Any], props: dict[str, Any], lines: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """The reconciled file for one sheet: the result of every prop and game line the grader settled."""
    p_out = {k: props[k] for k in (cs.prop_result_key(r) for r in sheet.get("rows") or []) if k in props}
    l_out = {k: lines[k] for k in (cs.line_result_key(g) for g in sheet.get("game_lines") or []) if k in lines}
    return {"sport": sheet.get("sport"), "date": sheet.get("date"), "reconciled_at": now.isoformat(timespec="seconds"),
            "source": SOURCE, "props": p_out, "lines": l_out,
            "counts": {"props": len({cs.prop_result_key(r) for r in sheet.get("rows") or []}), "props_graded": len(p_out),
                       "lines": len({cs.line_result_key(g) for g in sheet.get("game_lines") or []}),
                       "lines_graded": len(l_out)}}


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    ap.add_argument("--date", action="append", help="a day to reconcile (repeatable); default today and the 2 before")
    ap.add_argument("--sports", default=None, help="limit to these sports (default: every sport with a sheet)")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    sheets_dir = root / "cheatsheets"
    today = central_today()
    days = args.date or [(datetime.fromisoformat(today) - timedelta(days=k)).date().isoformat() for k in range(DAYS_BACK, -1, -1)]
    wanted = {s.strip() for s in args.sports.split(",")} if args.sports else None
    cache = sheets_dir / ".reconcile_cache"
    cache.mkdir(parents=True, exist_ok=True)
    srb = None
    for day in days:
        if day > today:
            continue
        sheets = []
        for path in sorted(sheets_dir.glob(f"*/{day}.json")):
            sport = path.parent.name
            if wanted and sport not in wanted:
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("rows") or doc.get("game_lines"):
                sheets.append((path, doc))
        if not sheets:
            print(f"RECONCILE date={day} no sheets", flush=True)
            continue
        sports = sorted({doc["sport"] for _, doc in sheets})
        srb = srb or _load("score_ranking_backtest")
        with tempfile.TemporaryDirectory(prefix="reconcile_") as work:
            out = Path(work) / f"graded_{day}.jsonl"
            code = srb.main(["pull", "--start", day, "--end", day, "--sports", ",".join(sports), "--source", "recorder",
                             "--cache", str(cache), "--out", str(out)])
            if code not in (0, None) or not out.is_file():
                # A failed pull must never overwrite results already on disk with an empty file.
                print(f"RECONCILE date={day} grader pull failed (exit {code}) -- nothing written", flush=True)
                continue
            graded = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        props, lines = graded_index(graded)
        now = datetime.now(timezone.utc)
        for path, doc in sheets:
            target = path.with_name(f"{day}.reconciled.json")
            try:
                prior = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            # A settled result never changes, so an earlier run's results stay when a re-run grades fewer.
            rec = reconcile(doc, {**(prior.get("props") or {}), **props}, {**(prior.get("lines") or {}), **lines}, now=now)
            c = rec["counts"]
            if not prior and not (c["props_graded"] or c["lines_graded"]):
                # Nothing final yet: no file, so the page offers no toggle onto a sheet of dashes.
                print(f"RECONCILE {doc['sport']} date={day} nothing settled yet -- no file", flush=True)
                continue
            write_atomic(target, rec)
            print(f"RECONCILE {doc['sport']} date={day} props {c['props_graded']}/{c['props']} "
                  f"lines {c['lines_graded']}/{c['lines']} graded_population={len(graded)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
