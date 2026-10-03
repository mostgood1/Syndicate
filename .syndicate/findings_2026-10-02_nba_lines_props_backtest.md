# NBA game lines + player props backtest, as-of, 2025-26 — lane `nba-lines-props-backtest`

Generated 2026-10-03 by `scripts/backtest_nba_lines_props.py` (worktree branch `session/nba-lines-props-backtest`),
same method and report shape as `scripts/backtest_nhl_props.py` (lane `nhl-player-props-projection`).
Full tables: `C:\tmp\nba_bt\out\report.md` / `report.json` (scratch; reproducible with
`py -3 scripts/backtest_nba_lines_props.py --out C:/tmp/nba_bt/out`).

## Verdict (one paragraph)

**No NBA market earns a probability or edge on the board for 2026-27.**
- **Props.** The smart-sim engine that production serves is significantly worse than the player's own as-of
  average in 9 of 11 markets (regular season, 8,434 player-games / 428 games). blk is no different and stl is
  worse, so no prop clears the point half of the gate. The book half cannot rescue any market.
- **Probabilities vs the book.** Neither served probability beats the de-vigged book anywhere. The market
  board's unblended Normal is worse in every market with a reading (ONNX stl ties). The picks' book-blended probability is worse in 7 of 9
  smart-sim markets with a verdict and no different in pa and reb.
- **Game lines.** The raw smart-sim margin and total are significantly worse than the captured consensus line.
  The market-anchored configuration that production runs by default ties the book, because it mostly IS the
  book (95% / 70% market weight).
- **Gate.** Apply the NHL rule: means only, probability and edge withheld on every NBA market. **No board
  change was made**; that needs a user decision.

## What was scored, and why that path (traced, not assumed)

- **The Layer-2 board has NO NBA projection source.** `board_enrichment._attach_projections_by_sport` falls
  through at `:1871` to `"no projection source wired for nba"`. NBA model numbers reach a user only on the NBA
  cards page / market board.
- **Game lines** (`syndicate/features/nba/cards.py:2064-2086`). The served margin/total is
  `game_cards.pred_margin/pred_total`, which is the **sum of q1..q4 smart-sim means** (regulation only;
  `refresh_nba_oddsapi_props._smart_sim_projection_index`, because `cards_sim_detail` drops `score`).
  Probabilities are fixed-scale logistics: win `m/6.5`, cover `(m+spread)/7.5`, over `(total-line)/10.5`,
  quarter win `/3.4`. The harness imports `cards._margin_win_prob`.
- **Market anchor.** Syndicate's port anchors the sim to the market by default (total 0.7·market + 0.3·model;
  margin 0.95·market + 0.05·model; `basketball_props_smart_sim._simulate_quarters_local`). The 2025-26
  upstream sims carry no `market_anchor`, so they are raw model output. Arm `smart_sim_anchored_replay`
  applies the anchor ARITHMETIC to the as-of line; it is not a re-sim.
- **Props.** Model mean = `mean_<stat>` (smart-sim) when that column exists, else `pred_<stat>` (ONNX); combos
  are sums. Two probabilities are served:
  - picks: `props_edges.model_prob`. With no `props_prob_calibration*.json` (none exists on the fleet or the
    mirror), pts/pra are shrunk to 0.5 by k=0.45/0.50, and ast/reb/pr/pa/ra are blended 65-85% toward the
    book's vig-inclusive implied price.
  - market board: `model_prob_over` = Normal(mean, sd), unblended (= `model_prob_raw`).
  - The harness CALLS `_compute_props_edges_file_only_local` on the as-of inputs. Parity check: the harness
    Normal reproduces `model_prob_raw` on 35,802 of 35,866 rows (64 off by > 0.002).
- **Not served, scored for context:** upstream `predictions_<date>.csv` (vendor games model), the only full-season
  game projection.

## As-of construction and substrate

- **Projections and odds = files the producers COMMITTED.** Sources are upstream `mostgood1/NBA-Betting`
  `data/processed/` (the source app Syndicate mirrored all season) and Syndicate `origin/main`
  `data/nba_source/` (2026 playoffs). For each (family, date) the harness takes the LAST version committed
  strictly before the date's FIRST tip (ESPN). Re-commits after the games are common (props_edges: 39 of ~200
  dates were last written after game day), and those versions are never used.
- **Not used:** the checkout's `data/**`. **Not available:** Render (all three services billing-suspended
  since 2026-09-30) and the fleet disk (NBA files only from 2025-05 and 2026-10, i.e. preseason).
