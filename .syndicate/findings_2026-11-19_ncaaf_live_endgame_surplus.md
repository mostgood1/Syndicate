# NCAAF live re-sim: the late "surplus" is a margin-blind end-game (todo #852, 2026-11-19)

Lane `ncaaf-live-endgame-surplus`, session 617b553b. The task came from the decision-engine session (local_c165dd50) as
#835's open lead H-ENDGAME (`findings_2026-11-19_ncaaf_live_total_dispersion.md`, "Diagnosis"). Kit (scratch,
reproducible): `C:\tmp\t852`. The #835 kit `C:\tmp\t835` was copied from, never edited. In the repo, only this file,
`lanes.md` and the #852 todo section were edited. No engine file was touched, nothing was pushed as code, nothing loaded.

**M2 discipline.** Nothing from slates 11-15..11-22 was read. `C:\tmp\elp\m2gate_kit\test` / `out` and
`C:\tmp\elp\m3_kit\live` were never opened. The ledger extracts are the dev Saturdays 10-24 / 10-31 / 11-07 / 11-14,
each from its own date's ledger file; 11-15's evidence file was not opened.

## Verdict

**The brief's premise is half right.** smartsim2's NCAAF end-game IS wrong, but not as a uniform late surplus, and not
mainly through #808's missing mechanisms.

1. **The engine's late scoring is blind to the score margin.** Resumed at a real Q4 state it expects about the same
   points left whether the game is a one-score game or a 30-point rout. Real games do not.
   - **Blowouts run OVER, and it is the LEADER.** A team ahead by 17+ keeps scoring at its full rate. Real leaders
     ease off.
   - **One-score games run UNDER, and it is the TRAILER** (too few snaps in the last two minutes) **plus overtime**
     (the engine's OT is one drive from the team's OWN 25, sudden death, two rounds at most: 3.6 points per OT game
     against 12.4 in real NCAAF).
   - The two cancel in the mean (2024: engine minus actual rest-of-game -0.01 at Q4 15:00; the 2026 ledger at 75-95%:
     +0.48, se 0.54), so a mean-only reading sees nothing. They do not cancel in the calibration slope.
2. **The +2.0 to +2.2 late gap to Kalshi on 11-14 is the blowouts.** Re-sim minus Kalshi at 75-95%: +0.45 in one-score
   games, +1.95 at 9-16, **+3.33 at 17+** (11 games). Kalshi prices the slowdown; the engine does not.
3. **#808's seven switches are reachable but are the wrong lever here.** They add +1.1 to +1.3 points of rest-of-game
   at EVERY margin. That fixes one-score games' last two minutes and makes blowouts worse; net worse at 75-90%.
4. **#686's existing default-off leader-only `blowout_damping_strength` is the lever.** At 0.9 (its default shape,
   untuned) it lifts the 2024 late calibration slope 0.67 -> 0.77 and log loss -0.026 (se 0.0075) on common lines.
   On the 2026 ledger finals at 75-95%, on top of #835's fix: log loss -0.0076 (se 0.0040), slope 0.84 -> 0.89, pace
   1.105 -> 1.082 against an actual 1.065. All of it comes from leads of 17+.
5. **BUILT, DEFAULT OFF, ON MAIN `44184da1e` (user "Build it here", then "Push it"; see "## FIX — RESULTS").**
   `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING` arms the damping for the live re-sim at the re-fitted strength 1.0 and
   threshold 17. 2024 FIT: -0.0186 vs production (se 0.0070). 2026 ledger on top of #835: -0.0086 (se 0.0038), slope
   0.84 -> 0.91. The one-score / overtime half is separate engine work.

## The brief's own instrument: 75-95% pace ratio and calibration slope against the ledger's finals (2026)

t835's finals instrument, copied (`ledger_score.py`, `ledger_score2.py`; production's raw P and its normal twin reproduce
t835's 0.45 / 0.41). The ledger records no possession, field position or down. So each arm's effect is the PAIRED
difference re-simmed at the same state with possession unknown, on the same seeds (60 sims, production's 2026 ratings
and live shrink), applied to production's recorded mean. Scored on every 2nd clocked state at 75-95% (478 states,
141 games with lines); each (game, line) counts once. Pace = engine rest / the close's even pace (ratio of means);
actual = 1.065.

