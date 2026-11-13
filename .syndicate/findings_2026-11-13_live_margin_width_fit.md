# Live full-game spreads and moneylines: fitting the model's over-confidence (todo #780, the margin half)

- **Lane** `live-margin-prob-scale`, session 8062940b.
- **User** 2026-11-13 "Fit them now" (spreads and moneylines, after the totals scale loaded).
- **Substrate:** production. The fleet's live gameline ledgers, read on the fleet host at nice 19, against ESPN finals.
- **Script:** `MARKET=spreads|h2h scripts/live_totals_width_fit.py`. Full output: `C:\tmp\livegrade\load780\fit_margin_1113.txt`.
- **Companion:** `.syndicate/findings_2026-11-13_live_totals_width_fit.md` (the totals scale, loaded 17:55:57Z 11-13).

## What was fitted

- **The transform** is the totals one: P_k = Phi(Phi^-1(P) / k), an estimator that moves no mean.
- **P** is the ledger's `model_home_win_prob`:
  - spreads: P(home margin > line), with `line` a threshold on the HOME margin;
  - h2h: P(home wins), the same question at line 0.
- **Outcome:** the final margin in the LEDGER's home orientation (`ledger_home_margin`; a game whose orientation is
  ambiguous is dropped and counted). A push is dropped.
- **Progress** (for the per-bucket reads only): points scored over the model's own total mean.
  `progress_fraction` is never populated for basketball or football: 0 of 190,000+ margin rows.
- **Population:** spreads / h2h rows on the full game with a model probability, priced or not, one per (event, state,
  line). NCAAB dates >= 11-13 (the PREREG_780 window) are never read.
- **Evaluation:** walk-forward by ledger date, Brier against k = 1, game-clustered 95%.

## Result (read 2026-11-13 ~19:35Z, ledger dates through 11-12)

### Spreads

| sport | graded states / games | k fitted | walk-forward Brier gain | per-bucket k | model - market Brier, k=1 -> k |
|---|---|---|---|---|---|
| NBA | 22,036 / 162 | **2.017** | -0.006 +- 0.007 (21 dates) | -0.008 +- 0.007 | +0.004 +- 0.014 -> -0.002 +- 0.008 |
| NCAAF | 93,683 / 325 | **1.797** | **-0.006 +- 0.004** (27) | -0.007 +- 0.004 | -0.003 +- 0.011 -> -0.008 +- 0.007 |
| NCAAB, all dates | 30,977 / 398 | 1.597 | **-0.004 +- 0.003** (9) | -0.004 +- 0.004 | +0.005 +- 0.007 -> -0.000 +- 0.003 |
| **NCAAB, after #768** (11-09..11-12) | 10,786 / 136 | **1.339** | -0.003 +- 0.003 (2) | -0.003 +- 0.003 | +0.007 +- 0.013 -> +0.003 +- 0.010 |
| WNCAAB | 3,354 / 74 | 1.190 | **+0.006 +- 0.005** (8): hurts | +0.002 +- 0.005 | -0.023 -> -0.016 |

- **Stability:**
  - NBA's walk-forward k held 2.02-2.03 over its last 4 steps (it came down from 2.6-3.0 in October).
  - NCAAF held 1.79-1.89 over its last 15 steps.
  - NCAAB fell 2.04 -> 1.61 as post-#768 nights entered, so the post-fix fit (1.34) is the one used.

### Moneylines (h2h)

| sport | graded states / games | k fitted | walk-forward Brier gain | model - market Brier, k=1 -> k |
|---|---|---|---|---|
| NBA | 3,962 / 162 | 1.038 | +0.003 +- 0.005 | +0.020 +- 0.012 -> +0.023 |
| NCAAF | 13,560 / 324 | 1.246 | -0.001 +- 0.003 | +0.009 -> +0.008 |
| NCAAB | 3,557 / 381 | 0.965 | +0.001 +- 0.001 | +0.009 -> +0.010 |
| WNCAAB | 488 / 61 | 0.801 | -0.001 +- 0.014 | -0.008 -> -0.009 |

**No gain in any sport, so moneylines are not tempered.** The model's moneyline IS worse than the market in NBA
(+0.020) and NCAAB (+0.009), but tempering does not close that gap. It is a discrimination / bias problem, not
over-confidence, and stays open under `#780`.

## Why spreads need it and moneylines do not

The OLS of (final margin - line) on (model margin mean - line), by progress (< 0.40, 0.40-0.75, >= 0.75):

