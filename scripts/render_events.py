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

- **It prints the window it ACTUALLY READ, separately from the span of the
  events it found.** Same reason `render_logs.py` prints coverage (`#434`: a
  pager reported 99 samples spanning 1.2s of a 51s request and the number looked
  fine). A window you did not read is the failure mode -- but the two lines must
  not be conflated, because a SPARSE window reads whole and still returns a
  narrow span. This was reported as one `COVERED` line until 2026-08-17, when a
  5-hour read that found a single 4-event deploy cycle printed
  `COVERED 14:33 .. 14:39` and was read as "the API only gave me 6 minutes" --
  retracting a correct all-clear. The span of what you found says nothing about
  how much you looked at.

- **A quiet window and a broken read are DIFFERENT and never print the same.**
  Zero events in a window is a real, useful answer -- but only once you know the
  endpoint answers at all. So an empty window triggers a positive control: an
  unfiltered `limit=1` read. Events present but none in your window => genuinely
  quiet (exit 0). Nothing at all => the reader is what failed (exit 2), which is
  NOT a measurement.

- **`server_failed` is not one thing.** `oomKilled`, `evicted`,
  `unhealthy` (health-check timeout), `earlyExit` (the process returned) and
  `nonZeroExit` (it returned a code) have different causes and different fixes;
  live-odds-worker's 19 failures over a week are ALL `earlyExit` and zero OOM,
  which a "19 failures" summary would bury. The reason is classified, never
  flattened -- and `nonZeroExit` carries its CODE onto the row for the same
  reason the bucket exists: measured 2026-09-04, its 67 occurrences split into
  29 x `1` on the two workers and **38 x `137` (128+9 = SIGKILL) on web alone**,
  which one flat bucket would bury exactly as "19 failures" would.

- **A run that DIED is never mistaken for a run that finished.** The event
  rows are the last thing printed, so anything that raises while rendering them
  leaves a screenful of plausible output on stdout and the traceback on stderr
  -- and a caller piping through `tail`/`grep` sees only the first of those.
  That is how this reader could answer "no OOM events" without ever having
  reached the recent window: `details.reason` is a bare STRING on
  `auto_deploy_disabled` and `_reason_detail` assumed a mapping, so from the day
  this shipped, ANY window containing one of those events died at it. Measured
  2026-09-04 -- an unfiltered refresh-worker read printed 289 plausible lines,
  died on the 2026-07-01 event, and never saw the other 7,236. So: no
  single event can kill the run (an unrenderable one prints as a row and is
  counted), and the listing ends with an explicit `END`/`COMPLETE` marker whose
  ABSENCE is the tell. `learnings.md` 2026-09-02 FORBIDDEN: drawing a conclusion
  from output the transport truncated.

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
import traceback
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

EXIT_OK, EXIT_READER_FAILED, EXIT_ABORTED = 0, 2, 3


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
) -> tuple[list[dict], int, str]:
    """Every event in [start, end], oldest-first, de-duplicated by event id.

    The endpoint returns NEWEST-first and pages backward through `cursor`, so
    this walks back to the floor and sorts on the way out.

    Returns `(events, pages, truncated)`, where `truncated` is `""` when the
    pager reached the end of the requested window and otherwise names WHY it
    stopped short. That third value is load-bearing, not decoration: whether the
    window was fully read cannot be recovered from the event list or the page
    count afterwards. A window that reads whole and holds four events is, from
    the outside, indistinguishable from one where the cursor stalled after four
    -- and only the first licenses a statement about the whole window.
    """
    service_id = SERVICE_IDS[service]
    key = _api_key()
    cursor = ""
    seen: dict[str, dict] = {}
    pages = 0
    # Survives only if the loop exhausts `max_pages` without ever breaking, i.e.
    # the far end of the window was never reached.
    truncated = f"hit the {max_pages}-page cap"

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
        if not isinstance(rows, list):
            # An unrecognised response shape is a reader problem, and must not be
            # reported as a window that ended. `learnings.md`: an unknown that
            # lands on the permissive branch is how a bad read passes for a good one.
            truncated = "the API returned an unexpected shape"
            break
        if not rows:
            # A genuinely empty page IS the end of the window.
            truncated = ""
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
        # No cursor, or a short page, means the window really is exhausted.
        if not cursor or len(rows) < _PAGE:
            truncated = ""
            break
        # `fresh == 0` on a FULL page that still carries a cursor is the
        # no-progress guard `render_logs.fetch_window` needs -- the server is
        # handing back the same page. Stopping is right, but this is NOT the end
        # of the window: whatever lies past the stall was never read.
        if fresh == 0:
            truncated = "the cursor stopped advancing"
            break

    ordered = sorted(seen.values(), key=lambda e: str(e.get("timestamp") or ""))
    return ordered, pages, truncated


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