**Without #835** (production as loaded):

| 75-95% | log loss | vs books (se) | slope | pace | mean F - c (se) |
|---|---|---|---|---|---|
| production (twin) | 0.696 | +0.017 (0.026) | 0.47 | 1.128 | -0.54 (0.54) |
| #808 (`eoh`) | 0.725 | +0.046 (0.031) | 0.47 | 1.262 | -1.67 (0.55) |
| damping 0.9 (`bd9`) | 0.682 | +0.003 (0.024) | 0.50 | 1.091 | -0.22 (0.53) |
| #808 + damping (`eoh_bd9`) | 0.705 | +0.026 (0.028) | 0.51 | 1.220 | -1.32 (0.54) |

**With #835's fix** (anchor (C - E0) x rho, k 1.2 -> 1.6). E0 re-taken under the arm: my E0 at production's seeds
reproduces t835's E0 on 185 of 185 games (to its 3-decimal rounding).

| 75-95% | log loss | vs prod+#835, paired (se) | slope | pace | mean F - c (se) |
|---|---|---|---|---|---|
| production + #835 | 0.6501 | - | 0.84 | 1.105 | -0.34 (0.54) |
| **damping 0.9 + #835** | **0.6424** | **-0.0076 (0.0040)** | **0.89** | **1.082** | -0.14 (0.53) |
| leads 17+ only (53 games): prod+#835 / bd9+#835 | 0.656 / 0.633 | -0.0229 (0.0127) | 1.16 / 1.10 | 1.085 / 0.983 (actual 0.763) | -2.72 / -1.85 |
| margin <= 16 only (103 games) | 0.647 / 0.646 | -0.0011 (0.0011) | 0.82 / 0.83 | 1.113 / 1.123 (actual 1.193) | +0.68 / +0.59 |

**Reading.**
- On 2026's own live states, the untuned damping moves every late number toward the finals on top of #835:
  - log loss -0.0076 (1.9 se);
  - slope 0.84 -> 0.89;
  - pace 1.105 -> 1.082 against an actual 1.065.
- All of the gain is in leads of 17+, and they are still 1.85 points over. Margins of 16 or less are untouched and still
  UNDER: actual pace 1.193 against 1.12. That half is the end-game clock and overtime, which damping does not reach.
- **Hold-out caveat.** These four Saturdays are the same dev window #835 used, and damping was not tuned on them (0.9
  is the field's own example strength). The clean hold-out is 11-21 / 11-28 after M2's verdict.

## The reframe: the ledger's finals, by margin (2026, production's own live re-sims)

The live gameline ledger (dev Saturdays 10-24..11-14), clocked by the in-play recorder (t835's `ledger_clock`), joined
to ESPN finals. One row per (game, state); SEs clustered by game. Engine = the ledger's `model_total_mean`.

| 75-95% of game time, \|margin\| at the state | games | engine rest | actual rest | engine - actual (se) |
|---|---|---|---|---|
| tie | 15 | 9.59 | 10.79 | -1.20 (1.82) |
| 1-8 | 79 | 9.71 | 10.01 | -0.30 (0.80) |
| 9-16 | 84 | 8.64 | 9.20 | -0.56 (0.90) |
| **17-24** | 58 | 9.24 | 7.12 | **+2.12 (0.94)** |
| **25+** | 32 | 9.12 | 6.26 | **+2.86 (0.96)** |

At 85-95% the same: +2.42 (0.84) at 17-24, +2.52 (0.97) at 25+, -0.77 (0.98) at 1-8.

**Pooled** (173 games, 75-95%): engine rest 9.23 vs actual 8.67 vs the close's even pace 8.16, i.e. ratio of means
1.13 (engine) and 1.06 (actual). The brief's "1.29x vs Kalshi's 0.82x" was a mean of ratios on 11-14's Kalshi-listed
games. On that same population the actual finals ran 0.87x and the slate's listed games went under, so Kalshi sat
near the finals and the engine above both.

## Where it comes from: resumed REAL states, 2024 (FIT season)

**Harness** (`C:\tmp\t852\resume.py`). Production's live path (`ncaaf/live_resim`'s rating shrink 0.3 and its loop,
`simulate_game` with the fleet's NCAAF profile `ncaaf-goal-line-refit-1`, md5 `da203b45`, copied from
`~/Syndicate/data/calibration/`). Resumed at the first scrimmage snap at or after Q4 15:00 / 10:00 / 6:00 / 3:00 of
every 2024 FBS-vs-FBS regular-season game in the CFBD mirror (726 games; 25 dropped where the plays' score disagreed
with the line score), with the real score, possession, field position, down and distance. 120 sims per state on the
state's OWN seed block (no common seed luck across games, learnings 2026-11-17), the same block in every arm.
- **Reproduction gate:** at production's seeds 1..120 the loop reproduces `resim_live_game`'s total histogram exactly
  on 20 of 20 test states.
