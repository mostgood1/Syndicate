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
