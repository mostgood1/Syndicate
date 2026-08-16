"""Read one Syndicate service's Render EVENTS -- kills, deploys, restarts.

WHY THIS EXISTS. `learnings.md`, 2026-08-15, FORBIDDEN:

    never conclude "no OOM" from a LOG search. Kills are EVENTS.
    ...a negative result about process death MUST come from the events API.
    `scripts/render_logs.py` cannot answer this question and a 0-match result
    from it is not evidence. Absence of a log line is evidence about the
    EMITTER, and a killed process emits nothing.

That rule named the tool that CANNOT answer the question and left nothing in its
place, so every session needing a kill census has hand-rolled one. This is the
tool. `render_logs.py` for what a process SAID; this for what happened TO it.

WHAT IT GETS RIGHT, and why each one is load-bearing:

- **It prints the window it ACTUALLY covered.** Same reason `render_logs.py`
  does (`#434`: a pager reported 99 samples spanning 1.2s of a 51s request and
  the number looked fine). A window you did not cover is the failure mode.

- **A quiet window and a broken read are DIFFERENT and never print the same.**
  Zero events in a window is a real, useful answer -- but only once you know the
  endpoint answers at all. So an empty window triggers a positive control: an
  unfiltered `limit=1` read. Events present but none in your window => genuinely
  quiet (exit 0). Nothing at all => the reader is what failed (exit 2), which is
  NOT a measurement.

- **`server_failed` is not one thing.** `oomKilled`, `evicted`,
  `unhealthy` (health-check timeout) and `earlyExit` (the process returned) have
  different causes and different fixes; live-odds-worker's 19 failures over a
  week are ALL `earlyExit` and zero OOM, which a "19 failures" summary would
  bury. The reason is classified, never flattened.

- **Local time, because that is when the operator was awake.** Slates, peaks and
  the MLB evening window are all local; UTC has produced a wrong recommendation
  here before. Both stamps are printed.

The secret stays out of argv: `RENDER_API_KEY` comes from the gitignored `.env`
via the same loader `deploy_preflight` uses, so this can be permitted as exactly
`Bash(python scripts/render_events.py *)`.

    py -3 scripts/render_events.py --since 2026-08-14T00:00:00Z
    py -3 scripts/render_events.py --failures-only --since 2026-08-09T00:00:00Z
    py -3 scripts/render_events.py --service web --since ... --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_preflight import SERVICE_IDS, _api_key, _get  # noqa: E402

# The API's cap for this endpoint. Paging the cursor is what makes the window
# whole; raising this would not.
_PAGE = 100
# A backstop, not a budget -- 100 pages is 10,000 events, far past any window
# worth reading interactively. It stops a pathological loop rather than
# bounding normal use.
_MAX_PAGES = 100

DEFAULT_TZ = "America/Chicago"

EXIT_OK, EXIT_READER_FAILED = 0, 2


def _local_zone(name: str):
    """The named zone, or the machine's local time if tzdata is unavailable."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return dt.datetime.now().astimezone().tzinfo


