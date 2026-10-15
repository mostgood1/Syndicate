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
from typing import Any, Callable, Mapping

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


def _key_of(shaped: Mapping[str, Any]) -> str:
    if shaped.get("player_name"):
        return "p:" + cs.prop_result_key({"player": shaped.get("player_name"), "market": shaped.get("market"),
                                          "side": shaped.get("side"), "line": shaped.get("line")})
    return "l:" + cs.line_result_key(shaped)


class ValueTap:
    """The number each production settler graded on -- read WITHOUT changing what any settler returns
    (user 2026-10-15: "yes add the actual stat line too").

    The settlers keep the value to themselves, their files belong to another lane, and production grading must not
    move for a display column. So for the length of one pull, in THIS process only, this wraps:
      * the entry points that receive the record being graded: `CompositeSettler.__call__` (every extra settler)
        and `MlbPropGrader.settle` (MLB props);
      * the comparisons that receive the number: `resolve_bet_status` as the ESPN (football, basketball, game lines)
        and NHL settlers call it, `prop_outcomes.settle_prop` (MLB props), `settle_over_under` (soccer stats) and
        `settle_runs` (MLB game lines).
    Every wrapper passes its arguments through untouched and returns the original's result, so the value shown is
    the one the result was decided on. A target that no longer exists is reported in `missing`, never guessed: that
    sport's values are simply absent and the run says so. Soccer's goalscorer markets compare no number (a goal
    count is checked inline), so they carry a result and no value."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.missing: list[str] = []
        self._current: Mapping[str, Any] | None = None
        self._restore: list[tuple[Any, str, Any]] = []

    def _wrap(self, owner: Any, name: str, make: Callable[[Any], Any]) -> None:
        original = getattr(owner, name, None)
        if original is None:
            self.missing.append(f"{getattr(owner, '__name__', owner)}.{name}")
            return
        self._restore.append((owner, name, original))
        setattr(owner, name, make(original))

    def _entry(self, original: Any) -> Any:
        tap = self

        def entry(settler: Any, shaped: Mapping[str, Any], *args: Any, **kwargs: Any) -> Any:
            outer, tap._current = tap._current, shaped
            try:
                return original(settler, shaped, *args, **kwargs)
            finally:
                tap._current = outer
        return entry

    def _record(self, value: Any, **extra: Any) -> None:
        if self._current is None or value is None:
            return
        # A game line's number reads as a stat only for a total (the combined score); a spread or moneyline is graded
        # on a margin, which is not what a reader means by "the actual".
        if not self._current.get("player_name") and "total" not in str(self._current.get("market") or "").lower():
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        self.values[_key_of(self._current)] = {"v": round(number, 2), **extra}

    def __enter__(self) -> "ValueTap":
        from syndicate.features.mlb import prop_outcomes
        from syndicate.features.shared import population_outcomes, population_outcomes_espn, population_outcomes_mlb
        from syndicate.features.shared import population_outcomes_nhl, population_outcomes_soccer

        self._wrap(population_outcomes.CompositeSettler, "__call__", self._entry)
        self._wrap(prop_outcomes.MlbPropGrader, "settle", self._entry)
        tap = self

        def via_status(original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                tap._record(kwargs.get("current_value"))
                return original(*args, **kwargs)
            return wrapped

        def via_args(position: int) -> Callable[[Any], Any]:
            def make(original: Any) -> Any:
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    if len(args) > position:
                        tap._record(args[position])
                    return original(*args, **kwargs)
                return wrapped
            return make

        def via_runs(original: Any) -> Any:
            def wrapped(market: Any, side: Any, line: Any, away_runs: Any, home_runs: Any, *args: Any, **kwargs: Any) -> Any:
                if "total" in str(market or "").lower():
                    tap._record((away_runs or 0) + (home_runs or 0))
                return original(market, side, line, away_runs, home_runs, *args, **kwargs)
            return wrapped

        self._wrap(population_outcomes_espn, "resolve_bet_status", via_status)
        self._wrap(population_outcomes_nhl, "resolve_bet_status", via_status)
        self._wrap(prop_outcomes, "settle_prop", via_args(2))
        self._wrap(population_outcomes_soccer, "settle_over_under", via_args(0))
        self._wrap(population_outcomes_mlb, "settle_runs", via_runs)
        return self

    def __exit__(self, *exc: Any) -> None:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()


def _with_value(graded: dict[str, Any], key: str, values: Mapping[str, Any]) -> dict[str, Any]:
    tapped = values.get(key)
    return {**graded, "v": tapped["v"]} if tapped else graded


def graded_index(rows: list[dict[str, Any]], values: Mapping[str, Any] | None = None
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Graded population rows -> (props by prop key, lines by line key); full game only, graded only. `values`
    (a `ValueTap`'s) adds the number each was graded on as `v`."""
    values = values or {}
    props: dict[str, dict[str, Any]] = {}
    lines: dict[str, dict[str, Any]] = {}
    for g in rows:
        if str(g.get("segment") or "full") not in ("full", "full_game") or g.get("y") is None:
            continue
        if g.get("player"):
            key = cs.prop_result_key(g)
            props.setdefault(key, _with_value({"y": float(g["y"])}, "p:" + key, values))
        else:
            event = str(g.get("game") or "").split("|", 1)[-1]
            key = cs.line_result_key({**g, "event_id": event})
            lines.setdefault(key, _with_value({"y": float(g["y"])}, "l:" + key, values))
    return props, lines