- **Ratings:** CFBD season SP+ (hindsight). The as-of blend's PPA cache was deleted with `C:\tmp\football_scenarios`.
  A level check is in the residual below.
- **Truth:** CFBD plays (post-play scores) and line scores, including overtime.
- One state per game per checkpoint, so SEs are over games.

**Regulation points, engine minus actual, by \|margin\| at the state (450 games):**

| checkpoint | 1-3 | 4-8 | 9-16 | 17+ | all (incl. OT) |
|---|---|---|---|---|---|
| Q4 15:00 | +0.53 (1.06) | -1.80 (0.80) | -0.44 (0.78) | **+2.05 (0.58)** | -0.01 (0.40) |
| Q4 10:00 | -0.24 (0.89) | -1.10 (0.76) | -0.48 (0.65) | **+2.43 (0.49)** | +0.18 (0.35) |
| Q4 6:00 | -0.49 (0.72) | -0.86 (0.61) | -0.38 (0.58) | **+2.23 (0.37)** | +0.11 (0.30) |
| Q4 3:00 | -1.91 (0.58) | -0.84 (0.43) | -0.86 (0.52) | +0.90 (0.25) | -0.66 (0.25) |

**Who: the leader in blowouts, the trailer in one-score games** (same states, engine / actual rest points by team):

| Q4 15:00 | leader | trailer |
|---|---|---|
| 4-8 | 7.76 / 8.04 (-0.28, se 0.53) | 6.15 / 8.29 (**-2.14**, se 0.61) |
| 17+ | 9.73 / 7.52 (**+2.21**, se 0.46) | 4.90 / 5.05 (-0.16, se 0.37) |

The same split holds at 10:00 (leader 17+ +2.50 se 0.34; trailer 4-8 -1.72 se 0.61) and 6:00 (+2.05 se 0.25; -1.47
se 0.54).

**When: the windows** (from the Q4 15:00 resumes, points by the snap's clock, engine / actual):

| \|margin\| | Q4 >5:00 | 5:00-2:00 | last 2:00 |
|---|---|---|---|
| 0-8 (180) | 8.58 / 8.35 (+0.23) | 3.02 / 2.72 (+0.30) | 2.29 / 3.52 (**-1.22**, se 0.32) |
| 9-16 (105) | 8.94 / 8.57 (+0.37) | 3.05 / 3.05 (0.00) | 2.29 / 3.10 (-0.81) |
| 17+ (165) | 9.06 / 8.80 (+0.26) | 3.11 / 1.76 (**+1.35**, se 0.25) | 2.46 / 2.02 (+0.44) |
| snaps, all | 23.9 / 22.4 | 8.1 / 6.8 | **4.7 / 7.3** |

Q2's last two minutes repeat the one-score pattern (38 games resumed at Q2 5:00): 3.00 vs 4.74 points (-1.74, se
0.64) on 6.4 vs 11.6 snaps, matching #808's pregame read (2.86 vs 5.27).

**Overtime.** Real 2023-24 FBS-vs-FBS: 65 OT games of 1,501 (4.3%), 12.40 points per OT game (median 9). The engine:
3.6 points per OT game from every late close state, and P(OT) 0.026 vs 0.044 from the same states. It is the
`game_simulator.py` OT block: possession to the other team at its OWN 25 (`field_position=25`), one drive per round,
sudden death, two rounds at most. College OT starts at the opponent's 25 and gives both teams the ball.

**Inside the engine** (`step_diag.py`, Q4 15:00 states, every 5th game, 60 sims; real from `real_blowout.py`, CFBD
2023-24, 1,427 games, by the margin entering Q4):

