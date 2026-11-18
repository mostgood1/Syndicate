# Engine read: the live re-sims against Kalshi's price (dev, 2026-11-17)

Lane `engine-learner`, umbrella #736. The user asked for it ("Yes, build it", answering "Build the engine read against
Kalshi's price now?"). It is the plan's engine read (plan_one_engine_pregame_live.md §2: bias, calibration and the
biggest disagreements the market won, by clock bucket; the queue goes to the sim owners). It is measured against
**Kalshi's in-play mid**, which `findings_2026-11-17_kalshi_prior_learner.md` found to out-forecast the books' fair
everywhere.

**Dev only:** slates 11-09, 11-10, 11-11, 11-13 and 11-14. Nothing of M2's or M3's windows was read.
Kit `C:\tmp\elp\engine_read`:
- `dump_examples.py` runs the frozen learner over `kprior/kbefore` and saves each line-instant with its outcome;
- `engine_read.py` computes the read.

## Method

- **Population:** 54,173 live line-instants on full-game lines with both a live re-sim opinion (`live_resim`,
  experts `981ef14f6`) and Kalshi's mid. The mid is the in-play recorder's last quote at or before the decision
  instant, at most 60 s old, placed by M3's index.
- **Weighting:** each line counts once (weight 1 / its ticks); SEs are clustered by game.
- **Outcome:** the learner's outcome truth.
- **Columns:**
  - bias: re-sim minus Kalshi, in pp, for our side (over / home covers / home wins);
  - log loss of the re-sim, Kalshi and the books;
  - calibration: a weighted logistic fit `y ~ a + b * logit(p)`. b < 1 means over-confident;
  - disagreements: lines where the re-sim and Kalshi differ by >= 5pp. "Outcome toward the re-sim" is the weighted
    mean of sign(re-sim - Kalshi) * (y - Kalshi), in pp. Positive means the outcome moved the re-sim's way.

