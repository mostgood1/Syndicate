# H42 — appearance-weighted shots/SOT re-split — RESULT 2026-10-13

Lane `soccer-shots-allocation-blend`. Pre-registration: `.syndicate/lanes.md`, line
"- **H42 PRE-REGISTERED 2026-10-08 ~14:45Z" (commit `ab09336a`), followed exactly:
estimator, grid (gamma 0..3 step 0.25), leave-one-date-out Poisson NLL over APPEARED
players, match-bootstrap 95% CI, the interior-gamma clause, and the minimum-data rule.
MEASUREMENT ONLY — no production code, fleet config or deploy touched. Scorer is scratch:
`C:\tmp\soccer-h42\score_h42.py`, output `C:\tmp\soccer-h42\score_h42.out.txt` and
`h42_result.json`. Run 2026-10-13 ~15:30Z by a scheduled task, at Idle priority.

## Verdict

| market | verdict | n rows / matches / dates | gamma per fold (10-09, 10-10, 10-11, 10-12) | held-out NLL current | H42 | diff (H42 - current), 95% CI |
|---|---|---|---|---|---|---|
| shots | **NOT SUPPORTED** | 2709 / 101 / 4 | 0, 0, 0, 0 (full-data 0) | 1.2757 | 1.2757 | 0.0000 [0.0000, 0.0000] |
| SOT | **NOT SUPPORTED** | 2709 / 101 / 4 | 0, 0, 0, 0 (full-data 0) | 0.7098 | 0.7098 | 0.0000 [0.0000, 0.0000] |

Each clause, each market:
- **Minimum data (>= 4 match dates, >= 60 matches): MET, barely.** 4 dates (10-09..10-12), 101 matches. Exactly at the date floor.
- **CI wholly below 0: FAILS.** Every fold picked gamma = 0, so the held-out model IS the current model; the diff is identically 0.
- **Fitted gamma interior in every fold: FAILS.** gamma = 0 at the grid's lower edge in 4 of 4 folds.

This is a clean negative, not a power problem: full-data mean NLL rises monotonically in
gamma for both markets (shots 1.2757 at 0 → 1.2857 at 0.25 → 1.4376 at 1 → 2.0903 at 3;
SOT 0.7098 → 0.7145 → 0.7671 → 0.9848). Concentrating the side's shots onto the
high-appearance-probability players makes the likelihood worse at every step.

## Reported only

Full-data mean NLL by gamma — shots: 0:1.2757, 0.25:1.2857, 0.5:1.3219, 0.75:1.3744, 1:1.4376,
1.25:1.5080, 1.5:1.5835, 1.75:1.6626, 2:1.7445, 2.25:1.8285, 2.5:1.9144, 2.75:2.0017, 3:2.0903.
SOT: 0:0.7098, 0.25:0.7145, 0.5:0.7275, 0.75:0.7456, 1:0.7671, 1.25:0.7908, 1.5:0.8161,
1.75:0.8425, 2:0.8698, 2.25:0.8979, 2.5:0.9264, 2.75:0.9554, 3:0.9848.

Brier (held-out H42 == current, since gamma = 0 in every fold):

| line | current | H42 | diff |
|---|---|---|---|
| shots 0.5 | 0.2180 | 0.2180 | 0 |
| shots 1.5 | 0.1605 | 0.1605 | 0 |
| shots 2.5 | 0.0892 | 0.0892 | 0 |
| SOT 0.5 | 0.1713 | 0.1713 | 0 |
| SOT 1.5 | 0.0566 | 0.0566 | 0 |

Starter vs sub by ACTUAL role (box-score starter flag), served if-playing mean vs actual:

| market | role | n | current | H42 | actual |
|---|---|---|---|---|---|
| shots | starter | 1903 | 1.026 | 1.026 | 1.166 |
| shots | sub | 806 | 0.612 | 0.612 | 0.568 |
| SOT | starter | 1903 | 0.356 | 0.356 | 0.412 |
| SOT | sub | 806 | 0.201 | 0.201 | 0.201 |

The starter under-projection is still there on fresh data (1.026 vs 1.166, a gap of 0.140,
ratio 0.88), but it is smaller than the 0.899 vs 1.101 (gap 0.202, ratio 0.82) the H38
blend left on the 09-17..09-30 window. **H42 did not narrow it** — gamma = 0 everywhere.
The narrowing is in the served model across windows (different dates, a 4-date sample, and
other model changes in between), not something H42 did. Read it as unexplained.

Per-league n (rows / matches), identical for both markets: belgian_pro_league 231/9,
bundesliga 254/9, championship 293/12, epl 276/10, eredivisie 226/9, la_liga 254/9,
ligue_1 249/9, mls 427/15, primeira_liga 214/9, serie_a 285/10.

## Data and coverage

- **Builds:** 7,792 archived files from `C:\tmp\soccer-arch\<league>\` (watcher, dates 10-09..10-19),
  copied to `C:\tmp\soccer-h42\cache\prod\recs\` as `<league>__<original name>`: 3,785 full builds
  (`recommendations_<date>.<mtime>.json`) and 4,007 pre-kickoff freeze files.
- **Format adapter (noted, no change to the test):** the freeze files are schema
  `soccer_prekickoff_freeze_v1` — `matches` is a DICT keyed by match id, each entry
  `{frozen_at, kickoff, match, player_props}` — which `common.load_recs` and `outcomes.py`
  cannot read (`AttributeError: 'str' object has no attribute 'get'`). Each entry was written as
  a one-match file in the regular build shape with `generated_at = frozen_at` (checked:
  `frozen_at` equals the source build's `generated_at`). Raw freeze files kept in
  `cache/prod/freeze_raw/`. `load_recs(prekickoff_only=True)` then applied its unchanged rule
  (latest build with generated_at strictly before kickoff) across both families.
- **Pre-kickoff recs:** 214 (league, match) pairs dated >= 2026-10-08; 101 have a completed ESPN
  outcome (113 are future fixtures 10-13..10-19; 1 ESPN fixture ABANDONED, dropped).
- **Outcomes:** `outcomes.py` (`SOCCER_AUDIT_CACHE=C:\tmp\soccer-h42\cache`,
  `SYNDICATE_REPO_ROOT=C:\tmp\soccer-lpb\runroot`): 102 fixtures past kickoff+3h, 101 FULL TIME;
  player/team shots and SOT capture 1.00 in all 10 leagues.
- **Join** (`audit_props.bind_players`, i.e. `namejoin_diag.strict_match`, per side):
  appeared box-score players bound to a model row **2965/3176 = 93.4%** (players with >= 1 shot:
  1462/1545 = 94.6%). Model rows bound to the box score: 3657/4776 = 76.6% — the model lists
  squad players outside the matchday 18, so that denominator is not a join failure. The task's
  80% threshold was applied to the appeared-player rate.
- **Rows:** 2,965 joined appeared rows; 256 dropped for `expected_shots` or
  `expected_shots_if_playing` <= 0 or missing (p_i undefined; dropped from BOTH arms); 2,709 scored.
  gamma = 0 reproduces the served if-playing mean to 4.4e-16.
- **Intersection the result rests on:** 4 match dates (2026-10-09, 10-10, 10-11, 10-12), 101 matches,
  10 leagues, 2,709 appeared player-rows. 10-09 and 10-12 are thin (9 and 5 matches) — the
  October international window. No date before 2026-10-08 was used.

## Next

Nothing ships. H42 is closed as NOT SUPPORTED for shots and SOT. The remaining starter gap
(1.026 vs 1.166 on these 101 matches) is not an allocation-within-side problem of this form;
any further test must be pre-registered afresh.
