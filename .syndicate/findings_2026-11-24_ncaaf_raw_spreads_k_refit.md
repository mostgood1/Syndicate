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

## RESULTS — read 2026-11-24 2:41 PM CST (nothing above was changed)

The pinned run (`C:\tmp\t780k_ncaaf\out\full.txt`; every pin OK, `P0 PASS`, `FULL_END`) read the fleet's ledger at
nice 19 and changed nothing on the fleet. The ranges below are game-clustered 95% intervals.

### VERDICT: KEEP-1.80. The rule passes at k 1.87, but the re-fit does not beat the served 1.80 since it shipped.

**PRIMARY (P-ALL, I-AC, 10-01..11-21):**
- 116,788 graded states / 449 games over 37 dates. Dropped: 672 pushes, 30 with score > final, and 810 unmatched to
  an ESPN final.
- In-sample k **1.872**. Log loss 0.6829 at k = 1, 0.6629 at 1.872, and 0.6629 at 1.80: the surface is flat between
  them.
- **Walk-forward** (35 dates, 115,009 states / 444 games):
  - gain against k = 1: **-0.007 +- 0.003** (-0.00658, se 0.00161);
  - model - market: -0.001 +- 0.009 at k = 1, then **-0.008 +- 0.006** at the fitted k (94,290 states).
