# Scheduled: OOM live-slate band measurement — 2026-08-16/17

Two ONE-TIME tasks (they auto-disable after firing). They **measure only** and
are told explicitly not to deploy.

| task | fires (local CDT) | fires (UTC) | purpose |
|---|---|---|---|
| `oom-band-early-read` | 2026-08-16 20:00 | 01:00Z | ~3h into the band; surfaces a kill during the evening rather than at dawn |
| `oom-band-full-report` | 2026-08-17 00:15 | 05:15Z | retrospective pass over the whole 22:00Z-05:00Z band |

**Why a retrospective pass rather than an all-night poller:** the Render logs API
retains the window, so one run after the band measures it densely and completely.
Polling for 7 hours would burn API calls to learn the same thing later.

## The question they answer, and only that one

**DID THE TRANSIENT MOVE?** Three fixes are live in `d72d670c` (live
2026-08-16T06:01:34Z) — `51ae7218` odds-shard duplicate, `21f8a165` ledger
streaming, `aa190d58` three-loads-to-one. All are exercised in production and
**none has been shown to change the ~2GB excursion.**

Judge against the night baselines: amplitude mean **1,950-2,235 MB**;
`min inactive_file` **26.3 / 42.2 MB** in the two windows that ended in a kill
versus **164-240 MB** in windows that survived.

**Excursions back at the old amplitude means the three shipped fixes were not
the 2GB.** That is a useful result, not a failure — it retires three candidates
and says the allocator is still unnamed.

## Why the band and not "is it up"

Kills cluster ~22:00Z-05:00Z. **The daytime lull is worthless as evidence:**
measured on the same clock window one day apart, peak anon was 2,816.7 MB
pre-fix and 2,898.5 MB post-fix with **zero excursions on both**, and the
pre-fix code once ran **17h51m clean** in daylight. Any "it's been up for N
hours" claim made outside the band should be disregarded.

## Tooling

`scripts/oom_band_report.py` (`c911d021`). Kills from the **events API** only —
a killed process emits no log line, and this repo carries a retracted "0 kills"
claim that came from a log grep. Splits the band on deploys, since each deploy
reboots the worker and re-runs hydration cold. Positive control: run against
02:00-03:00Z on 2026-08-16 it reproduces the hand-measured night exactly, both
kills, the deploy split, and `min inactive_file` 26.3 / 42.2.

## Note for whoever reads the result

If the live SHA is no longer `d72d670c`, the comparison is invalid — other
sessions redeploy this service frequently and one of them may have reverted the
fixes. Check the SHA before reading the numbers.
