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
**outside this repo and not under version control on any machine**. All three
prompts are embedded below verbatim, so the tasks can be recreated from this
file alone if those directories are lost. The bodies were inserted by script
rather than copied by hand — copying is how a mirror drifts from the thing it
mirrors — and verified byte-identical against the live files.

### Full prompt — `preband-refresh-worker-sha-check` (one-time, 2026-08-16T21:45:00Z)

````text
Pre-band state check on `refresh-worker`, 15 minutes before the OOM live-slate band opens at 2026-08-16T22:00:00Z. Self-contained — you have no memory of the session that created this.

WORKING DIR: C:\Users\tempadmin\OneDrive\Coding\Syndicate

WHY THIS EXISTS. Two measurement tasks fire tonight (`oom-band-early-read` at 01:00Z, `oom-band-full-report` at 05:15Z) and both test whether three shipped fixes moved a ~2 GB transient that OOM-kills this 4 Gi service. A deploy before or during the band reboots the worker, re-runs hydration cold, and fragments the segments — so the band's value depends on the service being untouched. As of 2026-08-16T16:29Z it was live on `97491161` (deployed 15:45:50Z) with nothing since, but refresh-worker took TEN deploys that day. This run establishes the state at band open so tonight's numbers rest on a known baseline instead of an assumption.

READ-ONLY. Deploy nothing, change no config, edit no file, open or close no lane.

STEP 0 — AM I ON TIME? Do this FIRST and report it FIRST. This task was scheduled for **2026-08-16T21:45:00Z**, 15 minutes before the band opens at 22:00Z. Scheduled tasks only run while the app is open; if it was closed, this fires on next launch instead — possibly hours or a day late. A late run that reports under a "pre-band" heading is WORSE than no reading, because the number looks like it answers a question it cannot answer.

```bash
py -3 -c "from datetime import datetime,timezone; n=datetime.now(timezone.utc); t=datetime(2026,8,16,21,45,tzinfo=timezone.utc); b=datetime(2026,8,17,5,0,tzinfo=timezone.utc); d=(n-t).total_seconds()/60; print(f'now {n:%Y-%m-%dT%H:%M:%SZ}  drift {d:+.1f} min  band_open={n>=t.replace(hour=22,minute=0)}  band_over={n>=b}')"
```

Classify the drift and say which case you are in, in your first line:

- **drift < −10 min** — **EARLY: THIS IS A MANUAL RUN, NOT THE SCHEDULED ONE.** A one-time task cannot fire ahead of its `fireAt`, so a negative drift means a human triggered this to test it. Label the whole report **TEST RUN** and do not issue a BAND verdict — the state you observe now is not the state at band open, and this output must never be mistaken for the 21:45Z reading. Reporting the live SHA, containment and event counts is still useful; presenting them as the pre-band answer is not. (Found 2026-08-16 by doing exactly this: a −264.6 min drift was classified ON TIME because the original branch bounded lateness only.)
- **−10 min ≤ drift < +10 min** — ON TIME. Proceed; the verdict means what it says.
- **+10 min to band open (22:00Z)** — LATE BUT STILL PRE-BAND. Proceed, and state the actual lead in minutes rather than implying 15.
- **at or after 22:00Z, band not over** — **NOT A PRE-BAND READING.** Say that first and plainly. The band has already opened, so "was the worker untouched going in" can no longer be answered — a deploy may have landed before you looked. Report what you find as an IN-BAND spot check, and say explicitly that the pre-band question is now unanswerable.
- **after 2026-08-17T05:00:00Z** — **THE BAND IS OVER; THIS TASK IS MOOT.** Do not report a verdict. Say the run was too late to serve its purpose, and point at `oom-band-full-report`, which measures the band retrospectively and reports the SHA it actually measured. Then stop.

Do not skip this because the drift "looks small". Report the number either way — a reader cannot tell an on-time run from a late one by its content alone, which is exactly why this step exists.

STEP 1 — live SHA on refresh-worker. Read it, do not quote a remembered value:

```bash
py -3 -c "import sys,json,urllib.request;sys.path.insert(0,'scripts');import render_deploy as rd;k=rd._load_api_key();sid=rd.SERVICE_IDS['refresh-worker'];req=urllib.request.Request(f'https://api.render.com/v1/services/{sid}/deploys?limit=20',headers={'Authorization':f'Bearer {k}'});rows=json.loads(urllib.request.urlopen(req,timeout=60).read().decode());d=next((r.get('deploy',r) for r in rows if (r.get('deploy',r)).get('status')=='live'),None);print(json.dumps({'sha':((d or {}).get('commit') or {}).get('id','')[:8],'finishedAt':(d or {}).get('finishedAt'),'trigger':(d or {}).get('trigger')},indent=1))"
```

