"""Close the two open NFL deploy obligations from the 2026-08-13 session.

Run AFTER the daily NFL season-projection autorun. Both obligations are settled
by that one event:

    111a5000  LAR/WSH pbp team-code aliases
    c7cff28c  writer guard (a run with no play-by-play refuses to write)

TIMING, AND THE MISTAKE THIS HEADER EXISTS TO PREVENT. The autorun fires at
**21:00Z = 16:00 CDT**, not 21:00 CDT. The ledger said "~21:00 CDT" in seven
places and every one was a UTC timestamp reported as local -- a five-hour error
that would have armed a watcher after the event. Render logs are UTC; this
repo's ledger is CDT. Convert once, at the point of writing.

WHAT EACH OBLIGATION NEEDS, and why the checks are shaped this way:

  111a5000 -- POSITIVE emission. Two clubs (WSH, LAR) whose nflverse
    abbreviations did not resolve rated `neutral_no_data` while every other
    club read `prior_season_fallback`. After the fix they must read
    `prior_season_fallback` too. This is directly observable in the artifact's
    own `rating_source`, so it needs no log access.

  c7cff28c -- an ABSENCE, and absence is the weak kind of evidence, so it is
    reported as such. The guard refuses only when a run has NO play-by-play.
    The worker demonstrably CAN see pbp_2025.csv (measured 2026-08-13: the
    21:02:06Z run wrote an artifact with a real rating on 16/16 games), so the
    guard is EXPECTED to stay silent and silence proves only that it did not
    misfire. The real check is therefore: did the autorun COMPLETE and write a
    healthy artifact? A guard that wrongly refused would show up as a missing
    or stale artifact, not as a log line.

Every log query carries a positive control. A failed read renders as a result
in this repo -- five instances in one session -- so a zero is only meaningful
beside a non-zero from the same instrument.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFRESH_WORKER = "srv-d91dpertqb8s73co8ls0"
BASE = "https://syndicate-an21.onrender.com"
CDT = timezone(timedelta(hours=-5))

# The two clubs the alias fix targets. `rating_source` is
# `...[<home>/<away>]`, so a game is listed here by the side the club plays.
ALIAS_CLUBS = ("WSH", "LAR")


def _env(name: str) -> str | None:
    path = os.path.join(REPO, ".env")
    try:
        for line in open(path, encoding="utf-8"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _both(dt: datetime) -> str:
    return f"{dt:%Y-%m-%d %H:%M}Z ({dt.astimezone(CDT):%H:%M} CDT)"


def main() -> int:
    key = _env("RENDER_API_KEY")
    if not key:
        print("RENDER_API_KEY not readable -- cannot query logs. ABORT (not a pass).")
        return 2
    headers = {"Authorization": f"Bearer {key}"}
    with urllib.request.urlopen(urllib.request.Request("https://api.render.com/v1/owners", headers=headers), timeout=60) as resp:
        owner = json.loads(resp.read().decode())[0]["owner"]["id"]

    now = datetime.now(timezone.utc)
    print(f"now {_both(now)}")
    print()

    def logs(text: str, hours: float, limit: int = 50):
        url = "https://api.render.com/v1/logs?" + urllib.parse.urlencode({
            "ownerId": owner, "resource": REFRESH_WORKER, "text": text,
            "startTime": (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": str(limit), "direction": "backward",
        })
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as resp:
                return (json.loads(resp.read().decode()) or {}).get("logs") or [], None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    # ---- control ---------------------------------------------------------
    ctl, err = logs("refresh_worker", 6, limit=5)
    if err or not ctl:
        print(f"POSITIVE CONTROL FAILED ({err or '0 rows'}) -- the log query is not working.")
        print("Every zero below would be meaningless. ABORT.")
        return 2
    print(f"positive control: {len(ctl)} [refresh_worker] rows in the last 6h -- queries work")
    print()

    # ---- did the autorun run? -------------------------------------------
    launches, _ = logs("SEASON_PROJECTION_LAUNCHING", 8, limit=30)
    launches = [r for r in (launches or []) if "nfl" in str(r.get("message") or "").lower()]
    print(f"[1] SEASON_PROJECTION_LAUNCHING (nfl) in last 8h: {len(launches)}")
    for row in launches:
        ts = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00").split(".")[0] + "+00:00")
        print(f"      {_both(ts)}  {str(row.get('message') or '').strip()[:110]}")

    writes, _ = logs("artifact_path=", 8, limit=30)
    writes = [r for r in (writes or []) if "nfl" in str(r.get("message") or "").lower()]
    print(f"[2] artifact_path= emissions (nfl) in last 8h: {len(writes)}")
    for row in writes:
        ts = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00").split(".")[0] + "+00:00")
        msg = str(row.get("message") or "").strip()
        on_disk = "/src/" not in msg
        print(f"      {_both(ts)}  mounted_disk={on_disk}  {msg[:110]}")

    if not launches:
        print()
        print("VERDICT: the autorun has NOT fired in this window. Nothing to close yet.")
        print("         Re-run after 21:00Z (16:00 CDT). This is NOT a failure.")
        return 1

    # ---- c7cff28c: did the guard misfire? -------------------------------
    refusals, rerr = logs("DegenerateProjectionRun", 8, limit=20)
    tb, _ = logs("Traceback", 8, limit=20)
    print()
    if rerr:
        print(f"[3] DegenerateProjectionRun: QUERY FAILED ({rerr}) -- NOT a zero")
    else:
        print(f"[3] DegenerateProjectionRun in last 8h: {len(refusals)}")
        for row in refusals[:5]:
            print(f"      {row.get('timestamp')}  {str(row.get('message') or '').strip()[:140]}")
    print(f"    Traceback in last 8h: {len(tb) if tb is not None else 'QUERY FAILED'}")

    # ---- 111a5000: the positive emission --------------------------------
    print()
    try:
        with urllib.request.urlopen(BASE + "/nfl/api/preseason/cards", timeout=90) as resp:
            cards = json.loads(resp.read().decode())
    except Exception as exc:
        print(f"[4] cards API unreadable ({exc}) -- cannot judge the alias fix. ABORT.")
        return 2

    rows = []
    for game in cards.get("games") or []:
        away = ((game.get("away") or {}).get("abbr") or "").upper()
        home = ((game.get("home") or {}).get("abbr") or "").upper()
        source = ""
        for panel in game.get("panels") or []:
            if panel.get("eyebrow") == "Game context":
                for item in panel.get("items") or []:
                    if "Projection source" in str(item):
                        m = re.search(r"\[([^\]]+)\]", str(item))
                        if m:
                            source = m.group(1)
        rows.append((away, home, source))

    both_neutral = [r for r in rows if r[2] and all(p.strip() == "neutral_no_data" for p in r[2].split("/"))]
    alias_rows = [r for r in rows if r[0] in ALIAS_CLUBS or r[1] in ALIAS_CLUBS]
    print(f"[4] artifact ratings: {len(rows)} games inspected")
    print(f"    both-sides-neutral (degenerate): {len(both_neutral)}")
    print(f"    games involving {ALIAS_CLUBS}:")
    alias_ok = True
    for away, home, source in alias_rows:
        sides = [p.strip() for p in source.split("/")] if source else []
        # rating_source is [home/away]
        bad = []
        if len(sides) == 2:
            if home in ALIAS_CLUBS and sides[0] == "neutral_no_data":
                bad.append(f"home {home}")
            if away in ALIAS_CLUBS and sides[1] == "neutral_no_data":
                bad.append(f"away {away}")
        if bad:
            alias_ok = False
        flag = "  <-- STILL neutral: " + ", ".join(bad) if bad else "  OK"
        print(f"      {away}@{home:4s} [{source}]{flag}")

    # ---- verdicts --------------------------------------------------------
    print()
    print("=" * 72)
    healthy_write = any("/src/" not in str(r.get("message") or "") for r in writes) if writes else False

    if alias_ok and alias_rows:
        print("111a5000 (LAR/WSH aliases): **CLOSED — PASS**")
        print("   Both clubs now resolve to a real rating. Positive emission, not an absence.")
    elif not alias_rows:
        print("111a5000: INDETERMINATE — no WSH/LAR game in the current week's artifact.")
        print("   Not a failure. Re-check on a week whose slate includes them.")
    else:
        print("111a5000: **FAIL** — a targeted club still rates neutral_no_data after a run.")

    print()
    if refusals is None:
        print("c7cff28c (writer guard): INDETERMINATE — the refusal query failed.")
    elif len(refusals) == 0 and healthy_write and not both_neutral:
        print("c7cff28c (writer guard): **CLOSED — PASS, as a NON-MISFIRE**")
        print("   The guard stayed silent AND the autorun wrote a healthy artifact to the")
        print("   mounted disk with 0 degenerate games. Since the worker can see the pbp,")
        print("   silence is the expected state — this proves the guard does not block a")
        print("   good run. It does NOT prove the guard would catch a bad one; that was")
        print("   proven end-to-end pre-deploy (no pbp -> exit 1, artifact byte-identical).")
    elif len(refusals) > 0:
        print("c7cff28c: **FIRED** — inspect above. Either the pbp went missing (the guard")
        print("   working as designed and NFL projections are now stale-but-honest), or it")
        print("   is misfiring. Check the pbp root before assuming the latter.")
    else:
        print("c7cff28c: INDETERMINATE — no healthy artifact write observed this window.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
