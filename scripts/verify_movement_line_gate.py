"""Verify the `#446` movement line gate against the SERVED board.

RUN IT:   py -3 scripts/verify_movement_line_gate.py

Standalone and read-only -- it reads `/api/board/layer2-shortlist` and
`/intelligence`, touches no credentials and changes nothing. Safe to schedule.

WHY IT LIVES IN THE REPO. It was written in a session scratchpad, and a
scheduled re-run pointed at that path would have failed silently tomorrow
morning -- the directory is session-scoped. A verification that cannot be re-run
is not a verification.

WHY THE GUARD EXISTS. The first version of this printed:

    tracked 2 · moved-line 0
    PRICE DELTA LEAKED ACROSS A MOVED LINE : 0   (was 19 -- must be 0)
    VERDICT: PASS

There were ZERO moved-line rows. The check passed because it had nothing to
test, on a 12-card end-of-night board. `PASS if not leaked and not bad_steam` is
trivially true when the population is empty, so the verdict said "the gate
works" when it meant "the gate was never exercised".

That is the third instrument of mine tonight to map a benign or unknown state
onto the wrong branch (the others: a 502 read as a clear deploy gate, and a
binary content check that cried wolf at an innocent deploy). It is also the
exact rule I had written into `learnings.md` four hours earlier -- never record a
detector's zero as a pass when the data gave it no chance to fire.

SO: every assertion below declares the minimum denominator it needs. Under that,
the verdict is INCONCLUSIVE and says what it was still waiting for. A verifier
that cannot fail cannot pass.
"""
import json
import urllib.request
from datetime import datetime, timezone

API = "https://syndicate-an21.onrender.com"

# Minimum denominators. Chosen from the population the DEFECT was found in
# (19 moved-line rows of 23 tracked): 3 is enough that a pass is not one lucky
# row, and low enough to be reachable on a thin slate.
MIN_MOVED_LINE_ROWS = 3      # to assert the leak check at all
MIN_TRACKED_ROWS = 8         # to call a coverage number meaningful
PRE_FIX = {"leaked": 19, "false_steam": 1, "coverage": 31}


def now():
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def read_board():
    sl = json.load(urllib.request.urlopen(f"{API}/api/board/layer2-shortlist?sport=all&limit=2000", timeout=180))
    html = urllib.request.urlopen(f"{API}/intelligence", timeout=180).read().decode("utf-8", "replace")
    obj, _ = json.JSONDecoder().raw_decode(html[html.index('{"boardContract"'):])
    return sl, obj["boardContract"]["cards"]


def assess(sl, cards):
    tracked = [c for c in cards if c.get("movement_state") == "tracked"]
    moved = [c for c in tracked if c.get("movement_open_line") != c.get("line")]
    same = [c for c in tracked if c.get("movement_open_line") == c.get("line")]
    steam = [c for c in cards if c.get("steam")]
    leaked = [c for c in moved if c.get("movement_price_delta") is not None]
    bad_steam = [c for c in steam if c.get("movement_open_line") != c.get("line")]

    lines = []
    lines.append(f"artifact            {sl.get('written_at')}   cards {len(cards)}")
    lines.append(f"tracked {len(tracked)}   same-line {len(same)}   MOVED-LINE {len(moved)}")
    lines.append(f"leaked price delta across a moved line : {len(leaked)}   (pre-fix {PRE_FIX['leaked']})")
    lines.append(f"steam {len(steam)}   of which on a moved line : {len(bad_steam)}   (pre-fix {PRE_FIX['false_steam']})")
    elig, matched = sl.get("movement_eligible_rows"), sl.get("movement_rows_matched")
    if isinstance(elig, int) and elig > 0 and isinstance(matched, int):
        lines.append(f"coverage {100.0*matched/elig:.0f}%  ({matched}/{elig})   baseline {PRE_FIX['coverage']}%")
    else:
        lines.append(f"coverage UNREADABLE (eligible={elig!r} matched={matched!r})")

    # --- the guard: every claim states the denominator it needs ---
    blockers = []
    if len(moved) < MIN_MOVED_LINE_ROWS:
        blockers.append(
            f"only {len(moved)} moved-line rows (need >={MIN_MOVED_LINE_ROWS}); "
            f"the leak check and the false-steam check have NOTHING TO TEST"
        )
    if len(tracked) < MIN_TRACKED_ROWS:
        blockers.append(
            f"only {len(tracked)} tracked rows (need >={MIN_TRACKED_ROWS}); "
            f"coverage is not a meaningful ratio"
        )

    if blockers:
        verdict = "INCONCLUSIVE"
        for b in blockers:
            lines.append(f"  BLOCKER: {b}")
        lines.append("  The gate is NOT shown to work and NOT shown to be broken.")
        lines.append("  Re-run on a slate with live line movement -- a zero here means nothing.")
    elif leaked or bad_steam:
        verdict = "FAIL"
        lines.append(f"  {len(leaked)} leaked deltas / {len(bad_steam)} false steam on a population that could test it")
    else:
        verdict = "PASS"
        lines.append(f"  {len(moved)} moved-line rows present and NONE leaked a price delta -- the gate fired")
    return verdict, lines, len(moved)


if __name__ == "__main__":
    # ONE-SHOT for scheduled use. The interactive version polled for 3 hours,
    # which is right when you are watching a deploy land and wrong for a cron
    # job -- a scheduled task that sits for 3h holds a slot and reports nothing
    # until it is far too late to act on.
    try:
        sl, cards = read_board()
    except Exception as exc:
        print(f"[{now()}] board unreadable: {type(exc).__name__} -- nothing measured", flush=True)
        raise SystemExit(1)

    verdict, lines, moved_n = assess(sl, cards)
    print(f"=== LINE GATE VERIFICATION ({verdict}) ===", flush=True)
    for line in lines:
        print("  " + line, flush=True)
    print("=== END ===", flush=True)

    # Exit code carries the verdict so a scheduler can act on it:
    #   0 PASS · 1 FAIL · 2 INCONCLUSIVE (not a failure -- nothing to test yet)
    raise SystemExit({"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[verdict])
