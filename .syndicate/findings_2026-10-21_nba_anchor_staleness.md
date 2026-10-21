# The NBA SmartSim's market anchor is a D-1/D-2 line, never refreshed: measured (lane `nba-sim-anchor-staleness`)

Session fe168a0f, 2026-10-21. Started from session b3292576 on lead §5.1 of
`findings_2026-10-21_post_tip_rebuilds.md` (lane freeze-nba-pregame-sims).

## Substrate

The fleet's production data root, read-only, read 2026-10-21 12:47 PM CT. The data root is
`/home/amyn/syndicate-prod/data/nba_source`. Files read:
- every surviving `data/processed/smart_sim_<D>_<H>_<A>.json` for 10-03..10-23. There are 74 sims. Each records
  `market_anchor`: the line, the weights, `model_total_raw`, `model_margin_raw` and the anchored values.
- `game_odds_<D>.csv` (rows plus mtime).
- `tracking/book_quotes/<D>.jsonl[.gz]` (main lines, full game, 10 US books).
- finals from `linescores_<D>.json` (period sums, OT included), else `recon_games_<D>.csv`.

Script: `scripts/nba_anchor_staleness.py`.

## 1. Why it is never refreshed (code)

- The sim job reads `total` / `home_spread` from the `predictions_<D>.csv` row. It falls back to
  `game_odds_<D>.csv` (`basketball_props_smart_sim.py`, job build ~:5554).
- **Writer.** Both files are written by `predict-date` (`source_cli/cli.py`):
  - it fetches OddsAPI current odds;
  - `consensus_lines_at_close` (`source_cli/odds_api.py`) takes the **modal** point across books. A tie goes to
    the smaller value.
- **Neither file is ever rewritten** (`scripts/refresh_nba_oddsapi_props.py`):
  - `_ensure_game_predictions_for_props_refresh` returns as soon as `predictions_<D>.csv` has rows. It re-runs
    `predict-date` only when the slate GREW.
  - `_seed_game_odds_from_props_snapshot` returns once `game_odds_<D>.csv` has prices.
  - `_merge_new_snapshot_matchups_into_game_odds` only APPENDS games it lacks, by design: "a game can drop out of
    the snapshot once it starts".
- The refresh's lookahead writes D+1 and D+2. So the line is whatever the market said on the first run that saw the
  date:
  - 10-20: 10-19 1:01 AM CT;
  - 10-21: 10-19 3:04 AM CT;
  - 10-22: 10-20 9:32 AM CT;
  - 10-23: 10-21 6:04 AM CT.
- **The reuse checks never compare odds** (§2 of the post-tip findings). A sim rebuilt for any other reason still
  reads the same line.

## 2. Method checks (both pass)

