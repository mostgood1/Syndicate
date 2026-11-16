# NFL segment re-grade on the #808 profile, weeks 11-13 — PRE-REGISTRATION (todo #752 + #808)

Written 2026-11-16 ~3:40 PM CST, before any week-11 game is played, before the profile load reaches the fleet,
and before any data below is read. User: "run the #752 segment re-grade after three weeks" (2026-11-16).
Run date: Tuesday 2026-12-08, 10:00 AM CST, after week 13's last game (MNF 12-08 01:15Z), by a scheduled task.

## Why now, and why it is #808's market test too

- #752's grade (`.syndicate/findings_2026-11-13_nfl_segment_skill.md`, 44 games, weeks 7-10, the OLD profile):
  totals +0.0065 [-0.0132, +0.0264] parity, spreads +0.0089 [-0.0016, +0.0200] parity,
  h2h **+0.0123 [+0.0017, +0.0237] loses**. It asked for a re-grade once the sample doubles, about 3 more weeks.
- Tonight's NFL profile load (lane `nfl-profile-load`: `data/calibration/nfl_profile.json`, version
  `nfl-808-v3h0.03-t0.825`, the seven #808 switches ON, `home_field_bonus` 0.03, `touchdown_weight_multiplier`
  0.825) changes the very histograms the segment rows are priced from. On weeks 7-10 the sim's quarter shares were
  q2 0.279 / q3 0.234 against the league's 0.313 [0.305, 0.320] / 0.205 [0.198, 0.212]. #808's FIT puts each
  quarter inside the league's CIs.
- #808's held-out read covered only the full-game ML / total / spread. The quarter and half markets are where the
  fix should show, so this re-grade is the market test the #808 findings left owed.

## Population

NFL 2026 regular season, weeks 11-13: 43 scheduled games, kickoffs 2026-11-20 01:15Z .. 2026-12-08 01:15Z.
A game is graded if it has all four of:
- (a) a pregame segment quote (`captured_at < commence_time`) in the fleet's
  `nfl_source/tracking/book_quotes/<date>.jsonl.gz`;
- (b) a regular-season `smartsim2_segment_distributions_2026_wk<w>.json` block for the matchup;
- (c) a final ESPN linescore;
- (d) **NEW: that week's sidecar was written on the fleet AFTER the profile load's ff**, with a fresh process on
  the fleet reading `source=artifact version=nfl-808-v3h0.03-t0.825` over the whole week. Evidence: the ff time
  recorded in `.syndicate/deploys.md`, the sidecar's mtime, and no revert of the file on main or on the fleet
  checkout in the window. A week that fails (d) is excluded BY NAME. It is never mixed into the graded set.

## Method

Unchanged from #752 (`39fe2d752`): `scripts/nfl_segment_skill.py` as on main at run time.
- Market: each book's LAST pregame two-sided pair, de-vigged proportionally; the consensus line (most books, ties
  to the median); the market probability is the mean of the de-vigged books at that line.
- Model: production's `probability_above` over the sidecar histogram; home/over side, line in the away frame;
  h2h = segment margin > 0; h2 = q3 + q4 + OT; pushes dropped.
- Unit: game x segment x market. Families: totals, spreads, h2h, each pooled over h1/h2/q1-q4.
- dBrier = Brier(model) - Brier(market); 95% CI by game-clustered bootstrap, 2,000 reps, seed 752.
- Verdict: beats if the CI's upper bound < 0, loses if its lower bound > 0, else parity (stated with n).

## Gates

**G1 — the new profile against the market (weeks 11-13 alone).** Per family, the dBrier and verdict above, on
the SERVED sidecars. Weeks 7-10's old-profile numbers are reported beside it, never pooled with it: the profiles
differ.

**G2 — the profile A/B on the same games (#808's market test).**
- Both arms are rebuilt in research through production's `build_projection`, with the
  `scripts/football_scenario_rates.py` harness on a private root pulled after week 13.
  - Each week is as-of `before_week`.
  - Seeds 1..`SEEDS_PER_GAME`, PYTHONHASHSEED=0, Idle priority.
  - The segment block comes from production's `FootballSegmentAccumulator`.
- Arm NEW reads the profile file. Arm OLD reads the in-source default
  (`SYNDICATE_CALIBRATION_PROFILE_PATH_NFL` at a path that does not exist).
- Both arms are priced at the same consensus lines as G1.
- Reproduction check, reported first: how many games' NEW-arm blocks equal the served sidecar's. If inputs differ
  (injury or roster snapshots of the day), say how many and why. G2 uses the rebuilt pair only.
- d = Brier(NEW) - Brier(OLD) per family; 95% CI by game-clustered bootstrap, 2,000 reps, seed 808.
- Verdict: better if the CI's upper bound < 0, worse if its lower bound > 0, else no detectable difference.
- Per-segment ds are reported, not gated.

**G3 — engine read, reported, not gated.** The sim's quarter shares (both arms) and the actual shares on these
games, beside the league's 2022-25 CIs.

## Predictions, registered now

| # | prediction |
|---|---|
| P1 | G1 totals and spreads: parity (the CIs span 0) at n of about 43. |
| P2 | G1 h2h: the point estimate is below weeks 7-10's +0.0123. |
| P3 | G2 totals: d < 0 in point estimate, with q2 and q3 the most improved segments. P(CI upper < 0) about 0.3. |
| P4 | G2 spreads and h2h: no detectable difference. |
| P5 | G3: arm NEW's q2 and q3 shares fall inside the league's CIs; arm OLD's do not. |

**Falsification of #808's segment claim:** G2 totals reads WORSE (the CI's lower bound > 0).

## What the result is allowed to change

- **Nothing is changed by the run itself.** The run writes results here, plus the todo, the log and a deploys.md
  READING.
- **G1's verdicts** may replace the NFL segment entries in `measured_market_skill` (today: weeks 7-10's, h2h rank
  x0.962). That is a code change and a load: the user's call after the read.
- **If G2 reads WORSE on any family,** the profile goes to the user for review. The off switch is removing
  `data/calibration/nfl_profile.json` in a commit, then an ff and a drained refresh-worker restart.
- **NCAAF (#805) is out of scope:** its profile stays OFF.

## Data (copied read-only from the fleet at run time, never written back)

- Quotes: `~/syndicate-prod/data/nfl_source/tracking/book_quotes/2026-11-19 .. 2026-12-07` (`.jsonl.gz`).
- Sidecars: `~/syndicate-prod/data/nfl_source/smartsim2_segment_distributions_2026_wk11..13.json`. The exact path
  is whatever `nfl_artifact_output_root()` resolves on the fleet; confirm it before copying.
- Linescores: ESPN, cached to a json.
- The private root for G2: the same pull recipe the #808 held-out used for `C:\tmp\football_scenarios\nfl_root_2026`.
