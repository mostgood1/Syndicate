# NFL live width fit (lane `nfl-live-width-fit`, todo #780) -- 2026-11-15

User: "Yes, record today" (to "Record the NFL live re-sim's numbers through today's slate?"), 2026-11-15 ~8:10 AM CST.
Every fleet read below is read-only, at nice 19. Scripts: `C:\tmp\livegrade\nfl780\`.

## The gap

- **NFL live totals and spreads have never priced.** Every full-game totals / spreads row in the NFL live gameline
  ledger is refused `live_resim_published_no_distribution_for_this_market`: 1,569 on 11-01 and 1,340 of 3,323 rows
  on 11-08 (`census.py`). The refused rows record no model mean (`total_mean` / `home_margin` None; `sigma` 2.0 on
  all 1,340 rows on 11-08, `rows.py`).
- **CORRECTED 9:10 AM CST, the same morning: the gate is DELIBERATE, not a key-name bug.** The 11-10 lead
  (`engine-experts`) is right that the lane carries `margin_dist` / `total_dist` in snake_case (`build_game_lens`
  spreads `**result` into it) and that the join reads only `marginDist` / `totalRunsDist`. But
  `nfl/live_resim.py:659-664` withholds the camelCase names on purpose: closed lane `nfl-live-distribution-grade`
  (2026-09-27, `scripts/backtest_nfl_live_totals.py`) graded NFL live margins a measured FAIL. Its worst powered
  bucket was 0.4290 against `#499`'s 0.150, and the sim sd was 8.4-8.6 against a residual sd of 13.4-13.7, i.e.
  ~35-40% too NARROW (k ~1.6). Totals were unmeasurable (1 of 10 buckets powered), and 36 of its 45 rows rested on
  ratings files written after the games. My first message to the user called this a key-name mismatch; it is not.
- **Wiring those keys would bypass that gate** and price NFL at the re-sim's raw width. Every sport #780 measured
  needed k 1.34-2.48.
- **Only the NFL moneyline prices live:** 86-144 rows on a Sunday, under the 600 s NFL quote ceiling (quotes up to
  396 s old on 11-08).

## Both halves of the fit are already kept on the fleet (no new recorder)

- **Model side:** `live_evidence/nfl/<date>.jsonl`, one `live_resim` row per re-sim tick, with `extra.margin_dist`
  and `extra.total_dist` (120 sims a tick, so a probability at a line carries about +-4.5 pp of sampling noise).
  The log started 11-09. Ticks come every 5-8 min: 22 for BUF @ MIN (MNF 11-09), 12 for WAS @ NYG (TNF 11-12),
  with a 42-minute gap 20:23-21:05 CST in the TNF game (`evlive.py`).
- **Book side:** `nfl_source/tracking/book_quotes/<date>.jsonl[.gz]`, every pull's per-book quote, kept, including
  in-play full-game totals and spreads: 2,580 / 3,108 rows from 21 books for MNF, 2,142 / 2,659 from 20 books for
  TNF (`today.py`).
- **Not gradeable:** the 11-01 and 11-08 Sundays (no evidence log yet), and anything before.
- The file `live/nfl_live_resim.json` on disk is 45 days old. The live snapshot moved to the shared store, which is
  what the evidence log reads, so this is not a gap.

## The live log keeps only the confident tail (read 8:55 AM CST, NE @ DET)

- `resim_live_game` refuses `uninformative_probability` whenever its P(home) is inside 0.35-0.65
  (`nfl/live_resim.py:565-572`), AFTER the sim runs, and returns no distribution. The refused lane is stamped
  `pregame` and the evidence row keeps nothing: no `extra`, no dists, no state (`refrow.py`).
- NE @ DET, 25 minutes after its 8:30 AM CST kickoff: 4 re-sim updates (8:35, 8:40, 8:45, 8:50 AM CST), all
  refused with p 0.40-0.50, so 0 recorded states. The in-play quotes are landing (273 totals / 339 spreads rows
  from 23 books, `today_1455Z.out`).
- So a fit on the live log is a fit on states with |p - 0.5| > 0.15 only (the harness docstring measured 93.8% of
  NFL games refused at some point). It is selection-biased toward lopsided games.
