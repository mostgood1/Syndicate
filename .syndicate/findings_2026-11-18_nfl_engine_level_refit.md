# NFL level re-fit on honest seeds: touchdown_weight_multiplier 0.825 -> 0.925 (candidate on a branch, NOT loaded)

Lane `nfl-engine-level-refit`, session 8062940b, 2026-11-18 (user: "Yes, re-fit it"). Todo `#813` part 3.
Pre-registered on main `b4272102b` before any arm ran. Harness and outputs: `C:\tmp\nfl813refit\` (`refit.py`,
`smoke.py`, `analyze_refit.py` which imports #808's own `analyze.py`, `hold_read.py`, each arm's `.jsonl`).
Candidate: branch `refit/nfl-level-t0.925` at `12034bf24` (`data/calibration/nfl_profile.json` +
`tests/test_nfl_calibration_profile_artifact.py`). **Nothing on main or on the fleet changed.**

## Why a re-fit

The loaded profile `nfl-808-v3h0.03-t0.825` chose its touchdown multiplier on #808's FIT, whose 136 games all
shared seeds 1..100. Those seeds read about +1.9 points a game over the long run (`findings_2026-11-17_nfl_engine_level_2026.md`).
So the multiplier was fitted to bring an inflated reading down to the league.

## Design (as pre-registered)

- **Lever:** `touchdown_weight_multiplier` only. The seven #808 switches and `home_field_bonus` 0.03 are unchanged.
- **Seeds:** every game on its own block, base = first 4 bytes of sha256('nfl-level-refit|' + game_id) masked to 31
  bits; seeds base+1..base+100 (FIT), base+1..base+1000 (held-out). The same blocks in every arm (paired). Done by
  wrapping the generator's `simulate_game` in the research process; production code is untouched.
- **FIT:** #808's 136 games (every 4th completed 2024-25 REG game), #808's league targets, R2 objective and gates
  (imported from `C:\tmp\football_eoh_fix\analyze.py`).
- **Pick:** the lowest-Q point passing G1-G4 (G5 reported); if none passes, the lowest Q, reported as a FIT FAIL.
- **Held-out:** 2026 wk9+ completed REG games, candidate vs the loaded t0.825, 1000 seeds a game; recommend only if
  none of HB-ML / HB-TOT / HB-SPR is shown worse.

## Harness gate (before any arm was read)

- On the shared seeds 1..100 (`REFIT_SHARED=1`), the harness reproduces #808's stored `fit_v3h0.03_t0.825` rows
  exactly on 3 of 3 games, quarter logs included.
- The profile resolves to the loaded artifact with only the multiplier overridden.
- Per-game seeds land on base+1..base+N (checked); 136 distinct seed blocks per arm.

## Data coverage

- FIT: primary mirror `pbp_2023/2024/2025.csv` (the files #808 read; FIT reproduction exact).
- Held-out: fleet `pbp_2025.csv` + `pbp_2026.csv` (copied 11-18 07:46 CST; the fleet rewrote pbp_2026 at 04:00) and
  `schedules_games.csv` (11-17 22:29). Completed 2026 REG games run through week 10, so the held-out is weeks 9-10:
  **29 games**, all with a close. 2026 wk1-8 was spent by #808. Weeks 9-10's aggregate final total was seen in the
  diagnosis (2026 to date 46.17 over 149 games), but nothing was tuned on it.

## FIT (136 games x 100 per-game seeds; league q1 8.93 / q2 14.02 / q3 9.50 / q4 13.17, regulation 45.62)

| arm | q1 | q2 | q3 | q4 | regulation | Q | gates failed |
|---|---|---|---|---|---|---|---|
| default profile | 9.27 | 12.39 | 10.36 | 12.16 | 44.18 | 55.27 | G1 q2/q3/q4, G2, G3, G4, G5 |
| **t0.825 (loaded)** | 8.89 | 13.78 | 8.92 | 12.50 | **44.08** | 10.18 | **G1 q3, G1 q4** |
| t0.875 | 9.03 | 13.94 | 9.02 | 12.64 | 44.63 | 6.42 | G3 |
| t0.900 | 9.10 | 14.03 | 9.15 | 12.72 | 44.99 | 4.29 | G3 |
| **t0.925 (pick)** | 9.16 | 14.10 | 9.26 | 12.83 | **45.35** | **2.93** | **G3** |
| t0.950 | 9.25 | 14.16 | 9.30 | 12.91 | 45.63 | 3.23 | G3 |
| t0.975 | 9.33 | 14.27 | 9.43 | 13.06 | 46.09 | 3.70 | G3, G5 |
| t1.025 | 9.44 | 14.48 | 9.58 | 13.21 | 46.71 | 7.25 | G1 q1, G3, G5 |

- Paired against t0.825, t0.925 adds +1.28 [+1.09, +1.46] points a game (q4 +0.34 [+0.22, +0.45]).
- **On honest seeds the LOADED profile fails its own G1 on q3 (8.92 vs [9.01, 10.00]) and q4 (12.50 vs [12.54, 13.84]).**
- **G3 (Q2 last-120 s snaps) as registered: FAIL at every t >= 0.875.** It reads 10.87-10.88 with a 95% CI of about
  +-0.04 (t0.925: 10.875 [10.835, 10.912]) against the league's upper bound 10.862, and it is flat in t (10.85 at
  0.825). So the pick is the lowest Q, t0.925, a **FIT FAIL on G3 alone**, a gate the lever does not move.
- t0.950 lands on the league's regulation total (45.63) but the quarter-weighted Q prefers t0.925.

## Held-out (2026 wk9-10, 29 games x 1000 per-game seeds; t0.925 minus the loaded t0.825)

| | cand - prod | 95% CI | Brier prod / cand |
|---|---|---|---|
| HB-ML | +0.0021 | [-0.0020, +0.0061] | 0.1839 / 0.1860 |
| HB-TOT | -0.0113 | [-0.0257, +0.0038] | 0.2313 / 0.2200 |
| HB-SPR | -0.0012 | [-0.0065, +0.0039] | 0.2639 / 0.2626 |

- **Rule: PASS, none shown worse.** At n = 29 the read rules out only large harm; nothing here is significant.
- Total signed error, sim minus real: prod -2.59 [-7.44, +1.99], cand -1.25 [-6.10, +3.34].
- |sim total - close total|, cand minus prod: -0.080 [-0.561, +0.387].

## The candidate

- `data/calibration/nfl_profile.json`: version `nfl-813-refit-v3h0.03-t0.925`, `touchdown_weight_multiplier` 0.925,
  `fit_from` rewritten with the numbers above.
- `tests/test_nfl_calibration_profile_artifact.py`: the pin moves to the new version and value.
- 187 tests pass across the 13 files that touch the NFL profile, the live re-sim and the end-of-half mechanisms (Idle).

## Loading it (the user's call; a BETTING CHANGE)

- Same path as lane `nfl-profile-load`: land the branch commit on main, a claimed fleet ff to that exact SHA, then a
  claimed and drained refresh-worker restart, because the live re-sim resolves the profile in-process at import.
  The pregame generator runs as a fresh subprocess, so it picks the file up at its next launch; week 11's projection
  would need a rebuild to show it before TNF.
- It moves NFL live moneyline pricing (through the live re-sim) and the displayed pregame totals.
- Timing: TNF 11-19 carries three owed #813 readings, scheduled for 11-20. Loading after them keeps those readings
  about the changes they were set up to measure.
- After a load: re-run the #780 NFL live width fit; the #752 segment re-grade restarts its clock.

## Not done

- The engine's level is fixed through one lever. Which rates carry the original 2.3-point miss (drive success, TD vs FG,
  pace) was not decomposed.
- NCAAF and other sports' harnesses that share a seed list were not surveyed (lead recorded 11-17).