- **Actuals:** stats.nba.com `playergamelogs` (2025-26 Regular Season + Playoffs) and ESPN scoreboards
  (finals, linescores incl. OT, tip times), fetched 2026-10-02.
  - Join by NBA PLAYER_ID: 12,894 rows.
  - The upstream 2026 playoff files carry **ESPN ids**, so those rows use a unique same-date name match: 6,359.
  - Unmatched rows (not on the slate, DNP, or no unique name): 7,055.
- **Baselines:** (a) the player's 2025-26 per-game average over games strictly before the date, (b) last-10,
  (c) for games, the captured book line.
- **Frozen / not as-of:** model code and constants as they stood in the producers on each date. This scores
  what was served, not a re-run of today's code. Today's code differs in one known way: the market anchor,
  covered by the replay arm.

### Coverage: per family, pre-tip versions only

| | regular (166 dates, 1,235 ESPN games) | playoff (44 dates, 85 games) |
|---|---|---|
| props_predictions | 163 (2 post-tip-only excluded) | 43 (1 excluded) |
| — of which smart-sim `mean_*` | 55 dates scored | 42 dates scored |
| props_odds (raw two-sided prop prices) | **5** (10-24..10-27, 03-26) | **6** (05-30..06-13) |
| game_odds (consensus) | 161 | 38 |
| period_lines | 40 | 38 |
| smart_sim per-game JSON | 553 games / 72 dates | 81 games / 40 dates |
| player logs | 164 | 44 |

**Intersections the results rest on:**
- Props, point accuracy: regular smart-sim 55 dates / 428 games / 8,434 player-games; regular ONNX 96 dates /
  703 games / 8,681; playoff smart-sim 42 dates / 83 games / 1,820.
- Props vs book: **ONNX 4 dates / 37 games; smart-sim 6 dates / 8 games.**
- Served game lines: 524 regular games with smart-sim + book (70 dates), 79 playoff games.
- Periods with book lines: 173-258 regular games.

## Player props: point accuracy (dMAE = MAE model − MAE own as-of average; game-clustered 95% CI)

Smart-sim engine (what production serves):

| market | regular n / games | bias | MAE model | MAE avg | dMAE [CI] | verdict | playoff dMAE [CI] (n 1,820 / 83 games) |
|---|---|---|---|---|---|---|---|
| pts | 8,434 / 428 | −1.11 | 5.473 | 4.837 | +0.636 [+0.535, +0.739] | WORSE | +0.016 [−0.195, +0.229] |
| reb | 8,434 / 428 | −0.38 | 2.122 | 1.928 | +0.193 [+0.158, +0.229] | WORSE | −0.015 [−0.086, +0.051] |
| ast | 8,434 / 428 | −0.47 | 1.532 | 1.406 | +0.126 [+0.101, +0.150] | WORSE | −0.062 [−0.124, +0.003] |
| threes | 8,434 / 428 | −0.05 | 0.987 | 0.897 | +0.090 [+0.077, +0.104] | WORSE | −0.017 [−0.044, +0.007] |
| pra | 8,434 / 428 | −1.96 | 7.434 | 6.463 | +0.971 [+0.825, +1.126] | WORSE | −0.010 [−0.345, +0.323] |
| pr | 8,434 / 428 | −1.49 | 6.667 | 5.864 | +0.803 [+0.673, +0.938] | WORSE | −0.069 [−0.336, +0.195] |
| pa | 8,434 / 428 | −1.59 | 6.220 | 5.407 | +0.813 [+0.692, +0.933] | WORSE | +0.030 [−0.238, +0.296] |
| ra | 8,434 / 428 | −0.85 | 3.018 | 2.728 | +0.290 [+0.235, +0.347] | WORSE | −0.083 [−0.213, +0.045] |
| stl | 8,434 / 428 | −0.08 | 0.767 | 0.724 | +0.043 [+0.032, +0.053] | WORSE | **−0.064 [−0.085, −0.043] BETTER** |
| blk | 8,434 / 428 | −0.19 | 0.503 | 0.506 | −0.003 [−0.009, +0.005] | NO DIFF | **−0.028 [−0.049, −0.004] BETTER** |
| tov | 8,434 / 428 | −0.04 | 1.030 | 0.910 | +0.120 [+0.102, +0.138] | WORSE | +0.019 [−0.014, +0.053] |

- The ONNX era (Oct to mid-Jan, `pred_*` only) is worse still on every market, e.g. pts +1.138 [+1.037, +1.233]
  over 8,681 player-games.
