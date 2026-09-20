"""Read the published model scorecard back and say what it actually covers.

Lane `daily-accuracy-suite` `[2026-09-20]`. This is a READER. It computes nothing,
grades nothing and publishes nothing: the daily `model-scorecard` Render cron
(`30 11 * * *`) does all of that and writes a dated artifact, and this reads that
artifact back over HTTP and reports on it.

WHY A READER AND NOT A SECOND GRADER. Re-grading here would produce a second
number for the same question, computed by different code on a different substrate,
and the first argument between the two would be unresolvable. The cron's artifact
is the measurement; this tool's whole job is to make its coverage and its silences
legible.

THE FOUR SILENCES IT EXISTS TO BREAK, each measured on production 2026-09-20:

1. A CRON THAT DISPATCHED BUT DID NOT PUBLISH looks exactly like one that worked.
   `lastRunAt` is a DISPATCH timestamp -- on this platform a scheduled job has been
   observed dispatching on time and its child not running for 9h13m. So freshness
   is judged on the ARTIFACT's own `generated_at`, never on a scheduler field.

2. A WINDOW CAN BE SHORTER THAN ITS LABEL. The `7d` and `28d` windows were
   byte-identical (263 cells each, same coverage block) because the population
   recorder started 2026-09-14. A `28d` heading over 6 days of data is a claim the
   data does not support, and nothing said so.

3. UNGRADED ROWS ARE COUNTED, NOT RATED. A count has no denominator: soccer's 2,887
   `player_not_in_box` is unreadable until you know it sits against 14,319 graded
   rows. This prints rates and sorts by them.

4. A SPORT THAT IS ABSENT AND A SPORT THAT IS OFF-SEASON LOOK THE SAME -- both are
   simply missing. NBA and NCAAB are deliberately excluded from the daily read
   while out of season (`publish_model_scorecard.py`, DEFAULT_SPORTS), which is a
   cost decision, not a defect; NHL is IN season, has a registered settler, and
   still graded zero rows, which is a defect. Printing them identically hides that.

EXIT CODES (so this can gate a scheduled task, not just inform a human):
    0  read, fresh, no regression
    2  the artifact is STALE -- older than --max-age-hours
    3  a sport that WAS graded in the previous artifact is graded no longer
    4  could not read the scorecard at all
    5  usage / no token
A non-zero exit always prints the reason first, on one line, prefixed `FAIL`.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"
TIMEOUT_SECONDS = 90.0

# Every sport the platform trades. A sport missing from the scorecard is only
# interesting against this list -- without it, "absent" has no denominator either.
TRADED_SPORTS = ("mlb", "nba", "ncaab", "ncaaf", "nfl", "nhl", "soccer", "wnba")

# Northern-hemisphere season windows, (start_md, end_md) inclusive, wrapping the new
# year where end < start. Used ONLY to label an absent sport `off-season` rather than
# `MISSING`; it never changes what is graded. Deliberately coarse: the question it
# answers is "should anyone expect rows today", not "is there a game tonight".
SEASON_WINDOWS = {
    "mlb": ((3, 20), (11, 5)),
    "nba": ((10, 1), (6, 25)),
    "ncaab": ((11, 1), (4, 10)),
    "ncaaf": ((8, 20), (1, 20)),
    "nfl": ((9, 1), (2, 15)),
    "nhl": ((9, 15), (6, 30)),
    "soccer": ((7, 15), (6, 5)),
    "wnba": ((5, 1), (10, 20)),
}


class ReadError(RuntimeError):
    pass


def _get_json(base_url: str, path: str, token: str) -> Any:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"X-Admin-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ReadError(f"{path} -> HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001 - the reason is reported, not handled
        raise ReadError(f"{path} -> {type(exc).__name__}: {exc}") from exc


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def in_season(sport: str, today: datetime) -> bool | None:
    """True/False, or None when we hold no window for the sport (so: don't claim)."""
    window = SEASON_WINDOWS.get(sport)
    if window is None:
        return None
    (start_month, start_day), (end_month, end_day) = window
    start, end, now = (start_month, start_day), (end_month, end_day), (today.month, today.day)
    return start <= now or now <= end if end < start else start <= now <= end


def cells_of(window: Any) -> list[dict[str, Any]]:
    return [cell for cell in (window or {}).get("cells") or [] if isinstance(cell, dict)]


def cell_key(cell: dict[str, Any]) -> str:
    return "|".join(str(cell.get(field) or "") for field in ("sport", "market", "segment", "phase"))


def window_is_degraded(scorecard: dict[str, Any], name: str) -> tuple[bool, str]:
    """A window is DEGRADED when its label promises more history than it holds.

    Two independent tests, because either alone is fooled:
      * its cells are identical to a SHORTER window's -- it contains nothing extra;
      * the recorder started fewer days ago than the label claims.
    """
    windows = scorecard.get("windows") or {}
    window = windows.get(name) or {}
    nominal_days = int("".join(ch for ch in name if ch.isdigit()) or 0)
    coverage = window.get("coverage") or {}

    started = _parse_utc((coverage.get("recorder_start") or "") + "T00:00:00Z")
    generated = _parse_utc(scorecard.get("generated_at"))
    if started and generated:
        held = (generated - started).days + 1
        if nominal_days and held < nominal_days:
            return True, f"label promises {nominal_days}d, recorder has held {held}d (since {coverage.get('recorder_start')})"

    mine = {cell_key(cell) for cell in cells_of(window)}
    for other_name, other in windows.items():
        other_days = int("".join(ch for ch in other_name if ch.isdigit()) or 0)
        if other_days and other_days < nominal_days and {cell_key(c) for c in cells_of(other)} == mine and mine:
            return True, f"cells identical to the {other_name} window -- it holds nothing {other_name} does not"
    return False, ""


def ungraded_rates(window: dict[str, Any]) -> list[tuple[str, str, int, int, float]]:
    """(sport, reason, count, graded_rows, rate) sorted by rate desc. A RATE, not a count."""
    coverage = window.get("coverage") or {}
    by_sport = coverage.get("by_sport") or {}
    out: list[tuple[str, str, int, int, float]] = []
    for sport, reasons in (coverage.get("ungraded_by_sport") or {}).items():
        graded = int((by_sport.get(sport) or {}).get("graded_rows") or 0)
        for reason, count in (reasons or {}).items():
            denominator = graded + sum((reasons or {}).values())
            rate = (int(count) / denominator) if denominator else 0.0
            out.append((str(sport), str(reason), int(count), graded, rate))
    return sorted(out, key=lambda row: row[4], reverse=True)


def build_report(scorecard: dict[str, Any], overlay: dict[str, Any], previous: dict[str, Any] | None,
                 *, max_age_hours: float, now: datetime) -> tuple[list[str], int]:
    lines: list[str] = []
    exit_code = 0

    generated = _parse_utc(scorecard.get("generated_at"))
    age_hours = (now - generated).total_seconds() / 3600.0 if generated else None
    stale = age_hours is None or age_hours > max_age_hours

    lines.append("=" * 78)
    lines.append(f"MODEL SCORECARD  {scorecard.get('version')}   slate {scorecard.get('today_central')}")
    lines.append("=" * 78)
    lines.append(
        f"published   {scorecard.get('generated_at')}  "
        + ("age unknown" if age_hours is None else f"{age_hours:.1f}h ago")
        + (f"   STALE (> {max_age_hours:g}h)" if stale else "   fresh")
    )
    lines.append("            (age is the ARTIFACT's own generated_at -- a scheduler's lastRunAt is dispatch, not execution)")

    grader = scorecard.get("grader") or {}
    lines.append(f"grader      core={grader.get('core_code')}  settlers={json.dumps(grader.get('settlers') or {}, sort_keys=True)}")
    if grader.get("settlers_unavailable"):
        lines.append(f"            UNAVAILABLE: {grader['settlers_unavailable']}")

    # ---- windows ------------------------------------------------------------------
    lines.append("")
    lines.append("-- windows " + "-" * 66)
    for name in sorted((scorecard.get("windows") or {}).keys(), key=lambda n: int("".join(c for c in n if c.isdigit()) or 0)):
        window = scorecard["windows"][name]
        degraded, why = window_is_degraded(scorecard, name)
        flag = "DEGRADED" if degraded else "ok"
        lines.append(f"  {name:<5} {len(cells_of(window)):>4} cells   {flag}" + (f" -- {why}" if why else ""))

    # ---- coverage by sport --------------------------------------------------------
    widest = max((scorecard.get("windows") or {}).items(),
                 key=lambda kv: int("".join(c for c in kv[0] if c.isdigit()) or 0), default=(None, {}))[1]
    cells = cells_of(widest)
    by_sport: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    markets: dict[str, set[str]] = collections.defaultdict(set)
    for cell in cells:
        by_sport[str(cell.get("sport"))][str(cell.get("phase"))] += 1
        markets[str(cell.get("sport"))].add(str(cell.get("market")))

    coverage = (widest or {}).get("coverage") or {}
    graded_by_sport = coverage.get("by_sport") or {}
    sport_versions = grader.get("sport_versions") or {}

    lines.append("")
    lines.append("-- coverage: every traded sport, pregame and live " + "-" * 27)
    lines.append(f"  {'sport':<8}{'pregame':>8}{'live':>6}{'mkts':>6}{'games':>7}{'dates':>6}  status")
    missing_in_season: list[str] = []
    for sport in TRADED_SPORTS:
        phases = by_sport.get(sport) or collections.Counter()
        graded = graded_by_sport.get(sport) or {}
        seasonal = in_season(sport, now)
        if phases:
            status = "graded"
        elif sport not in sport_versions:
            status = "NO SETTLER" + ("" if seasonal is False else "  <-- in season, cannot grade")
            if seasonal is not False:
                missing_in_season.append(sport)
        elif seasonal is False:
            status = "off-season (settler ready)"
        else:
            status = "SETTLER REGISTERED, ZERO ROWS  <-- in season"
            missing_in_season.append(sport)
        lines.append(
            f"  {sport:<8}{phases.get('pregame', 0):>8}{phases.get('live', 0):>6}"
            f"{len(markets.get(sport) or ()):>6}{graded.get('games', 0):>7}{graded.get('dates', 0):>6}  {status}"
        )
    if missing_in_season:
        lines.append(f"  !! in season and not graded: {', '.join(missing_in_season)}")

    # ---- verdicts -----------------------------------------------------------------
    verdicts = collections.Counter(str(cell.get("verdict")) for cell in cells)
    total = sum(verdicts.values()) or 1
    lines.append("")
    lines.append("-- verdicts " + "-" * 65)
    for verdict, count in verdicts.most_common():
        lines.append(f"  {verdict:<18}{count:>5}   {count / total:6.1%}")
    decided = total - verdicts.get("insufficient", 0)
    lines.append(f"  decided {decided} of {total} ({decided / total:.1%}) -- the rest have no sample yet, not no edge")

    for cell in sorted((c for c in cells if c.get("verdict") in ("beats_market", "loses_to_market")),
                       key=lambda c: c.get("brier_diff") or 0.0):
        lines.append(
            f"    {cell.get('verdict'):<15} {cell.get('sport')}|{cell.get('market')}|{cell.get('segment')}|{cell.get('phase')}"
            f"  diff {cell.get('brier_diff'):+.5f}  n={cell.get('games')}g/{cell.get('dates')}d  lodo_stable={cell.get('lodo_stable')}"
        )

    # ---- day over day -------------------------------------------------------------
    if previous:
        previous_cells = {cell_key(c): c for c in cells_of(
            max((previous.get("windows") or {}).items(),
                key=lambda kv: int("".join(ch for ch in kv[0] if ch.isdigit()) or 0), default=(None, {}))[1])}
        changes = [
            (cell_key(c), previous_cells[cell_key(c)].get("verdict"), c.get("verdict"))
            for c in cells
            if cell_key(c) in previous_cells and previous_cells[cell_key(c)].get("verdict") != c.get("verdict")
        ]
        lines.append("")
        lines.append(f"-- changed since {previous.get('today_central')} " + "-" * 50)
        lines.append(f"  {len(changes)} verdict change(s); {len(set(previous_cells) - {cell_key(c) for c in cells})} cell(s) disappeared")
        for key, was, now_verdict in changes[:25]:
            lines.append(f"    {key}  {was} -> {now_verdict}")
        gone_sports = {k.split("|")[0] for k in set(previous_cells) - {cell_key(c) for c in cells}}
        regressed = sorted(gone_sports - set(by_sport))
        if regressed:
            lines.append(f"  !! REGRESSION: {', '.join(regressed)} was graded and is not any more")
            exit_code = max(exit_code, 3)

    # ---- ungraded, as a rate ------------------------------------------------------
    rates = ungraded_rates(widest or {})
    if rates:
        lines.append("")
        lines.append("-- ungraded rows, worst rate first " + "-" * 42)
        lines.append("   (rate = this reason / (graded + all ungraded) for that sport)")
        for sport, reason, count, graded, rate in rates[:12]:
            lines.append(f"  {rate:6.2%}  {sport:<8}{reason:<34}{count:>7} ungraded   ({graded:,} graded rows)")

    # ---- optimization side --------------------------------------------------------
    lines.append("")
    lines.append("-- optimization (bucket overlay + weekly backtests) " + "-" * 25)
    expires = _parse_utc(overlay.get("expires_at"))
    lines.append(
        f"  overlay     switch_enabled={overlay.get('switch_enabled')}  valid={overlay.get('valid')} ({overlay.get('validation')})"
        f"  buckets={len(overlay.get('buckets') or ())}"
    )
    lines.append(f"              window={overlay.get('window')}  expires {overlay.get('expires_at')}"
                 + (f"  ({(expires - now).total_seconds() / 3600:.1f}h left)" if expires else ""))
    if expires and expires < now:
        lines.append("              !! EXPIRED -- the scorer has fallen back to the static table")
    weekly = scorecard.get("weekly_backtests")
    if weekly:
        jobs = weekly.get("jobs") or weekly.get("results") or []
        lines.append(f"  weekly      present: {len(jobs)} job(s)  {json.dumps(weekly)[:160]}")
    else:
        lines.append("  weekly      ABSENT from this artifact -- weekly backtests run Mondays only "
                     "(publish_model_scorecard.weekly_due -> weekday() == 0)")

    if stale:
        lines.insert(0, f"FAIL stale artifact: generated_at={scorecard.get('generated_at')} is older than {max_age_hours:g}h")
        exit_code = max(exit_code, 2)
    return lines, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--max-age-hours", type=float, default=26.0,
                        help="the daily cron runs at 11:30Z; 26h tolerates one missed run being reported, not two")
    parser.add_argument("--compare-to", default=None, metavar="YYYY-MM-DD",
                        help="a previous slate date to diff verdicts against (default: yesterday)")
    parser.add_argument("--no-compare", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit the machine-readable summary instead of the report")
    args = parser.parse_args(argv)

    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if not token:
        print("FAIL no ADMIN_TOKEN in the environment. Without it every read 401s and this "
              "tool would report an empty scorecard as a real one.", file=sys.stderr)
        return 5

    try:
        scorecard = _get_json(args.base_url, "/api/model-scorecard", token)
        overlay = _get_json(args.base_url, "/api/model-scorecard/overlay", token)
    except ReadError as exc:
        print(f"FAIL could not read the scorecard: {exc}", file=sys.stderr)
        return 4
    if not isinstance(scorecard, dict) or not scorecard.get("windows"):
        print(f"FAIL the scorecard read back is not a scorecard: {str(scorecard)[:200]}", file=sys.stderr)
        return 4

    previous = None
    if not args.no_compare:
        day = args.compare_to
        if not day:
            today = _parse_utc((str(scorecard.get("today_central")) or "") + "T00:00:00Z")
            day = (today - timedelta(days=1)).date().isoformat() if today else None
        if day:
            try:
                candidate = _get_json(args.base_url, f"/api/model-scorecard/{day}", token)
                previous = candidate if isinstance(candidate, dict) and candidate.get("windows") else None
            except ReadError:
                previous = None  # a missing prior day is normal early on, not a failure

    lines, code = build_report(scorecard, overlay if isinstance(overlay, dict) else {}, previous,
                               max_age_hours=args.max_age_hours, now=datetime.now(timezone.utc))
    if args.json:
        widest = max(scorecard["windows"].items(), key=lambda kv: int("".join(c for c in kv[0] if c.isdigit()) or 0))[1]
        print(json.dumps({
            "generated_at": scorecard.get("generated_at"),
            "today_central": scorecard.get("today_central"),
            "exit_code": code,
            "cells": len(cells_of(widest)),
            "verdicts": dict(collections.Counter(str(c.get("verdict")) for c in cells_of(widest))),
            "degraded_windows": [name for name in scorecard["windows"] if window_is_degraded(scorecard, name)[0]],
            "sports_graded": sorted({str(c.get("sport")) for c in cells_of(widest)}),
            "sports_missing": [s for s in TRADED_SPORTS if s not in {str(c.get("sport")) for c in cells_of(widest)}],
        }, indent=1))
    else:
        print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
