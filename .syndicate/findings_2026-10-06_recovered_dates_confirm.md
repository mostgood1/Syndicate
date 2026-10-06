# The 2026-09-30..10-04 recovered rows: 6 of 10 independently CONFIRMED, 2 unreachable, 2 empty

Lane `rescore-confirm-recovered-dates`, 2026-10-06. Every figure below is the tool's own
verification gate, which refuses unless the re-score reproduces the retained
`all_records` briers to 5dp AND both row counts.

| sport | date | games | all_records model / market | n | status |
|---|---|---|---|---|---|
| mlb | 2026-09-30 | 3 | 0.08236 / 0.06292 | 58/58 | **EXACT** |
| mlb | 2026-10-01 | 1 | 0.01559 / 0.04846 | 16/16 | **EXACT** |
| mlb | 2026-10-03 | 4 | 0.11173 / 0.13178 | 72/72 | **EXACT** |
| mlb | 2026-10-04 | 2 | 0.28133 / 0.37405 | 48/48 | **EXACT** |
| ncaaf | 2026-10-01 | 2 | 0.06954 / 0.14088 | 170/170 | **EXACT** |
| ncaaf | 2026-10-03 | 49 | 0.12358 / 0.11869 | 2472/2472 | **EXACT** |
| soccer | 2026-09-30 | 1 | — | — | UNREACHABLE: sport not wired |
| soccer | 2026-10-01 | 1 | — | — | UNREACHABLE: sport not wired |
| soccer | 2026-10-03 | 0 | — | — | nothing to confirm (0 games) |
| soccer | 2026-10-04 | 0 | — | — | nothing to confirm (0 games) |

All six reachable rows reproduced on the FIRST attempt, with no exclusion needed on any
of them — so for these dates the board's finals population and the re-score's coincide
exactly, the same result measured in detail for ncaaf 10-03.

## The two unreachable rows, and what it would take

`--sport soccer` exits **2** with `sport 'soccer' is not wired for re-scoring; wired:
mlb, ncaaf` — measured, not assumed. Wiring it needs a soccer finals provider, and that
is a harder adapter than NCAAF's for two reasons already recorded elsewhere in this
repo: soccer admits DRAWS (`finals_from_scores` scores a level game as "not a home win",
and `build_final_scores_index` only admits a level final for draw-bearing sports), and
its team-name join is the one with a known history of failures
(`tests/test_soccer_live_gameline_name_join.py`, `test_soccer_team_name_distinct_clubs.py`).
A name-pair join like NCAAF's would be the wrong instrument there.

Both unreachable rows carry **1 game** each, so the exposure is two single-game rows.

## What this does and does not establish

It establishes that the backfill captured the board's own measurement rather than a
lookalike: six independent reconstructions from the raw per-record ledgers, each pinned
by two briers and two row counts simultaneously.

It does NOT make any of these dates a RESULT. mlb 10-01 rests on one game and 10-04 on
two; the ncaaf 10-03 row is 49 games on a single Saturday. The pooled series is the only
place these belong, and `pool_live_gameline_trend.py` is the authority on it.
