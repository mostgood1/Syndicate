"""Watch the rest of the 2026-08-29 NCAAF slate for ESPN/board disagreement.

A BRIEF DISAGREEMENT IS A RACE, NOT A DEFECT, and this watcher exists in the
shape it does because I measured one. At 19:31:16Z the board read `final=1`
while ESPN still read `post=0`; 26 seconds later ESPN's own status had gone
`End of 4th Quarter` (state: in) -> `STATUS_FINAL` (state: post). The board's
ESPN fetch was simply fresher than mine. Reporting that instant would have
raised a false alarm on a working system.

So a mismatch must PERSIST across `MISMATCH_POLLS` consecutive reads (~8 min,
far past both the 45s chip TTL and the observed race) before it is reported.

Coverage rule: this speaks on the failure path, not only on progress. Silence
must mean "ESPN and the board agree", never "the watcher stopped looking" --
hence the degraded-read notice and the explicit agreement line on every change.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football"
        "/scoreboard?dates=20260829&groups=80&limit=200")
LENS = "https://syndicate-an21.onrender.com/ncaaf/api/live-lens"

POLL_SECONDS = 120
MISMATCH_POLLS = 4          # ~8 min sustained before it is a finding
SETTLE_AFTER_FINAL = 3      # confirm the all-final state before declaring done


def emit(line):
    print(line, flush=True)


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def read_espn():
    d = get(ESPN)
    ev = d.get("events") or []
    ins, post, detail = [], [], []
    for e in ev:
        try:
            state = e["status"]["type"]["state"]
        except Exception:
            continue
        label = f"{e.get('shortName')} {e['status']['type'].get('detail','')}"
        if state == "in":
            ins.append(label)
        elif state == "post":
            post.append(label)
        detail.append((e.get("shortName"), state))
    return len(ev), ins, post, detail


def read_board():
    d = get(LENS, timeout=75)
    hs = {r["label"]: r["value"] for r in (d.get("header_stats") or []) if isinstance(r, dict)}
    live_cards, final_cards = [], []
    for c in (d.get("rank_cards") or []):
        eye = str(c.get("eyebrow") or "")
        if eye == "Final":
            final_cards.append(str(c.get("title")))
        elif any(t in eye for t in ("Q1", "Q2", "Q3", "Q4", "OT", "Half")):
            live_cards.append(f"{c.get('title')} [{eye}]")
    return int(hs.get("Live") or 0), int(hs.get("Final") or 0), live_cards, final_cards


def main():
    last = None
    mismatch = 0
    errors = 0
    all_final = 0
    emit("watching the rest of the 08-29 NCAAF slate; a mismatch must persist "
         f"{MISMATCH_POLLS} polls (~{MISMATCH_POLLS * POLL_SECONDS // 60} min) to be reported")

    while True:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
        try:
            total, ins, post, _ = read_espn()
            b_live, b_final, live_cards, final_cards = read_board()
            errors = 0
        except Exception as exc:
            errors += 1
            if errors in (5, 15):
                emit(f"{stamp}  WATCH DEGRADED: {errors} consecutive read failures "
                     f"({type(exc).__name__}: {exc}) -- silence is NOT agreement right now")
            time.sleep(POLL_SECONDS)
            continue

        agree = (len(ins) == b_live) and (len(post) == b_final)
        sig = (len(ins), len(post), b_live, b_final)

        if sig != last:
            mark = "agree" if agree else "DISAGREE (settling)"
            emit(f"{stamp}  ESPN in={len(ins)} post={len(post)}/{total} | "
                 f"BOARD live={b_live} final={b_final}  -> {mark}"
                 + (f" | {ins[0]}" if ins else ""))
            last = sig

        if agree:
            mismatch = 0
            if len(post) == total and total > 0:
                all_final += 1
                if all_final >= SETTLE_AFTER_FINAL:
                    emit(f"{stamp}  SLATE COMPLETE -- all {total} games final, board agrees "
                         f"(final={b_final}). No mismatch was sustained at any point.")
                    return 0
            else:
                all_final = 0
        else:
            all_final = 0
            mismatch += 1
            if mismatch == MISMATCH_POLLS:
                emit(f"{stamp}  MISMATCH SUSTAINED {mismatch} polls "
                     f"(~{mismatch * POLL_SECONDS // 60} min) -- this is NOT a race")
                emit(f"          ESPN  in={len(ins)} post={len(post)}: {ins + post}")
                emit(f"          BOARD live={b_live} final={b_final}: {live_cards + final_cards}")
                mismatch = 0  # report once per sustained episode, keep watching

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
