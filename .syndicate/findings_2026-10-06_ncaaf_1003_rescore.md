# NCAAF 2026-10-03 re-score: the 49 games are CONFIRMED; the brier VALUES are not reproducible from available data

Lane `ncaaf-1003-rescore-confirm`, 2026-10-06. Ledger fetched from the local fleet
(`ncaaf_source/data/live_gameline_ledger/live_gameline_ledger_2026-10-03.jsonl`,
44,590,453 B, 43,967 records).

## The 49 is CONFIRMED, five independent ways

| reading | independent reconstruction | retained row | match |
|---|---|---|---|
| `records_considered` | 43,967 records in the ledger | 43,967 | EXACT |
| distinct games, scoreable | **49** event_ids with a full-segment h2h row carrying BOTH `model_home_win_prob` and `market_fair_prob` | `games_with_outcome` **49** | EXACT |
| `all_records` n | 2,472 such rows | 2,472 | EXACT |
| `fresh_quotes_only` n | 2,106 of those with `quote_age_seconds <= 120` | 2,106 | EXACT |
| `priceable_only` n | 1,067 of those with `priceable: true` | 1,067 | EXACT |

A sixth, from the board's own artifact rather than my reconstruction: `last_per_game`
reports **n=49** with `populations_matched: true` and `rows_without_market_prob: 0`.

So `games_with_outcome=49` is exactly what the hypothesis said it was — the count of
DISTINCT games with a scoreable full-game h2h row — and the capture is faithful to the
board (`live_gameline_score.games_with_outcome=49`, `records_considered=43967` in the
served artifact too). **The NCAAF pool's jump from 198 to 249 games is real.**

Context for the count: the ledger holds 54 distinct `event_id`s, so 5 games produced no
scoreable full-game h2h row at all. Market mix 21,001 spreads / 20,017 totals / 2,949
h2h; segments 36,569 `full` and the rest `h1/h2/q1..q4`.

## The brier VALUES could not be independently recomputed, and here is exactly why

**Neither source carries a per-game final outcome.**
- The LEDGER: all 43,967 rows are `game_state: live`. 36,569 carry `home_score`/
  `away_score`, but those are POINT-IN-TIME (the sampled row reads 0-0), and no row is
  ever written in a final state.
- The SERVED ARTIFACT: `finals_index` is a **diagnostics block, not a per-game index** —
  `finals_seen: 4508`, `finals_level: 0`, and every `finals_skipped_*` counter 0. (I first
  misread its 9 keys as 9 indexed games; it is 9 diagnostic FIELDS.) The grid's 300 rows
  carry `complete` but no scores.

**A last-captured-score proxy was tested and REFUTED, which is the useful part.** Taking
each game's latest row with both scores and deriving `home_won`:

| cut | my brier (model/market) | retained (model/market) | n |
|---|---|---|---|
| all_records | 0.19251 / 0.18210 | **0.12358 / 0.11869** | 2,472 = 2,472 |
| fresh_quotes_only | 0.19206 / 0.18128 | **0.12688 / 0.12189** | 2,106 = 2,106 |
| priceable_only | 0.18776 / 0.17681 | **0.14260 / 0.13192** | 1,067 = 1,067 |

**The n matches to the row on all three cuts while every brier is ~0.05-0.07 WORSE for
both model and market.** Identical denominators with systematically worse numerators is
the signature of a mislabelled OUTCOME, not a different row selection: the last captured
score is not the final score, because the collector stops snapshotting before many games
end, so the proxy calls some winners losers. It degrades model and market together, which
is what a bad label does and what a row-selection difference would not.

## What would be needed, and the caveat on it

An external NCAAF results source for 2026-10-03, keyed to these `event_id`s. That is a
DIFFERENT finals population from the board's, which is the splice
`rescore_live_gameline_date.py` refuses by design (`--finals-population statsapi` exists
precisely to force the caller to declare it). So a brier recomputed that way would not be
comparable to the neighbouring dates in the series, and must not be pooled with them.

`rescore_live_gameline_date.py` cannot do this date at all: `LEDGER_PATH` and the
`STATSAPI` schedule URL are both hardcoded to MLB, and `--sport` says so ("only mlb is
wired").