If that prints nothing or errors, say **the reader failed** and stop — a failed read is NOT a clean result.

STEP 2 — are the fixes still in what is running? Check CONTAINMENT, not SHA equality. This branch gets rebased, which renames every SHA while changing nothing; on 2026-08-16 an equality test made three live fixes look reverted:

```bash
git fetch origin --quiet; git merge-base --is-ancestor d72d670c <live-sha> && echo "FIXES PRESENT" || echo "INVESTIGATE"
```

`d72d670c` is the newest of the three fixes and they are linear (`164f6e80` -> `1409e96f` -> `d72d670c`), so that single check covers all three. If it fails, do NOT report a revert — re-check by content first (`git show <sha> | git patch-id --stable`, compared across `git log <live-sha>`), because the next rebase renames `d72d670c` too. Only genuinely absent patch-ids mean a revert. If the live SHA is not present in this checkout at all, say so rather than guessing — `git fetch origin` first, and if it is still absent the service is running a branch this clone does not have.

STEP 3 — deploys and kills since the last known state:

```bash
py -3 scripts/render_events.py --service refresh-worker --since 2026-08-16T15:45:50Z
```

Kills come from the EVENTS API only. Never conclude "no kills" from a log search — a killed process emits no log line, and this repo carries a retracted "0 kills" claim that came from a log grep.

**Daytime kills are no longer hypothetical.** Measured 2026-08-16: `oomKilled` at 16:34:32Z (11:34 local) and 17:19:42Z (12:19 local), both well outside the 15:00-23:59 local band that held 41 of the prior 42 kills, and both on an afternoon carrying 4+ deploy cycles. Report every kill you find with its local time; do not filter to the band, and do not treat a daytime kill as noise.

STEP 4 — report in under 12 lines:
- live SHA, its `finishedAt`, and whether it differs from `97491161`
- FIXES PRESENT or INVESTIGATE (and if INVESTIGATE, the patch-id result — never a bare revert claim)
- deploy count since 15:45:50Z, with local timestamps and who triggered each
- any `server_failed` events, classified (`oomKilled` / `evicted` / `unhealthy` / `earlyExit` — these have different causes and must not be flattened)
- **uptime at 22:00Z**, computed from the most recent deploy's `finishedAt`

VERDICT, one line, exactly one of — **unless STEP 0 classified this run as EARLY (manual test), NOT A PRE-BAND READING, or MOOT, in which case do not issue one at all; a verdict from a run that did not happen at band open is a claim the run cannot support:**
- **BAND CLEAN** — no deploy since 15:45:50Z, fixes present, worker warm. Tonight's measurement rests on a single uninterrupted process.
- **BAND COMPROMISED** — a deploy landed. Say when, by whom, and what uptime the band will actually open with. A short warm-up means the memory ratchet has not re-formed and the comparison against the recorded night baselines (amplitude 1,950-2,235 MB; min inactive_file 26.3/42.2 MB in windows that killed vs 164-240 MB in windows that survived) is weaker — say that plainly rather than letting the later tasks average through it.

Report local time (America/Chicago) alongside UTC. A wrong clock has produced a wrong recommendation in this repo before.
````

### Full prompt — `oom-band-early-read` (one-time, 2026-08-17T01:00:00Z)

````text
Early read on the refresh-worker OOM lane. Self-contained — you have no memory of the session that created this.

WORKING DIR: C:\Users\tempadmin\OneDrive\Coding\Syndicate

WHAT THIS IS. `refresh-worker` was OOM-killed repeatedly (4 Gi container). Three fixes shipped 2026-08-16 and are live and EXERCISED, but NOT ONE has been shown to move the ~2 GB transient that causes the kills:
  - odds-shard duplicate parse (~125 MB/build) — was `51ae7218`, now `164f6e80`
  - ledger streaming + LEDGER_CHUNKS_ACCEPTED logging (833,550,415 bytes accepted per load) — was `21f8a165`, now `1409e96f`
  - rank_recommendations loaded the whole ledger 3x per call -> 1x — was `aa190d58`, now `d72d670c`
