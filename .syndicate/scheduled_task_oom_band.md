# Scheduled: OOM live-slate band measurement — 2026-08-16/17

Three ONE-TIME tasks (they auto-disable after firing). They **measure only** and
are told explicitly not to deploy.

| task | fires (local CDT) | fires (UTC) | purpose |
|---|---|---|---|
| `preband-refresh-worker-sha-check` | 2026-08-16 16:45 | 21:45Z | 15 min before the band: is the service in a state worth measuring |
| `oom-band-early-read` | 2026-08-16 20:00 | 01:00Z | ~3h into the band; surfaces a kill during the evening rather than at dawn |
| `oom-band-full-report` | 2026-08-17 00:15 | 05:15Z | retrospective pass over the whole 22:00Z-05:00Z band |

**Why a pre-band check at all.** The band's value depends on the worker being
untouched: a deploy reboots it, re-runs hydration cold, fragments the segments,
and resets the memory ratchet that takes hours to re-form. refresh-worker took
**ten deploys on 2026-08-16** (01:29Z, 01:55Z, 02:23Z, 04:23Z, 04:57Z, 05:03Z,
05:29Z, 05:34Z, 06:01Z, 15:45Z), several by the operator and two `envUpdated`.
Assuming quiet was not defensible, so the state is read at band open instead.
It returns **BAND CLEAN** or **BAND COMPROMISED** — the latter naming when, who,
and what uptime the band actually opens with, so the later two tasks are read
against a known process rather than an assumed one.

Fifteen minutes is enough lead to KNOW, not to ACT — the band opens at 22:00Z
either way. That is the intended tradeoff: the check buys interpretation, not
prevention. It also **notifies nobody**: it was created from a scheduled-task
run session, which cannot subscribe another task to completion notifications,
so its output lands in its own session and has to be read there.

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

## Recoverability of these three tasks

The live tasks live under `~/.claude/scheduled-tasks/<id>/SKILL.md`, which is
**outside this repo and not under version control on any machine**. This file
records the reasoning for all three but embeds the full prompt of only
`preband-refresh-worker-sha-check` (below). **`oom-band-early-read` and
`oom-band-full-report` are NOT recoverable from this file** — if those task
directories are lost, their prompts are gone. Noted rather than fixed, because
both fire tonight and auto-disable; embed them here if the pattern is ever
reused.

### Full prompt — `preband-refresh-worker-sha-check` (one-time, 2026-08-16T21:45:00Z)

````text
Pre-band state check on `refresh-worker`, 15 minutes before the OOM live-slate band opens at 2026-08-16T22:00:00Z. Self-contained — you have no memory of the session that created this.

WORKING DIR: C:\Users\tempadmin\OneDrive\Coding\Syndicate

WHY THIS EXISTS. Two measurement tasks fire tonight (`oom-band-early-read` at 01:00Z, `oom-band-full-report` at 05:15Z) and both test whether three shipped fixes moved a ~2 GB transient that OOM-kills this 4 Gi service. A deploy before or during the band reboots the worker, re-runs hydration cold, and fragments the segments — so the band's value depends on the service being untouched. As of 2026-08-16T16:29Z it was live on `97491161` (deployed 15:45:50Z) with nothing since, but refresh-worker took TEN deploys that day. This run establishes the state at band open so tonight's numbers rest on a known baseline instead of an assumption.

READ-ONLY. Deploy nothing, change no config, edit no file, open or close no lane.

STEP 1 — live SHA on refresh-worker. Read it, do not quote a remembered value:

```bash
py -3 -c "import sys,json,urllib.request;sys.path.insert(0,'scripts');import render_deploy as rd;k=rd._load_api_key();sid=rd.SERVICE_IDS['refresh-worker'];req=urllib.request.Request(f'https://api.render.com/v1/services/{sid}/deploys?limit=20',headers={'Authorization':f'Bearer {k}'});rows=json.loads(urllib.request.urlopen(req,timeout=60).read().decode());d=next((r.get('deploy',r) for r in rows if (r.get('deploy',r)).get('status')=='live'),None);print(json.dumps({'sha':((d or {}).get('commit') or {}).get('id','')[:8],'finishedAt':(d or {}).get('finishedAt'),'trigger':(d or {}).get('trigger')},indent=1))"
```

If that prints nothing or errors, say **the reader failed** and stop — a failed read is NOT a clean result.

STEP 2 — are the fixes still in what is running? Check CONTAINMENT, not SHA equality. This branch gets rebased, which renames every SHA while changing nothing; on 2026-08-16 an equality test made three live fixes look reverted:

```bash
git fetch origin --quiet; git merge-base --is-ancestor d72d670c <live-sha> && echo "FIXES PRESENT" || echo "INVESTIGATE"
```

`d72d670c` is the newest of the three fixes and they are linear (`164f6e80` -> `1409e96f` -> `d72d670c`), so that single check covers all three. If it fails, do NOT report a revert — re-check by content first (`git show <sha> | git patch-id --stable`, compared across `git log <live-sha>`), because the next rebase renames `d72d670c` too. Only genuinely absent patch-ids mean a revert.

STEP 3 — deploys and kills since the last known state:

```bash
py -3 scripts/render_events.py --service refresh-worker --since 2026-08-16T15:45:50Z
```

Kills come from the EVENTS API only. Never conclude "no kills" from a log search — a killed process emits no log line, and this repo carries a retracted "0 kills" claim that came from a log grep.

STEP 4 — report in under 12 lines:
- live SHA, its `finishedAt`, and whether it differs from `97491161`
- FIXES PRESENT or INVESTIGATE (and if INVESTIGATE, the patch-id result — never a bare revert claim)
- deploy count since 15:45:50Z, with local timestamps and who triggered each
- any `server_failed` events, classified (`oomKilled` / `evicted` / `unhealthy` / `earlyExit` — these have different causes and must not be flattened)
- **uptime at 22:00Z**, computed from the most recent deploy's `finishedAt`

VERDICT, one line, exactly one of:
- **BAND CLEAN** — no deploy since 15:45:50Z, fixes present, worker warm. Tonight's measurement rests on a single uninterrupted process.
- **BAND COMPROMISED** — a deploy landed. Say when, by whom, and what uptime the band will actually open with. A short warm-up means the memory ratchet has not re-formed and the comparison against the recorded night baselines (amplitude 1,950-2,235 MB; min inactive_file 26.3/42.2 MB in windows that killed vs 164-240 MB in windows that survived) is weaker — say that plainly rather than letting the later tasks average through it.

Report local time (America/Chicago) alongside UTC. A wrong clock has produced a wrong recommendation in this repo before.
````
