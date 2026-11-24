# NCAAF live full-game spreads: re-fitting the RAW probit scale k (todo #780, lane `ncaaf-raw-spreads-k-refit`, 2026-11-24)

- **Lane** `ncaaf-raw-spreads-k-refit` (takes over the CLOSED `live-margin-prob-scale`), session 6bcf0cef.
- **Asked by** session 4f0a5e3e: re-fit `live_gameline_join._SPREADS_PROB_SCALE_BY_SPORT["ncaaf"]` (1.80, fitted on
  ledger dates through 11-12, loaded 20:18:40Z 11-13) and decide by #780's own rule whether to change it.
- **Trigger:** the t859s replay (`.syndicate/findings_2026-11-20_ncaaf_margin_aware_endgame.md`, "SPREADS-k RE-FIT
  RESULTS") fitted the RAW k at 2.314 on 24,316 tick-joined states / 127 games (11-09..11-23), with its walk-forward k
  at 1.73 / 1.77 / 1.93 / 2.44 over its last four dates.
- **Not touched:** `_SPREADS_PROB_SCALE_ANCHORED_BY_SPORT` (lane `ncaaf-margin-aware-endgame`, fitted 2.37).
- **Nothing changes on the fleet.** A value change would be a BETTING CHANGE: branch-only or default-off, and loaded
  only in a betting-change window on the user's yes.

## PRE-REGISTRATION — written 2026-11-24 2:23 PM CST, before any outcome after 11-12 was read

### What was read before this was written

- **The instrument** (`C:\tmp\t780k_ncaaf\instrument.py` -> `out\instrument.txt`; reads no outcome). Every NCAAF
  full-game spreads row on the fleet, 10-01..11-21 (39 ledger files; nothing after 11-21, since 11-22 / 11-23 had no
  games):
  - `sims_run` is 120 on every row.
  - Every row with a market price was point-estimated. Before the load, `model_home_win_prob` equals
    `agresti_coull_point(model_home_win_prob_raw, 120)` on every such row.
  - After the load (11-14..11-21, 27,349 rows), `model_home_win_prob_unscaled == agresti_coull_point(raw, 120)` and
    `model_home_win_prob == scale_prob(unscaled, 1.8)` on every row; the worst error is 0.0. Every one is at k 1.8.
  - Every row WITHOUT a market price holds the raw share k/120: it was refused before the point estimator. None is
    exactly 0 or 1.
- **The trap this exposes.** `scripts/live_totals_width_fit.py` reads `model_home_win_prob`. Since the 11-13 load
  that is the TEMPERED number on every NCAAF spreads row that reached the pricer. Re-run unchanged, #780's script fits
  k on numbers that k 1.80 has already tempered. It is reported below as TRAP, and gates nothing.
- **P0, the reproduction gate** (`out\p0.txt`): PASS. The kit, in "recorded" mode on ledger dates <= 11-12, reproduces
  the shipped fit exactly: 93,683 graded states / 325 games, k 1.797, walk-forward -0.006 +- 0.004 over 27 dates
  (-0.00571, se 0.00192), and model - market -0.003 -> -0.008. Its output is identical to the export's own
  `wf.report`. Those outcomes were already published (the 11-13 findings); no outcome after 11-12 has been read.

### Method (#780's own: `live_totals_width_fit.py`, `MARKET=spreads SPORTS=ncaaf`)

- **Kit:** `C:\tmp\t780k_ncaaf\fit.py`. It carries `wf.load` verbatim except for its window arguments and ONE line:
  which probability it reads (`psrc`).
- **Population (P-ALL, #780's):** NCAAF full-game spreads ledger rows with a model probability and a line, priced or
  not. One row per (event, `live_state_as_of`, line), first seen. Graded against ESPN finals in the ledger's home
  orientation; pushes, ambiguous orientations and score > final are dropped and counted.
- **Window:** every ledger date, 10-01..11-21.
- **Instrument (PRIMARY, I-AC):** the number the pricer applies k to:
  - `model_home_win_prob_unscaled` where it is present;
  - the recorded number where the row was point-estimated;
  - otherwise the join's own `agresti_coull_point(share, sims_run)`.
- **Fit:** the log-loss probit k on [0.70, 3.00], `P_k = Phi(Phi^-1(P) / k)`.
- **Walk-forward:** by ledger date from the 3rd date. Fit on every earlier date, score the next. The Brier change is
  taken against k = 1, game-clustered 95% (`live_totals_grade.cl_mean` / `fmt`).

### RULE (gated; #780's, as written in `.syndicate/findings_2026-11-13_live_margin_width_fit.md`)

- **The rule:** k = the fitted k (2 dp) when BOTH hold:
  - the walk-forward one-k gain is <= -0.003 Brier;
  - model - market at the fitted k is not worse than at k = 1 (point estimates).
- **Otherwise** k = 1.00.

### Change decision (gated; added here because what is served is now 1.80, not 1)

- **C2, the post-ship comparison:** on ledger dates >= 11-14, every NCAAF spreads row with a market price was served
  at 1.80. Each such date is scored by the walk-forward re-fit k, trained on every earlier date, minus the served
  1.80 (Brier, game-clustered).
- **The verdict:**
  - **KEEP-1.80** when the rule's k rounds to 1.80, or when C2's point estimate is >= 0 (the re-fit does not beat what
    is served, out of sample).
  - **CHANGE-TO-<k>** when the rule passes, its k differs from 1.80, and C2's point estimate is < 0. Whether C2's
    interval excludes 0 is reported as the strength of the case.
  - **REVERT-TO-1.00** when the rule fails. That is flagged, not acted on: it would untemper NCAAF spreads and needs
    its own read.
- **A CHANGE goes only to a branch:** the NCAAF entry of `_SPREADS_PROB_SCALE_BY_SPORT` and its tests, queued for a
  betting-change window on the user's yes. An ff ships all of main, so it does not land on main before its window.

### Reported, not gated

- **S1 P-MKT:** rows with a market price only (the pricer's population; all AC points).
- **S2 I-REC:** `P_SOURCE=unscaled`. This is #780's script with the one fix a post-load re-fit needs. Rows without a
  market price stay raw shares.
- **S3:** t859s's window, 11-09..11-21, on I-AC and P-ALL. A substrate check against its 2.314.
- **S4:** the shipped fit's window (<= 11-12), on I-AC instead of as recorded.
- **TRAP:** #780's script unchanged, on every date.
- **The extras:** the per-progress-bucket k; the all-dates k minus 1.80 on the C2 states (in-sample); model - market
  on the C2 states.

### Predictions (not gates)

- **Q1:** the primary k is in [1.85, 2.15]. The post-ship dates pull it up from 1.80 and October holds it down.
- **Q2:** the rule passes.
- **Q3:** C2 is within +- 0.002 and its interval spans 0. The walk-forward k entered 11-14 near 1.8, so most post-ship
  states are scored near the served value.
- **Q4:** S3 is in [2.1, 2.5], near t859s's 2.314.
- **Q5:** the TRAP k is well below the primary k.
- **Q6:** S4 is below 1.797, because the AC point is less extreme than the raw share it replaces on rows without a
  market price.

### Substrate notes

- **The engine:** no default-on NCAAF live engine change loaded in the window. #852 damping and #859's end game are
  DEFAULT OFF; the total-level shrink has been held at 1.0 since 10-03 (`git log` on `ncaaf/live_resim.py`,
  `game_simulator.py`, `smartsim2_projection.py`). The in-season blend ratings update weekly by design.
- **Population moves:**
  - #801 (11-14 19:29Z): evening kickoffs gained a projection, so after it they gained a market price.
  - The 120 s quote ceiling (11-11 18:11Z) changes which rows are PRICED, not which rows the fit reads.
- **Dates:**
  - 11-03..11-06 and 11-10..11-13 hold only rows with no market price (weeknight evening games before #801).
  - 11-14 and 11-21 are the two Saturdays after the load (9,966 and 13,796 rows).

### Pins (sha256, first 16; full list `C:\tmp\t780k_ncaaf\pins.sha256`; code = export of main `5e794e752`)

| file | sha256 |
|---|---|
| `fit.py` | `cafff9f7118273f9` |
| `instrument.py` | `40122be25cafc139` |
| `code/scripts/live_totals_width_fit.py` | `09c40c044bce58cb` (= t859s's pin) |
| `code/scripts/live_totals_grade.py` | `ab6c3fc85ef06647` (= t859s's pin) |
| `code/syndicate/features/shared/live_gameline_join.py` | `eafca9127518b871` (= t859s's pin) |

Run: `wsl -d Ubuntu-24.04 -- env T780K_MODE=full nice -n 19 /home/amyn/.venvs/syndicate/bin/python
/mnt/c/tmp/t780k_ncaaf/fit.py` -> `C:\tmp\t780k_ncaaf\out\full.txt`.
