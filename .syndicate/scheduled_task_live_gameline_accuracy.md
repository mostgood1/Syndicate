# Scheduled task -- `live-gameline-accuracy-snapshot`

**Recurring, 23:25 CT daily (+~8min dispatch jitter, so ~23:34).** Fires BEFORE
the midnight Central slate roll on purpose: after the roll the board serves the
NEW date with zero outcomes and tonight's completed games are unrecoverable.
That is also why it does NOT follow the `grading-freeze-payload-check`
"fire the morning after" convention -- there is no artifact to re-read, only a
live snapshot.

## What it captures

`live_gameline_score` off `/api/board/book-grid?sport=mlb`, appended to
`reports/live_gameline_accuracy/history.jsonl` by
`scripts/snapshot_live_gameline_score.py`.

## Why it exists

The scorer was ALREADY RUNNING and nobody knew: the lane header read "THE
EVALUATION HAS NOT STARTED" while `live_gameline_score` was being computed on
every board build and served on the public board payload. Nothing retained it --
each build overwrites the snapshot. The blocker on this lane was never access,
it was that the numbers evaporated.

## The reading, 2026-08-20T20:13Z

| cut | model brier | market brier | diff | n |
|---|---|---|---|---|
| `priceable_only` | 0.28706 | 0.24700 | **+0.04006** | 985 / 985 |
| `all_records` | 0.26871 | 0.24179 | +0.02692 | 1526 / **1449** |
| `last_per_game` | 0.32787 | 0.12162 | +0.20625 | 3 / 3 |

Brier is lower-is-better, so the model TRAILS the market on every cut.

## How to read it -- three bounds that outrank the headline

1. **`games_with_outcome` was 3.** `records_considered: 2799` and `n: 985` are
   repeated snapshots of the SAME three games across builds, not independent
   trials. No interval computed from n is real. Underpowered until pooled games
   reach ~100.
2. **`all_records` is an UNSOUND cut** -- model n=1526 vs market n=1449, so that
   Brier gap spans different row sets. `priceable_only` (985/985) is the
   like-for-like comparison and the one to quote.
3. **MAE points the OTHER way** (model 0.447 vs market 0.483). Better-centred,
   worse-calibrated is the shape that produces this. Do not pick the flattering
   metric.

## Pooling rule

Per date, take the row with the highest `games_with_outcome`. NEVER average
Briers across days unweighted -- a 3-game day would count as much as a 15-game
day. The independent unit is games.