def _parse_stamp(raw: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def fetch_events(
    *,
    service: str,
    start: str = "",
    end: str = "",
    max_pages: int = _MAX_PAGES,
) -> tuple[list[dict], int]:
    """Every event in [start, end], oldest-first, de-duplicated by event id.

    The endpoint returns NEWEST-first and pages backward through `cursor`, so
    this walks back to the floor and sorts on the way out.
    """
    service_id = SERVICE_IDS[service]
    key = _api_key()
    cursor = ""
    seen: dict[str, dict] = {}
    pages = 0

    for _ in range(max_pages):
        params = {"limit": str(_PAGE)}
        if start:
            params["startTime"] = start
        if end:
            params["endTime"] = end
        if cursor:
            params["cursor"] = cursor
        url = f"https://api.render.com/v1/services/{service_id}/events?" + urllib.parse.urlencode(params)
        rows = _get(url, key)
        pages += 1
        if not isinstance(rows, list) or not rows:
            break

        fresh = 0
        for row in rows:
            event = row.get("event") or {}
            ident = str(event.get("id") or event.get("timestamp") or "")
            if not ident or ident in seen:
                continue
            seen[ident] = event
            fresh += 1

        cursor = str(rows[-1].get("cursor") or "")
        # `fresh == 0` means this page held nothing new; a short page means the
        # window is exhausted. Either way, stop -- the same no-progress guard
        # `render_logs.fetch_window` needs.
        if not cursor or fresh == 0 or len(rows) < _PAGE:
            break

    ordered = sorted(seen.values(), key=lambda e: str(e.get("timestamp") or ""))
    return ordered, pages


def newest_event(service: str) -> dict | None:
    """The single most recent event, unfiltered -- the positive control.

    Without this, "nothing in your window" and "this read is broken" are the
    same output, and one of them is a measurement.
    """
    service_id = SERVICE_IDS[service]
    rows = _get(f"https://api.render.com/v1/services/{service_id}/events?limit=1", _api_key())
    if isinstance(rows, list) and rows:
        return rows[0].get("event") or None
    return None


def classify(event: dict) -> str:
    """The REASON a `server_failed` fired, never flattened to 'failed'.

    Returns one of oomKilled / evicted / unhealthy / earlyExit / unknown for a
    failure, or the event type itself for anything else.
    """
    kind = str(event.get("type") or "?")
    if kind != "server_failed":
        return kind
    reason = (event.get("details") or {}).get("reason") or {}
    if reason.get("oomKilled"):
        return "oomKilled"
    if reason.get("evicted"):
        return "evicted"
    if reason.get("unhealthy"):
        return "unhealthy"
    if reason.get("earlyExit"):
        return "earlyExit"
    # An unrecognised reason must not land in a known bucket -- an unknown that
    # defaults onto a familiar branch is how a new failure mode stays invisible.
    return "failed:unknown"


def _reason_detail(event: dict) -> str:
    reason = (event.get("details") or {}).get("reason") or {}
    oom = reason.get("oomKilled")
    if isinstance(oom, dict) and oom.get("memoryLimit"):
        return f"memoryLimit={oom['memoryLimit']}"
    if reason.get("unhealthy"):
        return str(reason["unhealthy"])
    return ""


def _deploy_trigger(event: dict) -> str:
    """Who or what started a deploy. `blueprint_sync` is the one that bites."""
    trigger = (event.get("details") or {}).get("trigger") or {}
    if not isinstance(trigger, dict):
        return ""
    user = trigger.get("user") or {}
    parts = []
    if user.get("email"):
        parts.append(str(user["email"]))
    for flag in ("manual", "rollback", "envUpdated", "clearCache", "firstBuild", "deployedByRender"):
        if trigger.get(flag):
            parts.append(flag)
    if not parts:
        # No user and no flag is the `blueprint_sync` shape -- see CLAUDE.md
        # `#284`. Say so rather than printing an empty column.
        parts.append("NO USER (blueprint_sync shape?)")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="refresh-worker", choices=sorted(SERVICE_IDS))
    parser.add_argument("--since", "--start", dest="since", default="", help="ISO8601, e.g. 2026-08-14T00:00:00Z")
    parser.add_argument("--end", default="", help="ISO8601; omit for 'up to now'")
    parser.add_argument("--failures-only", action="store_true", help="only server_failed events")
    parser.add_argument("--type", default="", help="only this event type, e.g. deploy_started")
    parser.add_argument("--tz", default=DEFAULT_TZ, help=f"zone for local stamps (default {DEFAULT_TZ})")
    parser.add_argument("--tail", type=int, default=0, help="print only the last N events")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    events, pages = fetch_events(service=args.service, start=args.since, end=args.end)

    selected = events
    if args.failures_only:
        selected = [e for e in selected if str(e.get("type")) == "server_failed"]
    if args.type:
        selected = [e for e in selected if str(e.get("type")) == args.type]

    zone = _local_zone(args.tz)

    def local(raw: str) -> str:
        parsed = _parse_stamp(raw)
        return parsed.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S") if parsed else "?"

    # THE POSITIVE CONTROL. Only paid for when the window came back empty --
    # that is the only case where "quiet" and "broken" are confusable.
    control = None
    if not events:
        control = newest_event(args.service)

    kinds: dict[str, int] = {}
    for event in selected:
        key = classify(event)
        kinds[key] = kinds.get(key, 0) + 1

    failures = [e for e in events if str(e.get("type")) == "server_failed"]
    last_failure = failures[-1] if failures else None
    covered_from = str(events[0].get("timestamp")) if events else None
    covered_to = str(events[-1].get("timestamp")) if events else None

    if args.json:
        payload = {
            "service": args.service,
            "requested": {"since": args.since or None, "end": args.end or None},
            "covered": {"from": covered_from, "to": covered_to},
            "tz": args.tz,
            "pages": pages,
            "events_total": len(events),
            "events_selected": len(selected),
            "kind_counts": kinds,
            "last_failure": (
                {
                    "timestamp": str(last_failure.get("timestamp")),
                    "local": local(str(last_failure.get("timestamp"))),
                    "kind": classify(last_failure),
                }
                if last_failure
                else None
            ),
            "reader_failed": bool(not events and control is None),
            "positive_control_newest": (
                {"timestamp": str(control.get("timestamp")), "type": str(control.get("type"))}
                if control
                else None
            ),
            "events": [
                {
                    "timestamp": str(e.get("timestamp")),
                    "local": local(str(e.get("timestamp"))),
                    "type": str(e.get("type")),
                    "kind": classify(e),
                    "detail": _reason_detail(e) or _deploy_trigger(e),
                }
                for e in (selected[-args.tail :] if args.tail > 0 else selected)
            ],
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK if (events or control) else EXIT_READER_FAILED

    print(f"# {args.service}  events   tz={args.tz}")
    print(f"# requested  {args.since or '(all)'} .. {args.end or '(now)'}")

    if not events:
        if control is None:
            # Not a measurement. Say so in the words the operator needs to read.
            print("# NO EVENTS RETURNED AND THE POSITIVE CONTROL IS ALSO EMPTY.")
            print("# This is a READER FAILURE, not a quiet service. Do not conclude anything.")
            return EXIT_READER_FAILED
        stamp = str(control.get("timestamp"))
        print(f"# COVERED    no events in the requested window   ({pages} page(s) fetched)")
        print(f"# CONTROL    the endpoint DOES answer: newest event overall is")
        print(f"#            {stamp}  ({local(stamp)} local)  {control.get('type')}")
        print("# So the window is genuinely QUIET. That is a reading, not a failure.")
        return EXIT_OK

    print(
        f"# COVERED    {covered_from} .. {covered_to}"
        f"   ({len(events)} events, {pages} pages)"
    )
    print(f"#            {local(covered_from)} .. {local(covered_to)} local")

    if kinds:
        print("#")
        print("# kind counts (selected):")
        for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"#   {count:5d}  {kind}")

    # The question the OOM lane asks every time: how long has it been clean?
    print("#")
    if last_failure is None:
        print("# CLEAN      no server_failed anywhere in the covered window")
    else:
        stamp = str(last_failure.get("timestamp"))
        parsed = _parse_stamp(stamp)
        end_parsed = _parse_stamp(covered_to)
        gap = ""
        if parsed and end_parsed:
            minutes = (end_parsed - parsed).total_seconds() / 60.0
            gap = f"   ({minutes:.1f} min before the end of coverage)"
        print(f"# LAST FAIL  {stamp}  ({local(stamp)} local)  {classify(last_failure)}{gap}")
    # A window's end is not "now" -- saying otherwise is how a stale read becomes
    # a claim about the present.
    print("# NOTE       'clean' is bounded by the covered window above, not by now.")
    print()

    shown = selected[-args.tail :] if args.tail > 0 else selected
    if args.tail > 0 and len(selected) > args.tail:
        print(f"# showing last {args.tail} of {len(selected)}")
    for event in shown:
        stamp = str(event.get("timestamp"))
        detail = _reason_detail(event) or _deploy_trigger(event)
        print(f"{local(stamp):19s}  {stamp:32s}  {classify(event):16s}  {detail}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