| entering Q4 | engine leader Q4 pts | real leader | engine trailer | real trailer |
|---|---|---|---|---|
| 0-8 | 6.54 | 7.49 | 5.59 | 7.54 |
| 25+ | **11.05** | **6.88** | 4.86 | 4.80 |

- Snaps outside the last 5:00 match reality (engine ~10-12 a team at ~25 s a snap; real 11-12.5), so pace is not it.
- The blowout leader sits in `neutral_offense` from 15:00 to 4:00 and scores 7.00 points there (4.09 in a one-score
  game). `four_minute_offense` starts only at 4:00 and `end_game_preservation` at 2:30, and neither stops scoring.
  Nothing makes a team up 28 ease off, and the leader is usually the better team.
- The trailer in a one-score game gets 2.5 snaps in the last 2:00 at 12.7 s each (real 4.2 snaps): no timeouts, no
  clock stops.

## #808's switches for NCAAF: reachable, wrong direction for blowouts

Arm `eoh`: all seven #808 switches ON (`halftime_kickoff`, `q2_urgency_ignores_score`, `end_of_half_clock`,
`end_of_half_kneel_out`, `end_of_half_clock_by_need`, `q4_kick_waits`, `kneel_out_q4_only`), timeouts as the live
producer would feed them (None -> 3). Paired against production on the same 153 games, states and seeds.

- **Reachability (off != on):** rest-of-game +1.17 (se 0.04) at Q4 15:00, +1.24 / +1.22 / +1.25 at 10:00 / 6:00 / 3:00.
- **By margin, Q4 15:00:** +1.23 at 0-8, +1.10 at 9-16, +1.17 at 17-24, +1.13 at 25+. Leader +0.79, trailer +0.38.
- **One-score games improve:** last 2:00 2.33 -> 3.56 points (real 3.67); surplus -1.64 -> -0.41.
- **Blowouts get worse:** 25+ surplus +4.27 -> +5.40; their last 2:00 2.55 -> 3.67 points (real 1.24). The kneel-out
  fires only when the clock can be run out, and the added snaps go to leaders who are still scoring.
- **Net, common lines vs the real final, Q4 15:00-6:00:** log loss +0.016 (se 0.012), slope 0.67 -> 0.68,
  rest ratio 1.01 -> 1.13. At Q4 3:00 in one-score games it helps (-0.076, se 0.058), not significantly.
- The prior from #808's own NCAAF arms (its clock raises Q4 from 14.36 to 15.5) held.

## #686's leader-only blowout damping: the matching mechanism, already in the engine

`play_simulator.blowout_damping_factor` (default `blowout_damping_strength` 0.0 = exact no-op, `388527c7d`) scales the
POSSESSING team's TD / FG / explosive weights when it LEADS by more than 14, ramping with the lead (span 14) and from the
start of Q3 to the end of Q4. It was built for #686 and recorded as not fixing #686. Its own comment states the defect
measured here ("this engine scores at FULL RATE in the fourth quarter of a 30-point game").

Arms on 2024 (paired, same states and seeds; `bd9` = strength 0.9 at the default shape, untuned):

| Q4 15:00-6:00, common lines vs the real final | slope | log loss vs production (se) | rest engine / actual |
|---|---|---|---|
| production | 0.67 | - | 1.010 |
| #808 (`eoh`) | 0.68 | +0.016 (0.012) | 1.126 |
| **damping 0.9 (`bd9`)** | **0.77** | **-0.026 (0.0075)** | 0.943 |
| #808 + damping 0.9 (`eoh_bd9`) | 0.77 | -0.018 (0.010) | 1.059 |
| \|m\| >= 17 only: production / bd9 | 0.90 / 0.96 | -0.066 (0.017) | 1.385 / 1.170 |
| \|m\| <= 8 only: production / bd9 | 0.56 / 0.55 | +0.003 (0.001) | 0.836 / 0.834 |

By margin, `bd9` minus production at Q4 15:00 (202 games): 0-8 -0.04, 9-16 -0.33, 17-24 **-1.34**, 25+ **-2.64**
(25+ surplus +4.28 -> +1.65; 17-24 +0.10 -> -1.24, an over-correction). The untuned shape damps 17-24 too hard and 25+
not hard enough: strength and threshold are the re-fit levers.

## Hypotheses (written into the lane before any test) and their verdicts

