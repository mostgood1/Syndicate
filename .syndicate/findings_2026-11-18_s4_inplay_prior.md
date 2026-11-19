# Findings — study S4 of the profit learning program: Kalshi as the in-play prior, the sim as the challenger (2026-11-18)

Asked for by the user 2026-11-18 ~9:50 PM CST: "start study s4 on kalshi as the in play prior". Written by the
portfolio session (lane `portfolio-monitor`). Read-only: nothing live, no env, no fleet state changed. Not
financial advice.

## Part A — already measured under a registration: Kalshi's in-play mid beats every fair we have

The in-game-trading lane's stage-2 scoreboard (`scripts/inplay_fair_score.py` -> `scripts/inplay_scoreboard.py`,
registered in `findings_2026-10-20_in_game_trading.md` section 3) scores each fair against **Kalshi's own in-play
mid at the same instants**, settled on the ticker's Kalshi result. A fair "goes" only if its Brier CI is < 0 (better
than the mid) **and** its fee-net markout CI is > 0.

**Cumulative read: `C:\tmp\inplay_scoreboard.md`, written 2026-11-18 01:41 CST, nights 10-20..11-17.**

| fair | NBA GAME (176 games) | NBA TOTAL (177 games) | verdict, every sport x market |
|---|---|---|---|
| **nba_resim** (the live re-sim, `model_home_win_prob`) | **dBrier +0.0240 [+0.0125, +0.0355]**; markout +60 s -1.72c | **+0.0180 [+0.0122, +0.0244]**; -1.81c | NO-GO |
| books (in-play consensus, >= 3 fresh books) | +0.0033 [+0.0024, +0.0041] | +0.0054 [+0.0041, +0.0068] | NO-GO in all 4 sports |
| score_time (Brownian / Poisson baseline anchored on Kalshi's pregame) | +0.0080 [-0.0011, +0.0175] | +0.0076 [+0.0048, +0.0104] | NO-GO in all 4 sports |

- dBrier = Brier(fair) - Brier(Kalshi mid). **Positive = Kalshi is better.** No fair beats Kalshi's mid in any
  sport or market. The sim is the furthest behind, beyond noise in both markets it can price.
- Every fair's sides lose after the taker fee within a minute: markouts are -1.5 to -2.7c per contract.
- So the first half of S4 holds: **Kalshi's in-play mid is the best in-play probability Syndicate has.** Any
  in-play trigger built on "the sim disagrees with Kalshi" trades against a better-informed price.

## Part B — PRE-REGISTRATION: does the sim earn any weight on top of Kalshi? (written before any number below is computed)

The sim can be worse alone yet still add information in a blend. This tests that, and nothing else.

**Population.**
- NBA rows in each night's `C:\tmp\inplay_<date>\fair_rows.jsonl` (the recorder output, also preserved in
  `~/syndicate-prod/data/research/inplay_recorder/`), with:
  - `kind` in {GAME, TOTAL} (spreads are not scored by the sim; see the scorer's docstring);
  - `fairs.nba_resim` present;
  - `0 < mid < 1`, and `y` in {0, 1}.
- NBA is the only sport with an in-play sim fair.
- **Coverage, counted before this was written (no outcomes read):** 26 nights carry `fair_rows.jsonl`, and 24 of
  them have NBA sim rows (11-03 and 11-08 have none; 10-21, 11-06 and 11-12 were not scored). GAME has 7,676 rows
  over 176 game-nights; TOTAL has 162,824 rows over 177.

**Split (by night, fixed now).**
- FIT = nights <= 2026-11-02 (13 nights, 95 GAME game-nights).
- TEST = nights >= 2026-11-04 (11 nights, 81 GAME game-nights).

**Blend.** `p = sigmoid( logit(mid) + w * (logit(sim) - logit(mid)) )`. Both probabilities are clipped to
[0.005, 0.995] before the logit. w = 0 is Kalshi alone, w = 1 is the sim alone.

**Fit.** For each kind separately (GAME, TOTAL), w is the grid value in {0.00, 0.01, ..., 1.00} that minimises the
mean log loss over FIT rows.

**Test (the decision).**
- On TEST rows: **D = mean log loss(blend at the FIT w) - mean log loss(Kalshi mid)**.
- 95% CI from a game-clustered bootstrap: resample games with replacement, 2,000 draws, seed 20261118.
- Brier difference reported beside it; it decides nothing.

**Rule, per kind.**
- **GO (the sim earns weight):** w_FIT > 0 **and** D's 95% CI upper bound < 0.
- **KILL:** otherwise. The sim gets weight 0 on top of Kalshi in that market, and Kalshi's mid is the in-play prior.
- A GO changes nothing live. It names a challenger: an in-play fair equal to the blend, to be paper-tested before any
  betting-change window.

**Reported with the verdict:**
- the coverage actually used, per side;
- w_FIT and the FIT log loss at w = 0 and at w_FIT;
- the TEST log loss of both;
- D with its CI;
- the share of TEST rows where the blend moves p by more than 1 pp.

## RESULT — KILL in both markets: the sim earns no weight on top of Kalshi (run 2026-11-19 03:54Z = 9:54 PM CST, read-only; pre-registration on main `ba0fb2812` at 03:53:04Z)

Script: `C:\tmp\pfmon\s4_blend.py`, exactly as registered. Result: `C:\tmp\pfmon\s4_blend_result.json`.

| kind | FIT rows / games | **w_FIT** | FIT log loss at w=0 / at w_FIT | TEST rows / games | TEST log loss: mid / blend | D [95%] | verdict |
|---|---|---|---|---|---|---|---|
| GAME | 4,192 / 95 | **0.00** | 0.51493 / 0.51493 | 3,484 / 81 | 0.43886 / 0.43886 | 0 (blend = mid) | **KILL** |
| TOTAL | 91,145 / 95 | **0.00** | 0.46474 / 0.46474 | 71,679 / 82 | 0.41430 / 0.41430 | 0 (blend = mid) | **KILL** |

- **On the FIT nights, every positive weight on the sim made the log loss worse**, so the fitted weight is the grid
  edge, 0. The registered rule needs w_FIT > 0, so the verdict is KILL in both markets.
- TEST is then Kalshi's mid itself: no row moves by more than 1 pp.
- **Kalshi's in-play mid is the in-play prior**, and the NBA re-sim gets weight 0 on top of it.

**Descriptive only (not the registered decision): log-loss change against Kalshi alone at fixed small weights**
(`C:\tmp\pfmon\s4_blend_sens.py`):

| w | GAME FIT | GAME TEST | TOTAL FIT | TOTAL TEST |
|---|---|---|---|---|
| 0.01 | +0.00062 | -0.00005 | +0.00011 | +0.00010 |
| 0.10 | +0.00656 | **-0.00023** | +0.00140 | +0.00129 |
| 0.25 | +0.01813 | +0.00047 | +0.00474 | +0.00470 |
| 1.00 (sim alone) | +0.10757 | +0.02439 | +0.04615 | +0.05722 |

- TOTAL is worse at every weight on both sides.
- **GAME on TEST alone is slightly better at a small weight** (-0.00023 nats at w = 0.10) while FIT was clearly
  worse. A drift toward the sim on later nights is possible, since the NBA re-sim has changed over the period: BC-052
  changed its history inputs on 11-18 itself. The size is about a hundredth of the Kalshi-vs-books gap.
- **Lead, not a result:** re-register a GAME-only blend once at least 80 new NBA game-nights accrue after 11-18
  (about mid-December at the current slate).

## What it means for the program

- S4 is closed. The in-play prior is Kalshi's mid: no in-play edge may come from "the sim disagrees with Kalshi" in
  NBA. The scoreboard's NO-GO says the same of books and the score-time baseline in every sport.
- An in-play challenger has to beat Kalshi's mid by being faster or better-informed, not by disagreeing with it.
  Examples: the score-change lag window, or depth and imbalance signals. That points at S6 (adverse selection
  features) and the recorder's score-change timing, not at the sim.
- Nothing goes to the 11-24 window from S4.
