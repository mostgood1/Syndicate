# NHL same-game-parlay correlations — box scores 2023-25 + REAL 2025-26 book lines — 2026-10-16

Lane `nhl-sgp-builder`. User 2026-10-16: "lets build the next logical sport - NHL" (after "Alt-line consistency
first"). Script `scripts/build_nhl_sgp_correlations.py` (worker agent, reviewed and landed by session 9e18a0e7;
the NFL estimator is imported, not copied); tests `tests/test_nhl_sgp_correlations.py` (21). Ran on the fleet at
nice 19, 18m38s, peak 2.65 GB. Published: `nhl_source/sgp/nhl_sgp_correlations.json` = the REAL-LINE fit;
`nhl_sgp_correlations_proxy.json` = the box-score proxy fit, kept for reference.

## Data (coverage stated)

- Box scores, regular season: 2023-24 1,312 games / 50,018 player-games / 173,771 proxy legs; 2024-25 1,312 /
  49,988 / 173,773. Pairs: 12.17 M train, 12.16 M holdout.
- **Historical NHL prop lines DO exist** (the brief assumed not): 2025-26 pregame OddsAPI snapshots for all 1,312
  games, 7 books, ~14 min before the start (median of a 66-game sample) -- SOG / points / assists / goals in
  `backfill/nhl_lines_2025_26/odds_skater_props/`, saves in `odds_saves` + `odds_saves_rest`; box scores in
  `backfill/nhl_source_dev/ingestion_cache/`. 73,331 legs graded (3.5% void/unmatched, 237 ambiguous names), 2.04 M pairs.
- Roles: the engine's own `line_slot` rule (average TOI over the team's last 8 EARLIER games -> L1-L4, D1-D3); G =
  the box score's starter flag (most TOI picks the reliever when a starter is pulled).

## Out of sample (diff in nats/pair, negative = copula beats independence; z)

| relation | A: proxy 23-24 -> 24-25 (shrunk) | A raw | B: proxy cells on 2025-26 real lines | B raw | C: real lines, before 2026-01-01 -> after |
|---|---|---|---|---|---|
| same player | -0.0797 (-151) | -0.0801 | -0.1042 (-110) | -0.1042 | -0.1065 (-79) |
| teammate | -0.00077 (-23.6) | -0.00122 | -0.00277 (-12.5) | -0.00280 | -0.00248 (-9.3) |
| opponent | 0.0000 (+1.1) | -0.00004 (-2.2) | -0.00001 (-1.9) | -0.00036 (-7.2) | -0.00030 (-8.6) |

Teammates beat independence in every test. **The lane's falsification line fires for OPPONENTS in the PROXY cells
only** (shrinkage zeroed all 551 opponent role cells); unshrunk proxy cells and the real-line fit beat independence.
Calibrated in C: predicted vs realised both-over 0.2495 vs 0.2492 (same player), 0.1894 vs 0.1885 (teammates).

## Strongest cells (published real-line value, proxy in brackets)

- Same player: SOG x goals L1 +0.43 (+0.40); SOG x points L1 +0.26 (+0.23); SOG x assists ~0.
- NESTED (one implies the other): goals x points, assists x points +0.91-0.95 -> listed in `nested_same_player` and
  EXCLUDED by `nhl/sgp.py`.
- Linemates (same slot): points L1 x L1 +0.32 (+0.33); assists L1 x goals L1 +0.31; points fall with line distance
  (L1xL2 +0.19, L1xL3 +0.09); points D1 x L1 +0.22; SOG L1 x L1 only +0.03.
- Goalie saves x opposing SOG L1: real-line +0.21 (raw +0.28), the cell alone z -11 in C.

## Engine read (2025-26 book lines vs a median proxy)

- SOG: proxy = book line 72%; when they differ the book is usually LOWER (24% vs 3%); overs hit 45% at proxy lines
  vs 50.4% at book lines. Points: 92% match (books use 1.5 on 5.7%). Goals / assists: 0.5 almost always.
- Saves: only 18% match -- book lines sit 0.56 saves BELOW the goalie's prior mean (regressed toward 23.5-24.5).
- De-vigged fair vs realised: assists 0.354 vs 0.342; saves 0.503 vs 0.516 (iid SEs, not clustered -- UNVERIFIED).

## Live (2026-10-16 7:53 PM CT, fleet 73744440)

The NHL 10-16 sheet carries 6 parlays (6 to `cheatsheets/nhl/sgp_ledger.jsonl`), served on `/cheatsheets?sport=nhl`;
e.g. DiPietro OVER 30.5 saves + LaCombe OVER 2.5 SOG: both 12% vs 9% unrelated, fair +706, worth it at +746, est.
+910 (FanDuel legs +1140 less the ASSUMED 18.5%). Legs come from the consistency ladder's priced alt rungs
(15-85% market probability) and the main lines.

## Follow-ups (the worker's decisions list; NOT done)

1. **Shrinkage defect, shared with NFL:** `shrink_cells` estimates tau around the cells' MEAN but shrinks toward 0, so
   a group of uniformly mildly-positive cells is over-shrunk (gives up 37% of the NHL proxy teammate gain). Fix =
   shrink each role cell toward its MARKET cell; re-run both sports' OOS before shipping.
2. **A shrunk-to-0 role cell hides the market cell** (`rho_for` returns the role cell first): NFL's 424 opponent role
   cells all shrank to 0, so NFL opponent pairs price as independent wherever a role cell exists. Same fix as 1.
3. Promote `fit_rho` / `shrink_cells` into a shared module (the NHL script loads them from the NFL script file).
4. UNVERIFIED: linemates are a TOI-rank proxy in the box scores (no line data); the sheet uses tonight's PROJECTED
   lineup, the fit used dressed lineups; no SGP prices exist, so no price study.