The original SHAs were REBASED away and no longer exist in the live line; the renames above were verified by `git patch-id --stable` on 2026-08-16. refresh-worker is live on **`97491161`** (finished 2026-08-16T15:45:50Z), which is `d72d670c` plus one unrelated NFL play-by-play path fix (`#441`) that touches no MLB ledger or odds allocator.

WHY NOW. Kills cluster in the LIVE-SLATE band, roughly 22:00Z-05:00Z. The daytime lull shows ZERO excursions on broken AND fixed code alike, so a clean afternoon proves nothing — the pre-fix code once ran 17h51m clean in daylight. This is ~3 hours into tonight's band.

RUN EXACTLY THIS:
    py -3 scripts/oom_band_report.py --start 2026-08-16T22:00:00Z

Then report, in under 15 lines:
1. Kills in the band (the tool reads these from the EVENTS API — never from logs; a killed process emits no log line, and this repo has a retracted "0 kills" claim that came from a log grep).
2. Excursion count/hr and mean amplitude per deploy-free segment. Night baseline amplitude is 1,950-2,235 MB.
3. min inactive_file per segment. THIS IS THE DISCRIMINATOR: the two windows that ended in a kill bottomed at 26.3 and 42.2 MB; surviving windows kept 164-240 MB.
4. A verdict in one sentence: are excursions back at the old amplitude (=> the three fixes were NOT the 2 GB), or genuinely reduced?

IMPORTANT HONESTY RULES, which this lane has already been burned by:
- Check CONTAINMENT, not SHA equality. The question is never "is live still `<pinned sha>`" — this branch gets rebased, which renames every SHA while changing nothing, and on 2026-08-16 that made three live fixes look reverted. Ask instead whether the fixes are still IN what is running:
      git merge-base --is-ancestor d72d670c <live-sha> && echo "fixes present" || echo "INVESTIGATE"
  `d72d670c` is the newest of the three (they are linear: `164f6e80` -> `1409e96f` -> `d72d670c`), so that one check covers all three. If it fails, do NOT conclude a revert — re-check by content before saying anything:
      git show <fix-sha> | git patch-id --stable      # compare against the same over `git log <live-sha>`
  Only if the patch-ids are genuinely absent has something been reverted. SAY SO FIRST if so.
- Report which SHA you actually measured, and whether it differs from `97491161`. A deploy mid-band splits the segments and the tool already knows that; an UNREPORTED one silently mixes two different builds into one average.
- Do NOT read a quiet window as success. State the window length. A short or deploy-fragmented band is not evidence.
- Do NOT claim a fix works. The only claim available tonight is whether the transient moved.

Append a short dated entry to `.syndicate/deploys.md` under a `## 2026-08-16 ~01:00Z — OOM band, early read` heading with the numbers and the verdict. Commit it through an ISOLATED index, because the shared git index in this worktree is stale continuously:
    IDX=/c/tmp/idx-oomband-early
    BASE=$(git rev-parse HEAD)
    GIT_INDEX_FILE=$IDX git read-tree $BASE
    GIT_INDEX_FILE=$IDX git add -- .syndicate/deploys.md
    GIT_INDEX_FILE=$IDX git diff --cached --numstat    # must show ONLY that file
    [ "$(git rev-parse HEAD)" = "$BASE" ] || echo "HEAD MOVED — re-read before committing"
    GIT_INDEX_FILE=$IDX git commit -F -
Use a FIXED index path as above, never `$$` or `mktemp` — each shell invocation is new, and an absent index file is an EMPTY one, not an error. If a `commit-guard` hook blocks the commit, that is a real finding: run `git reset -- <named path>` in a SEPARATE command (the hook blocks any command containing `git commit`, including one that also does the reset), then commit.

DO NOT DEPLOY ANYTHING. Measurement only.
````

### Full prompt — `oom-band-full-report` (one-time, 2026-08-17T05:15:00Z)

````text
Full retrospective measurement of the refresh-worker OOM band. Self-contained — you have no memory of the session that created this.

WORKING DIR: C:\Users\tempadmin\OneDrive\Coding\Syndicate

WHAT THIS IS. `refresh-worker` (4 Gi) is killed by a ~2 GB TRANSIENT, not a leak: anon climbs ~2 GB in 15-25 s, collapses ~2 GB in ~2 s, and every cycle reaches headroom ~0. Whether a cycle kills is decided by how much evictable page cache remains. Three fixes shipped 2026-08-16, all live and EXERCISED, and NOT ONE has yet been shown to move the transient:
  - odds-shard duplicate parse (~125 MB/build) — was `51ae7218`, now `164f6e80`
  - ledger streaming + LEDGER_CHUNKS_ACCEPTED (833,550,415 bytes accepted per load) — was `21f8a165`, now `1409e96f`
  - rank_recommendations loaded the whole ledger 3x per call -> 1x — was `aa190d58`, now `d72d670c`