| sport / family / clock | lines (games) | re-sim minus Kalshi, mean (mean abs), pp | log loss re-sim / Kalshi / books | re-sim minus Kalshi, ll (se) | calibration re-sim a, b | Kalshi a, b | disagreements >= 5pp: lines, outcome toward re-sim, pp (se) |
|---|---|---|---|---|---|---|---|
| nba|h2h|0-25 | 36 (36) | +0.5 (7.3) | 0.497 / 0.471 / 0.493 | +0.026 (0.024) | +0.44, 1.79 | +0.46, 1.38 | 33: -2.3 (7.2) |
| nba|h2h|25-50 | 37 (37) | +2.5 (7.2) | 0.375 / 0.354 / 0.388 | +0.021 (0.028) | -0.07, 1.78 | +0.47, 2.30 | 33: +0.2 (7.3) |
| nba|h2h|50-75 | 36 (36) | -0.0 (6.3) | 0.324 / 0.339 / 0.361 | -0.015 (0.019) | +0.08, 2.49 | +0.09, 2.83 | 30: +13.5 (6.7) |
| nba|h2h|75-95 | 30 (30) | -0.7 (5.7) | 0.292 / 0.296 / 0.335 | -0.004 (0.018) | +0.66, 1.97 | +0.37, 1.64 | 19: +9.4 (6.1) |
| nba|h2h|95-100 | 5 (5) | -4.2 (13.8) | 0.525 / 0.356 / 0.635 | +0.168 (0.280) | +14.15, -0.17 | +13.22, 0.55 | 4: +15.0 (22.6) |
| nba|h2h|all | 38 (38) | +0.6 (6.8) | 0.379 / 0.369 / 0.401 | +0.010 (0.018) | +0.27, 1.92 | +0.38, 1.91 | 38: +4.5 (5.1) |
| nba|h2h|ot | 1 (1) | -19.5 (19.5) | 0.796 / 0.444 / 0.879 | +0.352 (-) | +11.50, -0.14 | +12.34, 0.52 | 1: -31.5 (-) |
| nba|spreads|0-25 | 1269 (36) | -0.2 (7.1) | 0.446 / 0.400 / 0.425 | +0.046 (0.015) | +0.50, 1.54 | +0.53, 1.31 | 1142: -2.1 (3.6) |
| nba|spreads|25-50 | 1292 (37) | +1.5 (8.1) | 0.437 / 0.416 / 0.454 | +0.020 (0.020) | +0.13, 1.47 | +0.28, 1.31 | 1101: +3.8 (4.6) |
| nba|spreads|50-75 | 1167 (38) | +0.8 (7.9) | 0.447 / 0.452 / 0.474 | -0.004 (0.018) | +0.15, 1.44 | +0.23, 1.16 | 998: +8.5 (4.4) |
| nba|spreads|75-95 | 873 (36) | +1.1 (9.4) | 0.506 / 0.495 / 0.545 | +0.011 (0.025) | +0.14, 1.13 | +0.21, 0.98 | 684: +6.9 (4.6) |
| nba|spreads|95-100 | 216 (23) | +4.3 (15.1) | 0.654 / 0.604 / 0.653 | +0.051 (0.100) | +0.05, 0.56 | +0.18, 0.63 | 159: +0.9 (8.0) |
| nba|spreads|all | 1630 (38) | +0.8 (8.1) | 0.457 / 0.435 / 0.468 | +0.021 (0.014) | +0.24, 1.38 | +0.32, 1.19 | 1539: +3.6 (3.4) |
| nba|spreads|ot | 18 (1) | -12.5 (12.6) | 0.624 / 0.399 / 0.678 | +0.225 (-) | +15.79, -0.14 | +15.83, 0.05 | 17: -24.8 (-) |
| nba|totals|0-25 | 1178 (36) | +2.2 (6.1) | 0.432 / 0.394 / 0.422 | +0.037 (0.013) | -0.01, 1.48 | +0.21, 1.54 | 925: -6.6 (3.9) |
| nba|totals|25-50 | 1202 (37) | +1.5 (5.9) | 0.398 / 0.374 / 0.409 | +0.024 (0.009) | +0.51, 1.66 | +0.71, 1.73 | 957: -0.7 (3.5) |
| nba|totals|50-75 | 1114 (38) | +1.8 (6.9) | 0.456 / 0.416 / 0.430 | +0.040 (0.014) | +0.18, 1.25 | +0.35, 1.38 | 845: -5.0 (4.2) |
| nba|totals|75-95 | 836 (37) | -0.0 (7.5) | 0.489 / 0.465 / 0.496 | +0.024 (0.019) | +0.13, 1.05 | +0.14, 1.08 | 554: -0.6 (5.0) |
| nba|totals|95-100 | 171 (22) | -9.7 (18.1) | 0.745 / 0.552 / 0.639 | +0.193 (0.106) | +1.15, 0.80 | +0.89, 1.16 | 136: -10.2 (11.6) |
| nba|totals|all | 1499 (38) | +1.4 (6.7) | 0.442 / 0.408 / 0.435 | +0.034 (0.008) | +0.23, 1.33 | +0.37, 1.43 | 1359: -3.7 (2.6) |
| nba|totals|ot | 14 (1) | -10.0 (11.8) | 0.384 / 0.402 / 0.420 | -0.018 (-) | -0.24, 7.57 | -39.30, 43.74 | 10: +14.1 (-) |
| ncaaf|h2h|0-25 | 63 (63) | -6.3 (8.5) | 0.437 / 0.442 / 0.460 | -0.005 (0.029) | +0.20, 1.16 | -0.26, 1.11 | 60: +5.7 (5.6) |
| ncaaf|h2h|25-50 | 61 (61) | -4.2 (6.9) | 0.473 / 0.478 / 0.480 | -0.005 (0.021) | +0.09, 0.89 | -0.18, 0.91 | 59: +4.4 (5.4) |
| ncaaf|h2h|50-75 | 57 (57) | -2.5 (6.1) | 0.429 / 0.434 / 0.448 | -0.005 (0.021) | -0.22, 0.97 | -0.42, 1.06 | 47: +6.0 (5.9) |
| ncaaf|h2h|75-95 | 44 (44) | -0.7 (6.1) | 0.483 / 0.445 / 0.466 | +0.038 (0.027) | -0.23, 0.75 | -0.33, 0.89 | 32: -3.8 (7.3) |
| ncaaf|h2h|95-100 | 21 (21) | -3.6 (17.4) | 0.624 / 0.289 / 0.411 | +0.335 (0.226) | -0.32, 0.46 | -0.58, 2.33 | 15: -1.1 (9.9) |
| ncaaf|h2h|all | 63 (63) | -4.0 (7.3) | 0.455 / 0.450 / 0.463 | +0.005 (0.021) | +0.01, 0.92 | -0.27, 1.00 | 61: +4.5 (4.8) |
| ncaaf|spreads|0-25 | 405 (55) | -9.3 (12.4) | 0.641 / 0.631 / 0.691 | +0.010 (0.046) | +0.17, 0.88 | -0.24, 1.81 | 349: +6.9 (7.0) |
| ncaaf|spreads|25-50 | 425 (54) | -5.5 (10.2) | 0.576 / 0.598 / 0.689 | -0.022 (0.030) | -0.07, 1.17 | -0.38, 1.57 | 366: +12.0 (6.0) |
| ncaaf|spreads|50-75 | 338 (54) | -3.5 (10.3) | 0.618 / 0.610 / 0.693 | +0.007 (0.023) | -0.19, 0.96 | -0.36, 1.48 | 282: +4.2 (4.8) |
| ncaaf|spreads|75-95 | 291 (50) | -0.9 (13.2) | 0.676 / 0.607 / 0.665 | +0.069 (0.032) | +0.03, 0.56 | +0.00, 1.08 | 253: +0.9 (3.8) |
| ncaaf|spreads|95-100 | 84 (37) | -7.5 (19.0) | 0.654 / 0.364 / 0.546 | +0.291 (0.089) | +0.67, 0.63 | +0.77, 1.88 | 70: -11.5 (6.5) |
| ncaaf|spreads|all | 799 (55) | -5.5 (11.8) | 0.625 / 0.604 / 0.681 | +0.021 (0.025) | +0.00, 0.84 | -0.24, 1.42 | 716: +5.8 (4.1) |
| ncaaf|totals|0-25 | 226 (47) | -2.9 (14.8) | 0.703 / 0.656 / 0.693 | +0.047 (0.076) | -1.04, 0.41 | -1.18, 1.76 | 184: -0.3 (7.7) |
| ncaaf|totals|25-50 | 196 (47) | -5.0 (16.3) | 0.727 / 0.624 / 0.689 | +0.103 (0.090) | -0.65, 0.23 | -0.71, 2.42 | 169: -0.4 (7.9) |
| ncaaf|totals|50-75 | 195 (51) | +2.4 (13.0) | 0.715 / 0.596 / 0.696 | +0.119 (0.048) | -1.06, 0.51 | -1.06, 2.71 | 154: -8.3 (6.3) |
| ncaaf|totals|75-95 | 153 (47) | +7.7 (15.2) | 0.672 / 0.633 / 0.673 | +0.039 (0.069) | -0.31, 0.58 | -0.04, 0.85 | 131: +3.3 (6.5) |
| ncaaf|totals|95-100 | 25 (19) | +1.7 (19.4) | 0.652 / 0.526 / 0.546 | +0.126 (0.107) | -1.86, -0.07 | -1.78, 0.01 | 21: -1.7 (8.5) |
| ncaaf|totals|all | 475 (55) | +0.1 (14.9) | 0.704 / 0.626 / 0.685 | +0.077 (0.054) | -0.78, 0.41 | -0.76, 1.35 | 410: -1.4 (5.3) |
| nhl|h2h|0-25 | 29 (29) | -0.6 (5.9) | 0.671 / 0.669 / 0.652 | +0.002 (0.023) | -1.44, 0.76 | -1.48, 0.93 | 24: +8.3 (10.4) |
| nhl|h2h|25-50 | 30 (30) | +1.4 (5.0) | 0.530 / 0.499 / 0.522 | +0.031 (0.014) | -1.52, 1.79 | -1.47, 1.80 | 27: -7.8 (6.5) |
| nhl|h2h|50-75 | 29 (29) | +0.7 (4.0) | 0.427 / 0.409 / 0.419 | +0.017 (0.009) | -1.46, 1.45 | -1.47, 1.50 | 27: -2.2 (6.2) |
| nhl|h2h|75-95 | 26 (26) | +0.9 (3.8) | 0.372 / 0.357 / 0.374 | +0.015 (0.010) | -1.23, 1.36 | -1.19, 1.33 | 18: -6.3 (6.0) |
| nhl|h2h|95-100 | 13 (13) | -0.9 (4.1) | 0.446 / 0.478 / 0.528 | -0.032 (0.016) | -1.75, 3.55 | -1.51, 1.77 | 3: +34.8 (13.1) |
| nhl|h2h|all | 30 (30) | +0.7 (4.6) | 0.493 / 0.476 / 0.487 | +0.016 (0.011) | -1.45, 1.45 | -1.44, 1.47 | 29: -1.1 (6.1) |
| nhl|h2h|ot | 7 (7) | +3.6 (7.5) | 0.722 / 0.686 / 0.693 | +0.036 (0.051) | -2.16, 2.15 | -1.84, 0.56 | 5: -3.6 (21.9) |
| nhl|spreads|0-25 | 26 (18) | -3.5 (5.9) | 0.497 / 0.551 / 0.549 | -0.054 (0.035) | -1.62, 1.94 | -1.91, 2.02 | 17: +26.4 (12.6) |
| nhl|spreads|25-50 | 33 (18) | +1.3 (5.0) | 0.518 / 0.476 / 0.571 | +0.042 (0.031) | -0.96, 1.55 | -0.86, 1.89 | 21: -13.1 (9.4) |
| nhl|spreads|50-75 | 34 (17) | +1.1 (7.9) | 0.645 / 0.621 / 0.674 | +0.025 (0.039) | -1.56, 0.99 | -1.51, 0.99 | 26: +1.9 (10.0) |
| nhl|spreads|75-95 | 33 (17) | +8.7 (12.4) | 0.533 / 0.402 / 0.550 | +0.131 (0.074) | -1.26, 1.28 | -0.78, 2.51 | 27: -5.6 (7.7) |
| nhl|spreads|95-100 | 19 (13) | +6.0 (11.0) | 0.282 / 0.261 / 0.482 | +0.021 (0.084) | -0.24, 1.09 | -0.28, 2.90 | 11: +9.9 (8.4) |
| nhl|spreads|all | 56 (19) | +2.8 (8.4) | 0.527 / 0.485 / 0.578 | +0.042 (0.035) | -1.32, 1.34 | -1.15, 1.79 | 46: +2.8 (6.9) |
## Reading