def _reason_of(event: dict):
    """`details.reason` EXACTLY as the API sent it -- mapping, string, or None.

    Render does NOT use one shape for this field, and the reader assumed it did.
    Measured 2026-09-04 over a fully-paged read of refresh-worker (7,525 events,
    76 pages): 759 `server_failed` and 1,522 `deploy_ended` events carry an
    OBJECT here, while all 9 `auto_deploy_disabled` events carry the bare string
    `"setting_change"` (first at 2026-07-01T21:19:15.826277Z). The old
    `(details or {}).get("reason") or {}` looks defensive and is not: `or {}`
    only rescues the falsey cases, so a non-empty string passes straight through
    to `.get` and raises.

    Returning the raw value -- rather than coercing it to a mapping -- keeps the
    two cases distinguishable at the call sites, so an unexpected shape can be
    PRINTED instead of silently flattened into "no reason".
    """
    details = event.get("details")
    if not isinstance(details, dict):
        return None
    return details.get("reason")


def classify(event: dict) -> str:
    """The REASON a `server_failed` fired, never flattened to 'failed'.

    Returns one of oomKilled / evicted / unhealthy / earlyExit / nonZeroExit /
    unknown for a failure, or the event type itself for anything else.
    """
    kind = str(event.get("type") or "?")
    if kind != "server_failed":
        return kind
    reason = _reason_of(event)
    if not isinstance(reason, dict):
        # Absent, or a shape these buckets cannot be tested against. Either way
        # it is not evidence of any known failure mode, so it goes to the
        # unknown bucket -- never assumed empty and never assumed familiar.
        return "failed:unknown"
    if reason.get("oomKilled"):
        return "oomKilled"
    if reason.get("evicted"):
        return "evicted"
    if reason.get("unhealthy"):
        return "unhealthy"
    if reason.get("earlyExit"):
        return "earlyExit"
    if "nonZeroExit" in reason:
        # Presence, not truthiness. The other branches test truth because
        # `evicted: false` is routinely present-and-false; this key is only ever
        # emitted WITH a code, and a hypothetical `nonZeroExit: 0` is a
        # contradiction worth SEEING rather than dropping into the unknown
        # bucket. The code itself goes on the row -- see `_reason_detail`.
        #
        # Measured 2026-09-04 across all three services, full unfiltered reads:
        # 67 occurrences, and NOT ONE co-occurs with `oomKilled`, `earlyExit`,
        # `unhealthy` or a true `evicted` (all 67 pair with `evicted: false` and
        # nothing else). So this branch's position cannot silently outrank a
        # more specific one on any shape yet observed -- and it is last among
        # the named buckets so that it cannot do so on a shape not yet observed.
        return "nonZeroExit"
    # An unrecognised reason must not land in a known bucket -- an unknown that
    # defaults onto a familiar branch is how a new failure mode stays invisible.
    return "failed:unknown"


def _reason_detail(event: dict) -> str:
    """The human-readable half of `details.reason`, for ANY event type.

    This runs against every row, not just failures, so it must tolerate every
    shape Render puts in that field -- see `_reason_of`. A scalar reason IS the
    detail and gets printed as-is: `auto_deploy_disabled  setting_change` is
    precisely what a reader chasing CLAUDE.md `#284` wants to see, and dropping
    it to keep the mapping assumption would trade a crash for a silent omission.
    """
    reason = _reason_of(event)
    if reason is None:
        return ""
    if not isinstance(reason, dict):
        # A string, or something stranger. Show it rather than discarding it --
        # an unrecognised shape the operator can READ is a lead; one the reader
        # swallowed is the next hour of someone's life.
        if isinstance(reason, str):
            return reason
        return "raw reason: " + json.dumps(reason, sort_keys=True, default=str)
    oom = reason.get("oomKilled")
    if isinstance(oom, dict) and oom.get("memoryLimit"):
        return f"memoryLimit={oom['memoryLimit']}"
    if reason.get("unhealthy"):
        return str(reason["unhealthy"])
    if "nonZeroExit" in reason:
        code = reason["nonZeroExit"]
        # Deliberately NOT gated on `server_failed`. 66 of the 67 measured
        # occurrences are one, but the 67th is a `job_run_ended`
        # (2026-07-31T01:03:05.175631Z) whose exit code was invisible on the row
        # because `classify` -- correctly -- returns the event type for anything
        # that is not a service failure, and nothing else printed it.
        if code == 137:
            # 128+9. A shell/POSIX convention rather than a Render guarantee, so
            # it is annotated as a reading and the raw code is still shown. It
            # matters: all 38 of web's are 137, and a SIGKILL is the shape an
            # OOM triage is looking for even when Render did not label it one.
            return "nonZeroExit=137 (128+9 = SIGKILL)"
        return f"nonZeroExit={code}"
    if classify(event) == "failed:unknown" and reason:
        # The whole point of a failed:unknown bucket is that someone can SEE the
        # shape that did not match. Printing nothing would hide the new mode as
        # effectively as mis-bucketing it.
        return "raw reason: " + json.dumps(reason, sort_keys=True, default=str)
    return ""


