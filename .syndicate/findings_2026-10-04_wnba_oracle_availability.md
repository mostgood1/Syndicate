# FINDINGS — the ceiling of perfect injury information for WNBA props (oracle-availability re-run)

**Lane** `wnba-book-information`, session `39b666bb`. **Date** 2026-10-04. **Measurement only** — no flag, deploy or
board change. Follows `findings_2026-10-03_wnba_book_information.md` §2 item 1 ("NEXT MEASUREMENT … oracle-availability
re-run").

## What was run

- **Oracle arm.** An as-of re-run of the engine in which the availability exclusion list for each game is EXACTLY the
  players who did not play (box score, `--oracle-availability-box`): perfect pregame injury/inactive information,
  including coach's decisions no report carries — a **ceiling**, not something a feed can reach.
  `scripts/backtest_wnba_lines_props.py sim --oracle-availability-box`, code `~/wnba_bt/code6` (9a7f0d2f), 500 sims.
  Rate shrink (fix #3) applied post-hoc with the engine's own `apply_rate_shrink` + `build_exact_ladder_payload`;
  verified equal to the in-engine application on a real game (21 players, max |Δmean| **0.0**).
- **Stack arm.** The fix #2 + #3 stack (real availability rule + rate shrink) re-run, restricted to the same games.
- **Paired rows.** A (game, player, market) row counts only if BOTH arms priced it, the player played, and the book had
  a two-sided line (OddsAPI historical, tip −60, de-vigged modal line). `scripts/compare_wnba_oracle_availability.py`.

**Coverage.** Oracle dates **2026-08-01..10-01, 42 slate dates, 124 games** (rows land in 114 regular + 9 playoff games; 1 game contributes no paired row);
all 124 paired with the stack (0 missing). Inputs: `~/wnba_bt/inputs/{espn,box,odds_hist}` (WSL copies of the
backtest's ESPN games, box scores and the full OddsAPI historical backfill). **7,292 paired rows** over 8 markets.
Regular season is the readable sample; playoffs are ~75–106 rows/market over 9 games and are reported only in the JSON
(no playoff cell differs from zero).

Outputs: `~/wnba_bt/oracle_compare/oracle_compare.json`, `~/wnba_bt/bi_{oracle_shrunk,stack_same}/book_information.json`.

## 0. Headline

1. **Perfect injury information barely moves the model at the book's line.** Regular season, Brier oracle − stack:
   points **−0.0020 [−0.0059, +0.0020]**, rebounds −0.0012 [−0.0068, +0.0037], assists −0.0004, PRA −0.0008
   [−0.0083, +0.0065]. The one market where it clearly helps is **threes −0.0058 [−0.0102, −0.0020]**. MAE of the mean:
   no market moves (points −0.013 [−0.064, +0.040]).
2. **So the book's edge is mostly NOT availability.** The gap to the book on points closes from **+0.0136
   [+0.0066, +0.0207]** (stack − book) to **+0.0116 [+0.0050, +0.0181]** (oracle − book), about 15%; PRA closes about 4%
   (0.0223 → 0.0215). The "who is right when they disagree" slope barely moves: points **0.78 → 0.73**, PRA 0.85 → 0.83,
   minutes channel 0.42 → 0.38. With availability perfect, the book's disagreement still predicts the outcome almost
   one-for-one.
3. **Where availability DOES bite, the engine's redistribution overshoots.** In games with ≥15 late-out teammate-minutes
   (359 points rows, 71 games), the oracle removes the model's under-projection and then passes it:
   - points bias **−0.57 → +0.17**, PRA **−0.71 → +0.49**, PR −0.68 → +0.40, PA −0.53 → +0.39;
   - the remaining players' minutes surprise goes from **+1.15 to −0.57**: told exactly who sits, the sim hands the
     absent minutes to the rest and gives them more than they actually play;
   - the late-out model miss (book-information measure): points +0.58 [−0.10, +1.24] → −0.21 [−0.82, +0.38], rebounds
     **+0.42 [+0.13, +0.69] → +0.08 [−0.20, +0.33]**.
   Net Brier in these games is still a wash (points −0.0038 [−0.0145, +0.0071]): the bias swaps sign; it doesn't shrink.

## 1. Paired Brier, regular season (all rows)

| market | n | games | Brier oracle | Brier stack | Brier book | oracle − stack | stack − book | oracle − book |
|---|---|---|---|---|---|---|---|---|
| points | 1,112 | 114 | 0.2605 | 0.2625 | 0.2489 | −0.0020 [−0.0059, +0.0020] | +0.0136 [+0.0066, +0.0207] | +0.0116 [+0.0050, +0.0181] |
| rebounds | 957 | 114 | 0.2516 | 0.2528 | 0.2446 | −0.0012 [−0.0068, +0.0037] | +0.0082 [+0.0007, +0.0163] | +0.0070 [−0.0003, +0.0142] |
| assists | 726 | 114 | 0.2552 | 0.2556 | 0.2478 | −0.0004 [−0.0063, +0.0055] | +0.0078 [−0.0016, +0.0180] | +0.0074 [−0.0009, +0.0165] |
| threes | 737 | 114 | 0.2466 | 0.2524 | 0.2431 | **−0.0058 [−0.0102, −0.0020]** | +0.0094 [+0.0010, +0.0175] | +0.0035 [−0.0048, +0.0110] |
| PRA | 825 | 114 | 0.2706 | 0.2714 | 0.2492 | −0.0008 [−0.0083, +0.0065] | +0.0223 [+0.0122, +0.0336] | +0.0215 [+0.0118, +0.0328] |
| PR | 885 | 111 | 0.2646 | 0.2668 | 0.2498 | −0.0022 [−0.0085, +0.0039] | +0.0170 [+0.0072, +0.0276] | +0.0148 [+0.0072, +0.0238] |
| PA | 727 | 111 | 0.2627 | 0.2647 | 0.2495 | −0.0020 [−0.0084, +0.0042] | +0.0152 [+0.0054, +0.0258] | +0.0132 [+0.0035, +0.0235] |
| RA | 631 | 111 | 0.2553 | 0.2592 | 0.2493 | −0.0039 [−0.0104, +0.0030] | +0.0098 [−0.0009, +0.0204] | +0.0059 [−0.0049, +0.0169] |

Game-clustered bootstrap 95% CIs, 1,000 resamples. Negative = first arm better.

## 2. By late-out band (regular season, points and PRA)

"Late outs" = season-average minutes of teammates who played the team's previous game and did not play this one.

| market | band | n | games | Brier o − s | bias stack → oracle | MAE Δ (o − s) |
|---|---|---|---|---|---|---|
| points | none | 493 | 74 | +0.0014 [−0.0022, +0.0057] | +0.17 → −0.07 | +0.012 [−0.028, +0.053] |
| points | < 15 min | 260 | 45 | −0.0059 [−0.0136, +0.0012] | −0.42 → −0.50 | −0.030 [−0.155, +0.065] |
| points | ≥ 15 min | 359 | 71 | −0.0038 [−0.0145, +0.0071] | **−0.57 → +0.17** | −0.035 [−0.172, +0.097] |
| PRA | none | 359 | 74 | +0.0006 [−0.0045, +0.0064] | +0.13 → −0.26 | −0.015 [−0.079, +0.051] |
| PRA | < 15 min | 191 | 43 | +0.0021 [−0.0161, +0.0199] | −1.22 → −1.42 | −0.004 [−0.253, +0.244] |
| PRA | ≥ 15 min | 275 | 69 | −0.0047 [−0.0249, +0.0127] | **−0.71 → +0.49** | −0.120 [−0.341, +0.092] |
| RA | ≥ 15 min | 208 | 63 | −0.0123 [−0.0276, +0.0032] | −0.40 → +0.10 | −0.010 [−0.107, +0.088] |
| threes | none | 318 | 73 | **−0.0057 [−0.0109, −0.0009]** | −0.06 → −0.08 | −0.014 [−0.030, +0.000] |

Full table (all 8 markets × 3 bands) in `oracle_compare.json`.

**Book-information decomposition on the same 124 games** (slope of actual − model on line − model; regular season):

| market | arm | total | minutes channel | rate channel |
|---|---|---|---|---|
| points | stack | 0.78 [0.48, 1.06] | 0.42 [0.27, 0.57] | 0.36 [0.13, 0.56] |
| points | oracle | 0.73 [0.48, 0.98] | 0.38 [0.25, 0.52] | 0.35 [0.14, 0.55] |
| rebounds | stack | 0.65 [0.40, 0.89] | 0.37 [0.23, 0.50] | 0.28 [0.08, 0.46] |
| rebounds | oracle | 0.53 [0.27, 0.78] | 0.30 [0.16, 0.44] | 0.23 [0.04, 0.42] |
| PRA | stack | 0.85 [0.63, 1.09] | 0.48 [0.31, 0.64] | 0.37 [0.19, 0.55] |
| PRA | oracle | 0.83 [0.62, 1.04] | 0.44 [0.29, 0.59] | 0.39 [0.22, 0.57] |

The minutes channel barely changes under the oracle. The minutes information the book has is mostly NOT who plays; it is
how much they play: rotation, role and rest.

## 3. What this changes in the ranked list (book-information §2)

1. **Pregame inactive/injury report: DEMOTED.** Its measured ceiling at the book's line is ~15% of the points gap and
   about zero for rebounds, assists and PRA (threes is the exception). Production now applies the real injury feed
   (fleet ff 500a5643 + reading 2 MET, deploys.md 2026-10-04 16:51:50Z), which is worth having for the pools' sake
   (the board no longer prices props for OUT players), but it is not where the book's edge lives.
2. **Minutes redistribution when a player sits: NEW, a defect.** Given perfect availability, the sim over-assigns the
   absent minutes (remaining players −0.57 minutes vs actual; points bias +0.17, PRA +0.49 in ≥15-minute games). With
   the real feed now live in production, this overshoot is what the board will show on injury days. Candidate fix: fit
   the redistribution share (how many of an absent player's minutes go to each teammate) from the season's box scores,
   instead of the rotation model's implied share. This is a MECHANISM change in a calibrated engine, so it requires
   re-fitting the rates it interacts with (`model_engine_standard.md`).
3. **Minutes beyond availability (rotation, role, rest): PROMOTED to first.** The minutes channel of the book's edge
   (0.38 of 0.73 for points) survives perfect availability almost intact. Candidate source: ESPN rotation history
   (restored on the fleet 09-17) feeding expected minutes.
4. **Per-minute rate (~0.35 points, unchanged by the oracle):** matchup and usage. Not addressed by availability, as
   expected.

## 4. Caveats

- **A ceiling, and a narrow window.** 42 dates (Aug 1 – Oct 1); the 10-03 book-information numbers are full-season
  (points slope 0.94 there vs 0.78 here on the stack). The oracle also excludes coach's-decision DNPs no report carries,
  so a real feed reaches at most this.
- **The paired rows exclude** the players the real rule wrongly dropped (they enter only the oracle) and the DNPs the
  stack priced (they have no actual). Those rows are a coverage effect, measured in the 10-03 availability findings;
  this file measures pricing on the same bets.
- **Post-hoc shrink:** exact on the tested game. The dispersion and shape flags are OFF in both arms, as in production.
- **Late-out bands** are computed from the box score, so they are known after the fact. They are an analysis
  partition, not something the model could use at tip −60.
