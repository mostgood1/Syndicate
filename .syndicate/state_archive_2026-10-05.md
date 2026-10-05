# state archive — 2026-10-05

Subjects' superseded sub-block history, moved verbatim out of the COUNTED state files by `scripts/archive_state_subject.py`. Archives are excluded from `STATE_TOTAL`; counted files are not. Nothing here is deleted or summarised, and every live section points here.

## [mlb-ladders-native-builder] — archived from `state_mlb.md` 2026-10-05

2 sub-block(s), 10,354 chars, moved VERBATIM. Nothing summarised. The live section in `state_mlb.md` keeps the other 7 and points here.

### >>> (superseded) DEPLOY CANDIDATE `1ef337c0` <<<

**`deploy/mlb-mix-and-markets` = `1ef337c0`, parent `041188cb` (the LIVE SHA).**
4 files, +323/-4, additive. All four verified BYTE-IDENTICAL at `041188cb` and
at each change's base (or absent, for the two new tests) — an exact add.

**PRIMARY, and MEASURABLE — the conditional mix was never called.**
`apply_conditional_mix_to_pitcher` had exactly one caller anywhere, including
on main: `scripts/validate_crn_pa_seeding.py`, a validation script. The roster
build never invoked it, so `roster_artifact.py` faithfully serialised
`conditional_arsenal: {}` forever. Production's own `sim_input_report`
(host=worker) read **`conditional_arsenal 0.0%` on 2026-08-19 AND 2026-08-20**
with the artifact published, allowlisted and reachable the whole time.

**verify:** the FIRST `sim_input_report_<date>.json` written after the deploy
must show `conditional_arsenal` / `count_bucket_map` / `conditional_arsenal_source`
NON-ZERO. Read it at
`/api/ops/artifacts/export?pattern=*sim_input_report*`. This is a reading of a
PUBLISHED ARTIFACT, not a log line — the sim's stdout goes to a disk file the
Render log API cannot serve.

**RESOLVED 2026-09-07, and this verify was PARTLY UNSATISFIABLE as written.**
`conditional_arsenal` and `count_bucket_map` did go non-zero. The third clause,
`conditional_arsenal_source`, could not have been satisfied by ANY deploy of
this change: the field was never in `ser_pitcher`'s explicit serialize list, so
it was set in memory (`conditional_mix.py:99-101`), read back on load
(`roster_artifact.py:343`), and dropped on write. A defect in a different file,
unrelated to the conditional-mix wiring this block was verifying. Fixed by
`af70a5cd` (one line, plus `tests/test_roster_artifact_roundtrip.py`, a
`dataclasses.fields()` walk that fails pre-fix and passes post-fix). A
69-field round-trip audit of both profiles found this was the ONLY such field:
1 lost unfixed, 0 lost fixed.

**Lesson, and it generalises past MLB:** a compound `verify:` inherits its
weakest clause. Two of these three were testing the deploy; the third was
testing an unrelated file, so its failure said nothing about the change and the
verify could never pass. One clause per mechanism, each separately falsifiable.

**CLOSED 2026-09-07T17:44:53Z — read in production.** `b4b1535d` live at
17:24:04Z; the first `sim_input_report_2026-09-07.json` generated after it
(17:44:53Z, host=worker, rosters=8) reads **65/65 with `failures: []`**.
`pitcher.conditional_arsenal_source` went **0.0 → 0.86, EQUAL to
`conditional_arsenal`** — the value a correct fix predicts, since the producer
sets the pair on adjacent lines. It also proves the rosters were REBUILT rather
than reused: a pre-fix artifact lacks the key entirely, so no cache could
return non-zero for it. `bb_gb_rate` held at 0.6933/0.6786, which is CORRECT
for a same-date serialisation fix — see `deploys.md` for why that control not
moving is the expected reading here and not a null result.

