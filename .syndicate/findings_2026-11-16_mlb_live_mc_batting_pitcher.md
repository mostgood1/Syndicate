# MLB live MC: the batting team's pitcher is its pregame starter (todo #819)

Lane `mlb-live-mc-batting-pitcher`, 2026-11-16, read-only diagnosis plus a fix
held off main. Side finding of todo #814 (lane `live-player-exit-gate`).

## The defect (confirmed)

- `syndicate/features/mlb/live_lens_port/app_slice.py` `_live_mc_projection`
  builds `LiveSituation` with only the FIELDING side's pitcher id (from
  `current.pitcher`). The batting side's id is `None`.
- `syndicate/features/mlb/sim_engine/live_mc.py` `_build_initial_state` turns
  `None` into `_default_pitcher_id(roster)`, which is the roster's PREGAME starter,
  and writes it into `state.current_pitcher_by_team`.
- `simulate.py` `_select_pitcher_v2` takes that as "current". Inside the F5 leash
  (inning <= 5) it keeps him unless his pitch count is extreme, so a starter who
  left early pitches on. Past the leash, a starter pulled at 95+ pitches is often
  pulled again at once, and the reliever is then re-drawn from the whole bullpen.
- **A second form of the same defect:** when the actual starter is not the
  roster's starter (an opener, a late scratch, or a roster built on the probable),
  the sims bring in a pitcher who **never pitched in the game**.

Unit tests (`tests/test_mlb_live_mc_batting_pitcher.py`, toy rosters, bottom 3rd,
the home starter pulled after 38 pitches):
- unset id: the engine seeds the home starter; he records outs in >= 90% of 120
  sims, and the reliever actually on the staff in < 10%;
- set id: the engine honours it; the starter records 0 outs.

**So the engine already does the right thing with a set id: the fix is
caller-only.**

## Size (fleet data, read-only, Idle priority)

Substrate: the fleet's `~/syndicate-prod/data/mlb_source/source_artifacts/data`,
`raw/statsapi/feed_live/2026/` (183 feeds, 161 Final, 29 dates 06-14..10-27) and
`daily/snapshots/<date>/roster_*.json`. Script:
`scripts/mlb_live_mc_batting_pitcher_size.py`. Output: `C:\tmp\mlbbp\size_full.json`.
Ticks are reconstructed at each plate-appearance start, a proxy for the timed
live tick.

### How often a tick is in the defective state

4,931 of 12,042 PA-start ticks (**41%**). All 161 games have some.

| inning | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10+ |
|---|---|---|---|---|---|---|---|---|---|---|
| share | 0.6% | 3.3% | 9.6% | 17% | 28% | 49% | 80% | 95% | 99% | 100% |

### What it moves

260 affected ticks simulated: 2 per game drawn uniformly from its affected ticks,
on the games with a roster snapshot. 62 sampled ticks had no roster. Each tick
ran 300 sims in three arms with the production forward-tuning `cfg_kwargs`:
- off: today's code;
- on: the batting side's last pitcher passed in, same seed;
- null: off again with seed+1, which gives the noise floor.

"Net RMS" is sqrt(E[(on-off)^2] - E[(null-off)^2]). It is conservative: on and
off share a seed, so their noise is at most null's.

| stratum | n | net RMS d home WP | net RMS d total | mean d total (on-off) | wrong pitcher pitches (off) |
|---|---|---|---|---|---|
| all | 260 | 0.85 pp | 0.12 runs | -0.069 | 28% of sims |
| starter = roster SP, left < 75 pitches | 66 | 2.3 pp | 0.18 | -0.079 | 42% |
| starter = roster SP, left >= 75 | 154 | ~0 | 0.08 | -0.065 | 6% |
| actual starter != roster SP | 40 | 2.7 pp | 0.12 | -0.068 | **88%** (a pitcher who never pitched) |
| inning <= 5 | 33 | 3.4 pp | 0.20 | -0.17 | 64% |
| inning 6-7 | 91 | 1.5 pp | 0.17 | -0.091 | 30% |
| inning >= 8 | 136 | ~0 | ~0 | -0.030 | 17% |

- **Systematic bias:** off over-projects the remaining total by **0.069 runs**
  (se ~0.016, ~4 se) on affected ticks. It also under-projects the batting team's
  win probability by 0.5 pp (se ~0.2 pp).
- **Per-tick wobble:** typically under 1 pp, but 2-3 pp early in the game and
  after an early exit. Production runs 120 sims (`MLB_LIVE_GAME_MC_SIMS`), so
  each tick already carries ~4.5 pp of sampling sd. The bias is smaller than the
  noise on one tick, but it does not average out: it has a direction.
- Against the lane's registered prediction (median |d home WP| >= 0.5 pp): at
  300 sims the measured on-vs-off median is 1.0 pp, but the null median is 1.3 pp.
  So the median is noise-dominated and cannot decide. The net RMS (0.85 pp) and
  the signed total bias are the readable numbers.
- **Falsification NOT met:** the defect is real, and on totals it is material
  (0.07-0.17 runs in one direction).

## Related, NOT changed (follow-ups)

1. **Relievers are re-drawn from the full pregame bullpen.** That includes arms
   already used and removed. Nothing tracks "used" pitchers (`_select_reliever_v2`).
2. **A pitcher missing from the roster's bullpen gets the STARTER's profile.**
   `_pitcher_profile` falls back to `roster.lineup.pitcher`. 55 of the 260 sampled
   batting-side pitchers (21%) were not in the roster bullpen, and the fielding
   side has the same exposure today.

## The fix (built, NOT on main, needs the user's yes)

All of it is in `app_slice.py`. Nothing in `live_mc.py` changes.

- `_load_live_lens_snapshot` adds `teams[side].pitcherOrder`, from
  `liveData.boxscore.teams[side].pitchers` in appearance order (new helper
  `_box_pitcher_order`). It is needed because `boxscore.pitching` rows are sorted
  by pitches, not by order, so they cannot say who pitched last.
- `_live_mc_projection` passes the batting side's `pitcherOrder[-1]` when
  `MLB_LIVE_MC_BATTING_SIDE_PITCHER` is on (new helper
  `_live_mc_batting_side_pitcher`). **ABSENT = OFF**, which is today's behaviour.
  If the team has not pitched yet, it still falls back to the engine default.
- Tests: off != on at the engine and at the caller, plus OFF leaves the batting
  side unset. 8 pass. The 61 existing live-lens tests pass
  (`test_mlb_live_game_line_lens`, `test_live_mc_first5`, `test_live_lens_loop`).
- **Loan:** lane `live-player-exit-gate` loaned `_live_mc_projection`'s pitcher
  args + `live_mc.py` (main `726eb8b14`). The snapshot field and the two helpers
  go beyond that scope and need its OK too.
- **Mechanism vs estimator (standard 4.4):** the live MC uses the PREGAME-fitted
  manager overrides, and no live-specific rate was fitted on top. So no fitted rate
  absorbs this mechanism, and switching it on needs no re-fit. The one
  calibration that could have absorbed it is the live probability calibration, if
  any is applied to MLB live lanes; that is unchecked.
- MLB is out of season until spring 2027, so no fleet measurement is possible.
  The reading for spring: with the switch on, the live MC's `pitcherStatDist`
  shows 0 outs for every pulled starter.