1. **Nowhere does the live re-sim beat Kalshi's log loss**, overall or in any clock bucket with a usable sample.
   - Per sport and family (re-sim minus Kalshi, se): NBA h2h +0.010 (0.018), spreads +0.021 (0.014), totals
     **+0.034 (0.008)**; NCAAF h2h +0.005 (0.021), spreads +0.021 (0.025), totals +0.077 (0.054); NHL h2h +0.016
     (0.011), spreads +0.042 (0.035).
   - The books' fair is worse than Kalshi everywhere, and often worse than the re-sim.
2. **NBA totals lean to the over and lose.**
   - The re-sim sits +1.4pp over Kalshi overall, and +2.2pp in the first quarter of game time.
   - Where they disagree by 5pp or more, the outcome moves away from the re-sim: -3.7pp (se 2.6), and -6.6pp
     (se 3.9) in 0-25%.
   - Log loss is worse in every clock bucket.
3. **NCAAF totals are far over-confident.**
   - Calibration slope is 0.41, against Kalshi's 1.35: the re-sim's probabilities need pulling roughly 60% of the way
     to 50/50 in logit.
   - Its mean absolute gap to Kalshi is 14.9pp.
4. **NCAAF spreads lean away from the home side**, by -5.5pp overall and -9.3pp early.
   - Yet where they disagree, the outcome went the re-sim's way: +5.8pp (se 4.1), and +12.0pp (se 6.0) at 25-50%.
   - This is the one hint of information beyond Kalshi in this read. It rests on one Saturday, so re-check it on
     11-09..11-22.
