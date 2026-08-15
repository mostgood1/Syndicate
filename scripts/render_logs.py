"""Read a bounded window of one Syndicate service's Render logs, correctly.

WHY THIS EXISTS RATHER THAN A curl OR A THROWAWAY SNIPPET. `#434`.

**The Render logs API returns the NEWEST `limit` lines inside the window, and
presents them oldest-first.** `deploy_preflight.newest_log`'s docstring already
says so, and three sessions in a row have written a pager that ignores it:

    # WRONG -- re-reads the same tail and terminates
    while True:
        page = get(startTime=cursor, ...)
        cursor = newest_timestamp_in(page)

On 2026-08-14 that shape reported `PEAK 606.2 MB ... samples 99` for a
51-second overview pass while having covered **1.2 seconds** of it. The number
was plausible, carried a sample count, and was wrong by 200MB. Paging must go
BACKWARD: lower `endTime` to the oldest line seen until the window is exhausted.

**A window you did not cover is the failure mode, so this tool always prints the
window it ACTUALLY covered next to the one you asked for.** A sample count does
not reveal truncation -- 99 samples looks like coverage until you notice they
span 1.2s of a 51s request.

Also here because the secret must stay out of argv: `RENDER_API_KEY` is read
from the gitignored `.env` by the same loader `deploy_preflight` uses, so this
can be permitted as exactly `Bash(python scripts/render_logs.py *)` rather than
opening up `curl`.

    py -3 scripts/render_logs.py --text OVERVIEW_SPORT_BEGIN --start 2026-08-14T22:56:00Z
    py -3 scripts/render_logs.py --text CONTAINER_MEMORY --start ... --end ... --max-field memory_anon_mb
    py -3 scripts/render_logs.py --service live-odds-worker --text ODDS_ --start ... --tail 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_preflight import OWNER_ID, SERVICE_IDS, _api_key, _get  # noqa: E402

# One page is the API's cap. Paging backward is what makes the window whole;
# raising this would not.
_PAGE = 100
# A backstop, not a budget. 200 pages of 100 lines is far more than any window
# worth reading interactively, and it stops a pathological loop rather than
# bounding normal use.
_MAX_PAGES = 200


def fetch_window(
    *,
    service: str,
    text: str,
    start: str,
    end: str = "",
    max_pages: int = _MAX_PAGES,
) -> tuple[list[tuple[str, str]], int]:
    """Every line matching `text` in [start, end], oldest-first, de-duplicated.

    Returns (lines, pages_fetched). Pages BACKWARD -- see the module docstring.
    """
    service_id = SERVICE_IDS[service]
    key = _api_key()
    seen: dict[str, str] = {}
    cursor_end = end
    pages = 0

    for _ in range(max_pages):
        params = {
            "ownerId": OWNER_ID,
            "resource": service_id,
            "limit": str(_PAGE),
            "text": text,
            "startTime": start,
        }
        if cursor_end:
            params["endTime"] = cursor_end
        payload = _get("https://api.render.com/v1/logs?" + urllib.parse.urlencode(params), key)
        pages += 1
        rows = (payload or {}).get("logs") or []

        oldest = cursor_end
        fresh = 0
        for row in rows:
            stamp = str(row.get("timestamp") or "")
            message = str(row.get("message") or "")
            # The API's filter is a case-insensitive SUBSTRING match and
            # over-matches longer tokens, so re-check -- same reason
            # `deploy_preflight.newest_log` does.
            if text.lower() not in message.lower():
                continue
            if stamp not in seen:
                seen[stamp] = message
                fresh += 1
            if not oldest or stamp < oldest:
                oldest = stamp

        # `fresh == 0` means this page held nothing new; `oldest <= start` means
        # we have walked back to the requested edge. Either way the window is
        # done. `oldest == cursor_end` guards the degenerate no-progress case.
        if fresh == 0 or not oldest or oldest <= start or oldest == cursor_end:
            break
        cursor_end = oldest

    return sorted(seen.items()), pages


def _max_numeric_field(lines: list[tuple[str, str]], field: str) -> tuple[str, float] | None:
    pattern = re.compile(rf'"{re.escape(field)}":\s*(-?[0-9.]+)')
    best: tuple[str, float] | None = None
    for stamp, message in lines:
        match = pattern.search(message)
        if not match:
            continue
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if best is None or value > best[1]:
            best = (stamp, value)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="refresh-worker", choices=sorted(SERVICE_IDS))
    parser.add_argument("--text", required=True, help="substring to match (case-insensitive)")
    parser.add_argument("--start", required=True, help="ISO8601, e.g. 2026-08-14T22:56:00Z")
    parser.add_argument("--end", default="", help="ISO8601; omit for 'up to now'")
    parser.add_argument("--tail", type=int, default=0, help="print only the last N matches")
    parser.add_argument(
        "--max-field",
        default="",
        help="numeric JSON field to report the maximum of, e.g. memory_anon_mb",
    )
    parser.add_argument("--width", type=int, default=200, help="truncate each message to N chars")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    lines, pages = fetch_window(
        service=args.service, text=args.text, start=args.start, end=args.end
    )

    if args.json:
        payload = {
            "service": args.service,
            "text": args.text,
            "requested": {"start": args.start, "end": args.end or None},
            "covered": {
                "start": lines[0][0] if lines else None,
                "end": lines[-1][0] if lines else None,
            },
            "matches": len(lines),
            "pages": pages,
            "lines": [{"timestamp": t, "message": m} for t, m in lines],
        }
        if args.max_field:
            peak = _max_numeric_field(lines, args.max_field)
            payload["max_field"] = (
                {"field": args.max_field, "value": peak[1], "timestamp": peak[0]} if peak else None
            )
        print(json.dumps(payload, indent=2))
        return 0

    # THE COVERED WINDOW IS NOT DECORATION -- it is the check that this read is
    # a measurement rather than a sliver. Printed even when it equals the
    # request, because the case that matters is the one nobody looks at.
    print(f"# {args.service}  text={args.text!r}")
    print(f"# requested  {args.start} .. {args.end or '(now)'}")
    if lines:
        print(f"# COVERED    {lines[0][0]} .. {lines[-1][0]}   ({len(lines)} matches, {pages} pages)")
    else:
        print(f"# COVERED    nothing matched   ({pages} page(s) fetched)")
        return 0

    if args.max_field:
        peak = _max_numeric_field(lines, args.max_field)
        if peak is None:
            print(f"# max {args.max_field}: FIELD NOT PRESENT in any matched line")
        else:
            print(f"# max {args.max_field}: {peak[1]} at {peak[0]}")

    shown = lines[-args.tail :] if args.tail > 0 else lines
    if args.tail > 0 and len(lines) > args.tail:
        print(f"# showing last {args.tail} of {len(lines)}")
    for stamp, message in shown:
        print(f"{stamp}  {message.strip()[: args.width]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
