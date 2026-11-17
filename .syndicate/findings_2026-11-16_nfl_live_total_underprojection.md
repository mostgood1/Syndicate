# NFL live re-sim totals run low: the cause, sized

Lane `nfl-live-total-underprojection`, session 8062940b, 2026-11-16 (read 8:37 AM CST (14:37Z)). User: "Yes, look into it" (to "Look into why the NFL live
totals come in about 3.7 points low, here?"). Read-only: nothing loaded, no engine edit. Fleet HEAD `10094eae0`. Scripts
and outputs in `C:\tmp\livegrade\nfl780\harness` (`q_actual.py`, `pregame_all.py`, `level_probe.py`, `state_probe.py`, `poss_probe4.py`,
`resume_probe5/6/7.py`, each with its `.out`).

## The symptom

The 11-15 width fit (`findings_2026-11-15_nfl_live_width_fit.md`): the shipped `resim_live_game`, replayed at the end of
Q1 / Q2 / Q3 on 65 games (weeks 5-10, POINT_IN_TIME ratings), projects too few remaining points: -5.05 / -2.86 / -3.12,
overall -3.68 [-5.86, -1.43].

## Hypotheses (in the lane before any read, pushed `57f9ae580`)

- **H-ENV:** 2026 games score above the 2024-25 level smartsim2 is fitted to.
- **H-LIVE:** the live resume itself loses points the pregame engine keeps.

## Readings

1. **2026 scores at the league's level** (`q_actual.py`, ESPN linescores, the 65 games): q1 8.51 [7.38, 9.71], q2 13.48
   [11.97, 15.00], q3 10.09 [8.71, 11.58], q4 13.42 [11.46, 15.45], OT 0.55; final 46.05 [42.68, 49.48]. League
   2024-25: 8.93 / 14.02 / 9.50 / 13.17, regulation 45.62. Every quarter is inside the league's CI.
2. **The pregame projector also runs low** (`pregame_all.py`, the served CSVs, every final game of weeks 1-10, n 149):
   projected 43.93, final 46.17, projected minus final -2.24 [-4.58, -0.09]. Every 2026 row carries `rating_source`
   `+level_shrink_0.3`. No `SYNDICATE_NFL_TOTAL_LEVEL_SHRINK`, `_TOTAL_DIFF_CORRECTION`, `_DRIVE_PRIORS` or
   `_BLOWOUT_DAMPING` key is set in `local_production.env` or any `render_env` snapshot (lines counted, values not read).
3. **The level shrink is not it** (`level_probe.py`, the live loop's own seeds). The live re-sim reads the ratings
   artifact, which holds `team_rating`'s raw output; `build_projection` shrinks the two teams' common level to 0.3 first.
   (The generator's comment that the artifact "yields exactly what `build_projection` used" has been untrue since the
   shrink.) Same seeds, shrunk minus raw remaining points: kickoff -0.25 [-1.26, +0.81], end of Q1 -0.03, Q2 -0.18,
   Q3 -0.01 [-0.33, +0.30]. The raw arm reproduces the replay to the hundredth (-5.05 / -2.86 / -3.12).
4. **The score at the break is not it** (`state_probe.py`): Q4 resumed at the end of Q3 from the engine's OWN Q3-end
   scores loses as much as from the real ones (10.77 both, against 12.83 played through; seeds 1..60), in every
   score-gap bin (0-3, 4-8, 9-16, 17+).
5. **The cause, sized** (`resume_probe7.py`, 65 games, an independent seed block per game; Q4 points):
   - played through from kickoff 12.04 [11.64, 12.46];
   - resumed at the end of Q3 with the TRUE drive state (owner, field position, down, distance from the per-play
     `possession_log`): 11.99, so -0.06 [-0.26, +0.15]: **the resume is neutral when it knows the drive;**
   - resumed with possession marginalised, as production does (each side at its own 25, 1st and 10): 10.52, so
     **-1.47 [-1.65, -1.30] against the true state;**
   - from the REAL end-of-Q3 score, marginalised: 10.48; the real Q4 (+OT) 13.97 [11.88, 16.14].
   - Void: probe 3 (`poss_probe4.py`) read the MERGED `drive_log`, which ends a cross-quarter drive in the next quarter,
     so it passed the NEXT possession (median field position exactly 25). Its "-1.84" is withdrawn; probe 7 reads
     `possession_log`.
6. **Production never knows possession.** All 313 `live_resim` evidence rows of 11-09..11-16 carry
   `possession_marginalised=True`, and their `live_state` holds only period / clock_seconds / home_score / away_score.
   `nfl/live_game_state.py` keeps ESPN's raw `situation` on every live game (possession, down, distance, yardLine), but
   `nfl/live_resim.live_state_from_row` reads `possession_owner` / `down` / `distance` / `field_position`, which
   nothing fills. NCAAF's live re-sim does read `situation` (`ncaaf/live_resim.py:369-380`).
7. **Production's seeds are fixed.** Every game and every tick uses seeds 1..60 per possession plan, so the Monte Carlo
   error is shared by all games and never averages out. Measured, production's seed set minus independent seeds, Q4
   from the end of Q3: +0.26 [+0.09, +0.43] (own scores), +0.29 [+0.11, +0.46] (real scores); full games from kickoff
   12.83 (seeds 1..60) against 12.04 (independent). The 11-15 replay's CIs (bootstrap over games) understate its
   uncertainty for the same reason.

## Split of the end-of-Q3 shortfall (-3.12 on production's seeds)

- **Possession marginalised (the live path):** -1.47 [-1.65, -1.30].
- **The engine's level on these games:** Q4 played through 12.04 against the real Q4 + OT 13.97, -1.93, about +-2 (the
  real games' spread). Consistent with the pregame projector's -2.24 [-4.58, -0.09] over 149 games. It includes sim vs
  real overtime. Not isolated here: the engine was on target on 2024-25 (#808 FIT read, regulation 45.84 vs 45.62) and
  2026 scores at that level, so this is the engine's response to 2026's ratings.
- **Production's seed set:** +0.29 [+0.11, +0.46].
- Sum -3.11, against -3.12 measured.

## Verdicts

- **H-ENV: FALSE as stated** (its falsifier met: Q4 13.42 is inside [12.54, 13.84]). But an engine-level miss on 2026
  ratings exists: the pregame projector runs 2.24 points a game low.
- **H-LIVE: TRUE in part.** Each mid-game resume loses about 1.5 points through the marginalised possession; with the
  true drive state the resume is neutral. At halftime a fresh own-25 drive is close to real football (a kickoff), so the
  replay's -2.86 there is mostly the engine level.

## What it affects now

- **The NFL live MONEYLINE is priced from this re-sim today** (86-144 rows a Sunday, 11-08 census). Every tick restarts
  the drive in progress at the 25 with a coin-flip owner, so a team on the opponent's 5 reads the same as one pinned at
  its own 5. Its cost to the moneyline is not measured here.
- NFL live totals and spreads stay off. The 11-15 width fit's k (5.0 / 4.91) partly absorbed this location miss; re-fit
  after any fix.

## Fixes this points to (none made; each is the user's call)

`nfl/live_resim.py` is claimed by the OPEN lane `live-player-exit-gate`.

1. Fill `possession_owner` / `down` / `distance` / `field_position` from ESPN's `situation` for NFL. NCAAF's transform
   exists; NFL's `situation` shape is unchecked (the module's own docstring says so).
2. Seed each re-sim by (event, tick), not 1..60 everywhere.
3. The engine's level on 2026 ratings (-2.2 a game pregame): an engine / ratings question; related to #808 and lane
   `football-scenario-calibration`.

## Not measured

- Mid-quarter ticks: production resumes mid-drive too, and a red-zone drive restarts at the 25, so the loss there may
  be larger than at a quarter break.
- The moneyline's own cost.
- Why the engine runs low on 2026 ratings.

## The fix for part 1 (lane `nfl-live-possession-map`, user "Yes, fix it here")

Built 9:41 AM CST (15:41Z).

- **What:** `claude/nfl-live-possession-map` @ `2f8ae4a07` (pushed as a branch, NOT on main, NOT loaded): `scripts/_nfl_live_resim_tick.normalise_live_row` now maps ESPN's `situation` -- the side from `situation.possession` (a team id) against the row's new `home_team_id` / `away_team_id` (`nfl/live_game_state.py`), down / distance only when they are a real snap (ESPN's -1 between plays, when a kickoff names the KICKING team, falls back), and field position from ESPN's own `possessionText` / `downDistanceText` matched to the two abbreviations, never from `yardLine` (its NFL frame is unverified; NCAAF measured it from the HOME goal line, `shared/game_shape` reads it as distance to the opponent's goal), which is recorded as a diagnostic `yardline_frame`. Every ambiguity falls back to the pre-#813 marginalised state, named in `situation_basis`; `run_refresh_worker` prints one `NFL_LIVE_SITUATION live= carried= marginalised= basis= yardline_frame=` line per tick. Tests: 246 passed across the 9 NFL test files that import these modules, including reachability (the mapped state reaches `resim_live_game`: `possession_marginalised` False, and a 1st-and-goal state's total differs from the marginalised one).
- **Where it is:** Kept off main on purpose: other sessions fast-forward the fleet to main (twice today), which would load this before the payload check and the user's yes.
- **Check before any load:** MNF check armed: background `b8jy25pyl` (`C:\tmp\livegrade\nfl813\mnf_watch.py`, Windows only, ESPN only) runs the branch's own code on the live scoreboard every 120 s from 7:10 PM CST until LAC @ BAL is final, logging the raw situation, the mapped drive and the falsifier checks to `C:\tmp\livegrade\nfl813\out\mnf_reads.jsonl`.
- **Falsifiers (in the lane before any payload was read):** (a) fewer than half the in-progress reads carry both possession and parseable spot text; (b) the spot from `possessionText` disagrees with the spot from `downDistanceText` on any read; (c) a test shows the state does not reach `resim_live_game` (it does: the reachability test passes).

## The MNF check and the landing (10:16 PM CST (04:16Z))

- **Check:** MNF 11-16 check PASSED on 88 live reads of LAC @ BAL (the branch's code on ESPN's live scoreboard, every 120 s, `C:\tmp\livegrade\nfl813\out\mnf_reads.jsonl`): (a) 66 of 88 carried the real drive = 75% (81% outside the 7 halftime reads), every fallback named (13 `no_possession`: 7 at halftime, the rest just after a score or kickoff; 8 `between_plays`; 1 `no_spot_text`); (b) `possessionText` and `downDistanceText` agreed on 66 of 66; owner matched the possession id 66 of 66, field position always in 1..99; `yardLine` is HOME-goal frame on NFL too (37 home-only, 29 both, 0 to-goal-only); `homeTimeouts` / `awayTimeouts` present as ints on all 88. Session 431175b6's timeouts verdict at Q4 1:59: 78 exact + 2 boundary lag + 0 mismatch of 87 against ESPN's play-by-play.
- **Landed:** LANDED on main at 10:14:49 PM CST (04:14:49Z): `9049537d1` (the possession map) + `17ff69398` (timeouts), rebased on `0111eae90`, files byte-identical to the tested branch, 382 tests pass on the rebased tree; SHA sent to session 431175b6, whose drained refresh-worker restart after tonight's finals (~1 AM CST) loads it with the NFL profile (its ff + its claim). NOT loaded at this writing.
- **Side finding, recorded as a lead (not followed):** `shared/game_shape._football_situation` reads `yardLine` as distance-to-opponent-goal, so its `red_zone` is wrong on home possessions (7 false flags, 6 misses in 66 reads); ESPN's `isRedZone` was right on all 66.
- **Owed: the post-load reading at TNF 11-19 (IND @ HOU) -- `possession_marginalised` on live NFL rows (before: 313 of 313 True over 11-09..11-16) from session 431175b6's shared watcher `tnf_reads.jsonl`, plus the refresh-worker's `NFL_LIVE_SITUATION` basis counts; then re-run the #780 NFL width fit.**
