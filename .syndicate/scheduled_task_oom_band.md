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

**DID THE TRANSIENT MOVE?** Three fixes are live — odds-shard duplicate, ledger
streaming, three-loads-to-one. All are exercised in production and **none has
been shown to change the ~2GB excursion.**

Their SHAs were **rebased** on 2026-08-16, which renamed all three while
changing nothing:

| change | original SHA | live SHA |
|---|---|---|
| odds-shard duplicate parse | `51ae7218` | `164f6e80` |
| ledger streaming | `21f8a165` | `1409e96f` |
| three-loads-to-one | `aa190d58` | `d72d670c` |

Verified by `git patch-id --stable`, not by subject line. They are linear
(`164f6e80` → `1409e96f` → `d72d670c`), so one ancestry check on `d72d670c`
covers all three.

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

**Check containment, not SHA equality.** The earlier version of this note said
the comparison was invalid if live was no longer `d72d670c`. That test is wrong
and fired falsely within a day: refresh-worker moved to `97491161` (finished
2026-08-16T15:45:50Z) purely because the branch was rebased plus one unrelated
NFL play-by-play fix (`#441`). All three fixes were still running. A SHA
equality test cannot tell a revert from a rename.

The right check:

```bash
git merge-base --is-ancestor d72d670c <live-sha>
```

Present → the fixes are in what is running, regardless of the tip SHA. Absent →
still not proof of a revert; re-check by content with `git patch-id --stable`
across `git log <live-sha>` before saying anything, because the next rebase will
rename `d72d670c` too.

Live at last check: **`97491161`**, 2026-08-16T15:45:50Z. That value goes stale
in minutes — read it, don't quote it.