**THE ROSTER-REBUILD THEORY IS RETIRED — do not spend more time on it.**
`--use-roster-artifacts` only reuses an artifact for the SAME date that also
passes `_roster_artifact_matches_inputs`, so a fresh game date always rebuilds.
2026-08-20's rosters WERE built fresh and still came out empty. No env gate and
no forced rebuild could ever have fixed this. `SYNDICATE_MLB_ROSTER_REBUILD_DATE`
is now irrelevant to the conditional mix.

**RIDEALONG folded in, zero marginal cost:** `hitter_strikeouts` joins
`batter_strikeouts`. Its own preflight FAILED standalone on measurability
(0 players observed 08-16..19 → the reading would be 0→0), which is what a
ridealong is for. Expect it to stay 0 until books post that market; that is
NOT evidence the wiring failed.

**rollback:** redeploy `041188cb`.
### >>> (superseded) STANDING RIDEALONG <<< `[refreshed 2026-08-20T03:1xZ]`

**The branch this block used to name is SPENT.** `deploy/worker-ladders-ridealong`
/ `5c2851a4` shipped inside `041188cb` (live 02:03:08Z) — native builder, tests
and sim-job trigger are all live. Do not re-cut it. What follows below, from
**BUILT**, is the still-accurate description of that shipped module.

    carry      syndicate/features/mlb/ladders_build.py
               tests/test_mlb_ladders_build.py
    source     1e15addc (on origin/main); also cut as 15547572 on branch
               deploy/mlb-ladder-market-wiring, parent 041188cb
    scope      2 files, +92 / -4, additive; 25 tests pass, 4 new ones mutation-checked

**If the live SHA is still `041188cb`, just deploy `15547572`.** If the worker
has moved, re-cut onto the NEW live SHA — both files were byte-identical at
`041188cb` and at the change's base, so it is an exact add (`read-tree <live>`,
`update-index` the two paths with blobs from `1e15addc`, `commit-tree`).

**WHY RIDEALONG AND NOT A DEPLOY.** Its own preflight returned FAIL
`[2026-08-20T03:0xZ]` — not on safety, but on measurability:
`batter_strikeouts` is present for **0 players across 08-16..08-19**, so the
expected observation is 0 → 0, which neither confirms nor refutes the change,
while a standalone deploy costs a restart that KILLS AN IN-FLIGHT SIM. Riding
along makes the cost zero. Caveat that bounds the claim: those were WEB's
partial mirrors — the same 08-19 file read 47 players and then 14 an hour later
— so this is "not measurable tonight", NOT "the market is never captured".

**What it changes:** `hitter_strikeouts` joins `batter_strikeouts`, a market
already in `DEFAULT_HITTER_MARKETS` that we pay for on every hitter fetch and
never read. Pitcher `pitches`/`batters_faced` documented as permanently
marketless. doubles/triples/stolen_bases wired but UNFED — **user decision
2026-08-20: do not fetch them** (~+9% of burn, ~3 days of a ~39-day runway).

**ALSO ON THE SAME RESTART — `SYNDICATE_MLB_ROSTER_REBUILD_DATE=2026-08-19`**,
VERIFIED still set 03:07:35Z via `/v1/services/.../env-vars`. **EXPIRES 05:00Z.**
Whether the 02:03 deploy already spent it is **UNKNOWN — not determined.** The
sim-log tail shows no roster line, but the flag prints at the START of a run and
the endpoint serves only the last 8000 chars, so that absence is about the
WINDOW, not the run.

**THE CHECK THIS BLOCK ORIGINALLY NAMED DOES NOT WORK — corrected 03:3xZ.** I
said "check whether roster artifact mtimes moved after 02:03Z". You cannot:
`roster_objs/` is WORKER-LOCAL. The read allowlist appears to permit it
(`fnmatch` lets `*` cross `/`), but the SWEEP uses `Path.glob`, where `*` does
not cross `/`, so `snapshots/<date>/roster_objs/*.json` is never published.
Confirmed by export: **0 files visible on web.**