- **The better instrument already exists:** `scripts/backtest_nfl_live_totals.py` replays end-of-Q1/Q2/Q3 states of
  COMPLETED games through the shipped `resim_live_game` against the real finals, with `--band bypass` to include
  the refused states (labelled diagnostic). CORRECTED below: the gradeable population is weeks 5-10,
  about 83 games, not ~150 over weeks 1-10.

## Prediction, written before the data (see the lane)

Margins: already measured too narrow on 09-27 (k ~1.6, weeks 1-3, leaky ratings), so this is a re-measurement,
not a fresh prediction. Totals: still a prediction.


k > 1 on both totals and spreads. Falsified if the game-clustered 95% CI includes 1.0 or lies below it on both;
UNDETERMINED if the CI is wider than 1.0-2.5.

## Owed

- 8:55 AM CST: done (above). 12:40 PM CST: the noon games (`wait_today.sh`, still armed).
- The fit: the user chose the replay harness, "After tonight's games" (next section).

## The replay run, armed for after tonight's games

User: "After tonight's games" (to "Run the NFL replay harness on weeks 1-10?"), 10:27 AM CST (16:27Z).

- **Population:** weeks 5-10, about 83 games (about 70 in weeks 5-9 plus the 13 of week 10 that finish tonight; MNF 11-16 excluded), not the ~150 over weeks 1-10 I told the user: today is week 10, not 11; the fleet holds no ratings file for weeks 1-3; and week 4 has no earlier file to grade it point-in-time.
- **Ratings provenance:** each `smartsim2_ratings_2026_wk<N>.json` is rewritten nightly and last written Sunday night of week N (generated_at Monday 03:56-05:28Z, after that Sunday's games), so the same-week file is LEAKAGE_RISK for every game it grades. Headline: week N graded on the wk(N-1) file, written before week N's first kickoff (POINT_IN_TIME; staler than production's pregame file by MNF N-1 and TNF N, never leaky). The same-week run on weeks 5-9 is kept as a diagnostic only.
- **Code and flags:** fleet HEAD `05fee7b69`: `nfl/live_resim.py`, the harness, the smartsim2 tree, `live_gameline_join.py` and `prop_projections.py` are blob-identical to origin/main `a380bd283`. Flags: refresh-worker sets `SYNDICATE_NFL_LIVE_RESIM=1`; no role sets `SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN` or `SYNDICATE_NFL_LIVE_RESIM_SIMS`, so the harness's defaults (120 sims) are production's.
- **Instrument:** `scripts/backtest_nfl_live_totals.py --band bypass --dump-rows` (end of Q1/Q2/Q3, the shipped
  `resim_live_game`), then `C:\tmp\livegrade\nfl780\harness\nflfit.py`. lines: the in-play full-game totals / spreads quotes captured during that quarter break (ESPN summary wallclocks: end of quarter to the next quarter's first play), each book's latest, with book_updated_at after the last score and no earlier than 5 min before the break; de-vigged per book, averaged over books. Model P is the join's own `price_distribution_market` (Agresti-Coull at 120 sims). One row per (game, cutoff, line); k by log-loss as #780 (P_k = Phi(Phi^-1(P)/k)), 95% CI by resampling games, walk-forward by week; subsets: all states (band bypassed), the states production would publish (P(home) outside 0.35-0.65), and the main line.
- **Smoke, week 9, 2 games: harness 10 s; 6 of 6 states matched quotes in their break (19 totals + 19 spreads rows), so the whole run should take minutes.**
- **Armed: background job `bkzsy2638` (`C:\tmp\livegrade\nfl780\harness\run_tonight.sh`) waits for 10 PM CST, then until all 13 of tonight's week-10 games are final (cap 3 AM CST), then runs the harness and `nflfit.py` at nice 19, read-only; outputs in `C:\tmp\livegrade\nfl780\harness`.**
- **Not measured by this:** possession at the break (the harness marginalises it), states inside a quarter,
  and alt lines (the shards' full-game totals / spreads are main lines).

## Precondition: the live player-exit gate

Noted 10:29 AM CST (16:29Z). From the user, relayed verbatim 2026-11-15 by session `local_379fd729` (NCAAF backtesting), which opened lane `live-player-exit-gate` on main `89498a5c6`: "yes, open the lane and tell the NFL lane - we need this across ALL sports" and "NFL live PROPS depend on this info".

- **Precondition:** NFL live totals / spreads pricing (and NFL live prop projections) stays OFF until lane `live-player-exit-gate` has a measured `key_player_out` refusal on a real mid-game exit. This lane only measures k; it opens no gate and loads nothing, and switching pricing on is the user's decision either way.
- **Files:** No collision: this lane's only repo file is its findings file (its scripts live outside the repo, in `C:\tmp\livegrade\nfl780`); the gate's call sites (`nfl/live_resim.py`, `live_gameline_join.py`, `live_projection_join.py`) are not this lane's.
- **Already exposed:** The NFL live MONEYLINE already prices with no exit gate (86-144 rows a Sunday under the 600 s ceiling, 11-08 census), so a mid-game QB exit is unguarded there today.
- **What it means for k:** The k fitted tonight is measured on every replayed game, including any with a mid-game exit; those states price a team that has lost a starter, so k partly absorbs exit-driven misses. Once the gate can label exits, re-fit k on the states it would leave priced: it may be smaller.

## Exit labels in tonight's fit (not pre-registered)

Added 12:00 PM CST (18:00Z), from the user, relayed verbatim by session `local_379fd729` (NCAAF backtesting / fleet watcher): "yes, pass the exit labels to the NFL lane".

- **What:** `C:\tmp\livegrade\nfl780\harness\nflfit.py` now labels every replayed quarter break with the gate's own function, `live_player_status.exits_from_espn_summary("nfl", ..., require_in_progress=False)` (copied from origin/main `e0383ee5c`, blob `821c3320b`, into `C:\tmp\livegrade\nfl780\harness\lps`; on main, not on the fleet), run on the ESPN summary cut to what a tick during that break could have seen (plays and injury rulings stamped before the next quarter's first play). It adds, per market, `_gate_priced`, `_gate_priced_band_respected` and `_gate_refused` (diagnostic), plus a verdict on the gate-priced states marked NOT pre-registered; the pre-registered verdict is unchanged. Optional: if the module fails to import, the fit runs as before and says so.
- **Checked:** checked on today's NE @ DET (401873053, final): end of Q1, Q2 and Q3 all refused on `NE:Drake Maye:injured_in_play:KEY` since 14:41:43Z (8:41 AM CST); non-key exits are listed but do not refuse (Morgan Moses, out at the end of Q1, is back by the end of Q2). Smoke fit (week 9, 2 games) rc 0: 6 states labelled, 0 refused.
- **Limit:** KEY is decided on the final boxscore's passers, not the passers as of the break; a QB hurt before his first pass would be missed. Production's tick sees the live box, so this can only under-refuse.
- **Armed job unchanged:** `bkzsy2638` calls `nflfit.py` with the same two arguments; it picks the labels up.

## Result: k sits at the fit's bound, and no k makes the model beat the market

Read 10:36 PM CST 11-15 (04:36Z 11-16).

- **Run:** background `bkzsy2638` started 04:25:31Z 11-16 (10:25 PM CST) once 13 of 13 week-10 games were final and finished 04:32:27Z: harness rc 0 (180 s point-in-time, 196 s same-week), `nflfit.py` rc 0 on both. Fleet HEAD `10094eae0` (on main): `resim_live_game`'s body is byte-identical to `05fee7b69`'s (sha256 6c0df249cdeb on both), and on this path only the exit gate's lines in `live_resim.py` and `nfl/props.py` changed; `live_gameline_join.py` is unchanged. Outputs in `C:\tmp\livegrade\nfl780\harness` (`fit_shifted.out/json`, `fit_sameweek.out/json`, `harness_shifted_*`, `rows_*.json`).
- **Population (headline, POINT_IN_TIME, week N on the wk(N-1) ratings):** 85 completed games, weeks 5-10, 65 scored: 20 refused (4 degenerate ratings; 16 unrated team, because a team on bye the week before has no row in the earlier ratings file, a cost of the one-week shift). 195 end-of-quarter states, 192 with in-play quotes in the break. Rows: totals 584, spreads 547 (15 pushes dropped).
- **Totals, all states:** k 5.0, the fit's upper bound; 95% CI over games [1.58, 5.0]. Brier: model at k=1 0.2736, model at k 0.2485, market 0.2414. Model minus market: at k=1 +0.032 [-0.004, +0.070]; at k +0.007 [-0.002, +0.016]. Mean P(over): model 0.380, market 0.498, realised 0.524.
  - States production would publish (P(home) outside 0.35-0.65): k 4.18 [1.33, 5.0]; at k +0.008 [-0.003, +0.019].
  - Main line only: k 5.0 [1.91, 5.0]; at k +0.002 [-0.006, +0.011].
  - Exit gate would price (NOT pre-registered): k 5.0 [1.65, 5.0]; at k +0.007 [-0.002, +0.016].
  - By break: end of Q1 5.0, Q2 2.19, Q3 5.0. Walk-forward: k trained on the earlier weeks is 5.0 every week, and its Brier is above the market's in all 5 test weeks (6-10).
- **Spreads, all states:** k 4.91 [1.41, 5.0]. Brier: model at k=1 0.2647, at k 0.2488, market 0.2450. Model minus market: at k=1 +0.020 [-0.006, +0.045]; at k +0.004 [-0.003, +0.012]. Mean P(home covers): model 0.461, market 0.498, realised 0.393.
  - States production would publish: k 3.83 [1.19, 5.0]; at k +0.006 [-0.003, +0.016].
  - Main line only: k 5.0 [2.04, 5.0]; model minus market at k=1 +0.027 [+0.003, +0.051] and at k +0.005 [+0.0001, +0.011]: WORSE than the market at both.
  - Exit gate would price: k 3.73 [1.28, 5.0]; at k +0.003 [-0.006, +0.011].
  - By break: Q1 5.0, Q2 5.0, Q3 2.02. Walk-forward: the trained k beats the market's Brier in 1 of 5 weeks (week 8).
- **Pre-registered verdict:** totals UNDETERMINED (CI wider than 1.5), spreads UNDETERMINED. The hypothesis k > 1 is not falsified: every subset's CI lower end is above 1 (1.11 to 2.04). The upper end is the fit's bound, so k's SIZE is not measured: log-loss keeps falling to k = 5, where a model 80% becomes 57%.
- **Why totals run to k = 5: a LOCATION miss, not a width miss.** The harness's own totals score, independent of the book lines: projected total minus final = -3.68 points, 95% CI over games [-5.86, -1.43]; realised above predicted in 9 of 10 probability buckets. By break: -5.05 (end of Q1), -2.86 (halftime, no drive in progress), -3.12 (end of Q3). By week 5-10: -5.2, -5.1, -2.1, -6.0, +0.8, -4.3. A width scale can only pull a one-sided miss toward 50%, so the fit runs to its bound. The halftime figure rules out the harness's marginalised possession as the whole cause. Fixing it is engine work (the live re-sim's remaining-points rate), not #780's width scale.
- **Spreads:** margin signed bias +1.27 [-0.71, +3.21], not distinguishable from 0; over-confident in the middle (0.6-0.7 bucket: predicted 0.64, realised 0.53). The model's mean P(home covers) sits nearer the realised rate than the market's does, yet its Brier is worse: too confident game by game.
- **Same-week diagnostic (LEAKAGE_RISK, weeks 5-9, 70 games):** totals k 3.15 [1.37, 5.0], mean P(over) 0.388 against realised 0.494; spreads k 5.0 [1.93, 5.0], at k +0.007 [+0.0003, +0.013], worse than the market. The same picture with fresher (leaky) ratings, so the one-week shift is not the cause.
- **Exit gate (NOT pre-registered):** 4 of 195 states refused, in 2 games: NE @ DET at Q1-Q3 (Drake Maye, injured 14:41:43Z) and BUF @ NYJ at Q2 (Geno Smith, injured_in_play 19:25:37Z = 1:25 PM CST, back on the field by the end of Q3). The gate-priced figures match the all-state ones.
- **What it means:** no NFL k should ship. At the fitted k the model only gets within noise of the market (best: totals main line +0.002), never better, and at k=1 it is 0.02-0.03 worse. On this evidence NFL live totals and spreads stay off, whatever the exit gate shows. The next step for totals is the -3.7 point under-projection in the live re-sim; no lane holds it yet.
- **Not measured:** possession at the break (the harness marginalises it), alt lines, and production's own live ticks (the live log keeps only states outside 0.35-0.65).