The originals were REBASED away; the renames above were verified by `git patch-id --stable` on 2026-08-16. refresh-worker is live on **`97491161`** (finished 2026-08-16T15:45:50Z) = `d72d670c` plus one unrelated NFL play-by-play path fix (`#441`).

THIS RUN IS THE TEST. Kills cluster in the live-slate band ~22:00Z-05:00Z. Daytime is worthless as evidence — measured 2026-08-16, the same clock window one day apart showed peak anon 2,816.7 MB (pre-fix) vs 2,898.5 MB (post-fix) and ZERO excursions on both. The band is the only window that can separate them.

RUN EXACTLY THIS:
    py -3 scripts/oom_band_report.py --start 2026-08-16T22:00:00Z --end 2026-08-17T05:00:00Z

REPORT, comparing against these recorded NIGHT baselines (from `.syndicate/deploys.md`, 2026-08-16):
    amplitude mean          1,950 - 2,235 MB
    min inactive_file       26.3 / 42.2 MB in the two windows that ENDED IN A KILL
                            164 - 240 MB in windows that SURVIVED
    kills                   2 in 26 min (f8ca54e1); 1 at 22.2 min after boot (5c419007)
Give per-segment numbers (the tool splits on deploys, because a deploy reboots the worker and re-runs hydration cold), then a one-paragraph verdict answering exactly one question: DID THE TRANSIENT MOVE?
  - Excursions at 1,950-2,235 MB amplitude => the three fixes were NOT the ~2 GB. Say so plainly; that is a useful result, not a failure.
  - Materially lower amplitude or excursion rate => the first real reduction; still state the window length and deploy count.

HONESTY RULES this lane has already been burned by, twice:
- Check CONTAINMENT, not SHA equality. "Is live still `<pinned sha>`" is the wrong question — this branch gets rebased, which renames every SHA while changing nothing, and on 2026-08-16 that made three live fixes look reverted. Ask whether the fixes are still IN what runs:
      git merge-base --is-ancestor d72d670c <live-sha> && echo "fixes present" || echo "INVESTIGATE"
  The three are linear (`164f6e80` -> `1409e96f` -> `d72d670c`), so that single check covers all three. On failure do NOT report a revert — re-check by content (`git show <sha> | git patch-id --stable`, compared across `git log <live-sha>`) and only call it reverted if the patch-ids are genuinely absent. If they are, SAY SO FIRST.
- Report the SHA you actually measured and whether it moved from `97491161` during the band. The tool splits on deploys; an unreported redeploy still mixes two builds into one verdict.
- Count the deploys in the band. If the band is fragmented into short segments, the ratchet never re-warms and the result is weak — say that rather than averaging it away.
- A quiet band is NOT proof. State window length. The pre-fix code once ran 17h51m clean in daylight.
- Kills come from the EVENTS API only, which the tool already does. Never conclude "no kills" from a log search.

Then append a dated entry to `.syndicate/deploys.md` under `## 2026-08-17 ~05:1xZ — OOM BAND, FULL RESULT` containing the per-segment table, the verdict, and — if the transient did NOT move — the explicit note that the remaining allocator is still unnamed and the next candidate must be found by measurement, not by guessing. Commit through an ISOLATED index (the shared index here is stale continuously):
    IDX=/c/tmp/idx-oomband-full
    BASE=$(git rev-parse HEAD)
    GIT_INDEX_FILE=$IDX git read-tree $BASE
    GIT_INDEX_FILE=$IDX git add -- .syndicate/deploys.md
    GIT_INDEX_FILE=$IDX git diff --cached --numstat     # ONLY that file
    [ "$(git rev-parse HEAD)" = "$BASE" ] || echo "HEAD MOVED — re-read"
    GIT_INDEX_FILE=$IDX git commit -F -
FIXED index path, never `$$` or `mktemp`: each shell call is new, and an absent index file is an EMPTY one, not an error. If the `commit-guard` hook blocks you, that is a genuine stale-index finding — run `git reset -- <named path>` as its OWN command (the hook blocks any command containing `git commit`), then commit.

DO NOT DEPLOY ANYTHING. Measurement only. If the result is bad, the correct output is an accurate report, not a fix.
````
