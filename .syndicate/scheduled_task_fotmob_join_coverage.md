# Scheduled job -- `fotmob-join-coverage` (GitHub Actions, daily 12:00Z)

**NOT a local scheduled task, and that is an OVERRIDE.** Every other recurring
job in this repo is local (`vendor_sync_daily.ps1`, the Claude desktop tasks),
because `#486` `[2026-08-20, user decision]` removed `Daily Update`'s cron and a
cron re-added by `vendor-sync.yml` on 2026-09-06 was removed again on 2026-09-07.
On **2026-09-15** the user was shown `#486`, the re-removal and the
`learnings.md` rule ("A CONVENTION YOU COPY MAY BE A DECISION YOU ARE
OVERTURNING"), with a local task offered as the recommended alternative, and
chose **"Add the cron anyway (override #486)"**. `state_ledger.md`'s Actions
capability table and its "no `schedule:`" line were corrected in the same commit.

## What it does

`.github/workflows/fotmob-join-coverage.yml` runs
`scripts/check_fotmob_join_coverage.py --days 7` daily at 12:00Z (07:00 CT in
CDT, 06:00 in CST; GitHub cron is UTC and may be delayed).

It resolves every upcoming ESPN fixture in the 10 tracked leagues through
production's own path -- `espn_lineups.fetch_events(league,
date_windows=["YYYYMMDD"])`, the poller's single-date window, then
`resolve_fotmob_match_id` with ESPN's names and the Central date -- and prints
each miss beside FotMob's unclaimed fixtures in that league and window.

## Why it exists

A join miss is SILENT. The live poller writes `momentum.supported: false`,
reason `fotmob match id unresolved`, and the card hides the momentum panel. The
join is by name: `_ESPN_NAME_ALIASES` is keyed to exact ESPN spellings
("stade rennais", "fc cologne"), and the strict and loose passes depend on how
both vendors write a club. A respelling on either side would otherwise surface
only after kickoff, inside one game's live file. Adding aliases for spellings
nobody has seen is guessing (`learnings.md` 2026-09-06). Both vendors publish
fixtures days ahead, so this asks before match day.

## Capability and cost

READ-ONLY: no secrets, no push, no deploy, nothing written to `data/`. One run
is ~70 ESPN scoreboard requests and ~9 FotMob listing requests.

## Failure policy

| exit | meaning | run |
|---|---|---|
| 0 | every upcoming fixture joins | green |
| 1 | a fixture will not join (respelling, alias gap, or FotMob does not list it) | **red**, with the names in the job summary |
| 2 | a fetch could not be completed, so coverage is UNKNOWN there | green with a `::warning::` |

Exit 2 only warns because a vendor blip that reddens the build daily is how a
check becomes one people ignore (`ci.yml`'s own comment). That puts UNKNOWN on
the permissive branch, which `learnings.md` warns about, so: **an unknown-only
day is silent.** The next run re-asks about the same fixtures.

## When it goes red

The summary names the ESPN spelling and FotMob's unclaimed fixture. Add the
MEASURED spelling to `_ESPN_NAME_ALIASES` in
`syndicate/features/soccer/ingestion/fotmob_match_id.py` (or widen the loose
pass), then deploy live-odds-worker behind the usual locks. Baseline on
2026-09-15: 114/114 fixtures resolved over 7 Central days, all 10 leagues.

## Known limits

- GitHub disables scheduled workflows after 60 days of repository inactivity.
- A scheduled run is not a guaranteed run: GitHub can delay or drop it, and a
  billing lock has previously killed every run of this repo's workflows
  pre-step. Evidence of a run is its entry in the Actions tab, not the cron line.

## Has the cron ever fired? -- `fotmob-cron-fired-0916` (Wed 2026-09-16, 08:30 CT / 13:30Z, one-time)

**Not yet known as of 2026-09-15.** The `workflow_dispatch` run `35032523439`
(2026-09-15 22:45:36Z, success in 83 s, 114/114 resolved) proves the workflow,
the runner, the dependency install and the checker -- it does NOT prove the
schedule. GitHub delays or drops scheduled runs, disables schedules after 60 days
of repository inactivity, and a billing lock has previously killed every run of
this repo's workflows pre-step.

This local task reads `gh run list --workflow=fotmob-join-coverage.yml` and looks
for a run whose **`event` is `schedule`** on 2026-09-16. It fires 90 minutes after
the 12:00Z cron and polls until 15:00Z before concluding the cron did not run,
because top-of-hour schedules are frequently late. It dispatches nothing: a manual
run would not prove the schedule.

| verdict | meaning | what it records |
|---|---|---|
| FIRED, GREEN | `schedule` run, `conclusion: success` | run id, lateness against 12:00Z, the `FOTMOB_JOIN_COVERAGE resolved=x/y` line. The cron is proven end to end. |
| FIRED, RED | `schedule` run, `conclusion: failure` | exit 1 -- a fixture will not join. The `UNRESOLVED` lines name ESPN's spelling beside FotMob's unclaimed fixture. It does NOT fix it; it leaves a lead for a lane to add the MEASURED alias and deploy. |
| NOT FIRED | no `schedule` run by 15:00Z | a finding about GitHub, not the checker. It checks the cheap causes: workflow still `active`, the cron line still on `origin/main`, and whether any workflow ran at all (a billing lock shows as no runs anywhere). |

It writes the verdict to `.syndicate/log/2026-09-16.md`, adds a "First scheduled
run" section here, and resolves the `leads.md` lead that records the cron has
never fired.

## First scheduled run -- FIRED, GREEN (2026-09-16)

The cron has fired. Run `35093757133`, `event: schedule`, `conclusion: success`; created 07:04:30 CT (12:04:30Z) -- 4 min 30 s after the 12:00Z cron -- completed 07:06:01 CT (12:06:01Z); checker at 12:05:57Z: `FOTMOB_JOIN_COVERAGE resolved=108/108 unresolved=0 unknown=0 exit=0`.

Read by the one-time task `fotmob-cron-fired-0916` at 08:58 CT (13:58Z). The earlier `workflow_dispatch` run `35032523439` is the only other run; this one is the first with `event: schedule`. Fixture count moved 114 -> 108 because the 7-day window rolled, not because anything stopped resolving (`unresolved=0 unknown=0`).