- The smart-sim engine **under-projects systematically** in the regular season (pra −1.96, pts −1.11). The
  last-10 average beats the season average for most markets.
- In the playoffs the smart-sim engine ties the player's average, and slightly beats it for stl and blk. That
  population is one postseason of 83 games; NHL's playoff arm is the same kind of evidence.

## Player props vs the de-vigged book (proportional de-vig of two-sided lines; latest pre-tip snapshot per line/book)

Filters (all 10 dates): 84,858 edge rows, 2,903 dd/td excluded (yes/no), 668 one-sided, 1,060 void/unmatched,
61 with no baseline, 0 ambiguous player matches. 1 date (2026-05-26) was refused by production itself
("No edges computed").

| engine\|market | n / games | Brier book | Brier picks (blended) | Brier board (raw Normal) | dBrier picks−book [CI] | dBrier board−book [CI] |
|---|---|---|---|---|---|---|
| smart-sim pts | 1,408 / 8 | 0.2409 | 0.2900 | 0.3921 | +0.049 [+0.033, +0.066] | +0.151 [+0.109, +0.195] |
| smart-sim pra | 1,019 / 8 | 0.2447 | 0.2565 | 0.3917 | +0.012 [+0.001, +0.021] | +0.147 [+0.077, +0.201] |
| smart-sim reb | 781 / 8 | 0.2434 | 0.2394 | 0.2771 | −0.004 [−0.013, +0.004] | +0.034 [+0.001, +0.069] |
| smart-sim ast | 569 / 8 | 0.2445 | 0.2583 | 0.3623 | +0.014 [+0.002, +0.025] | +0.118 [+0.052, +0.171] |
| smart-sim threes | 511 / 8 | 0.2541 | 0.3097 | 0.3097 | +0.056 [+0.014, +0.103] | same |
| ONNX pts | 6,030 / 37 | 0.2444 | 0.2519 | 0.2705 | +0.008 [+0.001, +0.014] | +0.026 [+0.011, +0.041] |
| ONNX pra | 5,570 / 37 | 0.2412 | 0.2436 | 0.2768 | +0.002 [−0.001, +0.005] | +0.036 [+0.018, +0.054] |
| ONNX reb | 3,184 / 37 | 0.2459 | 0.2486 | 0.2725 | +0.003 [+0.000, +0.006] | +0.027 [+0.013, +0.039] |

- **Every market with a reading, both engines:** the unblended Normal (what the NBA market board shows) is
  significantly worse than the book. The exceptions are ONNX stl, which is no different
  (+0.0095 [−0.006, +0.027], 263 rows), and tov, which is unmeasurable (19 rows).
- The blended pick probability is never better than the book. It ties only where it is 65-85% the book's own
  price.
- Flat-stake ROI on the picks' +EV side is negative or indistinguishable from 0 in every market (best: ONNX
  ast +0.8% [−7.3%, +8.7%] on 1,933 bets). For the smart-sim engine, pts is −29.8% [−45.1%, −15.4%] on 1,179
  bets.
- **This half is THIN for the served engine: 8 games.** The OddsAPI historical backfill (approved,
  ~139k credits) would extend it to about 600 smart-sim games. It **cannot change the gate**, because the point
  half already fails every regular-season smart-sim market.

## Game lines (served = smart-sim quarter sum; regular season, 524 games with a pre-tip book)

| arm | margin dMAE vs line [CI] | total dMAE vs line [CI] | ML dBrier vs book [CI] | cover dBrier [CI] | over dBrier [CI] |
|---|---|---|---|---|---|
| smart_sim (raw, 2025-26 as served) | +1.903 [+1.290, +2.543] WORSE | +3.270 [+2.344, +4.169] WORSE | +0.040 [+0.025, +0.056] WORSE | +0.047 [+0.028, +0.066] WORSE | +0.047 [+0.027, +0.069] WORSE |
| anchored replay (2026-27 default) | +0.006 [−0.027, +0.042] = | +0.250 [−0.035, +0.552] = | +0.0005 [−0.002, +0.004] = | +0.0004 [−0.001, +0.002] = | +0.005 [−0.002, +0.013] = |
| predictions_csv (vendor, not served; 816 games) | +2.745 [+2.172, +3.331] WORSE | +2.495 [+1.842, +3.210] WORSE | +0.085 [+0.066, +0.104] WORSE | +0.069 WORSE | +0.039 WORSE |

- Raw smart-sim total bias is **−6.69** in the regular season (and **+13.6** over 79 playoff games). It is
  not OT: the regulation-only sum misses about 0.6 pts on average.
