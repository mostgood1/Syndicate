"""Which (venue, market family) pairs REACH the venue with an order, and which never do.

WHY THIS EXISTS, and it is one measured failure rather than a general worry.

Polymarket player props were refused at BUILD one hundred percent of the time,
for as long as the prop join had been producing matches, and no instrument said
so. Every refusal counted under `market_unresolved_for_position` -- a token that
reads like a venue data gap ("the market is not in our slate") while the real
cause was that `_polymarket_resolve_market` had no player-prop branch at all.
It surfaced on 2026-09-22 only because a DIFFERENT fix (`commence_time`,
`#681`) stopped masking it: `commence_unknown` fires first, so no prop had ever
reached the side resolver. See `learnings.md` 2026-09-22 and todo `#682`.

The counts needed to catch it were already being printed. Every live-odds-worker
cycle logs, per venue:

    [live_odds_worker] ORDER_PATH venue=polymarket status=ok positions=4
      markets={'totals': {'would_build': 3}, 'strikeouts': {'market_unresolved': 1}}
      examples={...}

`would_build` is "this position would become a real order". Anything else is a
refusal, by name. A family that is PRESENT in the plan and whose `would_build`
is zero for a whole day is a market we are ranking, sizing and never betting.
Nobody reads a per-cycle line for an absence, so this reads the day for them.

WHAT IT IS NOT. It is not a gate and it places nothing. It reads the Render logs
API and prints a census. It is also NOT a per-cycle worker task: worker periodic
work is never free (todo `#241` caused a production restart loop), and a
once-a-day read off the logs API costs the worker nothing.

THREE OUTCOMES, AND "I COULD NOT TELL" IS NOT SUCCESS:

    exit 0  CLEAR         every family in the window built at least once
    exit 1  ALERT         at least one family has positions and zero builds
    exit 2  INCONCLUSIVE  no ORDER_PATH lines at all, or lines we could not read

Exit 2 is deliberate and it is the rule `learnings.md` states as "unknown must
not default permissive": a silent instrument and a healthy one must never share
an outcome. An unreadable `markets={...}` is not evidence that anything built.

    py -3 scripts/venue_order_family_census.py                 # last 24 h
    py -3 scripts/venue_order_family_census.py --hours 6 --json
    py -3 scripts/venue_order_family_census.py --start 2026-09-22T00:00:00Z \
                                               --end   2026-09-22T16:30:04Z
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: What the emitter calls a position that would become a real order. Everything
#: else in a family's dict is a refusal token, so a new refusal reason needs no
#: change here -- the allowlist is the SUCCESS side, which is the small one.
BUILD_VERDICT = "would_build"

#: The text the logs API filters on. Narrow enough to page cheaply, wide enough
#: that a venue whose line says `status=no_positions` is still seen -- absence of
#: positions is a real answer and must not look like absence of the instrument.
LOG_TEXT = "ORDER_PATH venue="

#: The HEADER only. The `markets={...}` payload is cut out separately, so a
#: truncated or malformed payload still tells us WHICH VENUE could not be read
#: -- "something was unreadable" and "polymarket was unreadable" are different
#: findings, and the first one cannot be acted on.
_LINE = re.compile(
    r"ORDER_PATH\s+venue=(?P<venue>\S+)"
    r"(?:\s+status=(?P<status>\S+))?"
    r"(?:\s+positions=(?P<positions>\d+))?",
)


def _markets_payload(text: str) -> str | None:
    """The `{...}` after `markets=`, or None when the line carries none."""
    at = text.find("markets=")
    if at < 0:
        return None
    rest = text[at + len("markets=") :]
    cut = rest.find(" examples=")
    return (rest if cut < 0 else rest[:cut]).strip()


#: A family seen fewer times than this is REPORTED but not alerted on. One
#: refusal on one cycle is noise -- a market can be unpriced for a minute. The
#: Polymarket props case was 100% of hundreds of passes, so this bound does not
#: weaken the thing it exists to catch.
DEFAULT_MIN_OCCURRENCES = 3


def _parse_markets(raw: str) -> dict[str, dict[str, int]] | None:
    """The `markets={...}` payload as {family: {verdict: count}}, or None.

    None means UNREADABLE, which the caller must treat as inconclusive rather
    than as "nothing built" or "everything built".
    """
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(value, dict):
        return None
    out: dict[str, dict[str, int]] = {}
    for family, verdicts in value.items():
        if not isinstance(verdicts, Mapping):
            return None
        counts: dict[str, int] = {}
        for verdict, count in verdicts.items():
            try:
                counts[str(verdict)] = int(count)
            except (TypeError, ValueError):
                return None
        out[str(family)] = counts
    return out


def census(
    lines: Iterable[tuple[str, str]],
    *,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
) -> dict[str, Any]:
    """The census over `(timestamp, text)` log lines. Pure: no network, no clock.

    Kept separate from `main` so the rule can be tested against verbatim
    production lines instead of against a mock of itself.
    """
    venues: dict[str, dict[str, Any]] = {}
    unreadable: list[str] = []
    matched = 0

    for stamp, text in lines:
        body = text or ""
        match = _LINE.search(body) if "ORDER_PATH_FAILED" not in body else None
        if not match:
            if "ORDER_PATH" in body and "ORDER_PATH_FAILED" not in body:
                unreadable.append(f"{stamp} unparsed_line")
            continue
        matched += 1
        venue = match.group("venue")
        entry = venues.setdefault(
            venue,
            {
                "passes": 0,
                "statuses": Counter(),
                "positions_total": 0,
                "families": {},
                "unreadable_lines": 0,
                "first_seen": stamp,
                "last_seen": stamp,
            },
        )
        entry["passes"] += 1
        entry["last_seen"] = stamp
        entry["statuses"][match.group("status") or "(none)"] += 1
        if match.group("positions"):
            entry["positions_total"] += int(match.group("positions"))

        raw = _markets_payload(body)
        markets = _parse_markets(raw) if raw is not None else None
        if markets is None:
            entry["unreadable_lines"] += 1
            unreadable.append(f"{stamp} venue={venue} markets_unreadable")
            continue
        for family, verdicts in markets.items():
            fam = entry["families"].setdefault(
                family, {"verdicts": Counter(), "occurrences": 0, "builds": 0, "passes": 0}
            )
            fam["passes"] += 1
            for verdict, count in verdicts.items():
                fam["verdicts"][verdict] += count
                fam["occurrences"] += count
                if verdict == BUILD_VERDICT:
                    fam["builds"] += count

    alerts: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    for venue, entry in venues.items():
        for family, fam in entry["families"].items():
            if fam["builds"] > 0:
                continue
            row = {
                "venue": venue,
                "family": family,
                "occurrences": fam["occurrences"],
                "passes": fam["passes"],
                "builds": 0,
                "refusals": dict(fam["verdicts"]),
            }
            (alerts if fam["occurrences"] >= min_occurrences else watch).append(row)

    alerts.sort(key=lambda r: (-r["occurrences"], r["venue"], r["family"]))
    watch.sort(key=lambda r: (-r["occurrences"], r["venue"], r["family"]))

    if matched == 0:
        verdict = "INCONCLUSIVE"
        reason = "no ORDER_PATH lines in the window -- the instrument is silent, which is not the same as healthy"
    elif unreadable:
        verdict = "INCONCLUSIVE"
        reason = f"{len(unreadable)} line(s) could not be read; an unreadable line is not evidence that anything built"
    elif alerts:
        verdict = "ALERT"
        reason = f"{len(alerts)} family/families have positions and zero builds"
    else:
        verdict = "CLEAR"
        reason = "every family seen in the window built at least once"

    return {
        "verdict": verdict,
        "reason": reason,
        "lines_matched": matched,
        "min_occurrences": min_occurrences,
        "venues": {
            venue: {
                "passes": entry["passes"],
                "statuses": dict(entry["statuses"]),
                "positions_total": entry["positions_total"],
                "unreadable_lines": entry["unreadable_lines"],
                "first_seen": entry["first_seen"],
                "last_seen": entry["last_seen"],
                "families": {
                    family: {
                        "passes": fam["passes"],
                        "occurrences": fam["occurrences"],
                        "builds": fam["builds"],
                        "verdicts": dict(fam["verdicts"]),
                    }
                    for family, fam in sorted(entry["families"].items())
                },
            }
            for venue, entry in sorted(venues.items())
        },
        "alerts": alerts,
        "watch": watch,
        "unreadable": unreadable[:20],
    }


EXIT_CLEAR, EXIT_ALERT, EXIT_INCONCLUSIVE = 0, 1, 2


def exit_code(report: Mapping[str, Any]) -> int:
    return {"CLEAR": EXIT_CLEAR, "ALERT": EXIT_ALERT}.get(
        str(report.get("verdict")), EXIT_INCONCLUSIVE
    )


def render(report: Mapping[str, Any]) -> str:
    """The whole census, INCLUDING THE ZEROES -- a line printed only on failure
    cannot tell a healthy day from a day the instrument stopped."""
    out: list[str] = []
    for venue, entry in (report.get("venues") or {}).items():
        out.append(
            f"{venue}: passes={entry['passes']} positions_total={entry['positions_total']}"
            f" statuses={entry['statuses']} unreadable={entry['unreadable_lines']}"
            f" window {entry['first_seen']} .. {entry['last_seen']}"
        )
        if not entry["families"]:
            out.append("    (no market families in any pass)")
        for family, fam in entry["families"].items():
            flag = "  <-- NEVER BUILT" if fam["builds"] == 0 else ""
            out.append(
                f"    {family:<24} passes={fam['passes']:<4} occurrences={fam['occurrences']:<5}"
                f" builds={fam['builds']:<5} {fam['verdicts']}{flag}"
            )
    for row in report.get("alerts") or ():
        out.append(
            f"ALERT {row['venue']} {row['family']}: {row['occurrences']} position-pass(es)"
            f" over {row['passes']} pass(es), 0 built. refusals={row['refusals']}"
        )
    for row in report.get("watch") or ():
        out.append(
            f"watch {row['venue']} {row['family']}: 0 built but only {row['occurrences']}"
            f" occurrence(s) (< min_occurrences={report.get('min_occurrences')}) -- reported, not alerted"
        )
    for line in report.get("unreadable") or ():
        out.append(f"unreadable: {line}")
    out.append(f"{report.get('verdict')}: {report.get('reason')}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--service", default="live-odds-worker")
    parser.add_argument("--hours", type=float, default=24.0, help="window size when --start is absent")
    parser.add_argument("--start", default="", help="ISO8601 UTC, e.g. 2026-09-22T00:00:00Z")
    parser.add_argument("--end", default="", help="ISO8601 UTC; default now")
    parser.add_argument("--min-occurrences", type=int, default=DEFAULT_MIN_OCCURRENCES)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    start = args.start.strip()
    if not start:
        start = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    from render_logs import fetch_window  # local import: needs RENDER_API_KEY

    lines, pages = fetch_window(service=args.service, text=LOG_TEXT, start=start, end=args.end.strip())
    report = census(lines, min_occurrences=args.min_occurrences)
    report["service"] = args.service
    report["window"] = {"start": start, "end": args.end.strip() or "(now)", "pages": pages}

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"# {args.service}  {start} .. {args.end.strip() or '(now)'}  ({pages} page(s), {report['lines_matched']} line(s))")
        print(render(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