Every other reading is blind too, each for a DIFFERENT reason, which is worth
knowing before anyone spends the time again:
- `ROSTER_REBUILD armed` in Render logs: 0 hits, because the wrapper's stdout is
  redirected to a disk file and never reaches the collector.
- sim status `command`: it DOES carry the inner `daily_update` argv, but the ops
  endpoint served an IN-FLIGHT run's launcher record (`startedAt: None`), and
  completed `*_status.json` files are not exported.
- `ALL_PROCESS_MEMORY` cmdlines: stored TRUNCATED (`tools/daily_update.py`, no
  argv) and the flag is appended late, so its "absent" is about the truncation.

**So: whether the gate fired is NOT KNOWABLE from here.** Do not record either
answer. The cheap resolution is to stop asking and re-arm: point
`SYNDICATE_MLB_ROSTER_REBUILD_DATE` at the NEXT slate and let it ride with the
next refresh-worker deploy (the var needs a DEPLOY to inject, not a restart, so
it composes with the ridealong above). That trades one bounded rebuild for
certainty.

**BUILT.** `f86b24a3` + `6a213156`.
**Nothing imports `flask_frontend` any more.**

    syndicate/features/mlb/ladders_build.py     native builder, 17 prop groups
    tests/test_mlb_ladders_build.py             14 tests, mutation-checked
    scripts/run_mlb_daily_sim_job.py            trigger, before the publish sweep

**VERIFIED ON REAL DATA** (2026-05-28, the date the local mirror holds):

    PITCHER  strikeouts/outs/hits_allowed/earned_runs/walks_allowed
                 12 rows, 6 with lines, matched 6/6
             pitches, batters_faced                marketAvailable=false
    HITTER   hits/hits_runs_rbis/home_runs/total_bases/runs/rbi
                 156 rows, 58-71 with lines, matched 74/74
             hitter_strikeouts/doubles/triples/stolen_bases  marketAvailable=false
    both native readers render cards from the output

**Every market-backed prop matched 100%, zero unmatched odds on either side.**

**THE ODDS FEED IS NARROWER THAN THE SIM** — 5 of 7 pitcher props, 6 of 10
hitter. Those carry `marketAvailable: false` and are EXCLUDED from the join
accounting. Without that, four hitter props would report `matched 0/74` forever
and look exactly like the bug this module fixes.

**THE JOIN IS PUBLISHED:** `matchedPlayers` / `oddsPlayers` / `unmatchedOdds` /
`unmatchedSimNames` on every group. Sim keys on `mlbam_id`, odds on lowercase
name; names fold through an accent-stripping normaliser (the feed writes ASCII
where the roster writes diacritics).

**THE WRITER REFUSES TO OVERWRITE A GOOD ARTIFACT WITH AN EMPTY ONE** — an empty
rebuild renders identically to a correct one, so overwriting on zero rows would
destroy working output and look like a successful refresh.

**TRIGGER:** `is_stale()` fires on `artifact_missing` / `odds_newer` /
`sim_newer`, checked against BOTH odds files. Not a rebuild every tick. The
`sim_newer` clause is what re-derives ladders on GAME STATE, since sims re-run
every 15-20 min. Env kill-switch `SYNDICATE_MLB_LADDERS_REFRESH`, default on,
never fatal, skipped when the sim failed.

**DEPLOYED AND VERIFIED `[2026-08-20T02:18Z]`, `041188cb`.** `daily_ladders_*`
is allowlisted (2 patterns) — but note the sweep alone was NOT sufficient: the
artifact exceeded `_PUBLISH_MAX_BYTES` and was refused silently, so the sim job
now also publishes it DIRECTLY via `publish_hot_artifact`. See the root-cause
block above before assuming the allowlist is enough for a large artifact.

**Bugs caught by RUNNING the real reader, not by reading:** `away`/`home` are
OBJECTS and were being stringified whole into `team`/`matchup`; and the push
boundary (`>` vs `>=`) — mutation-tested, a whole-number line must push.
