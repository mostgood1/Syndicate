# -*- coding: utf-8 -*-
"""THE GATE ON RECLAIMING `#637`'s ~115 MB. Never expires anything itself.

`venue_odds` moved off the shared keyvalue store onto per-service disk
(`e4a471c0`). The old Redis copies are still there, living out their 10-day TTL,
and expiring them early would free the memory sooner.

WHY THIS EXISTS RATHER THAN JUST RUNNING THE EXPIRY
--------------------------------------------------------------------------
A service carries its history across the move by HYDRATING: on its FIRST write
of a file, `record_daily_odds` finds no disk copy, reads the old keyvalue copy
once, and writes it to disk. Expire a key BEFORE the services that write that
file have hydrated it and those files start empty -- and an accumulator that
records the opening on FIRST SIGHT does not lose the history quietly. It
re-dates every `opened_at` to the expiry moment and reads, forever after, as
though the book opened then. **Wrong data, permanently, with no way back.**

So the question this answers is not "how much would we free" but:

    for every venue_odds key still in Redis, has EVERY service that writes
    that file already hydrated it?

WHAT MAKES THE ANSWER TRUSTWORTHY
--------------------------------------------------------------------------
* `HYDRATED_FROM_KEYVALUE` DID NOT EXIST before `e4a471c0`. Its mere presence
  in a log dates it after that deploy, so a single generous `--since` cannot
  accidentally count a pre-deploy line. There are none to count.
* A service is only expected to hydrate a venue it actually WRITES. That is
  read from `DAILY_BOOK` lines in the same window, not assumed -- both workers
  turned out to write BOTH venues, which contradicted the split this lane
  believed for most of a session.
* A service that has written NOTHING in the window is reported as UNKNOWN and
  blocks the verdict. Silence is not consent: a worker that is down has not
  "finished hydrating", it has not started.

EXIT CODES: 0 every key SAFE. 2 at least one key PENDING or UNKNOWN. 3 the
census could not be taken (no keys read, or a service could not be queried) --
which is NOT the same as "safe", and is why it is not 0.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES = ("live-odds-worker", "refresh-worker")
BASE = "https://syndicate-an21.onrender.com"

# Local date, used only to tell a FINISHED game date from a future one.
_TODAY = __import__("datetime").date.today().isoformat()

# venue_odds/<venue>__<sport>__<YYYY_MM_DD>.json
KEY_RE = re.compile(r"venue_odds/([a-z0-9]+)__([a-z0-9_]+)__(\d{4}_\d{2}_\d{2})\.json")
HYD_RE = re.compile(
    r"HYDRATED_FROM_KEYVALUE venue=(\S+) sport=(\S+) game_date=(\S+) markets=(\d+)"
)
BOOK_RE = re.compile(r"\[(\w+)\] (?:(\w+)_)?DAILY_BOOK status=(\w+)")


def _admin_token(env_file: str) -> str:
    for line in open(env_file, encoding="utf-8-sig"):
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found in %s" % env_file)


def _redis_venue_odds_keys(token: str, top: int) -> tuple[dict[tuple[str, str, str], int], bool]:
    """(venue, sport, date) -> bytes, plus whether the listing may be truncated."""
    url = "%s/api/ops/keyvalue/usage?top_keys=%d" % (BASE, top)
    req = urllib.request.Request(url, headers={"X-Admin-Token": token})
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out: dict[tuple[str, str, str], int] = {}
    for entry in payload.get("largest_keys") or []:
        m = KEY_RE.search(str(entry.get("key") or ""))
        if m:
            out[(m.group(1), m.group(2), m.group(3).replace("_", "-"))] = int(entry.get("bytes") or 0)
    # The endpoint returns only the N largest keys. A venue_odds key smaller
    # than the Nth largest is INVISIBLE here -- and invisible must not read as
    # absent, which would let a key be expired that was never censused.
    listed = len(payload.get("largest_keys") or [])
    bucket = next(
        (b for b in (payload.get("buckets") or []) if b.get("bucket") == "reports/intelligence"),
        None,
    )
    truncated = listed >= top or bool(payload.get("keys_truncated"))
    if bucket and out:
        # Weak corroboration: if the intelligence bucket holds many more keys
        # than we matched, say so rather than implying the census is complete.
        truncated = truncated or int(bucket.get("key_count") or 0) > listed
    return out, truncated


def _logs(service: str, text: str, since: str) -> str:
    cmd = [
        sys.executable, os.path.join(REPO, "scripts", "render_logs.py"),
        "--service", service, "--text", text, "--start", since, "--width", "260",
    ]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=REPO)
    except Exception as exc:
        print("  ! could not read %s logs for %s: %s" % (service, text, exc))
        return ""
    return done.stdout or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-02T18:00:00Z",
                    help="ISO8601. Safe to set generously: HYDRATED_FROM_KEYVALUE "
                         "did not exist before e4a471c0, so no pre-deploy line can be counted.")
    ap.add_argument("--env-file", default=os.path.join(REPO, ".env"))
    ap.add_argument("--top-keys", type=int, default=100)
    args = ap.parse_args()

    token = _admin_token(args.env_file)
    keys, truncated = _redis_venue_odds_keys(token, args.top_keys)
    print("venue_odds keys still in Redis: %d" % len(keys))
    if truncated:
        print("  ! LISTING MAY BE TRUNCATED -- the usage endpoint returns only the")
        print("    largest keys. Treat any verdict below as covering ONLY these.")
    if not keys:
        print("\nNo venue_odds keys read. That is NOT 'safe to expire' -- it is")
        print("'the census could not be taken'. Exiting 3.")
        return 3

    hydrated: dict[str, set[tuple[str, str, str]]] = {}
    venues_written: dict[str, set[str]] = {}
    for svc in SERVICES:
        out = _logs(svc, "HYDRATED_FROM_KEYVALUE", args.since)
        hydrated[svc] = {(m.group(1), m.group(2), m.group(3)) for m in HYD_RE.finditer(out)}
        book = _logs(svc, "DAILY_BOOK", args.since)
        seen: set[str] = set()
        for m in BOOK_RE.finditer(book):
            tag = (m.group(2) or m.group(1) or "").lower()
            if "kalshi" in tag:
                seen.add("kalshi")
            elif "polymarket" in tag:
                seen.add("polymarket")
        venues_written[svc] = seen
        print("  %-18s hydrated %3d file(s), wrote venues: %s"
              % (svc, len(hydrated[svc]), ", ".join(sorted(seen)) or "(NONE SEEN)"))

    print("")
    verdicts: collections.Counter[str] = collections.Counter()
    rows: list[tuple[str, tuple[str, str, str], int, str]] = []
    for key, size in sorted(keys.items(), key=lambda kv: -kv[1]):
        venue = key[0]
        # Only services that demonstrably WRITE this venue are expected to
        # hydrate it. A service that writes nothing at all is UNKNOWN, not
        # exempt -- being down is not the same as being finished.
        owed, missing, unknown = [], [], []
        for svc in SERVICES:
            if not venues_written[svc]:
                unknown.append(svc)
            elif venue in venues_written[svc]:
                owed.append(svc)
                if key not in hydrated[svc]:
                    missing.append(svc)
        if unknown:
            verdict = "UNKNOWN (no writes seen: %s)" % ",".join(unknown)
        elif not owed:
            verdict = "NO WRITER (no service wrote %s in window)" % venue
        elif missing and key[2] < _TODAY:
            # NEVER, not "not yet" -- and the distinction is the whole point.
            #
            # `#637`, corrected 2026-09-03. The first version of this census had
            # one failure bucket, so a key that could never hydrate was reported
            # identically to one that simply had not yet. Measured: 7 of 15
            # PENDING keys were PAST GAME DATES. Nothing writes a finished date
            # again, so no service will ever open those files, so hydration can
            # never happen -- and a report that says "wait" about them is telling
            # the reader to wait for something that cannot occur. It sent me
            # chasing a refresh-worker write for hours.
            #
            # WHY EXPIRING THESE CANNOT CAUSE THE HARM THIS GATE EXISTS TO
            # PREVENT. The harm is not "data is lost", it is "a file starts empty
            # and the accumulator RE-DATES every `opened_at` to the expiry
            # moment", which is wrong data rather than absent data. That requires
            # a subsequent WRITE. A file nothing will write again cannot be
            # re-dated, so the failure mode is structurally unreachable here.
            #
            # WHAT IT DOES COST, stated because it is a real trade and not zero:
            # the Redis copy is the only copy, and expiring forfeits whatever
            # remains of its 10-day TTL. That is a decision about how much longer
            # to keep a write-only archive nobody currently reads -- a judgement
            # for a person, which is why this still does NOT return 0.
            verdict = "UNREACHABLE (past game date; %s will never write it again)" % ",".join(missing)
        elif missing:
            verdict = "PENDING (%s)" % ",".join(missing)
        else:
            verdict = "SAFE"
        verdicts[verdict.split(" ")[0]] += 1
        rows.append((verdict, key, size, ",".join(owed) or "-"))

    print("%-34s %-46s %10s  %s" % ("verdict", "key", "bytes", "expected to hydrate"))
    for verdict, key, size, owed in rows:
        print("%-34s %-46s %10d  %s" % (verdict, "%s__%s__%s" % key, size, owed))

    total = sum(keys.values())
    safe_bytes = sum(s for v, _, s, _ in rows if v == "SAFE")
    print("")
    print("  %d key(s), %.1f MB total; SAFE covers %d key(s), %.1f MB"
          % (len(keys), total / 1048576.0,
             verdicts["SAFE"], safe_bytes / 1048576.0))
    for name, count in sorted(verdicts.items()):
        print("    %-12s %d" % (name, count))

    unreachable_bytes = sum(sz for v, _, sz, _ in rows if v.startswith("UNREACHABLE"))
    if verdicts["UNREACHABLE"]:
        print("")
        print("  %d key(s) / %.1f MB are UNREACHABLE -- a PAST game date, which no"
              % (verdicts["UNREACHABLE"], unreachable_bytes / 1048576.0))
        print("  service will write again, so they can NEVER hydrate. WAITING DOES")
        print("  NOTHING FOR THEM. Expiring them cannot re-date an opening (that needs")
        print("  a later write, and there will not be one), but it DOES forfeit the")
        print("  rest of their 10-day TTL on the only remaining copy. A person decides.")

    if verdicts["SAFE"] == len(keys) and not truncated:
        print("\nEVERY key censused is SAFE. Expiry may proceed -- and it is still a")
        print("separate, explicit, destructive call that a human decides.")
        return 0
    if verdicts["PENDING"] or verdicts["UNKNOWN"] or truncated:
        print("\nNOT SAFE TO EXPIRE WHOLESALE. The 10-day TTL reclaims this at zero")
        print("risk; early expiry is only worth it if the memory is needed sooner.")
        return 2
    # Only SAFE + UNREACHABLE remain: nothing is waiting on anything, so a
    # further run cannot change the verdict. Still non-zero -- expiring the
    # UNREACHABLE set forfeits real data, which is a judgement, not a gate.
    print("\nNOTHING IS PENDING. Every key is SAFE or UNREACHABLE, so no further")
    print("waiting will change this reading.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
