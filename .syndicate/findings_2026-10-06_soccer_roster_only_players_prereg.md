# Soccer: roster-only players in the sim squad — measurement + PRE-REGISTRATION — 2026-10-06

Session b9bb5f37. User asked for this on 2026-10-06 ("do all of these"). NOT IMPLEMENTED: this is
a MECHANISM change to a calibrated engine (`docs/ai_context/model_engine_standard.md`). It is
registered here before any code so the test cannot be chosen after the result.

## Why (measured)

- **The rule.** A player gets a `player_props` row only if he has a row in the league's stats files
  (`players_*.csv`), deduplicated at `scripts/build_soccer_artifacts.py:521`. The ESPN roster is only a
  RESCUE inside the departed-player filter (`:452`, `:492`); it never ADDS a player. (Trace, 2026-10-05.)
- **On the board** (fleet grid 2026-10-05, window 10-04..10-11): 584 priced soccer prop rows were for
  players found in no sim squad. About half were spellings, fixed by `18425937`; on the ESPN roster
  with no stats row: 77; in neither source: 139.
- **On outcomes** (300 graded matches, pre-kickoff builds 07-22..09-30, ESPN box scores, original
  name matcher WITHOUT the 10-05 surname rule): players NOT in that match's sim list made 25.6% of
  starts, took 25.4% of shots and 24.5% of shots on target, and scored 24.4% of goals
  (214 / 878). Inflated by (a) older builds, before the 09-16 squad fixes, and (b) spelling misses
  the surname rule now catches. Still large enough that the listed players' shares are likely
  overstated wherever squads are incomplete.

## The change being registered

Add players who are on the match's ESPN roster but have no stats row, with:
- a positional-prior per-90 rate (league-position median from the stats files);
- a small expected minutes share by starter flag;
- the team totals unchanged, so their mass comes OUT of the listed teammates' shares rather than
  being added.

## Pre-registered test (fixed now, before code)

- **Data:** pre-kickoff builds from dates AFTER the change ships (forward), plus a replay on
  09-17..09-30 builds (the post-fix arm in `findings_2026-10-02_soccer_lines_props_backtest.md`).
- **Primary metric:** per-player SOT 0.5 and anytime-scorer log-loss on APPEARED players, model vs
  model-plus-roster-players, paired by match, bootstrap over matches.
- **Pass:** log-loss improves with a 95% CI wholly < 0 on BOTH markets. The listed players'
  calibration (realised / expected) must also move toward 1.0 (today it is starters 1.33 on first
  scorer; findings_2026-10-05_soccer_last_scorer.md).
- **Fail / falsified:** a CI that crosses 0 on either market, or a worse listed-player calibration.
  On a fail the change is not shipped. There is no re-tuning against the same window.
- **Re-fit obligation:** the shot/goal share rates were calibrated on incomplete squads. If the test
  passes, the share shrink (`calibration_role_mixture*`) is re-fitted before shipping
  (engine standard: "adding a MECHANISM requires re-fitting the rates that were absorbing it").

## Ownership

`scripts/build_soccer_artifacts.py` and the soccer engine files are held by lane
`soccer-corners-model-rebuild` (session abacd435). Implementation needs that lane or a recorded loan.
