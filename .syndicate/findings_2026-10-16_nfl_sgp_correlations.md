# NFL same-game-parlay leg correlations, measured at real closing lines — 2026-10-16

Lane `nfl-sgp-builder`. User 2026-10-16: build SGP recommendations, "NFL first", priced at an ASSUMED book
discount (no SGP price source exists). The joint probability is the one number Syndicate can measure itself, so it
is measured here and never assumed. Script: `scripts/build_nfl_sgp_correlations.py` (method in its docstring);
tests `tests/test_nfl_sgp.py` (13). Run on the fleet at nice 19; output in the session scratchpad
(`sgp_out5/nfl_sgp_correlations.json`) — **not yet published to the data root, nothing deployed.**

## Data (coverage stated, per CLAUDE.md)

- Book closes: `backfill/nfl_prop_closes_2023_25/<season>_wk<n>.jsonl` (DK, FD, MGM, Caesars, BetRivers,
  BetOnline, Bovada) — **2023: 132 events (partial season), 2024: 235, 2025: 226 = 593 games**, all matched to
  nflverse play-by-play (REG only).
- Legs graded: 2023 7,527 · 2024 13,988 · 2025 14,018 (one consensus line per player x market; a push dropped; a
  player with no dropback/carry/target in the game dropped, as a book voids a non-player — this also drops a
  played zero-touch game, a small bias toward the over).
- 2023 carried **1,003 duplicate-spelling legs** ("St Brown" / "St. Brown" -> one player): dropped, keeping the
  spelling more books quote. Before the fix they appeared as an "Anytime TD x Anytime TD, same player" cell at
  rho 0.95 — one bet paired with itself.
- Roles from season-to-date usage BEFORE the week (QB / RB1 / RB2 / R1 / R2 / R3 / UNK) — no hindsight.

## Result 1 — the correlations are real and they transfer (fit 2023-24, scored on 2025)

Four-cell log loss, Gaussian copula vs independence on the SAME marginals (so the difference is the correlation
only), game-clustered SE, 433,807 holdout pairs over 226 games:

| relation | pairs | diff (nats/pair) | SE | z |
|---|---|---|---|---|
| all | 433,807 | -0.00285 | 0.00012 | -23.1 |
| same player | 22,323 | -0.0426 | 0.0019 | -22.4 |
| teammates | 192,595 | -0.00131 | 0.00013 | -10.2 |
| opponents | 218,889 | -0.00014 | 0.00004 | -3.8 |

**Shrinkage was necessary, not cosmetic.** Unshrunk, the teammate gain was smaller (z -6.6) and opponent pairs
were no better than independence (z +0.1); an earlier unrecalibrated, unshrunk fit made opponent pairs 6 SE
WORSE. Empirical-Bayes per level x relation: type-level opponent cells have tau = 0 (all 424 shrink to 0 — role
detail for opponents is noise); teammates tau 0.083; same player 0.29. A cell at n = 300 has an SE near 0.08.

**Calibrated:** predicted vs realised joint hit rate on the selected holdout tickets 0.230 vs 0.232, 0.325 vs
0.320, 0.361 vs 0.350.

Strongest market-level cells (shrunk rho, all n > 1,100): Rec Yds x Receptions same player +0.82; Rush Att x Rush
Yds same player +0.72; Pass Att x Pass Yds +0.66; Pass TDs x Pass Yds +0.48; **QB Pass Yds x teammate Rec Yds
+0.33**; Pass Att x teammate Receptions +0.31; QB Pass TDs x teammate Anytime TD +0.29. Negative: opposing teams'
Rush Attempts -0.20 (game script); Pass Att x teammate Rush Yds -0.16; Ints x Pass TDs same player -0.17.

## Result 2 — what the price would have to be (exploratory, NOT a pre-registered test)

For each holdout pair, the orientation with the most joint probability per unit of the book's own vigged leg
prices; "max haircut" = 1 - prod(q) / p_joint = the largest SGP discount (vs the product of the leg prices) at
which the ticket is still +EV. **Median -14.0%, p90 -7.7%, p95 -0.5%, p99 +21.1%** — 95% of pairs are -EV even
if a book paid the full product of the vigged legs.

Realised on 2025, betting every pair the model calls +EV at an ASSUMED haircut h (payout = product x (1-h)):

| assumed h | tickets | same player | teammate | hit (pred) | realised ROI | SE |
|---|---|---|---|---|---|---|
| 0% | 21,274 | 12,276 | 8,997 | 0.232 (0.230) | +19.4% | 3.0 |
| 10% | 9,014 | 8,278 | 736 | 0.242 (0.244) | +20.9% | 4.1 |
| 18.5% | 5,031 | 4,906 | 125 | 0.320 (0.325) | +15.6% | 4.0 |
| 25% | 3,628 | 3,606 | 22 | 0.350 (0.361) | +7.1% | 3.1 |
| 30% | 2,240 | 2,238 | 2 | 0.355 (0.361) | +1.9% | 2.8 |

**Read this carefully — the ROI is the ASSUMPTION, not an edge.** Above a 10% haircut, 97-100% of the "+EV"
tickets are SAME-PLAYER pairs (a receiver's receptions AND yards) — the correlation every sportsbook's SGP engine
knows best and prices tightest. A flat assumed discount manufactures EV exactly where it is least credible. A
teammate stack (QB yds + his WR1 yds, rho 0.33 at two -115 legs) breaks even at a ~5% discount — real books
discount such stacks more than that (UNVERIFIED: no SGP quotes exist in the repo; the 10-13 research note puts
SGP margin at ~18.5%).

## Engine read

- The NFL prop model (rolling mean x game multiplier) has no joint structure at all; these cells are a validation
  target for any future NFL sim (a drive engine must reproduce QB-yds x WR-yds +0.33 and opponent rush attempts
  -0.20, or its parlay prices are wrong).
- Marginal calibration at the consensus close, 2023-25: **Rushing Attempts overs hit 47.1% vs fair 49.9% (-2.8 pp,
  n = 2,697) and Rushing Yards 46.8% vs 49.5% (-2.7 pp, n = 3,376)** — iid SE ~1.0, NOT game/player-clustered,
  so UNVERIFIED as a betting signal; every other market within ~1.3 pp.

## Implication for the builder (proposed, not built)

State each suggestion as **our joint probability -> fair SGP odds -> "worth it at +X or better"**, so the user
compares against the book's real SGP quote; show the assumed-discount estimate second, labelled an estimate.
Same-player tickets flagged as the pairing books price tightest. Paper ledger per suggestion; no edge label until a
pre-registered, game-clustered test passes (#621).