def merge_results(prior: Mapping[str, Any], fresh: Mapping[str, Any]) -> dict[str, Any]:
    """A settled result never changes: keep every earlier one, take the fresh ones, and never lose a value an
    earlier run captured to a run that did not."""
    out = {k: dict(v) for k, v in (prior or {}).items()}
    for key, entry in fresh.items():
        out[key] = {**out.get(key, {}), **entry}
    return out


def reconcile(sheet: dict[str, Any], props: dict[str, Any], lines: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """The reconciled file for one sheet: the result of every prop and game line the grader settled."""
    p_out = {k: props[k] for k in (cs.prop_result_key(r) for r in sheet.get("rows") or []) if k in props}
    l_out = {k: lines[k] for k in (cs.line_result_key(g) for g in sheet.get("game_lines") or []) if k in lines}
    return {"sport": sheet.get("sport"), "date": sheet.get("date"), "reconciled_at": now.isoformat(timespec="seconds"),
            "source": SOURCE, "props": p_out, "lines": l_out,
            "counts": {"props": len({cs.prop_result_key(r) for r in sheet.get("rows") or []}), "props_graded": len(p_out),
                       "props_valued": sum(1 for v in p_out.values() if "v" in v),
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
            with ValueTap() as tap:
                code = srb.main(["pull", "--start", day, "--end", day, "--sports", ",".join(sports), "--source", "recorder",
                                 "--cache", str(cache), "--out", str(out)])
            if tap.missing:
                print(f"RECONCILE date={day} value hooks MISSING {tap.missing} -- those sports carry results without values",
                      flush=True)
            if code not in (0, None) or not out.is_file():
                # A failed pull must never overwrite results already on disk with an empty file.
                print(f"RECONCILE date={day} grader pull failed (exit {code}) -- nothing written", flush=True)
                continue
            graded = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        props, lines = graded_index(graded, tap.values)
        now = datetime.now(timezone.utc)
        for path, doc in sheets:
            target = path.with_name(f"{day}.reconciled.json")
            try:
                prior = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            # A settled result never changes, so an earlier run's results stay when a re-run grades fewer.
            rec = reconcile(doc, merge_results(prior.get("props") or {}, props), merge_results(prior.get("lines") or {}, lines),
                            now=now)
            c = rec["counts"]
            if not prior and not (c["props_graded"] or c["lines_graded"]):
                # Nothing final yet: no file, so the page offers no toggle onto a sheet of dashes.
                print(f"RECONCILE {doc['sport']} date={day} nothing settled yet -- no file", flush=True)
                continue
            write_atomic(target, rec)
            print(f"RECONCILE {doc['sport']} date={day} props {c['props_graded']}/{c['props']} (values {c['props_valued']}) "
                  f"lines {c['lines_graded']}/{c['lines']} graded_population={len(graded)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
