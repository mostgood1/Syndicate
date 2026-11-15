# NFL live width fit (lane `nfl-live-width-fit`, todo #780) -- 2026-11-15

User: "Yes, record today" (to "Record the NFL live re-sim's numbers through today's slate?"), 2026-11-15 ~8:10 AM CST.
Every fleet read below is read-only, at nice 19. Scripts: `C:\tmp\livegrade\nfl780\`.

## The gap

- **NFL live totals and spreads have never priced.** Every full-game totals / spreads row in the NFL live gameline
  ledger is refused `live_resim_published_no_distribution_for_this_market`: 1,569 on 11-01 and 1,340 of 3,323 rows
  on 11-08 (`census.py`). The refused rows record no model mean (`total_mean` / `home_margin` None; `sigma` 2.0 on
  all 1,340 rows on 11-08, `rows.py`).
- **The likely cause is already a lead (leads.md, 2026-11-10, `engine-experts`):** the NFL re-sim publishes
  `margin_dist` / `total_dist` at lane level in snake_case, and the join does not read them there.
  `live_evidence_log.LANE_DIST_ALIASES` normalises the same keys for the log.
- **Wiring those keys alone would price NFL at the re-sim's raw width.** Every sport #780 measured needed k 1.34-2.48.
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

## Prediction, written before the data (see the lane)

k > 1 on both totals and spreads. Falsified if the game-clustered 95% CI includes 1.0 or lies below it on both;
UNDETERMINED if the CI is wider than 1.0-2.5.

## Owed

- 8:55 AM and 12:40 PM CST 11-15: confirm today's games land in both halves (`wait_today.sh`).
- After the Sunday-night final: the fit, on about 15 games.