- **Periods:** h1 and q1-q4 totals are significantly worse than the period lines (q1 +0.97 [+0.52, +1.45],
  h1 +1.81 [+0.95, +2.71]; 173-258 games). Margins are worse or no different. Quarter win probabilities have
  no book to compare against.
- **A false edge, found and removed.** Before the price fix, the anchored replay showed cover MODEL_BETTER
  with +31% ROI. Cause: the upstream consensus `game_odds` pairs main points with alt-line prices (e.g.
  −245/+180), and 502 of 1,281 rows are unpriced. Spread/total prices are now used only inside a main-line
  band (431 cover / 538 over pairs kept; 172 / 68 reset to −110). After the fix: NO_DIFFERENCE, 86 bets,
  ROI −4.8% [−27.2%, +16.0%]. **Spread/over book Brier here is a coin with noise;** the gate also requires
  beating p = 0.5.

## Gate list for 2026-27 (rule: PROBABILITY only if it beats its baseline AND the book, CI excluding 0)

| market | gate | deciding reading |
|---|---|---|
| pts, reb, ast, threes, pra, pr, pa, ra, stl, tov | MEAN_ONLY | worse than own average (regular, smart-sim) |
| blk | MEAN_ONLY | ties own average; worse than the book (+0.086 [+0.050, +0.129], 8 games) |
| dd, td | MEAN_ONLY | one-sided yes/no; not measurable vs a de-vigged book |
| game ML / cover / over | MEAN_ONLY | raw sim worse than the book; the anchored default ties it (no edge) |
| game margin / total (point) | MEAN_ONLY | same |
| h1 / q1-q4 margin, total, win prob | MEAN_ONLY | worse or no different vs period lines; no book for quarter ML |

**What the board does today that this contradicts (no change made; user decision owed):**
- The NBA market board shows `model_prob_over` (raw Normal) for props, and the cards show win, cover and over
  probabilities.
- Props picks are made from `props_edges` edges.
- The NHL precedent is `MEASURED_MARKETS = frozenset()` with probability withheld. The NBA equivalent would be
  a gate in `basketball_market_board.py`, `nba/cards.py` and the picks export, before opening night (~late
  October).

## Daily accuracy / weekly backtests: what covers NBA

- `publish_model_scorecard.SEASON_WINDOWS` has `nba: (10-01, 06-25)`, so the daily scorecard switches NBA on
  from Oct 1. The skill doc says it is "registered, reachability proved, correctness not yet measurable".
- It grades board rows with `row["projection"]`. NBA board rows get no projection (`board_enrichment:1871`), so
  **NBA model skill is ungradable there** (inferred from code, not read off a published scorecard). Only
  market-side rows will exist.
- `run_weekly_backtests.py` has a `wnba_projection` job and **no NBA job**. This script is the obvious
  candidate.
- The existing NBA accuracy code (`nba/market_accuracy.py`, `live_*_accuracy.py`) scores selected picks'
  W/L/ROI only. It has no MAE, Brier or baseline.

## Defects found in passing

- **`basketball_props_edges` short-key fallback is a many-to-many merge.** `PROP_NAME_JOIN` printed
  `unmatched_after_fallback` 142k-333k against `rows_considered` 9k-25k on 2025-10-24..27. Recorded as a lead
  (`.syndicate/leads.md`, 2026-10-03). In the scored rows it produced 0 ambiguous player assignments after
  dedup, but the counter is meaningless.
- **Upstream 2026 playoff `props_predictions` switched to ESPN player ids.** Any id-joined NBA grader
  silently drops them.
- **Upstream consensus `game_odds` spread/total prices are unreliable** (see above). Any Brier or ROI computed
  against them is suspect.
- **The repo `.env` `ODDS_API_KEY` is deactivated** (HTTP 401 `DEACTIVATED_KEY`, 2026-10-03).

## Not done / owed

- **OddsAPI historical backfill** (user-approved ~139k credits). Blocked: the repo key is deactivated, and
  auto mode refused reading the fleet's key twice as credential exploration, even after the user authorised it
  in chat. The harness is ready:
  `--fetch-odds` (dry run, 139,203-credit estimate) → `--fetch-odds --execute --max-credits 150000`, then
  `--analyze-only`. It writes only under `--out/cache`. The backfilled odds are not yet wired into scoring
  (`hist_props_csv` / `hist_game_book` exist; the book arm still reads the committed files).
- No board or engine change; nothing deployed.
