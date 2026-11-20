# smartsim2 college overtime (todo #855, lane `ncaaf-college-overtime`, 2026-11-20)

Started from #852's follow-ups (`findings_2026-11-19_ncaaf_live_endgame_surplus.md`): the engine's overtime scores
3.6 points per OT game against a real 12.4, which pulls late one-score NCAAF live totals low. The user answered "Lend it,
start OT (Recommended)" and "Extend the loan (Recommended)". The loan from `football-scenario-calibration` covers
`game_simulator.py`'s overtime block and `calibration_profile.py`'s one new field plus its `to_dict` entry (lanes.md,
main `f6f93c040`). Kit: `C:\tmp\t855`.

## Measured inputs (CFBD 2023-24 FBS-vs-FBS regular season, local mirror; `real_ot.py`, `real_ot.txt`)

| quantity | real |
|---|---|
| OT games | 65 of 1,502 (4.3%) |
| OT points per OT game | **12.40 [95% 10.62, 14.23]**, median 9 |
| OT periods | 1: 41, 2: 20, 3: 1, 4: 2, 8: 1 (3 or more: 0.062) |
| possessions from the opponent's 25 (135) | TD 0.556, FG 0.207, missed FG 0.074, turnover 0.052, downs 0.007, other 0.104 |
| two-point tries (801, TD play text, all games) | good 0.451 |