- **H-OT: FALSE as stated (wrong sign).** The engine's overtime is too SMALL, not too large: 0.10 vs 0.47 points per late
  state. It is part of the one-score UNDER-shoot.
- **H-LEADER: TRUE, for blowouts.** In 17+ leads the leader carries the whole surplus (+2.2 of +2.05 at Q4 15:00).
- **H-TRAILER: FALSE for blowouts** (trailer -0.16, se 0.37), **TRUE in reverse for one-score games** (-2.14, se 0.61).
- **H-PACE: FALSE outside the last 2:00** (23.9 vs 22.4 snaps from 15:00 to 5:00, within 10%). TRUE inside it, in
  the under direction (4.7 vs 7.3 snaps).
- **H-RESUME: FALSE.** The phantom-possession variant was tested on the ledger: 116 try-pending states (a TD shown,
  its try not yet) in 85 games. There the rest is -1.18 (se 0.26) BELOW the state after the try, not +6 above it. Only
  5 of 960 late states are try-pending. A resume at the real 2024 states shows the same margin pattern as the live
  ledger.
- **H-LEVEL: FALSE for the late gap.** The late mean is near zero (2024: -0.01 / +0.18 / +0.11 at 15:00 / 10:00 /
  6:00). The error is in the margin split, not the level. (The kickoff level on 38 games with hindsight ratings read
  +3.7, se 1.9; that is #835's H-CENTRE, which the anchor handles.)
- **The brief's suspect (#808 missing) is half right.** Its clock fixes the one-score last two minutes. Its kneel-out
  does not reach blowout leaders before the last 2:00, so on its own it makes the late centre worse.

## What a fix is (the design as first proposed; BUILT afterwards, see "## FIX — RESULTS")

**Built on the user's "Build it here"** (the brief: "if the user agrees"). The measured mechanism is #686's existing
leader-only damping. It is a profile field, so a live-only fix needs no smartsim2 edit and no loan from
`football-scenario-calibration`.

**The proposed fix (default OFF, live-only):**
- **Switch.** `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING` (absent = off). On, the NCAAF live re-sim runs production's profile
  with `blowout_damping_strength` (and, if the re-fit says so, `_lead_threshold`) at the fitted values. Pregame is
  untouched.
- **Where.** `resim_live_game`'s profile resolution in `syndicate/features/ncaaf/live_resim.py`. That is a section
  disjoint from `live-player-exit-gate`'s declared one (the `key_player_out` refusal in `build_live_lens_snapshot`).
  Every caller that passes no profile picks it up, #835's E0 included, so the anchor stays consistent.
- **Reachability first.** Absent: the histogram is byte-identical at a blowout Q4 state. On: the leader's late points
  fall. Then a typo fallback, the knobs, and the tick.
- **Re-fit (`model_engine_standard.md` 4.4).**
  - Strength x threshold on 2024 FIT resumed states, scored by common-line log loss. The untuned 0.9 / 14 over-damps
    17-24 (-1.24) and under-damps 25+ (+1.65).
  - Then #835's late k re-fitted on top (env knobs).
  - Hold-out: 11-21 and 11-28 after M2's verdict.
- **Loading.** A betting change, in a window (earliest Tue 12-08), on the user's own yes. It goes WITH #835's switch:
  both shape the same late distribution.

**Not part of this fix (follow-ups, each an engine mechanism plus a re-fit):**
1. **One-score games' last two minutes.** #808's `end_of_half_clock` brings them to reality (2.33 -> 3.56 vs 3.67).
   Two conditions before any live use:
   - it adds +1.1 to blowouts, so it goes on only after (or with) the damping;
   - NCAAF live producers do not feed `initial_timeouts_*` (#808 item 2). The real-timeouts arm (`eoh_to`) was defined
     and not run.
2. **College overtime** (`game_simulator.py`, `football-scenario-calibration`'s file, so a loan).
   - Today: one drive from the team's OWN 25, sudden death, two rounds at most. That gives 3.6 points per OT game
     against 12.4.
   - Real: both teams from the opponent's 25, two-point tries from the third OT.
   - Pregame cost about -0.4 points a game (4.3% x 8.8); late in close games -1 to -3.

## FIX — PRE-REGISTERED 2026-11-19 12:50 PM CST, BEFORE any fix code or re-fit run

**Decision.** The session asked "Build the live-only leader-damping switch (default off, with a re-fit)?". The user
answered **"Build it here"**.

**The change: one switch, no new mechanism code.** #686's `blowout_damping_*` fields already exist in
`CalibrationProfile` and `play_simulator`.
- **Switch:** `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING`. Absent or unrecognised = OFF; `on` / `1` / `true` / `yes` = ON.
- **ON:** `ncaaf/live_resim.resim_live_game`, when the caller passes no profile, runs production's NCAAF profile with
  `blowout_damping_strength` / `_lead_threshold` / `_lead_span` set from the fit below.
- **Where it reaches:**
  - every production caller passes no profile (the tick's `build_live_lens_snapshot`, #835's E0, the cutoff-replay
    harness), so #835's anchor sees the same engine;
  - an explicit `profile=` is honoured unchanged;
  - pregame is untouched.
- **Knobs:** `..._STRENGTH`, `..._THRESHOLD`, `..._SPAN`. A typo, a non-finite value or one out of range falls back
  to the fitted default, never to "no damping".
- **OFF:** the resolved profile IS `NCAAF_CALIBRATION_PROFILE`, the same object. Test-pinned byte-identical through
  `resim_live_game` and through the snapshot builder.
- **Observability:** one `NCAAF_LIVE_BLOWOUT_DAMPING` print per process on first use (on, strength, threshold, span).
  The re-sim result carries a `blowout_damping` key ONLY when on, so off output is unchanged.

**The re-fit (`model_engine_standard.md` 4.4: the damping's own levers; the level stays with #835's anchor).**
- **FIT:** 2024 resumed real CFBD states (`C:\tmp\t852\resume.py`, `T852_CPS=fit`). The first 150 games of the
  every-2nd task list (the same games as the `eoh` / `bd9` arms). Checkpoints Q3 7:30, Q4 15:00, Q4 7:30, Q4 3:00
  (where the damping acts). 60 sims a state on the state's own seed block, the same in every arm.
- **Criterion:** common-line log loss against the real final, over every fit state. Lines = the production arm's own
  25 / 50 / 75% rest quantiles + 0.5. Paired against the incumbent, game-clustered SE.
- **Grid (span 14 fixed):**
  - Stage 1: threshold {10, 14, 17, 21} at strength 0.9.
  - Stage 2: strength {0.6, 0.75, 0.9, 1.0} at stage 1's pick.
- **Selection with a noise floor** (learnings 2026-11-15). The incumbent is the field's own example (0.9, 14). A grid
  point replaces it only if its paired log-loss improvement over the incumbent exceeds 1 paired SE. Among those, the
  best wins. Otherwise the incumbent stays.

**Gates.**
- **G1:** on FIT, the pick beats production on log loss by more than 2 paired SE. Else nothing ships.
- **G2:** on FIT, one-score states (|margin| <= 8) are not worse than production by more than 1 paired SE.
- **G3:** on the 2026 ledger finals at 75-95%, on top of #835 (this dev window, already read once for 0.9 / 14):
  - log loss <= production + #835;
  - the rest pace ratio closer to the actual than production + #835's.

**Predictions** (from the `bd9` arm, before any fit run).
- 0.9 / 14 over-damps 17-24 (-1.24) and under-damps 25+ (+1.65), so stage 1 lands at 14 or 17, and stage 2 at 0.9 or
  1.0.
- The pick beats production on FIT by about -0.02 to -0.03.

**Clean hold-out after M2's verdict** (11-21, then 11-28): `ledger_score2.py` on those dates. Expected:
- 75-95% log loss below production + #835;
- slope at least production + #835's;
- the 17+ bucket's mean F - c closer to 0.

**Load:** a betting change, window only (earliest 12-08), on the user's own yes, TOGETHER with #835's switch.

## FIX — RESULTS (written 2026-11-19 after the runs; nothing above the pre-registration was changed)

### Verdict: BUILT, DEFAULT OFF; G1, G2 and G3 PASS. The pick is strength 1.0, threshold 17, span 14.

**The re-fit** (`fit_select.py`; `fit_stage1.txt`, `fit_stage2.txt`): 2024 FIT, 150 games x 4 checkpoints, 60 sims,
1,563 line-records. Log loss vs each comparator, paired SE:

| arm (strength / threshold) | log loss | vs incumbent (se) | vs production (se) | \|m\| <= 8 | \|m\| >= 17 |
|---|---|---|---|---|---|
| production | 0.6289 | | | | |
| 0.9 / 10 | 0.6191 | +0.0052 (0.0025) | -0.0099 (0.0083) | +0.0045 | -0.0367 |
| 0.9 / 14 (stage 1 incumbent) | 0.6139 | - | -0.0151 (0.0071) | +0.0019 | -0.0449 |
| 0.9 / 17 | 0.6119 | **-0.0019 (0.0018)** | -0.0170 (0.0063) | +0.0005 | -0.0463 |
| 0.9 / 21 | 0.6120 | -0.0019 (0.0031) | -0.0170 (0.0054) | +0.0003 | -0.0447 |
| 0.6 / 17 | 0.6156 | +0.0037 (0.0024) vs 0.9/17 | -0.0133 (0.0045) | +0.0001 | -0.0350 |
| 0.75 / 17 | 0.6140 | +0.0021 (0.0014) | -0.0149 (0.0055) | +0.0001 | -0.0394 |
| **1.0 / 17 (PICK)** | **0.6103** | **-0.0017 (0.0012) vs 0.9/17** | **-0.0186 (0.0070)** | +0.0000 (0.0012) | **-0.0503 (0.0161)** |

- **Stage 1:** 17 cleared the 1-SE floor narrowly: -0.00191 against se 0.00176, i.e. 1.09 SE. 21 tied it inside the
  floor and stayed out.
- **Stage 2:** 1.0 cleared it at 1.4 SE.
- **G1 PASS:** -0.0186 against production, se 0.0070 (2.7 SE).
- **G2 PASS:** one-score states +0.0000 (se 0.0012).
- **Predictions:** stage 1 at 14 or 17 held (17); stage 2 at 0.9 or 1.0 held (1.0). The gain, -0.019, landed just
  under the predicted -0.02 to -0.03.
- **Caveat:** strength 1.0 is the field's upper bound. At a lead of 31+ in the game's last seconds the leader's scoring
  weights reach their 0.01 floor.

**G3 PASS: the 2026 ledger finals at 75-95%, on top of #835** (`ledger_score2_pick.txt`, the same 478 states and 141
games as above, E0 re-taken under the pick):

| 75-95% | log loss | vs prod+#835 (se) | slope | pace (actual 1.065) | mean F - c |
|---|---|---|---|---|---|
| production as loaded | 0.6961 | +0.0461 (0.0155) | 0.47 | 1.128 | -0.54 |
| production + #835 | 0.6501 | - | 0.84 | 1.105 | -0.34 |
| **pick + #835** | **0.6414** | **-0.0086 (0.0038)** | **0.91** | **1.086** | -0.18 |
| leads 17+ only (53 games) | 0.6302 | -0.0260 (0.0121) | 1.18 | 0.997 (actual 0.763) | -1.97 |
| margin <= 16 only (103 games) | 0.6462 | -0.0012 (0.0009) | 0.83 | 1.123 (actual 1.193) | +0.59 |
| pick WITHOUT #835 | 0.680 | (vs production -0.016) | 0.51 | 1.097 | -0.27 |

The 17+ bucket is still about 2 points over the finals and one-score games are still under. The damping closes part
of the blowout gap. The rest of it, and the one-score half, are the follow-ups below.

### The code (ON MAIN `44184da1e`, pushed on the user's "Push it"; default off, not loaded)

- **`syndicate/features/ncaaf/live_blowout_damping.py` (NEW).** The switch, the three knobs, and `resolve(base)`,
  which returns `base` itself when off. One `NCAAF_LIVE_BLOWOUT_DAMPING` print per process when on.
- **`syndicate/features/ncaaf/live_resim.py`**, under the user-approved loan from `live-player-exit-gate`, +13 / -1.
  `resim_live_game`'s `profile` default is now `None`. That resolves to production's profile, or the damped one
  when on. The result carries a `blowout_damping` block only when on.
- **`tests/test_ncaaf_live_blowout_damping.py` (NEW), 44 passed.**
  - Reachability first: absent equals the pre-change explicit-profile call, byte for byte. Off and 5 unrecognised
    values equal absent. On changes a blowout's histogram. Through `run_refresh_worker._run_ncaaf_live_resim_tick`, off
    is byte-identical to absent and on changes the published lane.
  - Then: the leader's margin and total fall more than 1 point at 200 sims. An explicit profile is honoured.
    #835's E0 path carries the block. Off resolves to the same object. Only the damping fields change. The factor
    damps only a leader above the threshold in the second half.
  - Switch and knob parsing, including typo, nan, inf and out-of-range fallbacks to the fitted default.
- **Neighbouring suites:** 165 passed (`test_ncaaf_live_resim`, `_wiring`, `_total_dispersion`, `_segments`,
  `_level_shrink`, `test_ncaaf_live_gameline_registration`, `_player_exit`).

### Loading (the user's yes, in a betting-change window)

- **Keys,** in `~/syndicate-prod/local_production.env` (global, so refresh-worker's tick and #835's E0 both see it):
  `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING=on`.
- **Load it WITH #835's two keys:** `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION=on` and
  `SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAF=1`. G3 was read only in that combination.
- **Re-check before the load:** #835's late k (1.6) was fitted without the damping. The damped late centre is better,
  so the late widening may now be a little wide (pick + #835 slope 0.91 overall, 1.18 in 17+). Read it on 11-21 /
  11-28.
- **Betting change: yes.** Earliest window Tue 12-08 2-7 AM CST. Drained full `down` / `up`, preflight
  `--betting-change yes`, `betting_change.py add`.
- **Verify after the load:**
  - the refresh-worker log carries `NCAAF_LIVE_BLOWOUT_DAMPING on strength=1.0 lead_threshold=17.0 lead_span=14.0`;
  - on the first Saturday, `ledger_score2.py`'s 17+ bucket pace falls toward the actual.

## Reproduction (`C:\tmp\t852`, scratch)

- **Inputs:**
  - `ledger_extract2.py` (WSL, nice 19: the fleet ledger with per-team scores);
  - `ledger_ratings.py` (production's 2026 ratings, read-only);
  - t835's `ledger_clock_*` / `ledger_inputs_*`.
- **2024 harness:**
  - `resume.py` (`verify`; `run <season> <arm> [every]`, `T852_CPS=late` for Q4 only; a harness-only faster serializer,
    output-identical on 24 of 24 states);
  - `analyze.py`, `paired_margin.py`, `calib_arms.py`, `step_diag.py`, `real_blowout.py`.
- **2026 instrument:** `ledger_replay.py`, `e0_arms.py`, `ledger_score.py`, `ledger_score2.py`, `ledger_margin.py`,
  `ladder_margin.py`, `pat_pending.py`.
- Every table above is saved as a `*.txt` beside its script.
- Windows workers ran at Idle priority (4 at a time) and the WSL reads at nice 19.

## NOTE 2026-11-20 12:50 PM CST — the hold-out runner was replaced (for the scheduled checks)

The scheduled hold-out checks (`engine-ncaaf-checks-1124` / `-1130`, lane engine-learner) run
`C:\tmp\t852\check_slate_852.sh`. They expected sha256 prefix `4d0e07ba90c0918d`. **The runner now in place has sha256
prefix `997e220ff44eb273`** (full `997e220ff44eb273f959c281dbf0b34758194b00c361e966ec3269189c8a5bdb`).

- **Pinned commit `44184da1e`:** an export of main `44184da1eb1b3597bd5c8649eaa50ee335d97f4f` (#852's switch) in
  `C:\tmp\t852\code`, recorded in `code/COMMIT`. All three code-importing steps read it, and the runner exits 5 without
  it.
- **Interpreter:** pinned to `py -3.11`. On 11-20 `py -3` began resolving to a bare Python 3.12 with no psutil.
- **Re-run on 11-14 at 12:29 PM CST:**
  - The summary's first line names the commit and Python 3.11.9.
  - Rc 0; E0 reproduction 345 match, 0 differ; **CHECK VALID**.
  - Numbers unchanged from the unpinned clean run: the pick + #835 against production + #835, -0.0176 (se 0.0095);
    slope 0.76 -> 0.88.
- **Unchanged:** usage `<date> <week> [every]`, the summary file `check852_<date>.txt` and the last-line wording.