- **The book-quotes consensus reproduces the production anchor.** At the anchor's write time, the modal
  consensus of each book's standing line (book_quotes is written on change) equals the recorded anchor:
  - both lines, exactly, on 66 of 74 games;
  - the total on 67 of 74, the spread on 71 of 74;
  - 7 of the 8 misses are 0.5 pt. One is LAL_GSW 10-13, spread -2.5 vs -5.5.
  - The props-snapshot MEAN (the other seeder's statistic) matched 12 of 73. It is the wrong statistic for this
    anchor.
- **Anchor arithmetic.** `_apply_market_anchor_local` (imported, not copied) on the recorded raw means and line
  reproduces `anchored_total` / `anchored_margin` exactly on **74 of 74**.
- **Pass-through, anchored target -> served engine mean, across the 74 sims:**
  - total slope 1.03 ± 0.08;
  - margin slope 0.94 ± 0.07.
  The served counterfactual `served + (anchored_close - anchored_open)` therefore assumes 1. The anchored targets
  are scored on their own beside it, with the same result.

## 3. Staleness distribution

"Close" here is the modal consensus of each book's last pregame quote, with `captured_at <= tip`. The last capture
before tip came, over the 59 graded games:
- median 10 min before tip;
- p90 55 min;
- max 18 h, one game;
- on 10-20: 140, 115 and 1 min.

| population | games | anchor age at tip (h) | abs(Δ total), median / mean / p90 / max | ≥ 2 pt | abs(Δ spread), median / mean / p90 / max | ≥ 2 pt |
|---|---|---|---|---|---|---|
| preseason 10-03..10-16 | 56 | median 19, max 43 | 1.0 / 1.46 / 3.0 / 9.0 | 20 | 1.0 / 2.21 / 5.0 / 9.0 | 25 |
| regular 10-20..10-23 | 18 | median 63, max 67 | 1.0 / 1.00 / 3.0 / 3.0 | 4 | 0.5 / 0.92 / 3.0 / 4.0 | 3 |

- **The regular-season row is mostly PARTIAL.** Only 10-20's three games have closed:
  - DET_BOS: spread -1.5 -> +1.5, total 222.5 -> 220.5;
  - SAS_OKC: spread -2.5 -> +1.5;
  - NYK_PHI: spread -5.0 -> -4.5.
  - 10-21's 11 games are read at 12:47 PM CT against 6:00-9:40 PM CT tips. So far BKN_CHA has moved -1.5 -> +1.5
    (the favourite flipped), and LAL_GSW / MIA_MIN have moved 3.0 on the total.
  - 10-22 and 10-23 are days out.
- **Preseason moves are larger** (late rest decisions). Examples:
  - OKC_NOP 10-06: -7.5 -> +1.5;
  - UTA_SAS 10-12: +2.5 -> -5.5;
  - DAL_HOU 10-09: total 221.5 -> 230.5.

## 4. Would the near-close anchor have scored better? (totals and margins vs finals)

Paired abs-error difference, close minus anchor (negative = the close is better), ± SE. **59 graded games: 56
preseason + 3 regular season.** 10-21 is pending.

| quantity | MAE anchor | MAE close | diff ± SE | close better / worse / tied |
|---|---|---|---|---|
| line, total | 14.53 | 13.98 | **-0.54 ± 0.26** | 30 / 15 / 14 |
| line, margin | 12.92 | 11.83 | **-1.09 ± 0.38** | 33 / 15 / 11 |
| anchored target, total | 14.50 | 14.14 | -0.36 ± 0.18 | 29 / 17 / 13 |
| anchored target, margin | 12.84 | 11.81 | -1.03 ± 0.36 | 34 / 18 / 7 |
| **served sim, total** | 14.71 | 14.33 | **-0.39 ± 0.18** | 30 / 16 / 13 |
| **served sim, margin** | 12.94 | 11.96 | **-0.97 ± 0.36** | 34 / 18 / 7 |

- **With the consensus taken 30 min before tip** (one that a rebuild could still finish before the freeze), the
  served sim scores:
  - total -0.37 ± 0.16;
  - margin -0.86 ± 0.34.
- **Regular season alone: 3 games, uninformative.**
  - served total 0.00 ± 0.81;
  - served margin -0.48 ± 1.92.
- **What this rests on:** 59 games on 16 dates, 95% of them preseason. Preseason is a different population, with
  bigger late moves. So the regular-season effect is expected to be SMALLER than these numbers. Its direction
  (the close beats an earlier line) is the ordinary market property that the anchor exists to use.

## 5. What a stale anchor reaches today

The gain lands in the sim's own outputs. It reaches priced lines only through a small weight.
- **Layer 2 NBA game lines** blend the sim toward the de-vigged fair (`nba_game_book_blend.json` on the fleet,
  written 10-05):
  - w = 0.00 on spreads and h2h, 0.05 on totals, in the regular season;
  - 0 in preseason, and 0 on periods.
  So a stale anchor moves a traded game-line price only through the 0.05 totals weight.
- **Cards and the market board** show the sim's game margin and total. These are stale whenever the line moved.
- **The NBA live re-sim** starts from the pregame engine inputs, `engine_inputs/<D>/*.pkl`. It is shadow, not
  priced.
- **Props:** the anchored team total sets the engine's scoring target. Its effect on player means is small and
  UNMEASURED; the summed player points already run +8.5 over the anchored team score (`nba-no-history-standins`).

## 6. Cost of a refresh

- An anchor-drift rebuild (rebuild a pregame sim when the current modal consensus differs from its recorded anchor)
  was replayed over every pregame capture between the anchor's write time and tip - 30 min. Extra builds per game:

  | threshold | preseason (56 games) | regular (14 games, partial) |
  |---|---|---|
  | 0.5 pt | 7.0 | 2.6 |
  | 1.0 pt | 4.9 | 2.1 |
  | 1.5 pt | 2.7 | 0.9 |

- One build takes 47 s median, 70 s p90 (post-tip findings §4).
- The tip freeze already stops every rebuild after tip.

## 7. Found on the way, not acted on

1. **The anchor has two writers with two statistics.**
   - `predict-date` takes the MODAL point.
   - The props-snapshot seeder (`_aggregate_game_odds_from_market_rows`, used when `game_odds` is seeded or a
     newly priced game is appended) takes the MEAN.
   - A game appended later is therefore anchored on a different statistic. That is probably LAL_GSW 10-13's
     3-point spread miss.
2. **Preseason anchors were often written from 3-5 books.** 10-14's file was written at 12:31 AM CT, with 3 books
   on most games.
3. **`predictions_<D>.csv`'s market columns** (`market_home_margin`, `edge_spread`, `edge_total`) carry the same
   stale line to every reader of that file.

## 8. Decision and build

- **User, 2026-10-21 (AskUserQuestion):** "Refresh, on by default (Recommended)" and "Yes, ff when green".
  - On the ride-along question that followed: "Wait for its deploy (Recommended)".
- **Built in 6e406101:** `syndicate/features/shared/smart_sim_anchor_refresh.py` and four hooks in
  `basketball_props_smart_sim.py`:
  - the fresh-line load before the per-game loop;
  - the last reuse condition;
  - the job-line override;
  - the worker's `market_line_source` / `market_line_as_of` stamp.
- **Tests:** 14 new in `tests/test_smart_sim_anchor_refresh.py`, with off != on on the real loop. 193 pass across 17
  neighbouring suites.
- **Shadow dry run, fleet code against the fleet's 10-21 snapshot (11:14 AM CT):** 9 of 11 sims are 1 pt or more
  off the stored line. 10-23's snapshot (6:03 AM CT) was correctly ignored, because it is not newer than its
  predictions file (6:04 AM CT).
- The script gained `--stale-from game_odds`, for the pre-registered regular-season reading once sims carry the
  refreshed line.