5. **The last 5% of game time and overtime are the worst cells in every sport.** NCAAF spreads 95-100%: +0.291
   log loss. NBA totals 95-100%: +0.193. The queue's NBA rows at 96-99% show gaps like 0.26 against 0.88.
   - At a 60-180 s evidence cadence, the re-sim's state is stale exactly where every possession matters. This is
     most likely latency, not the model.
6. **NHL: Kalshi and the re-sim show the same large negative intercept** (h2h -1.45, spreads -1.32 / -1.15, about
   30 games). Before NHL is read further, check the NHL outcome label (overtime and shootout) against Kalshi's
   settlement rule.

## For the sim owners: the biggest disagreements Kalshi won

One row per game: the instant where the re-sim and Kalshi differed most and the outcome went Kalshi's way. "line" is
our side (over, or home covers at the live join's line).

**nba|h2h**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-13 | Oklahoma City Thunder at Los Angeles Clippers | h2h home  | 97% (95-100) | 0.14 | 0.61 | 1 |
| 2026-11-13 | Utah Jazz at Houston Rockets | h2h home  | 70% (50-75) | 0.43 | 0.74 | 1 |
| 2026-11-11 | Oklahoma City Thunder at Portland Trail Blazers | h2h home  | 94% (75-95) | 0.70 | 0.96 | 1 |
| 2026-11-09 | Indiana Pacers at Dallas Mavericks | h2h home  | 64% (50-75) | 0.30 | 0.56 | 1 |
| 2026-11-11 | San Antonio Spurs at Chicago Bulls | h2h home  | 44% (25-50) | 0.83 | 0.57 | 0 |
| 2026-11-14 | Brooklyn Nets at Memphis Grizzlies | h2h home  | 6% (0-25) | 0.48 | 0.72 | 1 |
| 2026-11-13 | Atlanta Hawks at Chicago Bulls | h2h home  | - (ot) | 0.68 | 0.93 | 1 |
| 2026-11-09 | San Antonio Spurs at Phoenix Suns | h2h home  | 21% (0-25) | 0.39 | 0.18 | 0 |

**nba|spreads**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-10 | Los Angeles Clippers at Phoenix Suns | spreads home 26.5 | 95% (75-95) | 0.82 | 0.07 | 0 |
| 2026-11-11 | Golden State Warriors at Houston Rockets | spreads home 11.5 | 98% (95-100) | 0.86 | 0.14 | 0 |
| 2026-11-13 | Oklahoma City Thunder at Los Angeles Clippers | spreads_alt home -2.5 | 97% (95-100) | 0.33 | 0.81 | 1 |
| 2026-11-09 | Washington Wizards at Detroit Pistons | spreads home 13.5 | 97% (95-100) | 0.85 | 0.37 | 0 |
| 2026-11-13 | New York Knicks at Indiana Pacers | spreads_alt home 6.5 | 71% (50-75) | 0.61 | 0.20 | 0 |
| 2026-11-11 | Oklahoma City Thunder at Portland Trail Blazers | spreads home 2.5 | 94% (75-95) | 0.51 | 0.92 | 1 |
| 2026-11-10 | Miami Heat at Utah Jazz | spreads_alt home -14.5 | 85% (75-95) | 0.43 | 0.83 | 1 |
| 2026-11-13 | Memphis Grizzlies at New Orleans Pelicans | spreads_alt home -25.5 | 94% (75-95) | 0.61 | 0.22 | 0 |

**nba|totals**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-09 | Indiana Pacers at Dallas Mavericks | totals_alt over 241.5 | 96% (95-100) | 0.26 | 0.88 | 1 |
| 2026-11-09 | New Orleans Pelicans at Golden State Warriors | totals over 229.5 | 96% (95-100) | 0.71 | 0.12 | 0 |
| 2026-11-11 | Golden State Warriors at Houston Rockets | totals over 222.5 | 98% (95-100) | 0.17 | 0.75 | 1 |
| 2026-11-09 | Cleveland Cavaliers at Charlotte Hornets | totals_alt over 227.5 | 51% (50-75) | 0.40 | 0.86 | 1 |
| 2026-11-09 | Denver Nuggets at Houston Rockets | totals_alt over 210.5 | 97% (95-100) | 0.73 | 0.34 | 0 |
| 2026-11-10 | Miami Heat at Utah Jazz | totals_alt over 220.5 | 99% (95-100) | 0.45 | 0.83 | 1 |
| 2026-11-09 | Washington Wizards at Detroit Pistons | totals_alt over 234.5 | 97% (95-100) | 0.55 | 0.17 | 0 |
| 2026-11-09 | Memphis Grizzlies at Toronto Raptors | totals_alt over 228.5 | 69% (50-75) | 0.61 | 0.26 | 0 |

**ncaaf|h2h**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-14 | Texas Longhorns at LSU Tigers | h2h home  | 100% (95-100) | 0.98 | 0.09 | 0 |
| 2026-11-14 | Syracuse Orange at NC State Wolfpack | h2h home  | 98% (95-100) | 0.98 | 0.14 | 0 |
| 2026-11-14 | Fresno State Bulldogs at Texas State Bobcats | h2h home  | 98% (95-100) | 0.02 | 0.72 | 1 |
| 2026-11-10 | Kent State Golden Flashes at Bowling Green Falcons | h2h home  | 97% (95-100) | 0.18 | 0.80 | 1 |
| 2026-11-14 | Wisconsin Badgers at Maryland Terrapins | h2h home  | 97% (95-100) | 0.35 | 0.82 | 1 |
| 2026-11-14 | Arkansas State Red Wolves at Coastal Carolina Chanticleers | h2h home  | 69% (50-75) | 0.39 | 0.73 | 1 |
| 2026-11-14 | Jacksonville State Gamecocks at Western Kentucky Hilltoppers | h2h home  | 96% (95-100) | 0.24 | 0.57 | 1 |
| 2026-11-13 | Florida State Seminoles at Pittsburgh Panthers | h2h home  | 53% (50-75) | 0.70 | 0.39 | 0 |

**ncaaf|spreads**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-14 | Jacksonville State Gamecocks at Western Kentucky Hilltoppers | spreads home 3.5 | 99% (95-100) | 0.14 | 0.98 | 1 |
| 2026-11-14 | Southern Mississippi Golden Eagles at Louisiana Tech Bulldogs | spreads home 38.5 | 95% (95-100) | 0.90 | 0.18 | 0 |
| 2026-11-14 | Fresno State Bulldogs at Texas State Bobcats | spreads home 1.5 | 98% (95-100) | 0.02 | 0.71 | 1 |
| 2026-11-14 | Michigan Wolverines at Oregon Ducks | spreads home 24.5 | 97% (95-100) | 0.75 | 0.10 | 0 |
| 2026-11-14 | East Carolina Pirates at Charlotte 49ers | spreads home -1.5 | 96% (95-100) | 0.29 | 0.94 | 1 |
| 2026-11-14 | San Jose State Spartans at Air Force Falcons | spreads home 23.5 | 97% (95-100) | 0.71 | 0.10 | 0 |
| 2026-11-14 | Kansas Jayhawks at West Virginia Mountaineers | spreads home -26.5 | 91% (75-95) | 0.18 | 0.80 | 1 |
| 2026-11-14 | Boston College Eagles at Notre Dame Fighting Irish | spreads home 35.5 | 85% (75-95) | 0.81 | 0.23 | 0 |

**ncaaf|totals**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-14 | Boston College Eagles at Notre Dame Fighting Irish | totals over 55.5 | 80% (75-95) | 0.80 | 0.23 | 0 |
| 2026-11-14 | San Jose State Spartans at Air Force Falcons | totals over 30.5 | 50% (50-75) | 0.94 | 0.39 | 0 |
| 2026-11-14 | Colorado State Rams at Washington State Cougars | totals over 75.5 | 52% (50-75) | 0.14 | 0.66 | 1 |
| 2026-11-14 | Auburn Tigers at Mississippi State Bulldogs | totals over 51.5 | 90% (75-95) | 0.54 | 0.07 | 0 |
| 2026-11-14 | Texas Tech Red Raiders at Oklahoma State Cowboys | totals over 70.5 | 36% (25-50) | 0.14 | 0.59 | 1 |
| 2026-11-14 | Utah Utes at Arizona Wildcats | totals over 56.5 | 47% (25-50) | 0.28 | 0.70 | 1 |
| 2026-11-14 | Minnesota Golden Gophers at Penn State Nittany Lions | totals over 62.5 | 75% (75-95) | 0.70 | 0.28 | 0 |
| 2026-11-14 | Stanford Cardinal at Virginia Tech Hokies | totals over 62.5 | 97% (95-100) | 0.63 | 0.21 | 0 |

**nhl|h2h**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-14 | San Jose Sharks at Utah Mammoth | h2h home  | 90% (75-95) | 0.60 | 0.17 | 0 |
| 2026-11-10 | Minnesota Wild at Montréal Canadiens | h2h home  | - (ot) | 0.42 | 0.01 | 0 |
| 2026-11-10 | Colorado Avalanche at Toronto Maple Leafs | h2h home  | 75% (50-75) | 0.52 | 0.21 | 0 |
| 2026-11-14 | Calgary Flames at Los Angeles Kings | h2h home  | 85% (75-95) | 0.51 | 0.23 | 0 |
| 2026-11-14 | New Jersey Devils at Washington Capitals | h2h home  | 59% (50-75) | 0.53 | 0.26 | 0 |
| 2026-11-11 | Utah Mammoth at Vegas Golden Knights | h2h home  | 3% (0-25) | 0.46 | 0.69 | 1 |
| 2026-11-09 | New York Islanders at San Jose Sharks | h2h home  | 85% (75-95) | 0.41 | 0.62 | 1 |
| 2026-11-10 | New Jersey Devils at Winnipeg Jets | h2h home  | 15% (0-25) | 0.39 | 0.60 | 1 |

**nhl|spreads**

| date | game | line | clock | re-sim | Kalshi | outcome |
|---|---|---|---|---|---|---|
| 2026-11-14 | Calgary Flames at Los Angeles Kings | spreads home -1.5 | 98% (95-100) | 0.08 | 0.80 | 1 |
| 2026-11-11 | Tampa Bay Lightning at Buffalo Sabres | spreads home -2.5 | 73% (50-75) | 0.77 | 0.26 | 0 |
| 2026-11-11 | Nashville Predators at Anaheim Ducks | spreads home -1.5 | 92% (75-95) | 0.66 | 0.17 | 0 |
| 2026-11-14 | Colorado Avalanche at Montréal Canadiens | spreads home -2.5 | 96% (95-100) | 0.90 | 0.42 | 0 |
| 2026-11-14 | Ottawa Senators at Pittsburgh Penguins | spreads home -1.5 | 90% (75-95) | 0.63 | 0.17 | 0 |
| 2026-11-14 | New Jersey Devils at Washington Capitals | spreads home -2.5 | 92% (75-95) | 0.82 | 0.42 | 0 |
| 2026-11-11 | Philadelphia Flyers at Edmonton Oilers | spreads home 1.5 | 85% (75-95) | 0.47 | 0.13 | 0 |
| 2026-11-14 | San Jose Sharks at Utah Mammoth | spreads home -1.5 | 94% (75-95) | 0.61 | 0.94 | 1 |

## Limits

- Dev, five nights: NBA 38 games, NCAAF 55-63 (one Saturday), NHL 30.
- Live full-game lines only: no pregame, no segments, no props.
- An outcome is one draw per game, so a single game's row is an example, not evidence.
- Re-run on 11-09..11-22 once M2's 11-24 read frees those slates.

## NHL outcome label: checked 2026-11-17 8:42 PM CST -- correct; the shared intercept is the games

The user asked for it ("Yes, check it"). Script: `C:\tmp\elp\engine_read\nhl_label_check.py` (dev slates only;
rows in `nhl_label_check.json`).

- **Our label equals Kalshi's own settlement on every dev NHL line: 86 of 86** (30 moneylines, 56 puck lines; 0
  disagreements, 0 unsettled). Our label is the learner's truth: the board's final-score chips. Kalshi's is the
  recorder's `res` for the same market, placed by M3's index in the live join's frame.
- **"Home" is the home team.** On all 30 moneylines, the market we trade as "home" ends with the SECOND code of
  Kalshi's event ticker, and Kalshi writes away then home (for example `KXNHLGAME-26NOV09NYISJ-SJ`, Islanders at
  Sharks).
- **So the -1.45 intercept that Kalshi and the re-sim share is the outcomes themselves.** Home teams won 7 of these 30
  dev games (23%), far below the ~54% both prices expect. It is a 30-game sample effect, not a defect. NHL's rows in
  this read are noise-dominated at this size, and nothing in the labels needs fixing.
