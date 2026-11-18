# Findings — study S3 of the profit learning program: maker entry (2026-11-18)

Asked for by the user 2026-11-18 ~4:10 PM CST: "start study S3 on maker entry". Written by the portfolio session
(lane `portfolio-monitor`). Read-only on the fleet: the only write is a copy of log lines into the research store.
Not financial advice.

## Status: two pre-registered maker tests already exist, and neither is due a decision today

S3 asks whether posting a resting bid (earning the spread) instead of taking the ask makes the book positive. Two
tests were registered for that before any result, and S3 reads them at their own decision points rather than
registering a third:

| test | registration | decision point | where it stands 11-18 |
|---|---|---|---|
| **paper maker shadow** (resting bids on Kalshi, filled from public trade prints = model B) | `findings_2026-10-20_kalshi_maker_shadow_preregistration.md` (`023f3978`) | each cell at 200, 400, 600 B-filled orders; calendar stop 2027-01-31 | **no look yet** in any cell |
| **live maker pilot** ($5/order, $10/day, pregame post-only on live-plan positions) | `findings_2026-10-31_maker_pilot_review.md`, "Pre-registered re-judge" | 11-14 or 30 timed fills, whichever is later | **about 21 of 30 timed fills**, due about 11-24, only if fill times are saved |

Earlier context (not re-tested here):
- `findings_2026-10-19_kalshi_maker_entry_paper.md`: maker entry NO-GO overall. Fills won 5.37 pp below the close,
  because a resting bid fills when the world has moved against it.
- `findings_2026-10-24_maker_vs_taker_shadow.md`: no cell beat taker out of sample.

## Paper maker shadow (evaluation 2026-11-18 12:30Z; descriptive, NOT a look)

| cell | B placed | B filled (events) | fill rate | filled ROI [95%] | filled wins - close [95%] |
|---|---|---|---|---|---|
| soccer totals | 380 | **171** (103) | 45% | -11.9% [-28.1, +4.9] | -5.9 pp [-12.6, +1.2] |
| NCAAF segment totals | 212 | 78 (70) | 37% | -1.2% [-22.3, +20.0] | -1.6 pp [-11.6, +8.5] |
| soccer spreads | 90 | 40 (37) | 44% | +23.3% [-10.1, +54.3] | +12.5 pp [-1.8, +26.0] |

- Adverse selection shows in every cell: the fair at fill is 0.25-0.67 pp below the fair at place, and filled orders'
  fair drifts the wrong way to the close.
- **Projected looks** (pace 11-04 -> 11-18):
  - **soccer totals reaches 200 about 11-26/27** (+3.4 a day). Its numbers so far lean toward the registered
    futility stop. The look decides, not this table.
  - NCAAF segment totals: +2.3 a day, about 01-10 before 200.
  - **Soccer spreads: +0.5 a day, so about 77 by the 2027-01-31 calendar stop, under 200.** Its +23% will not be
    judged: under 200 at the stop, the registration calls it **INSUFFICIENT, "not shown", never "no"**.
  - For scale, soccer totals today would not be a futility stop at 95%: its ROI upper bound is +4.9% and its
    wins-minus-close upper bound is +1.2 pp. Futility needs ROI upper < 0 or wins-minus-close upper < -1 pp.
- The shadow's job is still running: the 11-18 evaluation was written at 12:30Z, and `looks.json` shows CONTINUE for
  all three cells.

## Live maker pilot

- **Ledger (11-18):**
  - 64 pilot rows: 35 filled, 28 rejected (expired at kickoff / cancelled), 1 failed;
  - 32 of the 35 fills are settled: **15 won, 17 lost**;
  - fills run about 1.4 a day.
- **The registered criterion is mechanism, not P&L:**
  - mean edge at FILL >= +1.5 pp with a 90% CI lower bound > 0;
  - **and** filled wins minus fair not below -3 pp;
  - otherwise pause.
  - The 11-14 interim (n=14): edge at fill +0.86 pp [-0.03, +1.72]. Since the 11-03 fair-move cancel: +1.30 pp
    [+0.13, +2.37] (n=7).
- **The measurement is leaking.**
  - "Edge at fill" needs the fill time. The ledger row still has none: `venue_filled_at` is on 0 of 35 fills, the
    measurement debt named on 10-31.
  - So fill times exist only in `MAKER_PILOT FILL` log lines.
  - The live-odds-worker log now rotates in **about 3.5 days** (5 x 210 MB): on 11-18 the oldest line was from 11-15.
  - Nothing was capturing those lines. The fill times for 11-02..11-09 and 11-10..11-14 are gone from disk. The
    11-14 re-judge read the 11-10..11-14 times while they still existed.
- **Saved 11-18 ~22:15Z (copy only):** every `MAKER_PILOT` line still on disk, 844 lines, including 8 FILL lines
  (11-15..11-18). Saved to `~/syndicate-prod/data/research/maker_pilot/maker_pilot_log_lines.txt`, deduplicated.
- **Also saved (11-18 ~22:30Z):**
  - the 11-14 re-judge kept its own copy of the pilot lines for 11-09..11-14 in `C:\tmp\maker_rejudge`, which is not
    backed up;
  - those lines are merged into the same file (1,592 lines, deduplicated);
  - its scripts and results (`paths5.py`, `paths5.json`) are copied to `research/maker_pilot/rejudge_2026-11-14/`.
- **Timed fills now: 7 (October, from the 10-31 review) + 14 distinct filled orders with a FILL line 11-10..11-18
  = about 21.** All 14 say `filled_as=maker`, so the pilot's stop rule (any TAKER fill) has not fired.
  - About 9 more are needed, so the re-judge is about 11-24, but only if each fill's line is saved within ~3 days.
  - Durable fix: write `venue_filled_at` on the ledger row. That is a ledger-only change, not a betting change; it
    needs its own lane and a live-odds-worker restart.
  - **Bridge, set up 11-18 (user: "Yes, set it up"):** the Windows task `SyndicateMakerPilotLines` runs daily at
    7:30 AM local.
    - It runs `C:\SyndicateProd\maker_pilot_preserve\preserve_maker_pilot_lines.sh` (source:
      `scripts/preserve_maker_pilot_lines.sh`).
    - Copy only: it merges every `MAKER_PILOT` line into the research file, deduplicated, and excludes the
      self-matching `ALL_PROCESS_MEMORY` lines.
    - **Exit 3 = a FILL with `filled_as=TAKER`** (the pilot's stop rule); **exit 4 = a possible gap**.
    - Log: `~/syndicate-prod/logs/maker_pilot_preserve.log`.
    - Tested on temporary logs: copy, re-run, gap, taker and no-logs cases.
    - First run 22:57Z: result 0, 1,592 lines, 14 distinct fills, 0 TAKER.

## What this means for the program

- No maker challenger is ready for the 11-24 window. The earliest registered decisions are the pilot's re-judge
  (about 11-24, if fill times are kept) and the shadow's soccer-totals 200 look (about 11-26/27). Both fall after
  11-24, so the next window that could act on either is **12-08**.
- The pilot's re-judge either keeps the $10/day canary or pauses it. A pass is not a scale-up. Any larger maker
  route would be a new lane, a new registration and the user's decision.