def _deploy_trigger(event: dict) -> str:
    """Who or what started a DEPLOY. `blueprint_sync` is the one that bites.

    Only meaningful for deploy/build events. A `server_failed` carries no
    `trigger` at all, and reading that absence as "no user" printed
    `NO USER (blueprint_sync shape?)` against all 20 of live-odds-worker's
    `earlyExit` failures -- dressing a restart-loop finding up as a config-push
    finding. Absence of a field is a fact about THIS event's shape, not evidence
    about how it was triggered.
    """
    if str(event.get("type") or "") not in ("deploy_started", "build_started"):
        return ""
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


def _describe(event: dict) -> tuple[str, str]:
    """`(kind, detail)` for one row, or a visible placeholder if it cannot be.

    One malformed event must not cost the census. The alternative -- letting it
    propagate -- is what made this tool a false-negative instrument: the rows
    print last, so the exception lands on stderr underneath a screenful of
    perfectly plausible stdout. An unrenderable row is loud, counted in the END
    line, and does not stop the read.
    """
    try:
        return classify(event), (_reason_detail(event) or _deploy_trigger(event))
    except Exception as exc:  # noqa: BLE001 -- shape errors are the whole point
        return "!!UNRENDERABLE", f"{type(exc).__name__}: {exc}"


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

    events, pages, truncated = fetch_events(service=args.service, start=args.since, end=args.end)

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
        key = _describe(event)[0]
        kinds[key] = kinds.get(key, 0) + 1

    failures = [e for e in events if str(e.get("type")) == "server_failed"]
    last_failure = failures[-1] if failures else None
    # The span of the EVENTS FOUND. Deliberately not called "covered" -- it is
    # not a coverage figure, and naming it one misled a reader once already.
    span_from = str(events[0].get("timestamp")) if events else None
    span_to = str(events[-1].get("timestamp")) if events else None
    requested_from = args.since or "(service start)"
    requested_to = args.end or "(now, i.e. this read)"

    def row_payload(event: dict) -> dict:
        stamp = str(event.get("timestamp"))
        kind, detail = _describe(event)
        return {
            "timestamp": stamp,
            "local": local(stamp),
            "type": str(event.get("type")),
            "kind": kind,
            "detail": detail,
        }

    if args.json:
        payload = {
            "service": args.service,
            "requested": {"since": args.since or None, "end": args.end or None},
            # `read` is how much was looked at; `event_span` is what was found.
            # The old single `covered` key conflated them.
            # `pages` stays at the top level, where it already was.
            "read": {
                "fully_paged": not truncated,
                "truncated_reason": truncated or None,
            },
            "event_span": {"from": span_from, "to": span_to},
            "tz": args.tz,
            "pages": pages,
            "events_total": len(events),
            "events_selected": len(selected),
            "kind_counts": kinds,
            "last_failure": (
                {
                    "timestamp": str(last_failure.get("timestamp")),
                    "local": local(str(last_failure.get("timestamp"))),
                    "kind": _describe(last_failure)[0],
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
            # A JSON document is self-terminating: a run that died mid-print
            # yields text that will not parse, so this mode needs no separate
            # completeness marker the way the text listing does.
            "events": [row_payload(e) for e in (selected[-args.tail :] if args.tail > 0 else selected)],
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
        print(f"# READ       no events in the requested window   ({pages} page(s) fetched)")
        print(f"# CONTROL    the endpoint DOES answer: newest event overall is")
        print(f"#            {stamp}  ({local(stamp)} local)  {control.get('type')}")
        if truncated:
            print(f"# PARTIAL    the pager stopped short -- {truncated}.")
            print("# So this is NOT a quiet window. Part of it was never read.")
        else:
            print("# So the window is genuinely QUIET. That is a reading, not a failure.")
        return EXIT_OK

    if truncated:
        print(f"# READ       PARTIAL -- {truncated}, after {pages} page(s).")
        print(f"#            Requested {requested_from} .. {requested_to}; the pager did NOT")
        print(f"#            reach the far end. Oldest event it got to: {span_from}")
    else:
        print(f"# READ       {requested_from} .. {requested_to}   fully paged, {pages} page(s)")
    print(f"# EVENTS     {len(events)} event(s), spanning {span_from} .. {span_to}")
    print(f"#            {local(span_from)} .. {local(span_to)} local")
    print("#            That is the span of the events FOUND, not the window read. A sparse")
    print("#            window reads whole and still spans minutes -- a narrow span here is")
    print("#            not a short read. Judge coverage by READ above, never by this line.")

    if kinds:
        print("#")
        print("# kind counts (selected):")
        for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"#   {count:5d}  {kind}")

    # The question the OOM lane asks every time: how long has it been clean?
    print("#")
    if last_failure is None:
        print("# CLEAN      no server_failed anywhere in the window READ above")
    else:
        stamp = str(last_failure.get("timestamp"))
        parsed = _parse_stamp(stamp)
        end_parsed = _parse_stamp(span_to)
        gap = ""
        if parsed and end_parsed:
            minutes = (end_parsed - parsed).total_seconds() / 60.0
            gap = f"   ({minutes:.1f} min before the NEWEST EVENT, which is not 'now')"
        print(f"# LAST FAIL  {stamp}  ({local(stamp)} local)  {_describe(last_failure)[0]}{gap}")
    # What bounds 'clean' is the window READ, not the span of events in it. Under
    # the old single COVERED line these looked like the same thing, and the
    # narrower one won -- which understated a clean read to a ~6-minute slice.
    if truncated:
        print("# NOTE       'clean' covers only the pages actually read -- see PARTIAL above.")
    else:
        print(f"# NOTE       'clean' covers the whole requested window, {requested_from}")
        print(f"#            .. {requested_to} -- NOT merely the event span above.")
    print()

    shown = selected[-args.tail :] if args.tail > 0 else selected
    if args.tail > 0 and len(selected) > args.tail:
        print(f"# showing last {args.tail} of {len(selected)}")
    unrenderable = 0
    for event in shown:
        stamp = str(event.get("timestamp"))
        kind, detail = _describe(event)
        if kind == "!!UNRENDERABLE":
            unrenderable += 1
        print(f"{local(stamp):19s}  {stamp:32s}  {kind:16s}  {detail}")

    # THE COMPLETENESS MARKER. The rows are the last thing printed, so a run
    # that dies here leaves stdout looking finished; stderr carries the
    # traceback and a pipe through `tail`/`grep` throws it away. This line is
    # the only thing that distinguishes the two, and its ABSENCE is the signal.
    print("#")
    print(f"# END        {len(shown)} row(s) printed of {len(selected)} selected, {len(events)} read.")
    if unrenderable:
        print(f"# BAD SHAPE  {unrenderable} event(s) could not be rendered -- see the !!UNRENDERABLE")
        print("#            rows above. They were COUNTED, not skipped, but their kind is unknown.")
    print("# OUTPUT COMPLETE -- this run reached the end of its listing. If you do not see")
    print("#            this line, what you are reading is a FRAGMENT and settles nothing.")
    return EXIT_OK


def _abort(exc: BaseException) -> int:
    """Say on STDOUT that the run died; the traceback still goes to stderr.

    Deliberately printed to stdout: the caller who most needs this is the one
    piping through `tail`/`grep`, and stderr is exactly what that caller has
    already discarded. Exit code is its own value (3) so a script can tell an
    aborted run from a quiet window (0) and from a dead reader (2).
    """
    print("#")
    print(f"# ABORTED    render_events died mid-run: {type(exc).__name__}: {exc}")
    print("# OUTPUT ABOVE IS INCOMPLETE. It is not a census and supports no conclusion")
    print("#            in either direction -- least of all 'no OOM events'.")
    sys.stdout.flush()
    traceback.print_exc()
    return EXIT_ABORTED


if __name__ == "__main__":
    try:
        _code = main()
    except KeyboardInterrupt:
        _code = _abort(KeyboardInterrupt("interrupted"))
    except Exception as exc:  # noqa: BLE001 -- the banner is the point
        _code = _abort(exc)
    raise SystemExit(_code)
