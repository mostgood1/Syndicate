# NCAAF 2026-10-03 re-score: FULLY REPRODUCED — 49 games and all six brier values, exactly

**SUPERSEDED HEADLINE, kept because the path matters:** this file first concluded the brier values were
"not reproducible from available data". That was true of the LEDGER AND THE SERVED ARTIFACT ALONE and
false of the problem — an external finals source closed it. The reasoning that follows is unchanged and
correct; only the verdict on the briers is replaced, at the bottom.

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

## RESOLVED — external finals reproduce every figure EXACTLY `[2026-10-06, lane ncaaf-1003-external-finals]`

Source: ESPN's public FBS scoreboard for 2026-10-03 (`groups=80`), 54 events, **all 54 final**, against the
ledger's 54 distinct `event_id`s. Join on normalised team display names: **49/49 games matched, 0 unmatched,
0 orientation flips.**

| cut | ESPN-population model / market | retained model / market | n | verdict |
|---|---|---|---|---|
| all_records | 0.12358 / 0.11869 | 0.12358 / 0.11869 | 2,472 = 2,472 | **EXACT** |
| fresh_quotes_only | 0.12688 / 0.12189 | 0.12688 / 0.12189 | 2,106 = 2,106 | **EXACT** |
| priceable_only | 0.14260 / 0.13192 | 0.14260 / 0.13192 | 1,067 = 1,067 | **EXACT** |

Distance from the external recomputation to the retained figure: **0.00000**. To the refuted
last-captured-score proxy: 0.06893. **So the mislabelled-outcome diagnosis above was right** — the proxy's
identical-n-but-worse-brier signature was exactly that, and nothing was wrong with the row selection.

**AND THE POPULATION CAVEAT DOES NOT BITE FOR THIS DATE, which is a measured result rather than an
assumption.** I had warned that an external finals set would be a different population and so unpoolable.
Six brier values reproducing to 5dp over 2,472 rows with identical n can only happen if the outcome vectors
are identical, so for NCAAF 2026-10-03 the board's finals and ESPN's coincide exactly. The retained row is
therefore independently verified END TO END — `records_considered`, game count, all three cuts' n, and all
six briers — and the NCAAF pool's 198 -> 249 game jump is fully corroborated.

Home-win rate over the 49 games: **28/49 = 0.5714**.

`rescore_live_gameline_date.py` still cannot serve this date (`LEDGER_PATH` and the StatsAPI schedule URL
are hardcoded to MLB, and `--sport` says "only mlb is wired"), so the reproduction above was done by hand
against the raw ledger. Wiring an NCAAF finals adapter into that tool is the obvious follow-up and has no
lane.