- The walk-forward k held **1.76-1.86 from 10-27 on**, and 1.81 entering 11-21.
- **The rule (#780's): PASS. Its k is 1.87.**

**C2, POST-SHIP (gated; 22,576 states / 121 games on 11-14..11-21):**
- The walk-forward k on those dates was 1.78 / 1.77 / 1.77 / 1.76 / 1.77 / 1.78 / 1.81.
- **Walk-forward re-fit minus the served 1.80: +0.00000 +- 0.0001 (se 0.00005).** So the pre-registered verdict is
  KEEP-1.80.
- The served 1.80 minus k = 1 on the same states: **-0.011 +- 0.006.** The shipped scale keeps paying out of sample.
- Model - market on those states: -0.004 +- 0.008 at 1.80, and the same at the walk-forward k.
- In-sample, not gated: the all-dates 1.87 minus 1.80 on these states is -0.000 +- 0.000.

**Reported, not gated:**

| read | states / games | k | walk-forward gain vs k=1 | model - market, k=1 -> k |
|---|---|---|---|---|
| S1 P-MKT (rows with a market price; all AC points) | 94,891 / 369 | 1.878 | -0.009 +- 0.003 | +0.004 -> -0.004 |
| S2 I-REC (#780's script + the unscaled read only) | 116,788 / 449 | 1.894 | -0.007 +- 0.003 | -0.001 -> -0.007 |
| S3 t859s's window 11-10..11-21 | 24,776 / 131 | 2.578 | -0.010 +- 0.008 | +0.005 -> -0.004 |
| S4 shipped window (<= 11-12) on I-AC | 93,683 / 325 | 1.775 | -0.006 +- 0.004 | -0.003 -> -0.009 |
| TRAP: #780's script unchanged | 116,788 / 449 | **1.800** | -0.005 +- 0.003 | -0.003 -> -0.007 |

- **Per progress bucket** (in-sample, P-ALL I-AC): early (< 0.40) k 2.910 on 47,937 states / 446 games; mid
  (0.40-0.75) 1.737 on 44,970 / 445; late (>= 0.75) 1.457 on 23,881 / 422.
- **S3's walk-forward path** was 3.00 / 2.32 / 2.51 / 1.75 / 1.75 / 1.71 / 1.75 / 1.91 / 2.38: the same volatility
  t859s saw (1.73 / 1.77 / 1.93 / 2.44).

### Predictions

- **Q1 HELD:** 1.872 is in [1.85, 2.15].
- **Q2 HELD:** the rule passed.
- **Q3 HELD:** C2 is +0.00000 and its interval spans 0.
- **Q4 FAILED, just above:** S3 is 2.578, against [2.1, 2.5]. It is the same high reading as t859s's 2.314 on a
  different population: t859s used tick-joined states only and read through 11-23.
- **Q5 HELD IN DIRECTION ONLY:** TRAP 1.800 against 1.872. Post-ship rows are 19% of the states, so on all dates the
  trap moves k little. On a post-ship-only window it would divide k by about 1.8.
  - **The trap reads exactly the shipped 1.800.** A naive re-run of #780's script would have "confirmed" 1.80 for the
    wrong reason.
- **Q6 HELD:** S4 is 1.775, below the recorded 1.797.

### Why the short window reads high: one Saturday, inside the date-to-date noise (POST-HOC, gates nothing)

`C:\tmp\t780k_ncaaf\posthoc_dates.py` (sha256 `dd594fea23d96f47`, written after the results were read) ->
`out\posthoc_dates.txt`, P-ALL I-AC:

- **Each Saturday alone:**

  | Saturday | k | games |
  |---|---|---|
  | 10-03 | 1.33 | 50 |
  | 10-10 | 1.36 | 42 |
  | 10-17 | 2.15 | 46 |
  | **10-24** | **3.00** | 41 |
  | 10-31 | 1.58 | 44 |
  | 11-07 | 1.30 | 46 |
  | 11-14 | 1.63 | 53 |
  | **11-21** | **2.81** | 56 |

  A single Saturday has ranged 1.30-3.00, and the bound was hit before the load (10-24). 11-21's 2.81 is inside that
  spread. October and November show no trend.
- **Weeknight dates** (1-6 games each) sit at the fit's bounds about as often before the load as after it:
  - k 3.00 on 10-08, 10-15, 10-22, 10-23, 10-29, 10-30, 11-03, 11-04, 11-10, 11-11, 11-13, 11-18, 11-19 and 11-20;
  - k 0.70-1.03 on 10-02, 10-13, 10-20, 10-27, 11-05, 11-06 and 11-12.
- **Leaving dates out:**
  - all dates without 11-21: k **1.815**;
  - the post-ship dates alone: k 2.584 (22,576 states / 121 games); without 11-21, 2.364.
- **So the "rising k":** t859s's 1.73 -> 2.44, and S3 here, are short windows that two Saturdays and a handful of
  one-game weeknights dominate. On every date, 11-21 moves k from 1.815 to 1.872, and the walk-forward never left
  1.76-1.86 after October.

### What this does not show

- **C2 has little power here.** It can tell a re-fit from 1.80 only when the walk-forward k has moved away from 1.80,
  and it never did. C2 = 0 says that re-running #780's method date by date would not have changed the served number.
  It does not say that a much larger k (2.3-2.6, the post-ship in-sample fit) would not have done better on those
  dates. That claim rests on an in-sample fit to about two Saturdays whose per-date k spans 1.3-3.0, and it is not
  established.
- **The per-bucket spread is larger than any change of the single k:** early 2.91, mid 1.74, late 1.46. On <= 11-12,
  #780's own per-bucket walk-forward gained -0.007 against the one k's -0.006 (`out\p0.txt`), about 0.001 more.
  - LEAD, not this lane's: a per-progress k (or a k that falls with game progress) for NCAAF spreads.
- **The engine:** the post-12-08 engine (#852 damping, #859 end game, if loaded) changes what k corrects. Re-fit after
  it loads, as #780's raw k, on its own ticks.

### What follows

- **No code change:** `_SPREADS_PROB_SCALE_BY_SPORT["ncaaf"]` stays 1.80. No branch, no betting change, nothing
  queued for a window.
- **#780's re-fit script has a defect (the user's call):** `scripts/live_totals_width_fit.py` reads
  `model_home_win_prob`, which on every post-load row of a tempered market (NBA / NCAAF totals, NBA / NCAAF / NCAAB
  spreads) is the tempered number. Any re-fit owed under #780 must read `model_home_win_prob_unscaled`. The kit's
  `psrc` is the fix. (It landed on main later the same day; see the last section.)
- **Re-fit again:** after the 12-08 engine loads, or after a few more Saturdays (each adds about 10-14k states).

## THE SCRIPT FIX, LANDED — 2026-11-24 3:20 PM CST (user "Yes, land it"; lane `width-fit-engine-prob`)

- **On main `6656aca80`.** `scripts/live_totals_width_fit.py` now fits k on the ENGINE's number (`fit_prob`; env
  `P_SOURCE`):
  - **engine (default):** reads `model_home_win_prob_unscaled` (before #780's k), else
    `model_home_win_prob_uncalibrated` (before #816's calibration), else the recorded number. A row that was
    transformed with no engine number beside it is dropped and counted (`no_engine_probability`).
  - **`ac`:** the same, and a raw share is replaced by the join's `agresti_coull_point(share, sims_run)`. This is the
    kit's I-AC.
  - **`recorded`:** the old read.
- **Not a betting change:** no fleet role runs the script.
- **Verified on the fleet ledger** at nice 19 (NCAAF spreads; `C:\tmp\t780k_ncaaf\verify_repo.sh` -> `out\verify_*.txt`;
  script sha256 `f4732d4f203fac76`):

  | run | window | k | matches |
  |---|---|---|---|
  | default | <= 11-12 | 1.797 | the shipped fit's output, line for line (only the new `[P_SOURCE=...]` header token differs) |
  | engine | through 11-21 | 1.894 | the kit's S2 |
  | `ac` | through 11-21 | 1.872 | the kit's PRIMARY |
  | `recorded` | through 11-21 | 1.800 | the kit's TRAP |

- **Tests:** `tests/test_live_totals_width_fit_source.py`, 12, including off != on through `load()`. 3 source
  mutations are caught: the old read in `load()`, the unscaled branch removed, and the AC branch removed.
- **Still not recoverable from the ledger:** #847's per-cell live calibration. It keeps its uncalibrated number on the
  verdict only. It is off: its key is absent on every fleet layer and in both workers' environ, 2026-11-24.
