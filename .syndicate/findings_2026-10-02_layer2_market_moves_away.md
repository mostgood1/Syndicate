# "The market is moving AWAY from our top picks" — sanity check, 2026-10-02

Lane `layer2-freshness-1h`, session b9bb5f37. Read-only analysis. Substrate: the LOCAL
WSL FLEET (Render suspended since 09-30): `GET /api/board/layer2-shortlist?limit=2000&sport=<s>`
at 2026-10-02 14:47Z (2,984 rows, five sports), and `/api/ops/clv/report?date=&sport=&rows=1`
(admin, read-only, user-approved) for 09-29..10-02. Nothing in `data/` was used.

**User concern:** almost all of the top-scored Layer 2 candidates show the market moving away
from the recommendation.

## 1. What the "away" arrow measured, and why the top is full of it

`movement_vs_pick` was ONE book's price, our first publish -> now. A price that LENGTHENS on our
side raises EV, and EV dominates the score, so the top of the board is enriched for "away" by
construction (same mechanism as `findings_2026-09-21_top_opps_adverse_movement.md` H1).

| top 100 by score | rows |
|---|---|
| moved "away" (single book) | 64 |
| ... of which the no-vig CONSENSUS also moved against the pick (<= -0.25 pp) | **20** |
| ... consensus held (\|d\| < 0.25 pp) or moved TOWARD the pick | 44 |
| median single-book move / median consensus move, away rows | -1.32 pp / **0.00 pp** |
| exchange-priced (ProphetX/Novig/Kalshi) | 75 |

Consensus delta (`movement_fair_delta_pp`) is present on 2,982 of 2,984 served rows.

## 2. Does the market move away AFTER we publish? No — CLV says the opposite

Same-book, pregame closes only. `clv_pct = implied(close) - implied(open)`, + = the close moved
toward the pick. Game-cluster bootstrap (1,000 draws). Dates actually resolved: 09-30 (1,389
rows), 10-01 (3,411), 10-02 (30); **the fleet holds no openings before 09-30.**

| rows | n | games | mean | 95% CI | toward / flat / away |
|---|---|---|---|---|---|
| all published | 4,830 | 20 | +0.72 | [+0.19, +1.14] | 43 / 28 / 29% |
| EV 0-5.26% (the board window) | 366 | 17 | **+2.14** | [+0.69, +2.95] | 55 / 20 / 25% |
| top 25 by EV per date x sport (<=3/game) | 57 | 17 | **+1.63** | [+0.95, +2.38] | 54 / 19 / 26% |
| top 10 by EV per date x sport | 53 | 16 | +1.56 | [+0.84, +2.25] | 53 / 19 / 28% |
| EV 4-5.26% | 39 | 6 | +5.93 | [+2.09, +7.82] | 69 / 21 / 10% |
| exchange / sportsbook (EV window) | 234 / 132 | 9 / 17 | +2.66 / +1.22 | | |

Every sport's mean is positive in the EV window. **Weakest: NCAAF game lines** (n 29, 2 games):
+0.85 [-0.06, +1.60], with 55% of rows closing AWAY — the one segment where the user's
impression is directionally right, on two games.

## 3. Limits — stated because they bound the conclusion

- **~17 finished games.** NFL is one game, NCAAF two. The Render-era work (09-01..09-28, ~900
  games: `findings_2026-09-21_layer2_score_outcomes.md`, `..._top_opps_adverse_movement.md`,
  `findings_2026-09-29_layer2_fee_net_out_of_sample.md`) points the same way, on a different host.
- Top-K here is by **EV at open**, a proxy for the score (the CLV rows carry no score).
- CLV is not ROI; fees not charged here. The outcome test is the scheduled `score_v2` per-sport
  decision (`layer2-score-v2-promotion-decision-1006`).

## 4. What changed / is owed

- **Display (this lane):** the card's arrow now follows the CONSENSUS move; one book's drift is
  neutral price information ("Better price now · ... · market unchanged"). Red only when the
  market moved against the pick.
- **Score (NOT changed, user decision owed since 09-25):** the movement term still penalises the
  single-book "away" rows, which beat the close in every measured sport. The obvious next step —
  key the term on the consensus move — is UNTESTED: nobody has measured whether
  consensus-against rows lose to the close. The price trail can answer it.
