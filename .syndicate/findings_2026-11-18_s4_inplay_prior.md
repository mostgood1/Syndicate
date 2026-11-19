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
