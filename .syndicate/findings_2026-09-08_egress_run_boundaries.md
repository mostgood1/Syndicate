# The 2026-09-08 egress run: nothing in any log started it, and nothing in any log stopped it

`[2026-09-08, session 2029c069, scheduled task `bandwidth-spike-tripwire`]`
Subject: `state_worker.md [render-egress-spikes]`. **Evidence only — no mechanism claimed.**

## The run

Web metered, hourly, buckets converted to the real hour they cover (they are
RIGHT-labelled). Local times are UTC-5.

| covers (UTC) | local | metered MB |
|---|---|---|
| 02:00-13:00 | 21:00-08:00 | 27.5 - 46.1 each (baseline) |
| 13:00-14:00 | 08:00-09:00 | 74.3 |
| 14:00-15:00 | 09:00-10:00 | **420.6** |
| 15:00-16:00 | 10:00-11:00 | **2470.7** |
| 16:00-17:00 | 11:00-12:00 | **2962.7** |
| 17:00-18:00 | 12:00-13:00 | **2817.1** |
| 18:00-19:00 | 13:00-14:00 | **2904.8** |
| 19:00-20:00 | 14:00-15:00 | 220.7 |
| 20:00-21:00 | 15:00-16:00 | 77.6 (at age 66m, still creeping) |

~11.8 GB in six hours against a baseline that would have been ~170 MB.
`refresh-worker` (6.0-13.7 MB/h) and `live-odds-worker` (13.8-17.0 MB/h) were
FLAT across the whole window, including both boundaries. Web-only, as in
September's earlier run.

## Every logged flow is flat across a 13.2x drop

Captures in `reports/bandwidth_spikes/web_20260908T{14,15,16,17,18,19,20}0000Z.json`.

| covers | metered | edge MB | app served MB | publish-in MB | edge `export` MB |
|---|---|---|---|---|---|
| 13:00-14:00 | 74.3 | 24.7 | 81.0 | 219.7 | 1.4 |
| 14:00-15:00 | 420.6 | 59.3 | 137.8 | 234.8 | 2.9 |
| 15:00-16:00 | 2470.7 | 101.4 | 146.7 | 166.4 | 20.6 |
| 16:00-17:00 | 2962.7 | 275.0 | 317.8 | 230.2 | 223.9 |
| 17:00-18:00 | 2817.1 | 275.4 | 343.7 | 453.0 | 265.6 |
| 18:00-19:00 | 2904.8 | 245.1 | 339.6 | 417.6 | 256.3 |
| 19:00-20:00 | **220.7** | **253.3** | **308.8** | **439.2** | **250.3** |

**The last two rows are the result.** Between two ADJACENT hours the meter falls
**13.2x** while edge is **+3%**, app served **-9%**, publish-in **+5%**, and the
dominant endpoint's own volume is **-2%**. Nothing that stopped is in any log.

The rise is the same shape in reverse: `14:00-15:00 -> 15:00-16:00` the meter goes
**5.9x** (420.6 -> 2470.7) while edge goes **1.7x**, app **1.06x**, and publish-in
goes **DOWN** (234.8 -> 166.4).

Both boundaries land on the hour. The rise begins at 14:00Z and the collapse at
19:00Z; the `19:00-20:00` total of 220.7 MB is too low for the run to have
continued into that hour at all, so the stop is at or within minutes of 19:00Z.

## ELIMINATED: the export pollers, which is what the first captures looked like

Two MLB pollers dominate the edge log in the spike hours, ~55 requests/hour each,
and they are what makes a capture read as if a script were the driver:

    mlb_source/**/daily_summary_*.json&limit=40      n=55   mean 2430 KB   136.8 MB/h
    mlb_source/data/book_grid/book_grid_*.json&limit=6  n=55   mean 1868 KB   105.2 MB/h

In the quiet 13:00-14:00Z hour neither exists; edge `export` is **116 requests /
1.43 MB** (~12 KB each, two soccer `live_gameline_ledger` pollers only). So the
per-request size rose ~64x when they appeared, which is a real change and is NOT
the driver:

- they appear in `15:00-16:00Z` at only 20.6 MB, an hour AFTER the meter had
  already risen 5.7x; and
- **they run at FULL RATE straight through the stop** — 336 requests / 250.3 MB in
  `19:00-20:00Z` against 338 / 265.6 MB in `17:00-18:00Z`, an hour metered 12.8x
  higher.

They are the largest logged flow and they are anti-correlated with the meter at
both boundaries. Do not re-propose them without new evidence.

## Deploys: co-occurrence at the start, ruled out at the stop

Web deploy `09f6ab86` finished **14:02:20Z**, within ~2 min of the rise. That is
co-occurrence, and deploys are already eliminated as a bandwidth mechanism
(`[render-egress-spikes]`). At the stop there is nothing: the only deploy in
`19:00-20:00Z` is `b4f4c790`, finished **19:49:04Z** — 49 minutes into an hour
that only metered 220.7 MB in total, so it cannot have ended a 2,900 MB/h regime.

## What this adds

The open contradiction now has its **cleanest discriminating pair**: two adjacent
hours, all four logged quantities within 10%, metered 13.2x apart. Previous pairs
were hours or days apart and differed in workload; these do not. It sharpens the
existing either/or rather than resolving it — **either the meter counts something
none of these logs contain, or the log is materially incomplete in exactly the
high-volume hours** — and it removes the most plausible logged candidate.

**Not checked, and the next thing I would check:** web's own OUTBOUND fetches, the
one flow in neither request log. The `HTTP_COMPRESSION ... BILLED_wire` counter the
earlier lane used **is not being emitted on the current deploy** (0 lines in the
`18:00-19:00Z` app log), so it cannot be read from the log as it stands. What IS
there: 124 `request_path_guard` "compute in request path" warnings for
`wnba_has_games_for_date_espn_fetch` / `wnba_public_scoreboard_live_state_fetch`
in that hour — web making outbound ESPN calls from the request path. That count is
from a page-capped scan (6,000 of 8,476 lines) and is **not** a rate; it is a
pointer to an instrument worth restoring, not a finding.

**What would falsify a "web outbound" hypothesis:** restore the billed-wire
counter and find its per-hour total flat across the 19:00Z boundary too.
