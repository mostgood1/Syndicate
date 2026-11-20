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