| market | NBA | NCAAF | NCAAB (spreads: after #768; h2h: all dates) |
|---|---|---|---|
| spreads (line = the market's) | b -0.01 / 0.44 / 0.69 | 0.46 / 0.73 / 0.79 | 0.49 / 0.70 / 0.81 |
| h2h (line = 0) | 0.81 / 0.84 / 0.88 | 0.76 / 0.91 / 0.97 | 0.87 / 0.82 / 0.91 |

- A spread line is the market's own margin estimate. The model's distance from it is mostly noise: none of it carries
  information early in NBA games.
- At margin 0 the model's mean carries real information (b 0.76-0.97), and the moneyline is about right.
- **It is not a width fix.** The pure width ratio (error sd / implied sd) is 0.84-1.23, and walk-forward width scaling
  gains nothing (+0.000 to +0.001). The fitted k is a correction toward the market's line, learned only from outcomes.
  The totals scale is the same thing, read the same way.

## The decision rule, and how it was set

- **The rule:** scale a sport and market when the walk-forward one-k gain is at least 0.003 Brier and the model's Brier
  against the market does not get worse.
- **How it was set:** written after this fit was read, then checked against every earlier decision. It reproduces all
  of them:
  - totals: NBA -0.006 scaled, NCAAF -0.015 scaled, NCAAB after #768 -0.001 not, WNCAAB -0.001 not;
  - spreads: NBA scaled, NCAAF scaled, NCAAB scaled, WNCAAB not;
  - h2h: none scaled.
- **NBA spreads is the marginal one.** Its one-k interval reaches 0 (-0.006 +- 0.007). It is scaled on three
  grounds: the per-bucket interval excludes 0 (-0.008 +- 0.007), the slope is ~0 early, and k is stable.
  `SYNDICATE_LIVE_SPREADS_PROB_SCALE_NBA=1` turns NBA back alone.
- **NCAAB's post-fix gain** rests on 2 walk-forward dates. Re-fit it with the totals re-fit once more post-fix nights
  exist.

## What was built (on main, NOT LOADED: the user's decision)

- **`live_gameline_join._SPREADS_PROB_SCALE_BY_SPORT`:** NBA 2.02, NCAAF 1.80, NCAAB 1.34. Every other sport is 1.
- **Switches:** `SYNDICATE_LIVE_SPREADS_PROB_SCALE=off` (every sport), `_<SPORT>=<k>` (one sport). Junk falls back to
  the table. Independent of the totals switch.
- **One place decides a row's k:** `full_game_prob_scale(market, segment, sport)`.
  - totals -> `totals_prob_scale`, spreads -> `spreads_prob_scale`, h2h and every segment -> 1.0.
  - An absent segment is not "full" (the join's no-permissive-branch rule).
  - The pricer's call site and the Live column (`live_display_block`) both read it, so a price and the display agree.
- **`price_distribution_market`** now records `prob_scale` on spreads rows as it does on totals (1.0 = untempered).
  The precision gate judges the scaled edge against the scaled sim error.
- **Ledger:** still v7. A spreads row with `prob_scale` None was written before this, and one with a value after it.
  `model_home_win_prob_unscaled` carries the engine's number wherever k != 1. h2h stays None.
- **Tests:** `tests/test_live_margin_prob_scale.py`, 43.
  - Reachability first: off != on through `attach_live_gamelines` and through `board_enrichment`.
  - The table, the switches and their independence, which rows are tempered, the gate, the display, the ledger.
  - 8 source mutations, each caught.
  - `test_live_totals_prob_scale.py`'s "spreads untouched" test now asserts what is true: the TOTALS switch leaves
    spreads and h2h alone.
  - The 73 test files that drive the join and the ledger: 1,512 of 1,513 passed. The failure was
    `test_live_display_other_sports.py::test_ncaaf_stale_quote_reads_its_graded_margin_and_its_moneyline_shows`,
    which asserted the untempered NCAAF spreads display number (0.70). That is this change working as designed:
    0.61 at k 1.80. The test now reads the engine's number with the switch off, then checks the tempered one with
    it on and the moneyline unchanged. Its file passes, along with both scale files (113).

## Replay on production rows (fleet ledger, the new code's functions, read-only)

Spreads / full rows in the gate population, each judged by the same precision gate before and after:

| sport | dates | priced rows | median priced \|edge\| | priced \|edge\| >= 20 pp |
|---|---|---|---|---|
| NBA (k 2.02) | 11-11..11-12 (14 games) | 262 -> 257 (-1.9%) | 16.1 -> 8.3 pp | 75 -> 6 |
| NCAAF (k 1.80) | 11-07..11-08 (32) | 3,389 -> 3,355 (-1.0%) | 18.2 -> 10.3 pp | 1,445 -> 487 |
| NCAAB (k 1.34) | 11-11..11-12 (71) | 2,252 -> 2,188 (-2.8%) | 12.9 -> 9.6 pp | 400 -> 173 |
| WNCAAB (k 1) | 11-11..11-12 | 168 -> 168 | unchanged | unchanged |

## What it does not touch

- **Moneylines,** in any sport (measured: no gain).
- **Segment spreads** (not fitted).
- **Totals:** their own table and switch; the totals reading tonight is unaffected.
- **NHL:** k 1. Its puck line is display-only, and its calibration has its own lanes (`#773`).
- **Real-money in-play orders:** the book-consensus `ingame:` rule, not the join.
- **The PREREG_780 test:** NCAAB totals only. NCAAB spreads tempering does not change a totals row.

**Readers of `model_home_win_prob` on spreads rows:**
- After a load it is the tempered number.
- `engine_experts.live_resim_expert` already reads `model_home_win_prob_unscaled` whenever `prob_scale` != 1, for any
  market.
- Its consumed-input note (`engine_experts.py`, "set only on totals rows") will be stale. That is that lane's file.

## Loading

- **Steps:** a fleet ff to a SHA containing this, then a claimed refresh-worker restart.
- **Expected on load:**
  - NBA / NCAAF / NCAAB full-game spreads ledger rows carry `prob_scale` 2.02 / 1.80 / 1.34, with
    `model_home_win_prob_unscaled` beside it.
  - Their priced share is within a few % of the same rows' unscaled gate.
  - The priced |edge| median falls by about half in NBA and NCAAF, and about a quarter in NCAAB.
  - h2h and WNCAAB are unchanged.
- **Falsified if** a scaled sport's priced share falls by more than 10% (per row, scaled vs unscaled), or an h2h or
  WNCAAB row moves.
