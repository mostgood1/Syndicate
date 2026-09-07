# The five MLB season artifacts have not been REBUILT since 2026-08-18

`[2026-09-07, lane segment-regrade-apply, delegated investigation]`

## Read this first: the question that prompted this is DEAD, the finding is not

This investigation was commissioned to explain ten pitcher fields reading 0.0% in
production's `sim_input_report`. **That symptom was a measurement artifact and
the explanation is already landed upstream by `ncaaf-live-resim-wire`:**
`sim_input_checklist.py` globbed the wrong pipeline directory AND sorted
ASCENDING, so it measured the eight OLDEST roster files on disk — all from
**2026-06-15**. The arsenal and pitch-splits artifacts did not exist until
2026-08-20, so those rosters could never contain the audited fields. Nineteen
identical nightly reports were nineteen re-measurements of June.

Production after their fix: **10 failures -> 1** (16:27:40Z), and that last one,
`conditional_arsenal_source`, is a write-side omission they have since fixed in
`ser_pitcher`.

**So do not cite this file as evidence that pitcher Statcast inputs are unfed.**
They are fed. What follows is a DIFFERENT problem found while looking for that
one, which survives the retraction because it rests on the artifacts' own
contents rather than on the checklist.

## The finding: fresh mtimes, three-week-old contents

`[production]` Every one of the five season artifacts has a disk mtime from
TODAY and an embedded `generated_at` from three weeks ago:

| file | disk mtime | artifact's own `generated_at` |
|---|---|---|
| `arsenal_2026.json` | 2026-09-07T14:48:01Z | **2026-08-18T00:54:59Z** |
| `quality_2026.json` | 2026-09-07T14:48:25Z | **2026-08-18T01:00:44Z** |
| `batted_ball_2026.json` | 2026-09-07T15:05:53Z | **2026-08-18T00:15:08Z** |
| `pitch_splits_2026.json` | 2026-09-07T15:06:17Z | **2026-08-17T23:10:09Z** |
| `conditional_mix_2026.json` | 2026-09-07T15:06:51Z | **2026-08-18T01:53:55Z** |

**The fresh mtime is the trap.** `pull_season_artifacts()`
(`artifact_publisher.py:2820-2854`) copies each file from web's
`/api/ops/artifacts/export` onto the worker before every sim run. That is a
mirror of a mirror: it touches the file daily and regenerates nothing. Anyone
checking freshness by mtime — the obvious check — sees a current file.

`[from-code]` **Nothing on any schedule rebuilds them.** The five builders
(`scripts/build_mlb_{arsenal,conditional_mix,pitch_splits,batted_ball,quality}_artifact.py`)
exist, were all created in one ~2.5-hour session on 2026-08-17
(`fcaa53e0`, `f4d9e865`, `106f6c57`, `aea264c1`), and **each has exactly one
commit in its entire git history**. None appears in `render.yaml`, in any GitHub
Actions workflow, or in `todo.md`.

`SYNDICATE_ENABLE_MLB_STATCAST_REFRESH_TRIGGER=true` IS live on refresh-worker
`[production, env-vars API]` and looks like the answer. It is not: it runs
`scripts/refresh_mlb_statcast_features.py`, which writes
`mlb_source/source_artifacts/data/statcast/features/` — **a different artifact
family entirely** (`refresh_mlb_statcast_features.py:34`). A flag whose name
matches the concern and whose target does not.

**It was called at creation time and never closed.** The pitch-splits builder's
own docstring: *"(3) remains open: a scheduled populator on the worker. Pitch
mix drifts through a season, so a one-off fill goes stale."*

## What this actually costs, stated honestly

**Not today's roster.** `[local, real production bytes]` Today's starters
(656550 Grant Holmes, 666200, 691587, 680570, 678394, 676282, 669432 — 7 of 8
sampled from production's `probables.json`) are all present as keys in the frozen
artifacts, and direct execution of `apply_arsenal_to_pitcher`,
`apply_conditional_mix_to_pitcher` and `_apply_cached_statcast_pitch_splits`
against those bytes populates every field. Three-week-old aggregates for
established pitchers are stale, not absent.

**The exposure is drift and new arrivals.** A pitcher debuting after 2026-08-18
has no entry at all, and pitch mix moves across a season. Both grow with time,
neither announces itself, and the reading that would show it — `generated_at` —
is not what anyone checks.

## Recommendation, and one thing NOT to do

Schedule the five builders. Cheap when last run (arsenal: two Statcast
leaderboard calls, 551 pitchers / 450 batters, superseding an ~80-minute
per-pitcher pipeline), season aggregates, weekly cadence plausible — it matches
`refresh_mlb_statcast_features.py`'s own 7-day default.

**UNVERIFIED and load-bearing before anyone schedules it:** the arsenal builder's
usage line invokes a separate `.venv_x64` interpreter, a Windows-ARM64
`pybaseball`/`cryptography` workaround used elsewhere in this repo. Whether that
constraint applies on Render's x64 Linux worker, or the builder runs fine under
the normal interpreter, **nobody has tried**. Establish that before wiring a job,
or the scheduled task fails in a way that looks like a missing artifact.

**Do NOT flip `SYNDICATE_ENABLE_MLB_STATCAST_REFRESH_TRIGGER` for this.** It is
already on and feeds something else.

## Two loose ends recorded rather than resolved

1. **`SYNDICATE_MLB_ROSTER_REBUILD_DATE = 2026-09-07`** is set on refresh-worker
   `[production]`, pinned to today's exact date, with no matching lane in
   `lanes.md`. Whoever set it should say so; a date-pinned override silently
   stops applying tomorrow.

2. **An unresolved tension I am not papering over.** The June-rosters explanation
   accounts for the ten fields reading 0.0%, but the same reports showed pitcher
   `bb_*` and `statcast_quality_mult` at **77.44%** — and those artifacts were
   also generated 2026-08-18, so June rosters should not carry them either. One
   of "the sample was purely June", "batted-ball fields have another source", or
   "the two field families were measured over different roster sets" is wrong.
   Nothing here depends on which, but it means the retraction above is not yet a
   complete account of the old symptom.

## Tooling gaps that made this harder than it should have been

- **The sim job's own diagnostic is unreadable.** `apply_conditional_mix_to_rosters`
  already prints `CONDITIONAL_MIX applied=N/M` per game
  (`daily_update.py:5156-5159`) — the line that would settle applier questions
  directly — but the job's stdout goes to a worker-local disk file with no ops
  route to read it. `state_mlb.md` named this gap on 2026-08-19 and it is still
  open; the 2026-08-20 deploy's own promised 2026-08-21 verification was never
  taken.
- **`/v1/services/<id>/deploys` was blocked** for the delegated session by the
  deploy-guard classifier, so it could not read refresh-worker's live commit —
  a read-only question. Worth knowing the guard blocks reads, not just deploys.
