"""Did WNBA settlement actually start working? Refuses to answer when it can't.

WHY THIS IS A SCRIPT AND NOT A NOTE. The gate for this lane lived in
`.syndicate/deploys.md` as four prose steps. A list in a ledger still depends on
the next reader finding it, reading it in order, and noticing which step is
unreadable -- and on 2026-09-01 this lane got the SAME question wrong three
separate ways in one evening, each time from a reading that looked fine:

  * from a file's SIZE     (45.8MB "captured" -- 0 exchange rows in it)
  * from a sport-blind counter (`venue_priced` carries no `sport=`)
  * nearly from an EMPTY POPULATION (no WNBA games 08-31..09-16)

None of those three preconditions announces itself. Care does not enumerate
preconditions; a checklist does, and an executable checklist does it for the
next reader too.

THREE OUTCOMES, not two -- following `scripts/verify_wnba_totals_pricing.py`,
which exits 3 rather than 0 for exactly this reason:

    0  PASS        settlement produced graded rows
    1  FAIL        every precondition held and it still produced none -- a defect
    3  UNREADABLE  a precondition is missing; the question cannot be asked yet

**Exit 3 is not a failure and must never be reported as one.** It is the answer
"you cannot know yet", which is the answer that was missing when two watchers
burned ~35 minutes on a change that was structurally impossible.

Usage:
    py -3 scripts/verify_wnba_settlement_gate.py --date 2026-08-30
    py -3 scripts/verify_wnba_settlement_gate.py            # newest played date
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASE = os.environ.get("SYNDICATE_BASE_URL", "https://syndicate-an21.onrender.com")
# The commit that added the cross-disk publish. Without it the producer writes to
# refresh-worker's disk and the web-facing endpoint reads web's -- so step 3 is
# STRUCTURALLY unreachable and a zero there says nothing about settlement.
PUBLISH_FIX_COMMIT = "1da0a328"

PASS, FAIL, UNREADABLE = 0, 1, 3


def _get(path: str, token: str | None = None, timeout: int = 120) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    request = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _admin_token() -> str | None:
    token = (os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def _say(verdict: str, reason: str, detail: dict) -> None:
    print(f"{verdict}: {reason}")
    for key, value in detail.items():
        print(f"    {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", help="slate to check, YYYY-MM-DD (default: newest played)")
    args = parser.parse_args(argv)
    token = _admin_token()

    date_str = args.date
    if not date_str:
        try:
            dates = _get("/wnba/api/archive?date=2026-08-30").get("available_dates") or []
            date_str = dates[-1] if dates else None
        except Exception as exc:
            _say("UNREADABLE", "could not resolve a target date", {"error": f"{type(exc).__name__}: {exc}"})
            return UNREADABLE
    if not date_str:
        _say("UNREADABLE", "no WNBA dates available", {})
        return UNREADABLE

    # ---------------------------------------------------------- precondition 1
    # The publish fix must be LIVE on refresh-worker. Read by CONTENT where
    # possible; the deployed-commit read is what this lane had to learn to do.
    try:
        version = _get("/api/ops/version", token)
        live_commit = str(version.get("commit") or version.get("sha") or "")[:8]
    except Exception:
        live_commit = ""

    # ---------------------------------------------------------- precondition 2
    # The slate must contain completed games. During the FIBA World Cup break
    # (no WNBA games 2026-08-31..2026-09-16) every date in that window settles
    # nothing, and a zero there is not a defect.
    # THE ENDPOINT MATTERS AND THE FIRST VERSION OF THIS GATE HAD IT WRONG.
    # `/wnba/api/live-lens-accuracy` is the DAILY payload (`days[]`, a
    # hit_rate/wins/losses summary) and carries no `overall.props.n_settled` at
    # all -- so reading it returned settled=0 on a system that was settling 54
    # rows, i.e. my own gate produced the false NEGATIVE it exists to prevent.
    # `/wnba/api/live-player-props-lens-accuracy` is the settlement payload.
    try:
        signals = _get(f"/wnba/api/live-player-props-lens-accuracy?start={date_str}&end={date_str}")
    except Exception as exc:
        _say("UNREADABLE", "live-lens-accuracy did not answer",
             {"date": date_str, "error": f"{type(exc).__name__}: {exc}"})
        return UNREADABLE

    # The settlement payload puts per-day meta under `debug.days`, not `days`
    # -- `days` is the DAILY payload's shape. Reading the wrong one made this
    # gate report "no signals" against a payload carrying 102 of them.
    days = (signals.get("debug") or {}).get("days") or signals.get("days") or [{}]
    day = days[0] if days else {}
    signal_meta = day.get("signals") or {}
    raw_rows = signal_meta.get("raw") or 0
    if not signal_meta.get("exists") or not raw_rows:
        _say("UNREADABLE", "no live-lens signals for this date -- nothing to settle",
             {"date": date_str, "signals_exists": signal_meta.get("exists"),
              "raw": raw_rows, "path": signal_meta.get("path"),
              "note": "an off day or the World Cup break reads exactly like this"})
        return UNREADABLE

    # ---------------------------------------------------------- precondition 3
    # The recon artifacts must have CROSSED to web. Counted by asking web for
    # them -- not by trusting that the producer logged `status: ok`, which is a
    # statement about the worker's disk.
    recon_count = 0
    recon_error = None
    if token:
        try:
            pattern = f"wnba_source/**/recon_*_{date_str}.csv"
            listing = _get("/api/ops/artifacts/export?names_only=1&pattern="
                           + urllib.parse.quote(pattern), token)
            recon_count = int(listing.get("count") or 0)
        except Exception as exc:
            recon_error = f"{type(exc).__name__}: {exc}"
    if recon_count == 0:
        _say("UNREADABLE", "recon artifacts have not reached WEB -- settlement cannot join",
             {"date": date_str,
              "recon_files_on_web": recon_count,
              "error": recon_error or "-",
              "live_web_commit": live_commit or "unknown",
              "publish_fix_commit": PUBLISH_FIX_COMMIT,
              "note": ("the producer writes to refresh-worker's disk; this endpoint reads web's. "
                       "Allowlisting makes a path eligible to cross, it does not carry it.")})
        return UNREADABLE

    # ------------------------------------------------------------- the question
    # Read the authoritative aggregate, not a truncated view: `overall` is the
    # whole graded population, `per_day` is a per-date summary. A top-N slice
    # would answer a narrower question than the one asked.
    overall = (signals.get("overall") or {}).get("props") or {}
    settled = int(overall.get("n_settled") or 0)
    detail = {
        "date": date_str,
        "signals_raw": raw_rows,
        "recon_files_on_web": recon_count,
        "n_settled": settled,
        "win_rate": overall.get("win_rate"),
        "leakage_note": signals.get("leakage_note") or overall.get("leakage_note") or "-",
    }
    if settled > 0:
        _say("PASS", "settlement produced graded rows", detail)
        if not (signals.get("leakage_note") or overall.get("leakage_note")):
            print("    WARNING: no leakage_note on a settled payload -- check the "
                  "per-period split before quoting any hit rate as performance.")
        return PASS

    _say("FAIL", "signals present and recon on web, and still zero graded rows", detail)
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