**The engine today** (`game_simulator.py` OT block): possession goes to the other team at its OWN 25. One drive a
round, sudden death, two rounds at most. That gives 3.6 points per OT game from late close states (#852).

## PRE-REGISTRATION — written 2026-11-20 before any code or engine run of the new block

**The change: ONE switch, `CalibrationProfile.college_overtime: bool = False`** (plus its `to_dict` entry).
- **OFF:** the existing OT block runs unchanged, byte-identical. Pinned before the edit: sha256 over
  `simulate_game(...).to_dict()`, seeds 1..20.
  - `ncaaf_pregame` `2b2b1a67…` (equal to #808's pin, so the method reproduces);
  - `ncaaf_tied_late` (Q4 0:20, 24-24) `2528c374…`;
  - `nfl_tied_late` `c0d7eb8f…`.
- **ON, when regulation ends tied:**
  - **Periods 1 and 2:** each team gets one possession from the OPPONENT's 25 (`field_position` 75, 1st and 10,
    `quarter` 4 + k, clock 900 so no clock ends a drive). The first possessor in period 1 is a coin flip from the
    sim's own rng, and the order alternates each period.
  - **Two-point try:** in period 2 a touchdown scores 6 plus a try that is good with p = 0.451 (measured), instead
    of the engine's 7.
  - **From period 3:** alternating two-point attempts, one each, good with p 0.451.
  - **The game ends** when the scores differ after both teams' turns. Cap: 12 periods (then it stays tied).
  - **Accepted approximation:** the drive logic is the engine's own (no `drive_simulator` edit is lent). So a second
    team trailing by 4+ may still kick a field goal. H-DRIVE measures what that costs.

**Hypotheses.**
- **H-RULES:** the 3.6 vs 12.4 gap is the rules, not drive efficiency.
- **Rival H-DRIVE:** the engine's short-field efficiency is itself off.

**M1 (the gate for H-RULES)** — the 65 real OT games, resumed at the end of regulation tied:
- **Setup:** `initial_quarter` 4, `initial_clock_seconds` 0; season SP+ ratings with the live shrink, as in #852's
  harness; 1,000 sims a game on the game's own seed block.
- **Engine read:**
  - OT points per OT game against the real CI [10.62, 14.23];
  - the share of games needing a 3rd period against 0.062 (falsified outside 0.031-0.124);
  - per possession from the 25, P(TD) / P(FG) against 0.556 / 0.207.
- **H-RULES is FALSE** if points per OT game fall outside the CI or the 3+ share falls outside its band. H-DRIVE is
  then read from the per-possession shares.

**M2 (what it does to the late live totals):** the #852 2024 harness, Q4 checkpoints, the first 150 games of the
every-2nd task list, 60 sims a state, paired seeds.
- The rest-of-game change and engine-minus-actual by |margin|.
- Common-line log loss against the real final, at |m| <= 8 and overall, against production.

**Predictions** (written before any run).
- **M1:**
  - points per OT game 11.0-13.5;
  - 3+ share 0.04-0.10;
  - P(TD) per possession 0.45-0.65.
- **M2:**
  - at |m| <= 8, rest-of-game up +0.2 to +0.5 at Q4 15:00 and +0.4 to +1.0 at Q4 3:00;
  - |m| >= 17 unchanged within 0.05;
  - log loss at |m| <= 8 lower than production by at least its paired SE at Q4 3:00.

**Scope.**
- Engine mechanism plus tests only.
- The push to main is the user's call.
- Live use (a switch in the NCAAF live re-sim, as #852) is a separate decision.
- Pregame use would add about +0.4 points a game (4.3% x ~8.8), so it would need a level re-fit first
  (`model_engine_standard.md` 4.4). It is not proposed here.

## RESULTS (written after the runs; nothing above was changed)

### Verdict: H-RULES TRUE. M1's gate passes, and M2's predictions all hold. ON MAIN `42af6a923` (user "Push it"), default off, not used by any profile.

**The code** (worktree `frosty-edison-10dcd8`, under the loan; the commit is below):
- `calibration_profile.py`, +9 lines: the `college_overtime` field and its `to_dict` entry.
- `game_simulator.py`, +67 / -1: `_college_overtime`, the switch's branch in front of the unchanged old block, and
  two measured constants. A period-2 touchdown's try is written into the drive and step logs too, so the logs sum to
  the score. The first test run caught that the logs did not.
- `tests/test_smartsim2_college_overtime.py`, 12 passed:
  - reachability: OFF equals the three pre-change digests; ON changes a tied game;
  - a game not tied at the end of regulation is identical on and off;
  - the rules: both teams possess in period 1 from the opponent's 25; the order alternates; a period-2 TD is 6 or 8,
    never 7; overtime always ends decided; from period 3 only twos score; the cap holds.
- **Neighbouring suites:** 189 passed. They include #808's own pinned digests, the profile key-set tests, NFL live
  timeouts and the NCAAF live re-sim suites.

**M1, the 65 real OT games of 2023-24, 600 sims each, production profile** (`C:\tmp\t855\m1_ot.py`, `m1_ot.txt`):

| | OT points per OT game | 3rd period needed | possessions from the 25: TD / FG / none |
|---|---|---|---|
| real (CFBD) | **12.40 [10.62, 14.23]** | 0.062 | 0.556 / 0.207 / 0.237 |
| engine OFF (today) | 3.73 | 0.000 | 0.288 / 0.081 / 0.632 (from its OWN 25) |
| **engine ON** | **13.87** | **0.112** | **0.593 / 0.194 / 0.213** |

- **The gate passes:** 13.87 is inside the real CI, and 0.112 is inside the registered band 0.031-0.124.
- **H-RULES is TRUE.** H-DRIVE is small: the engine's touchdown rate from the 25 is 3.7 points (of share) above the
  real one.
- **Prediction misses, reported:** points 13.87 against the predicted 11.0-13.5, and the 3+ share 0.112 against
  0.04-0.10. Both lean high, consistent with the slightly high touchdown rate. The second team's kick when trailing by
  4+ is not the cause: it would push the other way.
- **Prediction held:** P(TD) 0.593, inside 0.45-0.65.

**M2, the 2024 harness, the first 150 games of the every-2nd list, Q4 checkpoints, 60 sims, paired**
(`m2_read.py`, `m2_read.txt`). Rest-of-game, ON minus OFF:

| \|margin\| | Q4 15:00 | 10:00 | 6:00 | 3:00 |
|---|---|---|---|---|
| 0-8 | **+0.50** (se 0.08) | +0.73 | +0.90 | **+0.99** (0.21) |
| 9-16 | +0.19 | +0.17 | +0.03 | 0.00 |
| 17+ | **+0.00** | 0.00 | 0.00 | 0.00 |

Common-line log loss against the real final, ON vs production:

| | log loss | vs production (se) | slope | rest engine / actual |
|---|---|---|---|---|
| Q4 15:00-6:00, all | 0.6101 | -0.0062 (0.0041) | 0.69 -> 0.73 | 1.020 -> 1.049 |
| Q4 15:00-6:00, \|m\| <= 8 | 0.6836 | -0.0135 (0.0104) | 0.57 -> 0.60 | 0.843 -> 0.897 |
| **Q4 3:00, \|m\| <= 8** | **0.7410** | **-0.0718 (0.0449)** | **0.26 -> 0.41** | 0.630 -> 0.778 |
| Q4 3:00, all | 0.5930 | -0.0244 (0.0154) | 0.43 -> 0.50 | 0.864 -> 0.942 |
| \|m\| >= 17 | unchanged | 0.0000 | | |

- **All three M2 predictions held:**
  - +0.50 and +0.99 sit at the edges of the predicted +0.2-0.5 and +0.4-1.0;
  - 17+ is unchanged;
  - one-score log loss at Q4 3:00 is lower by 1.6 paired SE.
- **What is left in one-score games** is the last two minutes: the engine gives 2.31 points against a real 3.58,
  unchanged by OT. That is #808's end-game clock (#852's follow-up); one-score engine-minus-actual is still -1.0 to
  -2.1.

### What it would take to use it (the user's calls)
1. **The push to main: DONE, `42af6a923`.** Default off and byte-identical, so it changes nothing on the fleet.
2. **Live use**, the natural use, where it closes the OT half of #852's one-score gap.
   - An NCAAF live switch (as #852's damping: profile resolution in `resim_live_game`, which needs
     `live-player-exit-gate`'s loan widened, or a resolver added to `ncaaf/live_blowout_damping.py`).
   - A betting change, window only.
   - The level stays with #835's anchor. It adds about +0.4 points to E0 in the anchor's input, and the anchor
     takes that back.
3. **Pregame use** needs a level re-fit first. Not proposed.
